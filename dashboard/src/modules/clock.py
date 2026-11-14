"""Clock: Home widgets (Clock S/M/L, Timers S/M) and the Clock page.

The Clock page has two tabs. World clock: a map with the day/night line and a card
per city (config.json "clock.cities": name, zone, latitude, longitude). Timers:
hr / min / sec wheels with a number pad, the timers that are running (any number
at once) and recent lengths that start with one tap (seeded from "clock.timers",
in minutes). The Timers widget starts those seed lengths with one tap; every
clock widget shows the timer ending soonest. When one ends, a fullscreen alert
appears, the backlight comes on and a chime repeats until it is dismissed.

Running timers and the recents list are kept in ~/.local/state/dashboard/clock.json,
so they survive a dashboard restart and a deploy.
"""

import os
import subprocess
import time
from datetime import datetime, timezone

from gi.repository import Gdk, GLib, Gtk

import clock_logic
import core
import icons
from clock_widgets import Face, Icon, Ring, Wheel, WorldMap, icon_button

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.expanduser("~/.local/state/dashboard")
STATE_PATH = os.path.join(STATE_DIR, "clock.json")
CHIME_PATH = os.path.join(STATE_DIR, "chime-1.wav")   # bump the number when write_chime changes
LAND_PATH = os.path.join(HERE, "assets", "world-land.json")
CHIME_DEVICE = "plughw:CARD=WM8962"  # the tablet's own speakers
ALARM_FLOOR = 8   # of 16: an alarm is never quieter than this, whatever the volume is set to
GREEN = (0.19, 0.82, 0.35)
ACCENT = "#7FB3E3"


def _label(text, css, **props):
    label = Gtk.Label(label=text, **props)
    label.get_style_context().add_class(css)
    return label


def _button(text, css, on_click):
    button = Gtk.Button(label=text)
    button.get_style_context().add_class(css)
    button.connect("clicked", lambda _b: on_click())
    return button


