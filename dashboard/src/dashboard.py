#!/usr/bin/env python3
"""Fullscreen touch dashboard for the Surface RT.

Layout: a side menu on the left (Home, one entry per module that has a page,
Sleep pinned at the bottom) and the current page on the right. Home is a grid of
widgets the user arranges with Edit home (remove, resize S/M/L, move, add);
home_layout.py packs them into pages and keeps the layout in
~/.local/state/dashboard/home.json. Swipe sideways on Home to change page.

Modules are listed in config.json and live in modules/<name>.py, each with a
`Module` class (see core.Module). The screen-off module is always loaded.
"""

import importlib
import json
import os
import sys
import time
import traceback

os.environ.setdefault("NO_AT_BRIDGE", "1")  # no accessibility bus here: skip the failing lookup

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import home_layout  # noqa: E402
import icons  # noqa: E402
from core import Backlight, label, set_text, timed, watch_stalls  # noqa: E402
from volume import Volume  # noqa: E402

ALWAYS_LAST = "screen_off"
STATE_DIR = os.path.expanduser("~/.local/state/dashboard")
HOME_PATH = os.path.join(STATE_DIR, "home.json")
ACCENT = "#7FB3E3"
MUTED = "#AEB8C2"
HEALTH_COLORS = {"ok": "#5FC48C", "warn": "#E8A86B", "bad": "#E87B7B"}
# The first-run Home, as in the mockup; widgets not listed go to the Add sheet.
PREFERRED = [("clock", "M"), ("timers", "S"), ("controls", "S"),
             ("airplay", "S"), ("system", "M")]
SWIPE_PX = 120  # a sideways drag at least this long on Home changes the page


