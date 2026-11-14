"""System: battery, network, load, health, brightness and volume.

Home widgets: System (health, battery, CPU / RAM) and Controls (big brightness
and volume bars). The System page has the details, the sliders, Restart app /
Reboot, and the tap-to-fix panel (sysfix.FixPanel): Wi-Fi checks and fixes, and
service restarts. The Home header's health chip, Wi-Fi and battery come from here.
"""

import os
import subprocess
import threading
import time

from gi.repository import GLib, Gtk, Pango

import core
import icons
import sysfix
import volume

BATTERY = "/sys/class/power_supply/surface-rt-battery"
CPU_TEMP = "/sys/class/thermal/thermal_zone1/temp"  # cpu-thermal
WIFI_IF = sysfix.WIFI_IF
HEALTH_INTERVAL = 30  # seconds; each check pings the router once
PAGE_REFRESH = 10
POLL_S = 5            # battery, load, memory, temperature
CPUS = os.cpu_count() or 4
HEALTH_ICON = {"ok": ("check", "#5FC48C"), "warn": ("warn", "#E8A86B"), "bad": ("warn", "#E87B7B")}


def _row(label_text):
    row = Gtk.Box(spacing=12)
    row.pack_start(core.label(label_text, "sys-key"), False, False, 0)
    # Ellipsize so a long value (e.g. an SSID) can't widen the window past the screen.
    value = Gtk.Label(xalign=1, hexpand=True, ellipsize=Pango.EllipsizeMode.END, width_chars=6)
    value.get_style_context().add_class("sys-value")
    row.pack_end(value, True, True, 0)
    return row, value


def _bar():
    bar = Gtk.LevelBar(min_value=0, max_value=1)
    bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
    for name in ("low", "high", "full"):     # one colour, no traffic-light offsets
        bar.remove_offset_value(name)
    bar.get_style_context().add_class("meter")
    return bar


