"""Tap-to-fix: Wi-Fi checks, service controls and the FixPanel widget.

Used by the System tile's fullscreen view (modules/system.py) and by the
standalone rescue screen (rescue.py), so it must not import anything from
modules/. Every command runs off the GTK thread, so a slow ping or a
`systemctl restart` never freezes the screen.
"""

import subprocess
import threading

WIFI_IF = "mlan0"
WPA_CLI = "/sbin/wpa_cli"
IW = "/sbin/iw"
SERVICES = ("ssh", "lightdm")
# Restarting these can cut the screen or the network for a moment: arm first.
RISKY = {"lightdm"}
DNS_NAME = "deb.debian.org"
INTERNET_IP = "1.1.1.1"


# ---- pure helpers (no GTK, tested on the Mac) -------------------------------

def parse_wpa_status(text):
    """`wpa_cli status` output -> dict of key=value lines."""
    out = {}
    for line in (text or "").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_ipv4(text):
    """`ip -4 -o addr show <if>` output -> the first address without prefix, or ''."""
    for line in (text or "").splitlines():
        parts = line.split()
        if "inet" in parts:
            i = parts.index("inet")
            if i + 1 < len(parts):
                return parts[i + 1].split("/")[0]
    return ""


def default_gateway(text):
    """`ip -4 route show default` output -> gateway address, or ''."""
    for line in (text or "").splitlines():
        parts = line.split()
        if parts[:1] == ["default"] and "via" in parts:
            i = parts.index("via")
            if i + 1 < len(parts):
                return parts[i + 1]
    return ""


def parse_power_save(text):
    """`iw dev <if> get power_save` -> True (on), False (off) or None (unknown)."""
    value = (text or "").strip().lower()
    if value.endswith(": on"):
        return True
    if value.endswith(": off"):
        return False
    return None


def parse_failed_units(text):
    """`systemctl --failed --plain --no-legend` -> list of unit names."""
    units = []
    for line in (text or "").splitlines():
        parts = line.replace("●", " ").split()
        if parts and "." in parts[0]:
            units.append(parts[0])
    return units


def parse_is_active(names, text):
    """`systemctl is-active a b c` prints one state per line, in order."""
    states = (text or "").split()
    return {name: (states[i] if i < len(states) else "unknown") for i, name in enumerate(names)}


def health(state):
    """The worst problem in a collect() result -> (level, text). level: ok | warn | bad."""
    problems = []  # (rank, level, text): lower rank is worse
    wifi = state.get("wifi", {})
    if wifi.get("wpa_state") != "COMPLETED":
        problems.append((0, "bad", "Wi-Fi not connected"))
    elif not state.get("ip"):
        problems.append((1, "bad", "Wi-Fi has no IP address"))
    elif state.get("gateway_ok") is False:
        problems.append((2, "bad", "router not reachable"))
    for name, active in state.get("services", {}).items():
        if active != "active":
            problems.append((3, "bad", f"{name} is {active}"))
    if state.get("internet_ok") is False and not any(r <= 2 for r, _l, _t in problems):
        problems.append((4, "warn", "no internet"))
    elif state.get("dns_ok") is False and state.get("internet_ok"):
        problems.append((5, "warn", "DNS not working"))
    failed = state.get("failed", [])
    if failed:
        problems.append((6, "warn", f"{len(failed)} failed unit" + ("s" if len(failed) > 1 else "")))
    if state.get("power_save") is True:
        problems.append((7, "warn", "Wi-Fi power save is on"))
    if not problems:
        return "ok", "All good"
    problems.sort()
    _rank, level, text = problems[0]
    if len(problems) > 1:
        text += f" (+{len(problems) - 1} more)"
    return level, text


# ---- commands --------------------------------------------------------------