def load_config():
    try:
        with open(os.path.join(HERE, "config.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"config.json unreadable ({exc}), using defaults", flush=True)
        return {}


def safe(what, fn, *args):
    """Call fn; a broken module prints its error instead of taking the dashboard down."""
    try:
        return fn(*args)
    except Exception:
        print(f"{what} failed:", flush=True)
        traceback.print_exc()
        return None


def css_class(widget, *names):
    ctx = widget.get_style_context()
    for name in names:
        ctx.add_class(name)
    return widget


def set_class(widget, name, on):
    ctx = widget.get_style_context()
    (ctx.add_class if on else ctx.remove_class)(name)


def icon_button(icon_name, text, on_click, css="pill", size=20, color=icons.FG):
    """A button with an icon and optional text; on_click() takes no arguments."""
    button = css_class(Gtk.Button(), css)
    box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
    box.pack_start(icons.Icon(icon_name, size, color), False, False, 0)
    if text:
        box.pack_start(label(text), False, False, 0)
    button.add(box)
    button.connect("clicked", lambda _b: on_click())
    return button


class Card:
    """One Home widget at one size: the module's tile under an overlay that carries
    the edit controls. Built once and kept, on Home or off it."""

    def __init__(self, wid, size, tile):
        self.wid, self.size, self.tile = wid, size, tile
        self.root = Gtk.Overlay()
        self.root.add(tile)
        self.place = None       # (page, col, row, w, h) while it is on Home
        self.controls = None    # the edit controls, made on first use
        self.left = self.right = None
        self.editing = False


class Dashboard:
    def __init__(self):
        self.config = load_config()
        self.backlight = Backlight()
        self.volume = Volume()  # speaker level + the hardware volume buttons
        self.exit_code = 0
        self.modules = {}       # name -> loaded Module, so modules can reach each other
        self.current = "home"   # the page on screen: "home" or a module name
        self.editing = False
        self.home_page = 0
        self.cards = {}         # (widget id, size) -> Card: built once, kept for good
        self.page_grids = []    # one Gtk.Grid per Home page
        self.owners = {}        # widget id -> the module that draws it
        self.available = {}     # widget id -> allowed sizes
        self.widget_info = {}   # widget id -> (title, icon)

        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.window = Gtk.Window(title="Dashboard")
        self.window.connect("destroy", Gtk.main_quit)
        self.window.connect("realize", self._hide_cursor)

        names = [n for n in self.config.get("modules", ["clock", "system"]) if n != ALWAYS_LAST]
        names.append(ALWAYS_LAST)
        for name in names:
            self._load(name)
        for name, module in list(self.modules.items()):
            if safe(f"module {name!r} setup", lambda m=module: m.setup() or True) is None:
                del self.modules[name]
        for module in self.modules.values():
            for wid, (title, sizes, icon) in module.widgets.items():
                self.owners[wid] = module
                self.available[wid] = tuple(sizes)
                self.widget_info[wid] = (title, icon)
        self.items = home_layout.load(HOME_PATH, self.available, PREFERRED)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, hexpand=True)
        self.stack.add_named(self._build_home(), "home")
        for name, module in self.modules.items():
            if module.icon is None:
                continue
            page = safe(f"module {name!r} page", module.page)
            if page is not None:
                holder = css_class(Gtk.Box(), "page")   # a Box takes CSS padding; an EventBox page wouldn't
                holder.pack_start(page, True, True, 0)
                self.stack.add_named(holder, name)

        shell = css_class(Gtk.Box(), "shell")
        shell.pack_start(self._build_rail(), False, False, 0)
        shell.pack_start(self.stack, True, True, 0)
        self.window.add(shell)

        self._layout_home()
        for name, module in self.modules.items():
            safe(f"module {name!r} start", module.start)
        self._tick_date()
        GLib.timeout_add_seconds(20, self._tick_date)

        watch_stalls(self.window)
        self.window.fullscreen()
        self.window.show_all()
        self.stack.set_visible_child_name("home")
        self._update_rail()

    def _load(self, name):
        try:
            mod = importlib.import_module(f"modules.{name}")
            self.modules[name] = mod.Module(self)
        except Exception:
            print(f"module {name!r} failed to load:", flush=True)
            traceback.print_exc()

    @staticmethod
    def _hide_cursor(widget):
        display = widget.get_display()
        widget.get_window().set_cursor(Gdk.Cursor.new_for_display(display, Gdk.CursorType.BLANK_CURSOR))

    def quit_for_restart(self):
        """Exit; run.sh starts the dashboard again."""
        Gtk.main_quit()

    # ---- side menu and pages --------------------------------------------------

    def _build_rail(self):
        rail = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "rail")
        self.rail_buttons = {}
        entries = [("home", "home", "Home")]
        entries += [(name, m.icon, m.menu_title) for name, m in self.modules.items()
                    if m.icon is not None and self.stack.get_child_by_name(name) is not None]
        for name, icon, title in entries:
            button = self._rail_button(icon, title, lambda n=name: self.show_page(n))
            rail.pack_start(button, False, False, 0)
            self.rail_buttons[name] = button
        screen_off = self.modules.get(ALWAYS_LAST)
        if screen_off is not None:
            sleep = self._rail_button("moon", "Sleep", screen_off.sleep)
            css_class(sleep, "rail-sleep")
            rail.pack_end(sleep, False, False, 0)
        return rail

    @staticmethod
    def _rail_button(icon, title, on_click):
        button = css_class(Gtk.Button(), "rail-btn")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        button._icon = icons.Icon(icon, 30, MUTED)
        box.pack_start(button._icon, False, False, 0)
        box.pack_start(label(title, "rail-label", xalign=0.5), False, False, 0)
        button.add(box)
        button.connect("clicked", lambda _b: on_click())
        return button

    def _update_rail(self):
        for name, button in self.rail_buttons.items():
            active = name == self.current
            set_class(button, "active", active)
            button._icon.set_color(ACCENT if active else MUTED)

    def show_page(self, name):
        """Go to Home or a module's page (the side menu calls this; so can modules)."""
        if self.stack.get_child_by_name(name) is None:
            return
        if self.editing and name != "home":
            self.set_editing(False)
        if name == self.current:
            if name == "home":
                self._go_home_page(0)   # Home again from Home: back to the first page
            return
        old = self.modules.get(self.current)
        if old is not None:
            safe(f"{old.name} page_hidden", old.page_hidden)
        with timed(f"show_page {name}"):
            self.current = name
            self.stack.set_visible_child_name(name)
            new = self.modules.get(name)
            if new is not None:
                safe(f"{name} page_shown", new.page_shown)
            self._update_rail()

    # ---- Home: header ---------------------------------------------------------

    def _build_home(self):
        home = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18), "home")

        header = css_class(Gtk.Box(spacing=22), "home-header")
        self.date_label = label("", "home-date")
        header.pack_start(self.date_label, False, False, 0)

        self.health_btn = css_class(Gtk.Button(), "status-chip")
        health = Gtk.Box(spacing=8)
        self.health_icon = icons.Icon("check", 20, HEALTH_COLORS["ok"], 2.4)
        self.health_label = label("Checking…", "home-health")
        health.pack_start(self.health_icon, False, False, 0)
        health.pack_start(self.health_label, False, False, 0)
        self.health_btn.add(health)
        self.health_btn.connect("clicked", lambda _b: self.show_page("system"))
        header.pack_start(self.health_btn, False, False, 0)

        self.wifi_label = label("", "home-status", max_width_chars=22,
                                ellipsize=Pango.EllipsizeMode.END)
        self.battery_label = label("", "home-status")
        for icon, size, text in (("wifi", 20, self.wifi_label), ("battery", 24, self.battery_label)):
            box = Gtk.Box(spacing=8)
            box.pack_start(icons.Icon(icon, size, MUTED), False, False, 0)
            box.pack_start(text, False, False, 0)
            header.pack_start(box, False, False, 0)

        right = Gtk.Box(spacing=14)
        self.dots = Gtk.Box(spacing=0, valign=Gtk.Align.CENTER)
        right.pack_start(self.dots, False, False, 0)
        self.header_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, hhomogeneous=False)
        self.header_stack.add_named(icon_button("pencil", "Edit home", lambda: self.set_editing(True)), "view")
        edit = Gtk.Box(spacing=12)
        edit.pack_start(icon_button("plus", "Add widget", self.open_add), False, False, 0)
        done = css_class(Gtk.Button(label="Done"), "pill", "pill-accent")
        done.connect("clicked", lambda _b: self.set_editing(False))
        edit.pack_start(done, False, False, 0)
        self.header_stack.add_named(edit, "edit")
        right.pack_start(self.header_stack, False, False, 0)
        header.pack_end(right, False, False, 0)
        home.pack_start(header, False, False, 0)

        self.body = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vexpand=True)
        holder = Gtk.EventBox()
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE,
                               hexpand=True, vexpand=True)
        holder.add(self.pages)
        # Capture phase: the swipe sees drags that start on a widget's buttons too.
        # It never claims the touch, so taps still reach the buttons.
        swipe = Gtk.GestureDrag.new(holder)
        swipe.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        swipe.connect("drag-begin", self._on_drag_begin)
        swipe.connect("drag-update", self._on_drag_update)
        swipe.connect("drag-end", self._on_drag_end)
        holder._swipe = swipe
        self._drag_on_slider = False
        self.body.add_named(holder, "grid")
        self.body.add_named(self._build_add_sheet(), "add")
        home.pack_start(self.body, True, True, 0)
        return home

    def _tick_date(self):
        text = time.strftime("%A %-d %B")
        set_text(self.date_label, text)
        return True

    def set_status(self, battery=None, wifi=None, health=None):
        """The System module reports here; the Home header shows it."""
        if battery is not None:
            set_text(self.battery_label, battery)
        if wifi is not None:
            set_text(self.wifi_label, wifi)
        if health is not None:
            level, text = health
            set_text(self.health_label, text)
            self.health_icon.set_name_("check" if level == "ok" else "warn", HEALTH_COLORS.get(level, MUTED))
            for name in HEALTH_COLORS:
                set_class(self.health_label, f"health-{name}", name == level)

    # ---- Home: the grid ----------------------------------------------------------
    # Nothing here is rebuilt. A card is built once per (widget, size) and kept; each
    # Home page is its own grid in the `pages` stack. A layout change moves cards
    # between grid cells, a page change switches the stack, and Edit mode shows or
    # hides controls that sit on every card.

    def _new_grid(self):
        grid = Gtk.Grid(column_spacing=16, row_spacing=16, column_homogeneous=True,
                        row_homogeneous=True, hexpand=True, vexpand=True)
        grid._fillers = []      # [filler Box] for the cells no card covers
        grid.show()
        self.pages.add_named(grid, str(len(self.page_grids)))
        self.page_grids.append(grid)
        return grid

    def _card(self, wid, size):
        key = (wid, size)
        card = self.cards.get(key)
        if card is None:
            with timed(f"build widget {wid} {size}"):
                tile = safe(f"widget {wid!r}", self.owners[wid].widget, wid, size)
            if tile is None:
                tile = css_class(Gtk.Box(), "widget")
                tile.add(label(f"{self.widget_info[wid][0]} couldn't load", "widget-sub", xalign=0.5))
            card = self.cards[key] = Card(wid, size, tile)
            card.root.show_all()
        return card

    def _layout_home(self):
        with timed("layout_home"):
            self._layout_home_now()

    def _layout_home_now(self):
        placed = home_layout.pack(self.items)
        pages = max((p[1] for p in placed), default=0) + 1
        self.home_page = max(0, min(self.home_page, pages - 1))
        wanted = {(item["widget"], item["size"]): (page, col, row, w, h)
                  for item, page, col, row, w, h in placed}

        # take out the cards that left Home or changed cell; the rest stay where they are
        for key, card in self.cards.items():
            if card.place is not None and wanted.get(key) != card.place:
                self.page_grids[card.place[0]].remove(card.root)
                card.place = None
        while len(self.page_grids) < pages:
            self._new_grid()
        while len(self.page_grids) > pages:
            grid = self.page_grids.pop()
            self.pages.remove(grid)
            grid.destroy()

        used = [set() for _ in range(pages)]
        for key, (page, col, row, w, h) in wanted.items():
            card = self._card(*key)
            if card.place is None:
                self.page_grids[page].attach(card.root, col, row, w, h)
                card.place = (page, col, row, w, h)
            used[page] |= {(col + dx, row + dy) for dx in range(w) for dy in range(h)}

        # an (empty) filler in every free cell keeps the 4x2 cells the same size
        for page, grid in enumerate(self.page_grids):
            free = [(col, row) for row in range(home_layout.ROWS) for col in range(home_layout.COLS)
                    if (col, row) not in used[page]]
            if [f._cell for f in grid._fillers] == free:
                continue
            for filler in grid._fillers:
                grid.remove(filler)
                filler.destroy()
            grid._fillers = []
            for col, row in free:
                filler = Gtk.Box()
                filler._cell = (col, row)
                filler._plus = None
                grid.attach(filler, col, row, 1, 1)
                filler.show()
                grid._fillers.append(filler)

        self.pages.set_visible_child(self.page_grids[self.home_page])
        self._sync_edit()
        self._render_dots(pages)

    def _render_dots(self, pages):
        dots = self.dots.get_children()
        if len(dots) != (pages if pages > 1 else 0):
            for child in dots:
                self.dots.remove(child)
                child.destroy()
            dots = []
            if pages > 1:
                for i in range(pages):
                    button = css_class(Gtk.Button(), "page-dot-btn")
                    button._dot = css_class(Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER),
                                            "page-dot")
                    button.add(button._dot)
                    button.connect("clicked", lambda _b, n=i: self._go_home_page(n))
                    self.dots.pack_start(button, False, False, 0)
                    dots.append(button)
            self.dots.show_all()
        for i, button in enumerate(dots):
            set_class(button._dot, "active", i == self.home_page)

    def _go_home_page(self, page):
        if page != self.home_page and 0 <= page < len(self.page_grids):
            with timed("home page change"):
                self.home_page = page
                self.pages.set_visible_child(self.page_grids[page])
                self._sync_edit()
                self._render_dots(len(self.page_grids))

    def _on_drag_begin(self, gesture, _x, _y):
        # A drag that starts on a slider is the slider's, not a page swipe.
        event = gesture.get_last_event(gesture.get_current_sequence())
        target = Gtk.get_event_widget(event) if event is not None else None
        while target is not None and not isinstance(target, Gtk.Scale):
            target = target.get_parent()
        self._drag_on_slider = target is not None

    def _on_drag_update(self, gesture, dx, dy):
        # Clearly sideways: take the touch, so the button it started on doesn't click too.
        if not self._drag_on_slider and abs(dx) > 30 and abs(dx) > 2 * abs(dy):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _on_drag_end(self, _gesture, dx, dy):
        if self._drag_on_slider or self.body.get_visible_child_name() != "grid":
            return
        if abs(dx) < SWIPE_PX or abs(dx) < 2 * abs(dy):
            return
        page = self.home_page + (1 if dx < 0 else -1)
        if 0 <= page < len(self.page_grids):
            # after the release is delivered, so the page isn't switched under it
            GLib.idle_add(lambda: self._go_home_page(page) and False)

    # ---- Home: Edit mode ----------------------------------------------------------

    def set_editing(self, on):
        with timed("set_editing"):
            self.editing = on
            self.header_stack.set_visible_child_name("edit" if on else "view")
            self.body.set_visible_child_name("grid")
            self._sync_edit()

    def _sync_edit(self):
        """Show the edit controls on the page in view (while editing), hide them everywhere else."""
        last = len(self.items) - 1
        for index, item in enumerate(self.items):
            card = self.cards.get((item["widget"], item["size"]))
            if card is None or card.place is None:
                continue
            on = self.editing and card.place[0] == self.home_page
            if on and card.controls is None:
                self._build_controls(card)
            if card.controls is None:
                continue
            if on != card.editing:
                card.editing = on
                set_class(card.tile, "editing", on)
                for control in card.controls:
                    control.set_visible(on)
            if on:
                card.left.set_visible(index > 0)
                card.right.set_visible(index < last)
        for card in self.cards.values():     # a card that just left Home
            if card.place is None and card.editing:
                card.editing = False
                set_class(card.tile, "editing", False)
                for control in card.controls:
                    control.set_visible(False)
        for page, grid in enumerate(self.page_grids):
            on = self.editing and page == self.home_page
            for filler in grid._fillers:
                if on and filler._plus is None:
                    filler._plus = icon_button("plus", "", self.open_add, css="edit-empty",
                                               size=36, color=MUTED)
                    filler.pack_start(filler._plus, True, True, 0)
                    filler._plus.show_all()
                if filler._plus is not None:
                    filler._plus.set_visible(on)

    def _index(self, wid):
        for index, item in enumerate(self.items):
            if item["widget"] == wid:
                return index
        return None

    def _build_controls(self, card):
        """The edit controls of one card, made the first time it is edited. They act on
        the widget's place in the list at the time of the tap, so they never go stale."""
        wid = card.wid
        shield = Gtk.EventBox(visible_window=False)   # swallows taps meant for the widget
        remove = icon_button("cross", "", lambda: self._remove(wid), css="edit-chip", size=22)
        remove.set_tooltip_text(f"Remove {self.widget_info[wid][0]}")
        self._place(remove, Gtk.Align.START, Gtk.Align.START)
        card.controls = [shield, remove]

        sizes = self.available[wid]
        if len(sizes) > 1:
            seg = css_class(Gtk.Box(spacing=4), "edit-seg")
            for s in sizes:
                button = css_class(Gtk.Button(label=s), "edit-size")
                if s == card.size:
                    css_class(button, "active")
                button.connect("clicked", lambda _b, s=s: self._resize(wid, s))
                seg.pack_start(button, False, False, 0)
            self._place(seg, Gtk.Align.END, Gtk.Align.START)
            card.controls.append(seg)

        moves = Gtk.Box(spacing=8)
        card.left = icon_button("left", "", lambda: self._move(wid, -1), css="edit-chip")
        card.right = icon_button("right", "", lambda: self._move(wid, 1), css="edit-chip")
        moves.pack_start(card.left, False, False, 0)
        moves.pack_start(card.right, False, False, 0)
        self._place(moves, Gtk.Align.END, Gtk.Align.END)
        card.controls.append(moves)

        for control in card.controls:
            card.root.add_overlay(control)
            control.show_all()
            control.hide()
            control.set_no_show_all(True)
        for arrow in (card.left, card.right):
            arrow.set_no_show_all(True)

    @staticmethod
    def _place(widget, halign, valign):
        widget.set_halign(halign)
        widget.set_valign(valign)
        widget.set_margin_start(12)
        widget.set_margin_end(12)
        widget.set_margin_top(12)
        widget.set_margin_bottom(12)

    def _set_items(self, items, follow=None):
        """New layout: save it, and show the page where widget `follow` ended up."""
        self.items = items
        try:
            home_layout.save(HOME_PATH, items)
        except OSError as exc:
            print(f"[home] could not save the layout: {exc}", flush=True)
        if follow is not None:
            for item, page, *_rest in home_layout.pack(items):
                if item["widget"] == follow:
                    self.home_page = page
        self._layout_home()

    def _remove(self, wid):
        index = self._index(wid)
        if index is not None:
            self._set_items(self.items[:index] + self.items[index + 1:])

    def _resize(self, wid, size):
        index = self._index(wid)
        if index is None or self.items[index]["size"] == size:
            return
        items = [dict(i) for i in self.items]
        items[index]["size"] = size
        self._set_items(items, follow=wid)

    def _move(self, wid, step):
        index = self._index(wid)
        if index is not None:
            self._set_items(home_layout.move(self.items, index, step), follow=wid)

    def _add(self, wid):
        preferred = dict(PREFERRED).get(wid, self.available[wid][0])
        if preferred not in self.available[wid]:
            preferred = self.available[wid][0]
        self.body.set_visible_child_name("grid")
        self._set_items(self.items + [{"widget": wid, "size": preferred}], follow=wid)

    def _build_add_sheet(self):
        sheet = css_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18), "add-sheet")
        head = Gtk.Box(spacing=16)
        head.pack_start(label("Add a widget", "add-heading"), False, False, 0)
        head.pack_end(icon_button("back", "Back", lambda: self.body.set_visible_child_name("grid")),
                      False, False, 0)
        sheet.pack_start(head, False, False, 0)
        self.add_grid = Gtk.Grid(column_spacing=16, row_spacing=16, column_homogeneous=True)
        sheet.pack_start(self.add_grid, False, False, 0)
        return sheet

    def open_add(self):
        for child in self.add_grid.get_children():
            self.add_grid.remove(child)
            child.destroy()
        placed = {i["widget"] for i in self.items}
        missing = [w for w in self.available if w not in placed]
        if not missing:
            self.add_grid.attach(label("Every widget is already on Home.", "widget-sub"), 0, 0, 1, 1)
        for n, wid in enumerate(missing):
            title, icon = self.widget_info[wid]
            button = css_class(Gtk.Button(), "add-item")
            box = Gtk.Box(spacing=16)
            box.pack_start(icons.Icon(icon, 32), False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
            text.pack_start(label(title, "add-title"), False, False, 0)
            text.pack_start(label("Sizes " + " · ".join(self.available[wid]), "widget-sub"), False, False, 0)
            box.pack_start(text, True, True, 0)
            box.pack_end(icons.Icon("plus", 26, ACCENT), False, False, 0)
            button.add(box)
            button.connect("clicked", lambda _b, w=wid: self._add(w))
            self.add_grid.attach(button, n % 3, n // 3, 1, 1)
        for n in range(len(missing), 3):   # keep three columns, so one entry isn't full width
            self.add_grid.attach(Gtk.Box(), n, 0, 1, 1)
        self.add_grid.show_all()
        self.body.set_visible_child_name("add")


def main():
    app = Dashboard()
    Gtk.main()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main())