class Module(core.Module):
    name = "system"
    icon = "chip"
    menu_title = "System"
    widgets = {
        "system": ("System", ("S", "M"), "chip"),
        "controls": ("Brightness & volume", ("S", "M"), "sun"),
    }

    def setup(self):
        self.data = {}
        self.health = None
        self.panel = None
        self._page_timer = 0
        self._health_busy = False
        self._raw = None          # the last _read()
        self._net = None          # (ssid, ip) from the last sysfix.collect(); None until the first
        self._bright_written = None
        self._bright_touched = 0.0
        self.forget_widgets()
        vol = getattr(self.app, "volume", None)
        if vol is not None and vol.available:
            vol.listeners.append(self._on_volume)
        GLib.timeout_add_seconds(HEALTH_INTERVAL, self._health_tick)
        GLib.timeout_add_seconds(2, lambda: self._health_tick() and False)
        # Wi-Fi name and address right away, without waiting for the first health check's pings
        sysfix.call_async(lambda: sysfix.collect(network=False), self._on_net)

    def forget_widgets(self):
        self._views = []          # system widgets: dicts of labels / bars to fill
        self._bright = []         # brightness scales on Home
        self._vols = []           # volume scales on Home

    # ---- sliders (Home and page share these helpers) ------------------------

    def _bright_scale(self, orientation):
        bl = self.app.backlight
        scale = Gtk.Scale.new_with_range(orientation, 5, max(bl.max, 6), 1)
        scale.set_draw_value(False)
        scale.set_value(max(5, bl.get()))
        scale.connect("value-changed", lambda s: self._set_brightness(s.get_value()))
        return scale

    def _set_brightness(self, value):
        value = int(value)
        self._bright_touched = time.monotonic()
        if value != self._bright_written:     # a drag reports the same step many times
            self._bright_written = value
            self.app.backlight.set(value)

    def _volume_scale(self, orientation):
        vol = getattr(self.app, "volume", None)
        if vol is None or not vol.available:
            return None
        scale = Gtk.Scale.new_with_range(orientation, 0, volume.STEPS, 1)
        scale.set_draw_value(False)
        scale.set_value(vol.step)
        scale.connect("value-changed", lambda s: vol.set(round(s.get_value()), show=False))
        return scale

    def _on_volume(self, step):
        for scale in self._vols + ([self.page_vol] if getattr(self, "page_vol", None) else []):
            if round(scale.get_value()) != step:
                scale.set_value(step)

    # ---- Home widgets -------------------------------------------------------

    def widget(self, wid, size):
        if wid == "controls":
            return self._controls_widget(size)
        return self._system_widget(size)

    def _controls_widget(self, size):
        vertical = size == "S"
        orient = Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if vertical else Gtk.Orientation.VERTICAL,
                      spacing=14, homogeneous=True)
        pairs = [("sun", self._bright_scale(orient), self._bright)]
        vol_scale = self._volume_scale(orient)
        if vol_scale is not None:
            pairs.append(("speaker", vol_scale, self._vols))
        for icon, scale, registry in pairs:
            registry.append(scale)
            scale.get_style_context().add_class("big-bar")
            if vertical:
                scale.set_inverted(True)     # up is brighter / louder
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                col.pack_start(scale, True, True, 0)
                col.pack_start(icons.Icon(icon, 28, "#C4CCD4"), False, False, 0)
            else:
                col = Gtk.Box(spacing=14)
                col.pack_start(icons.Icon(icon, 28, "#C4CCD4"), False, False, 0)
                col.pack_start(scale, True, True, 0)
            box.pack_start(col, True, True, 0)
        return core.tile(box, None, size)

    def _system_widget(self, size):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.pack_start(core.widget_head("chip", "System"), False, False, 0)
        view = {"size": size}
        health = Gtk.Box(spacing=10)
        view["health_icon"] = icons.Icon("check", 26, "#5FC48C", 2.4)
        view["health_text"] = core.label("Checking…", "sys-w-health", ellipsize=Pango.EllipsizeMode.END)
        health.pack_start(view["health_icon"], False, False, 0)
        health.pack_start(view["health_text"], True, True, 0)
        box.pack_start(health, False, False, 0)
        box.pack_start(Gtk.Box(), True, True, 0)
        if size == "M":
            meters = Gtk.Box(spacing=24, homogeneous=True)
            for key, title in (("cpu", "CPU"), ("ram", "RAM")):
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                line = Gtk.Box()
                line.pack_start(core.label(title, "widget-sub"), False, False, 0)
                view[key] = core.label("", "sys-w-value", xalign=1)
                line.pack_end(view[key], False, False, 0)
                col.pack_start(line, False, False, 0)
                view[key + "_bar"] = _bar()
                col.pack_start(view[key + "_bar"], False, False, 0)
                meters.pack_start(col, True, True, 0)
            box.pack_start(meters, False, False, 0)
        foot = Gtk.Box(spacing=12)
        view["net"] = core.label("", "widget-sub", ellipsize=Pango.EllipsizeMode.END)
        view["battery"] = core.label("", "widget-sub", xalign=1)
        foot.pack_start(view["net"], True, True, 0)
        foot.pack_end(view["battery"], False, False, 0)
        box.pack_start(foot, False, False, 0)
        self._views.append(view)
        self._fill_view(view)
        return core.tile(box, lambda: self.app.show_page(self.name), size)

    def _fill_view(self, view):
        d = self.data
        if self.health is not None:
            level, text = self.health
            icon, color = HEALTH_ICON[level]
            view["health_icon"].set_name_(icon, color)
            core.set_text(view["health_text"], text)
        if not d:
            return
        core.set_text(view["battery"], f"Battery {d['battery']}")
        core.set_text(view["net"], d["ip"] if view["size"] == "S" else f"{d['ssid']} · {d['ip']}")
        if "cpu" in view:
            core.set_text(view["cpu"], d["load"])
            core.set_text(view["ram"], d["mem"])
            for bar, value in ((view["cpu_bar"], min(1.0, d["load1"] / CPUS)),
                               (view["ram_bar"], d["mem_frac"])):
                if abs(bar.get_value() - value) >= 0.01:   # under 1 %: not worth a repaint
                    bar.set_value(value)

    # ---- the System page ----------------------------------------------------

    def page(self):
        root = Gtk.Box(spacing=24)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.get_style_context().add_class("sys-panel")
        left.set_size_request(400, -1)
        left.pack_start(core.label("System", "page-heading"), False, False, 4)
        self.page_values = {}
        for key, title in (("battery", "Battery"), ("ssid", "Wi-Fi"), ("ip", "IP"),
                           ("load", "CPU"), ("mem", "RAM")):
            row, value = _row(title)
            left.pack_start(row, False, False, 0)
            self.page_values[key] = value

        left.pack_start(core.label("Brightness", "sys-key"), False, False, 6)
        self.page_bright = self._bright_scale(Gtk.Orientation.HORIZONTAL)
        self.page_bright.get_style_context().add_class("big-bar")
        left.pack_start(self.page_bright, False, False, 0)
        self.page_vol = self._volume_scale(Gtk.Orientation.HORIZONTAL)
        if self.page_vol is not None:
            left.pack_start(core.label("Volume", "sys-key"), False, False, 6)
            self.page_vol.get_style_context().add_class("big-bar")
            left.pack_start(self.page_vol, False, False, 0)

        buttons = Gtk.Box(spacing=12, homogeneous=True)
        restart = Gtk.Button(label="Restart app")
        restart.connect("clicked", lambda _b: self.app.quit_for_restart())
        self.reboot = Gtk.Button()
        self.reboot.get_style_context().add_class("danger")
        sysfix.arm_button(self.reboot, "Reboot", self._reboot)
        buttons.pack_start(restart, True, True, 0)
        buttons.pack_start(self.reboot, True, True, 0)
        left.pack_end(buttons, False, False, 0)
        root.pack_start(left, False, False, 0)

        self.fix_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.fix_holder.pack_start(core.label("Fixes", "page-heading"), False, False, 4)
        root.pack_start(self.fix_holder, True, True, 0)
        return root

    def page_shown(self):
        if self.panel is None:
            # Built on first open: every module (AirPlay too) is loaded by then.
            self.panel = sysfix.FixPanel(airplay=self._airplay(), on_change=self._on_state)
            self.fix_holder.pack_start(self.panel, True, True, 0)
            self.panel.show_all()
        self.panel.refresh()
        self.update()
        if not self._page_timer:
            self._page_timer = GLib.timeout_add_seconds(PAGE_REFRESH, self._page_tick)

    def page_hidden(self):
        if self._page_timer:
            GLib.source_remove(self._page_timer)
            self._page_timer = 0

    def _page_tick(self):
        self.panel.refresh()
        return True

    def _airplay(self):
        mod = getattr(self.app, "modules", {}).get("airplay")
        if mod is None:
            return None
        return (lambda: mod.proc is not None, mod.stop)

    def _reboot(self):
        self.reboot.set_label("Rebooting…")
        subprocess.Popen(["sudo", "-n", "systemctl", "reboot"])

    # ---- health -------------------------------------------------------------

    def _health_tick(self):
        if not self._health_busy and not self.page_open():   # the page's panel refreshes itself
            self._health_busy = True
            sysfix.call_async(sysfix.collect, self._on_state)
        return True

    def _on_net(self, state):
        if state is not None:
            self._net = (state.get("wifi", {}).get("ssid", ""), state.get("ip", ""))
            self.update()

    def _on_state(self, state):
        self._health_busy = False
        if state is None:
            return
        self._net = (state.get("wifi", {}).get("ssid", ""), state.get("ip", ""))
        self.health = sysfix.health(state)
        if hasattr(self.app, "set_status"):
            self.app.set_status(health=self.health)
        for view in self._views:
            self._fill_view(view)

    # ---- the numbers --------------------------------------------------------

    def start(self):
        # The sysfs reads (battery and temperature go over I2C) sometimes take 50-100 ms,
        # so a thread does them and the GTK thread only shows the result.
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self):
        while True:
            try:
                raw = self._read()
            except Exception as exc:  # a failed read must not end the polling
                print(f"[system] read failed: {exc}", flush=True)
                raw = None
            if raw is not None:
                GLib.idle_add(self._apply, raw)
            time.sleep(POLL_S)

    def _read(self):
        """The raw numbers. Runs in the polling thread: no GTK in here."""
        info = {}
        for line in core.read_sysfs("/proc/meminfo", "").splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) if rest.split() else 0
        return {
            "cap": core.read_sysfs(f"{BATTERY}/capacity", "?"),
            "status": core.read_sysfs(f"{BATTERY}/status", ""),
            "load1": os.getloadavg()[0],
            "temp": core.read_sysfs(CPU_TEMP),
            "total": info.get("MemTotal", 0),
            "avail": info.get("MemAvailable", 0),
            "brightness": self.app.backlight.get(),
        }

    def _apply(self, raw):
        self._raw = raw
        with core.timed("system apply"):
            self.update()
        return False

    def update(self):
        """Show the last numbers read (GTK thread; no I/O)."""
        raw = self._raw
        if raw is None:
            return
        suffix = {"Charging": " charging", "Full": " (full)"}.get(raw["status"], "")
        # The Wi-Fi name and address come from the health check, which also runs in a
        # thread (_on_state).
        if self._net is None:
            ssid, ip = "…", "…"
        else:
            ssid, ip = self._net[0] or "not connected", self._net[1] or "–"
        load1, temp = raw["load1"], raw["temp"]
        temp_txt = f" · {int(temp) / 1000:.0f}°C" if temp else ""
        total, avail = raw["total"], raw["avail"]

        self.data = d = {
            "battery": f"{raw['cap']}%{suffix}",
            "ssid": ssid,
            "ip": ip,
            "load1": load1,
            "load": f"{load1:.2f}{temp_txt}",
            "mem": f"{(total - avail) // 1024} / {total // 1024} MB",
            "mem_frac": (total - avail) / total if total else 0.0,
        }
        if hasattr(self.app, "set_status"):
            self.app.set_status(battery=d["battery"], wifi=d["ssid"])
        for view in self._views:
            self._fill_view(view)
        if self.page_open():
            for key, value in getattr(self, "page_values", {}).items():
                core.set_text(value, d[key])

        # Keep the brightness sliders in sync if it was changed elsewhere (e.g. backlight.sh).
        # Not while a slider is in use: the reading is a moment old and would pull it back.
        cur = raw["brightness"]
        page_bright = getattr(self, "page_bright", None)
        if time.monotonic() - self._bright_touched < 2:
            return
        for scale in self._bright + ([page_bright] if page_bright else []):
            if cur >= 5 and abs(cur - scale.get_value()) >= 1:
                scale.set_value(cur)