class Module(core.Module):
    name = "clock"
    icon = "clock"
    menu_title = "Clock"
    widgets = {
        "clock": ("Clock", ("S", "M", "L"), "clock"),
        "timers": ("Timers", ("S", "M"), "timer"),
    }

    def setup(self):
        conf = getattr(self.app, "config", {}).get("clock", {})
        self.cities = clock_logic.parse_cities(conf.get("cities", clock_logic.DEFAULT_CITIES))
        self.seed = [int(m) * 60 for m in conf.get("timers", clock_logic.DEFAULT_TIMERS)]

        state = clock_logic.load_state(STATE_PATH)
        self.recents = clock_logic.recents_sync(state.get("recents", []), state.get("seed"), self.seed)
        self.timers = clock_logic.TimerSet()
        self.timers.load(state.get("timers", []))

        self.editing = False      # the recents list's Edit mode
        self.rows = {}            # timer id -> the widgets of its row that change
        self.finished = []        # lengths (seconds) of the timers the alert is showing
        self._tick_id = 0
        self._chime = None
        self._volume_before = None
        self._world_minute = None
        self.forget_widgets()

        self.world_box = self._build_world()
        self.timers_box = self._build_timers()
        self.alert = self._build_alert()

    def forget_widgets(self):
        self._clock_views = []    # (size, time label, date label, [(city, label)])
        self._countdowns = []     # (box shown while a timer exists, its label)

    # ---- Home widgets -------------------------------------------------------

    def widget(self, wid, size):
        if wid == "timers":
            return self._timers_widget(size)
        return self._clock_widget(size)

    def _clock_widget(self, size):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        time_label = _label("", f"clock-w-time-{size}", xalign=0)
        date_label = _label("", "clock-w-date", xalign=0)
        box.pack_start(time_label, False, False, 0)
        box.pack_start(date_label, False, False, 0)
        box.pack_start(Gtk.Box(), True, True, 0)   # push the rest to the bottom

        cities = []
        if size != "S":
            row = Gtk.Box(spacing=36, homogeneous=False)
            for city in self._away_cities()[:4 if size == "L" else 3]:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                name = _label(city["name"], "clock-w-city", xalign=0)
                value = _label("", "clock-w-city-time", xalign=0)
                col.pack_start(name, False, False, 0)
                col.pack_start(value, False, False, 0)
                row.pack_start(col, False, False, 0)
                cities.append((city, value))
            box.pack_start(row, False, False, 0)
        box.pack_start(self._countdown_chip(), False, False, 0)
        self._clock_views.append((size, time_label, date_label, cities))
        self._fill_clock_view(self._clock_views[-1], time.localtime(), datetime.now().astimezone())
        return core.tile(box, self.open_world, size)

    def _away_cities(self):
        """The configured cities not on local time (the widget's big time is local)."""
        now = datetime.now().astimezone()
        away = []
        for city in self.cities:
            try:
                same = clock_logic.city_now(city["tz"], now)["time"] == time.strftime("%H:%M")
            except Exception:
                same = False
            if not same:
                away.append(city)
        return away

    def _countdown_chip(self):
        chip = Gtk.Box(spacing=10, halign=Gtk.Align.START)
        chip.get_style_context().add_class("clock-w-chip")
        chip.pack_start(icons.Icon("timer", 22, ACCENT, 2), False, False, 0)
        text = _label("", "clock-w-chip-text")
        chip.pack_start(text, False, False, 0)
        chip.set_no_show_all(True)
        text.show()
        chip.get_children()[0].show()
        self._countdowns.append((chip, text))
        self._fill_countdown(chip, text)
        return chip

    def _timers_widget(self, size):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        head = Gtk.Box(spacing=10)
        head.pack_start(core.widget_head("timer", "Timers"), False, False, 0)
        countdown = _label("", "clock-w-countdown", xalign=1)
        head.pack_end(countdown, False, False, 0)
        box.pack_start(head, False, False, 0)
        self._countdowns.append((countdown, countdown))
        self._fill_countdown(countdown, countdown)

        presets = self.seed[:4]
        cols = 2 if size == "S" else 4
        grid = Gtk.Grid(row_spacing=10, column_spacing=10, row_homogeneous=True,
                        column_homogeneous=True, vexpand=True)
        for i, seconds in enumerate(presets):
            whole = seconds % 60 == 0 and seconds < 3600
            text = str(seconds // 60) if whole else clock_logic.format_short(seconds)
            button = _button(text, "clock-w-preset", lambda s=seconds: self._start(s))
            grid.attach(button, i % cols, i // cols, 1, 1)
        box.pack_start(grid, True, True, 0)
        box.pack_start(_label("minutes · tap to start", "widget-sub", xalign=0.5), False, False, 0)
        return core.tile(box, self.open_timers, size)

    def _fill_countdown(self, shown, text_label):
        soonest = self.timers.soonest()
        text = ""
        if soonest is not None:
            text = clock_logic.format_short(self.timers.remaining(soonest))
            if len(self.timers.timers) > 1:
                text += f"  +{len(self.timers.timers) - 1}"
        if text_label.get_text() != text:
            text_label.set_text(text)
        shown.set_visible(soonest is not None)

    def _fill_clock_view(self, view, now, aware):
        size, time_label, date_label, cities = view
        core.set_text(time_label, time.strftime("%H:%M", now))
        core.set_text(date_label, time.strftime("%a %-d %b" if size == "S" else "%A %-d %B", now))
        for city, value in cities:
            info = clock_logic.city_now(city["tz"], aware, city["lat"], city["lon"])
            core.set_text(value, info["time"])

    # ---- the clock: one wake-up per minute ----------------------------------

    def start(self):
        self.update()
        self._schedule()
        self._refresh_timers()
        if self.timers.timers:
            self._ensure_tick()   # restored timers; one that ran out meanwhile rings now
        GLib.idle_add(self._prepare_chime)

    def _schedule(self):
        # Wake just after the next minute boundary instead of every second: fewer redraws.
        delay = 60 - time.localtime().tm_sec
        GLib.timeout_add_seconds(delay, self._on_minute)

    def _on_minute(self):
        try:
            self.update()
        finally:
            self._schedule()
        return False

    def update(self):
        now, aware = time.localtime(), datetime.now().astimezone()
        for view in self._clock_views:
            self._fill_clock_view(view, now, aware)

    # ---- the Clock page: World clock and Timers tabs ------------------------

    def page(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        tabs = Gtk.Box(spacing=0, halign=Gtk.Align.START)
        tabs.get_style_context().add_class("seg")
        self.tab_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vexpand=True)
        self.tab_stack.add_named(self.world_box, "world")
        self.tab_stack.add_named(self.timers_box, "timers")
        self.tab_buttons = {}
        for name, text in (("world", "World clock"), ("timers", "Timers")):
            button = _button(text, "seg-btn", lambda n=name: self._show_tab(n))
            tabs.pack_start(button, False, False, 0)
            self.tab_buttons[name] = button
        root.pack_start(tabs, False, False, 0)
        root.pack_start(self.tab_stack, True, True, 0)
        self._tab = "world"
        self._mark_tabs()
        return root

    def _mark_tabs(self):
        for name, button in self.tab_buttons.items():
            ctx = button.get_style_context()
            (ctx.add_class if name == self._tab else ctx.remove_class)("active")

    def _show_tab(self, name):
        self._tab = name
        self.tab_stack.set_visible_child_name(name)
        self._mark_tabs()
        if name == "world":
            self._refresh_world(force=True)
        elif self.editing:
            self.editing = False
            self._rebuild_list()
        self._refresh_timers()
        self._ensure_tick()

    def page_shown(self):
        self._show_tab(self._tab)

    def _world_visible(self):
        return self.page_open() and self._tab == "world"

    def _timers_visible(self):
        return self.page_open() and self._tab == "timers"

    # ---- shared pieces ------------------------------------------------------

    @staticmethod
    def _section():
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

    @staticmethod
    def _hide_cursor(widget):
        widget.get_window().set_cursor(
            Gdk.Cursor.new_for_display(widget.get_display(), Gdk.CursorType.BLANK_CURSOR)
        )

    @staticmethod
    def _show(win):
        win.fullscreen()
        win.show_all()
        win.present()

    def _save(self):
        try:
            clock_logic.save_state(STATE_PATH, {
                "seed": self.seed, "recents": self.recents, "timers": self.timers.dump(),
            })
        except OSError as exc:
            print(f"[clock] could not save timers: {exc}", flush=True)

    def _ensure_tick(self):
        if not self._tick_id:
            self._tick_id = GLib.timeout_add(500, self._tick)

    def _tick(self):
        try:
            done = self.timers.poll()
            if done:
                self._save()
                self._rebuild_list()
                self._finished(done)
            self._refresh_timers()
            if self._world_visible():
                self._refresh_world()
            if self.alert.get_visible() and self._chime is not None and self._chime.poll() is not None:
                self._play_chime()  # the sound file ended: play it again
        except Exception as exc:  # a broken refresh must not take the dashboard down
            print(f"[clock] tick failed: {exc}", flush=True)
        if (self.timers.running() or self._world_visible()
                or self._timers_visible() or self.alert.get_visible()):
            return True
        self._tick_id = 0
        return False

    # ---- world clock --------------------------------------------------------

    def _build_world(self):
        root = self._section()
        self.map = WorldMap(LAND_PATH)
        root.pack_start(self.map, True, True, 0)
        cards = Gtk.Box(spacing=16, homogeneous=True)
        self.city_rows = []
        for city in self.cities:
            card = Gtk.Box(spacing=18)
            card.get_style_context().add_class("clock-city")
            face = Face(104)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
            name = _label("", "clock-city-name", xalign=0)
            meta = _label("", "clock-city-meta", xalign=0)
            sun = _label("", "clock-city-meta", xalign=0)
            for label in (name, meta, sun):
                text.pack_start(label, False, False, 0)
            card.pack_start(face, False, False, 0)
            card.pack_start(text, True, True, 0)
            cards.pack_start(card, True, True, 0)
            self.city_rows.append((city, face, name, meta, sun))
        if not self.city_rows:
            cards.pack_start(_label("No cities in config.json", "clock-city-meta"), False, False, 0)
        root.pack_start(cards, False, False, 0)
        return root

    def open_world(self):
        self._tab = "world"
        if self.page_open():
            self._show_tab("world")
        else:
            self.app.show_page(self.name)

    def _refresh_world(self, force=False):
        now = datetime.now().astimezone()
        minute = (now.hour, now.minute)
        if minute == self._world_minute and not force:
            return
        self._world_minute = minute
        dots = []
        for city, face, name, meta, sun in self.city_rows:
            info = clock_logic.city_now(city["tz"], now, city["lat"], city["lon"])
            face.set(info["hour"], info["minute"], info["daytime"])
            name.set_text(f"{city['name']}, {info['time']}")
            meta.set_text(f"{info['day']}, {info['offset']}")
            sun.set_text(f"☀ ↑ {info['sunrise']}   ↓ {info['sunset']}" if info["sunrise"] else "")
            if city["lat"] is not None:
                dots.append((city["name"], info["time"], city["lat"], city["lon"]))
        self.map.set(dots, clock_logic.terminator(now.astimezone(timezone.utc)))

    # ---- timers view --------------------------------------------------------

    def _build_timers(self):
        root = self._section()
        body = Gtk.Box(spacing=24)

        # left: running timers, then recents
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_size_request(320, -1)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll.add(self.list_box)
        body.pack_start(scroll, False, False, 0)

        # middle: hr / min / sec wheels and Start
        entry = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26, valign=Gtk.Align.CENTER)
        wheels = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.wheels = []
        for index, (unit, count) in enumerate((("hr", 24), ("min", 60), ("sec", 60))):
            if index:
                colon = _label(":", "clock-colon", valign=Gtk.Align.CENTER)
                colon.set_margin_top(30)   # level with the wheels, which sit under their labels
                wheels.pack_start(colon, False, False, 0)
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            column.pack_start(_label(unit, "clock-unit"), False, False, 0)
            wheel = Wheel(count, self._on_wheel, self._select)
            column.pack_start(wheel, False, False, 0)
            wheels.pack_start(column, False, False, 0)
            self.wheels.append(wheel)
        entry.pack_start(wheels, False, False, 0)
        self.start_btn = _button("Start", "clock-action", self._start_entry)
        self.start_btn.get_style_context().add_class("clock-go")
        self.start_btn.set_halign(Gtk.Align.CENTER)
        entry.pack_start(self.start_btn, False, False, 0)
        body.pack_start(entry, True, True, 0)

        # right: number pad typing into the selected wheel
        pad = Gtk.Grid(row_spacing=10, column_spacing=10, valign=Gtk.Align.CENTER)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0"]
        for i, key in enumerate(keys):
            action = self._backspace if key == "⌫" else (lambda d=key: self._digit(int(d)))
            pad.attach(_button(key, "clock-key", action), i % 3, i // 3, 1, 1)
        body.pack_start(pad, False, False, 0)

        root.pack_start(body, True, True, 0)
        self._typed = 0
        self._selected = None
        self._select(self.wheels[1])
        self._set_wheels(self.recents[0] if self.recents else 300)
        self._rebuild_list()
        return root

    def open_timers(self):
        self._tab = "timers"
        if self.page_open():
            self._show_tab("timers")
        else:
            self.app.show_page(self.name)

    # -- entry: wheels and pad --

    def _entry_seconds(self):
        h, m, s = (wheel.get_value() for wheel in self.wheels)
        return h * 3600 + m * 60 + s

    def _set_wheels(self, seconds):
        for wheel, value in zip(self.wheels, clock_logic.split_hms(seconds)):
            wheel.set_value(value)
        self._on_wheel()

    def _on_wheel(self):
        if hasattr(self, "start_btn") and len(self.wheels) == 3:
            self.start_btn.set_sensitive(self._entry_seconds() > 0)

    def _select(self, wheel):
        self._selected = wheel
        self._typed = 0
        for other in self.wheels:
            other.set_selected(other is wheel)

    def _digit(self, digit):
        wheel = self._selected
        value = wheel.get_value() * 10 + digit if self._typed else digit
        if value >= wheel.count:
            value = digit
        wheel.set_value(value)
        self._typed += 1
        if self._typed >= 2:   # two digits typed: move on to the next column, like a microwave
            index = self.wheels.index(wheel)
            if index + 1 < len(self.wheels):
                self._select(self.wheels[index + 1])
            else:
                self._typed = 0

    def _backspace(self):
        wheel = self._selected
        wheel.set_value(wheel.get_value() // 10)
        self._typed = 1 if wheel.get_value() else 0

    def _start_entry(self):
        seconds = self._entry_seconds()
        if seconds > 0:
            self._start(seconds)

    # -- actions --

    def _start(self, seconds):
        self.timers.add(seconds)
        self.recents = clock_logic.recents_add(self.recents, seconds)
        self._changed()
        self._ensure_tick()

    def _toggle(self, timer):
        if timer.state == "running":
            self.timers.pause(timer)
        else:
            self.timers.resume(timer)
            self._ensure_tick()
        self._save()
        self._refresh_timers()

    def _cancel(self, timer):
        self.timers.cancel(timer)
        self._changed()

    def _forget(self, seconds):
        self.recents = [s for s in self.recents if s != seconds]
        if not self.recents:
            self.editing = False
        self._changed()

    def _toggle_edit(self):
        self.editing = not self.editing
        self._rebuild_list()

    def _changed(self):
        self._save()
        self._rebuild_list()
        self._refresh_timers()

    # -- the list --

    def _rebuild_list(self):
        for child in self.list_box.get_children():
            self.list_box.remove(child)
        self.rows = {}
        for timer in self.timers.timers:
            self.list_box.pack_start(self._timer_row(timer), False, False, 0)
        if self.recents:
            head = Gtk.Box()
            head.pack_start(_label("Recents", "clock-section", xalign=0), True, True, 0)
            head.pack_end(_button("Done" if self.editing else "Edit", "clock-edit", self._toggle_edit),
                          False, False, 0)
            self.list_box.pack_start(head, False, False, 0)
            for seconds in self.recents:
                self.list_box.pack_start(self._recent_row(seconds), False, False, 0)
        self.list_box.show_all()

    def _timer_row(self, timer):
        row = Gtk.Box(spacing=14)
        row.get_style_context().add_class("clock-row")
        ring = Ring(60)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        left = _label("", "clock-row-left", xalign=0)
        sub = _label("", "clock-row-sub", xalign=0)
        text.pack_start(left, False, False, 0)
        text.pack_start(sub, False, False, 0)
        pause_btn, pause_icon = icon_button("pause", 26, "clock-round", lambda: self._toggle(timer))
        cancel_btn, _icon = icon_button("cross", 26, "clock-round", lambda: self._cancel(timer))
        row.pack_start(ring, False, False, 0)
        row.pack_start(text, True, True, 0)
        row.pack_end(cancel_btn, False, False, 0)
        row.pack_end(pause_btn, False, False, 0)
        self.rows[timer.id] = (timer, ring, left, sub, pause_icon)
        return row

    def _recent_row(self, seconds):
        row = Gtk.Box(spacing=14)
        row.get_style_context().add_class("clock-row")
        if self.editing:
            remove, _icon = icon_button("minus", 24, "clock-remove", lambda: self._forget(seconds))
            row.pack_start(remove, False, False, 0)
        # tapping the text loads the length into the wheels; the green button starts it
        pick = Gtk.Button()
        pick.get_style_context().add_class("clock-recent")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.pack_start(_label(clock_logic.format_short(seconds), "clock-recent-time", xalign=0), False, False, 0)
        text.pack_start(_label(clock_logic.duration_name(seconds), "clock-row-sub", xalign=0), False, False, 0)
        pick.add(text)
        pick.connect("clicked", lambda _b: self._set_wheels(seconds))
        row.pack_start(pick, True, True, 0)
        if not self.editing:
            play, _icon = icon_button("play", 28, "clock-play", lambda: self._start(seconds), GREEN)
            row.pack_end(play, False, False, 0)
        return row

    def _refresh_timers(self):
        """The parts that change every second: the rows' countdowns and the tile's button."""
        for timer, ring, left, sub, pause_icon in self.rows.values():
            paused = timer.state == "paused"
            text = clock_logic.format_short(self.timers.remaining(timer))
            if left.get_text() != text:
                left.set_text(text)
            ring.set(self.timers.fraction(timer), paused)
            ends = "paused" if paused else time.strftime("ends %H:%M", time.localtime(self.timers.ends_at(timer)))
            note = f"{clock_logic.duration_name(timer.total)} · {ends}"
            if sub.get_text() != note:
                sub.set_text(note)
            pause_icon.set_kind("play" if paused else "pause")
        # the Home widgets: the soonest timer (+ how many more), hidden when none
        for shown, text_label in self._countdowns:
            self._fill_countdown(shown, text_label)

    # ---- time's up ----------------------------------------------------------

    def _build_alert(self):
        win = Gtk.Window()
        win.get_style_context().add_class("clock-alert")
        win.connect("delete-event", lambda *_: True)
        win.connect("realize", self._hide_cursor)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.pack_start(_label("Time’s up", "clock-alert-heading"), False, False, 0)
        self.alert_detail = _label("", "clock-alert-detail")
        box.pack_start(self.alert_detail, False, False, 0)
        buttons = Gtk.Box(spacing=24, halign=Gtk.Align.CENTER)
        self.repeat_btn = _button("Repeat", "clock-repeat", self._repeat)
        self.repeat_btn.set_no_show_all(True)
        buttons.pack_start(self.repeat_btn, False, False, 0)
        buttons.pack_start(_button("Dismiss", "clock-dismiss", self._dismiss), False, False, 0)
        box.pack_start(buttons, False, False, 0)
        win.add(box)
        return win

    def _finished(self, timers):
        ringing = bool(self.finished)
        self.finished.extend(timer.total for timer in timers)
        names = [clock_logic.duration_name(total) for total in self.finished]
        self.alert_detail.set_text(f"{names[0]} timer" if len(names) == 1 else " · ".join(names))
        self.repeat_btn.set_visible(len(names) == 1)
        if ringing:
            return
        # Wake the screen if the screen-off tile had blanked it.
        screen_off = getattr(self.app, "modules", {}).get("screen_off")
        if screen_off is not None and screen_off.overlay.get_visible():
            self.app.backlight.on()
            screen_off.overlay.hide()
        self.alert.set_keep_above(True)
        self._show(self.alert)
        self._ensure_tick()
        volume = getattr(self.app, "volume", None)
        if volume is not None and volume.available and volume.step < ALARM_FLOOR:
            self._volume_before = volume.step
            volume.set(ALARM_FLOOR, show=False)
        try:
            self._prepare_chime()
            self._play_chime()
        except OSError as exc:
            print(f"[clock] no alarm sound: {exc}", flush=True)

    def _prepare_chime(self):
        if not os.path.exists(CHIME_PATH):
            os.makedirs(STATE_DIR, exist_ok=True)
            clock_logic.write_chime(CHIME_PATH)
        return False

    def _play_chime(self):
        self._chime = subprocess.Popen(
            ["aplay", "-q", "-D", CHIME_DEVICE, CHIME_PATH],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _dismiss(self):
        if self._chime is not None:
            if self._chime.poll() is None:
                self._chime.terminate()
            try:
                self._chime.wait(timeout=1)   # reap it: no zombie aplay left behind
            except subprocess.TimeoutExpired:
                self._chime.kill()
            self._chime = None
        # Put the volume back, unless it was changed with the buttons while ringing.
        volume = getattr(self.app, "volume", None)
        if self._volume_before is not None and volume is not None and volume.step == ALARM_FLOOR:
            volume.set(self._volume_before, show=False)
        self._volume_before = None
        self.finished = []
        self.alert.hide()

    def _repeat(self):
        total = self.finished[0]
        self._dismiss()
        self._start(total)