def run(args, timeout=10):
    """Run a command -> (ok, output). Never raises."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as exc:
        return False, str(exc)


def _ping(host):
    return run(["ping", "-c", "1", "-W", "2", host], timeout=5)[0]


def collect(network=True):
    """Gather everything the panel and the health line show. Blocking: call off the GTK thread.

    network=False skips the pings and DNS lookup (they're left as None, "not checked").
    """
    _ok, wpa = run([WPA_CLI, "-i", WIFI_IF, "status"], timeout=4)
    _ok, addr = run(["ip", "-4", "-o", "addr", "show", WIFI_IF], timeout=4)
    _ok, route = run(["ip", "-4", "route", "show", "default"], timeout=4)
    _ok, ps = run([IW, "dev", WIFI_IF, "get", "power_save"], timeout=4)
    _ok, active = run(["systemctl", "is-active", *SERVICES], timeout=6)
    _ok, failed = run(["systemctl", "--failed", "--plain", "--no-legend"], timeout=6)
    state = {
        "wifi": parse_wpa_status(wpa),
        "ip": parse_ipv4(addr),
        "gateway": default_gateway(route),
        "power_save": parse_power_save(ps),
        "services": parse_is_active(SERVICES, active),
        "failed": parse_failed_units(failed),
        "gateway_ok": None, "internet_ok": None, "dns_ok": None,
    }
    if network:
        state["gateway_ok"] = _ping(state["gateway"]) if state["gateway"] else False
        state["internet_ok"] = _ping(INTERNET_IP)
        state["dns_ok"] = run(["getent", "hosts", DNS_NAME], timeout=5)[0]
    return state


WIFI_ACTIONS = (
    # (label, command, risky)
    ("Reconnect", ["sudo", "-n", WPA_CLI, "-i", WIFI_IF, "reassociate"], False),
    ("Power save off", ["sudo", "-n", IW, "dev", WIFI_IF, "set", "power_save", "off"], False),
    ("Restart network", ["sudo", "-n", "systemctl", "restart", "dhcpcd"], True),
)


def restart_unit_cmd(unit):
    return ["sudo", "-n", "systemctl", "restart", unit]


# ---- GTK -------------------------------------------------------------------
# Imported lazily so the helpers above can be tested without GTK.

def _gtk():
    from gi.repository import GLib, Gtk, Pango
    return GLib, Gtk, Pango


def run_async(args, done, timeout=30):
    """Run a command in a thread; call done(ok, output) on the GTK loop."""
    GLib, _Gtk, _Pango = _gtk()

    def work():
        ok, out = run(args, timeout=timeout)
        GLib.idle_add(lambda: done(ok, out) and False)

    threading.Thread(target=work, daemon=True).start()


def call_async(fn, done):
    """Run fn() in a thread; call done(result) on the GTK loop."""
    GLib, _Gtk, _Pango = _gtk()

    def work():
        try:
            result = fn()
        except Exception as exc:  # a failed check must not kill the thread silently
            print(f"[sysfix] {exc}", flush=True)
            result = None
        GLib.idle_add(lambda: done(result) and False)

    threading.Thread(target=work, daemon=True).start()


def arm_button(button, label, action, seconds=4):
    """First tap shows "Tap again"; a second tap within `seconds` runs action()."""
    GLib, _Gtk, _Pango = _gtk()
    state = {"armed": False}

    def disarm():
        state["armed"] = False
        button.set_label(label)
        return False

    def clicked(_b):
        if not state["armed"]:
            state["armed"] = True
            button.set_label("Tap again")
            GLib.timeout_add_seconds(seconds, disarm)
            return
        state["armed"] = False
        action()

    button.set_label(label)
    button.connect("clicked", clicked)
    return button


def label(text, css_class=None, xalign=0.0, ellipsize=False):
    _GLib, Gtk, Pango = _gtk()
    lab = Gtk.Label(label=text, xalign=xalign)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
    if css_class:
        lab.get_style_context().add_class(css_class)
    return lab


def _set_level(widget, level):
    ctx = widget.get_style_context()
    for name in ("fix-ok", "fix-warn", "fix-bad", "fix-unknown"):
        ctx.remove_class(name)
    ctx.add_class(f"fix-{level}")


def _make_panel_class():
    _GLib, Gtk, _Pango = _gtk()

    class FixPanel(Gtk.Box):
        """Wi-Fi checks and actions on the left, services on the right, a status line below.

        airplay: optional (is_running, stop) callables for the dashboard's uxplay receiver.
        on_change: optional callback(state) after every refresh (e.g. to update a health line).
        """

        def __init__(self, airplay=None, on_change=None):
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            self.airplay = airplay
            self.on_change = on_change
            self._busy = False
            self._again = False

            cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20, homogeneous=True)
            cols.pack_start(self._build_wifi(), True, True, 0)
            cols.pack_start(self._build_services(), True, True, 0)
            self.pack_start(cols, True, True, 0)

            self.status = label("", "fix-status", ellipsize=True)
            self.pack_start(self.status, False, False, 0)

        # -- layout --

        def _panel(self, title):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.get_style_context().add_class("fix-panel")
            box.pack_start(label(title, "card-title"), False, False, 0)
            return box

        def _check_row(self, grid, row, name):
            mark = label("…", "fix-mark", xalign=0.5)
            mark.set_size_request(28, -1)
            key = label(name, "fix-key")
            value = label("", "fix-value", xalign=1.0, ellipsize=True)
            value.set_hexpand(True)
            grid.attach(mark, 0, row, 1, 1)
            grid.attach(key, 1, row, 1, 1)
            grid.attach(value, 2, row, 1, 1)
            return mark, value

        def _build_wifi(self):
            panel = self._panel("Wi-Fi")
            grid = Gtk.Grid(column_spacing=12, row_spacing=8)
            self.checks = {}
            for i, (key, name) in enumerate((
                ("assoc", "Connected"), ("ip", "IP address"), ("gateway", "Router"),
                ("internet", "Internet"), ("dns", "DNS"), ("power", "Power save"),
            )):
                self.checks[key] = self._check_row(grid, i, name)
            panel.pack_start(grid, False, False, 0)

            buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            for text, cmd, risky in WIFI_ACTIONS:
                btn = Gtk.Button()
                btn.get_style_context().add_class("fix-btn")
                act = (lambda c=cmd, t=text: self._do(t, c))
                if risky:
                    btn.get_style_context().add_class("danger")
                    arm_button(btn, text, act)
                else:
                    btn.set_label(text)
                    btn.connect("clicked", lambda _b, a=act: a())
                buttons.pack_start(btn, False, False, 0)
            panel.pack_end(buttons, False, False, 0)
            return panel

        def _build_services(self):
            panel = self._panel("Services")
            grid = Gtk.Grid(column_spacing=12, row_spacing=10)
            self.svc_rows = {}
            names = list(SERVICES) + (["airplay"] if self.airplay else [])
            for i, name in enumerate(names):
                mark = label("…", "fix-mark", xalign=0.5)
                mark.set_size_request(28, -1)
                key = label("AirPlay" if name == "airplay" else name, "fix-key")
                value = label("", "fix-value", xalign=1.0)
                value.set_hexpand(True)
                btn = Gtk.Button()
                btn.get_style_context().add_class("fix-row-btn")
                if name == "airplay":
                    btn.set_label("Stop")
                    btn.connect("clicked", lambda _b: self._stop_airplay())
                elif name in RISKY:
                    btn.get_style_context().add_class("danger")
                    arm_button(btn, "Restart", lambda n=name: self._do(f"Restart {n}", restart_unit_cmd(n)))
                else:
                    btn.set_label("Restart")
                    btn.connect("clicked", lambda _b, n=name: self._do(f"Restart {n}", restart_unit_cmd(n)))
                grid.attach(mark, 0, i, 1, 1)
                grid.attach(key, 1, i, 1, 1)
                grid.attach(value, 2, i, 1, 1)
                grid.attach(btn, 3, i, 1, 1)
                self.svc_rows[name] = (mark, value, btn)
            panel.pack_start(grid, False, False, 0)

            panel.pack_start(label("Failed units", "fix-subtitle"), False, False, 6)
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_kinetic_scrolling(True)
            self.failed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            scroll.add(self.failed_box)
            panel.pack_start(scroll, True, True, 0)

            refresh = Gtk.Button(label="Check again")
            refresh.get_style_context().add_class("fix-btn")
            refresh.connect("clicked", lambda _b: self.refresh())
            panel.pack_end(refresh, False, False, 0)
            return panel

        # -- data --

        def refresh(self):
            if self._busy:
                self._again = True
                return
            self._busy = True
            call_async(collect, self._apply)

        def _apply(self, state):
            self._busy = False
            if state is not None:
                self._fill(state)
                if self.on_change:
                    self.on_change(state)
            if self._again:
                self._again = False
                self.refresh()

        def _set_check(self, key, level, text):
            mark, value = self.checks[key]
            mark.set_text({"ok": "✓", "bad": "✗", "warn": "!", "unknown": "–"}[level])
            _set_level(mark, level)
            value.set_text(text)

        @staticmethod
        def _tri(value, ok_text, bad_text):
            if value is None:
                return "unknown", "not checked"
            return ("ok", ok_text) if value else ("bad", bad_text)

        def _fill(self, state):
            wifi = state["wifi"]
            connected = wifi.get("wpa_state") == "COMPLETED"
            self._set_check("assoc", "ok" if connected else "bad",
                            wifi.get("ssid", "") if connected else (wifi.get("wpa_state") or "no answer").lower())
            self._set_check("ip", "ok" if state["ip"] else "bad", state["ip"] or "none")
            gw = state["gateway"] or "no route"
            self._set_check("gateway", *self._tri(state["gateway_ok"], gw, f"{gw}: no reply"))
            self._set_check("internet", *self._tri(state["internet_ok"], INTERNET_IP, f"{INTERNET_IP}: no reply"))
            self._set_check("dns", *self._tri(state["dns_ok"], DNS_NAME, "lookup failed"))
            ps = state["power_save"]
            self._set_check("power", "unknown" if ps is None else ("warn" if ps else "ok"),
                            "unknown" if ps is None else ("on" if ps else "off"))

            for name, active in state["services"].items():
                mark, value, _btn = self.svc_rows[name]
                level = "ok" if active == "active" else "bad"
                mark.set_text("✓" if level == "ok" else "✗")
                _set_level(mark, level)
                value.set_text(active)
            if self.airplay:
                mark, value, btn = self.svc_rows["airplay"]
                running = bool(self.airplay[0]())
                mark.set_text("●" if running else "○")
                _set_level(mark, "ok" if running else "unknown")
                value.set_text("running" if running else "stopped")
                btn.set_sensitive(running)

            for child in self.failed_box.get_children():
                child.destroy()
            if not state["failed"]:
                self.failed_box.pack_start(label("none", "fix-value"), False, False, 0)
            for unit in state["failed"]:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                row.pack_start(label(unit, "fix-key", ellipsize=True), True, True, 0)
                btn = Gtk.Button(label="Restart")
                btn.get_style_context().add_class("fix-row-btn")
                btn.connect("clicked", lambda _b, u=unit: self._do(f"Restart {u}", restart_unit_cmd(u)))
                row.pack_end(btn, False, False, 0)
                self.failed_box.pack_start(row, False, False, 0)
            self.failed_box.show_all()

        # -- actions --

        def _say(self, text, level=None):
            self.status.set_text(text)
            _set_level(self.status, level or "unknown")

        def _do(self, what, cmd):
            self._say(f"{what}…")

            def done(ok, out):
                if ok:
                    self._say(f"{what}: done", "ok")
                else:
                    last = out.splitlines()[-1] if out else "failed"
                    self._say(f"{what} failed: {last}", "bad")
                # Wi-Fi needs a few seconds to settle before the checks mean anything.
                GLib_, _G, _P = _gtk()
                GLib_.timeout_add_seconds(3, lambda: self.refresh() and False)

            run_async(cmd, done)

        def _stop_airplay(self):
            self._say("Stopping AirPlay…")
            try:
                self.airplay[1]()
            finally:
                subprocess.run(["pkill", "-x", "uxplay"], capture_output=True)
            self._say("AirPlay stopped", "ok")
            self.refresh()

    return FixPanel


_FixPanel = None


def FixPanel(*args, **kwargs):  # noqa: N802 - looks like a class to callers
    global _FixPanel
    if _FixPanel is None:
        _FixPanel = _make_panel_class()
    return _FixPanel(*args, **kwargs)
