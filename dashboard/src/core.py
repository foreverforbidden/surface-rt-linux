"""Shared pieces for dashboard modules: the Module base class and small system helpers."""

import contextlib
import glob
import os
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


# Timing switch: DASH_PROFILE=1, or `touch ~/.local/state/dashboard/profile` on the
# tablet (run.sh passes no environment), then restart the dashboard. Lines go to app.log.
PROFILE = (os.environ.get("DASH_PROFILE") == "1"
           or os.path.exists(os.path.expanduser("~/.local/state/dashboard/profile")))


@contextlib.contextmanager
def timed(name, floor_ms=5):
    """Print how long the block took when profiling is on and it took floor_ms or more."""
    if not PROFILE:
        yield
        return
    t0 = time.monotonic()
    try:
        yield
    finally:
        ms = (time.monotonic() - t0) * 1000
        if ms >= floor_ms:
            print(f"[perf] {time.strftime('%H:%M:%S')} {name} {ms:.0f} ms", flush=True)


def watch_stalls(window=None, beat_ms=100, floor_ms=50):
    """Profiling only: log main-loop stalls (a tap waits that long) and slow window repaints."""
    if not PROFILE:
        return
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        late = (now - last[0]) * 1000 - beat_ms
        if late >= floor_ms:
            print(f"[perf] {time.strftime('%H:%M:%S')} main loop stalled {late:.0f} ms", flush=True)
        last[0] = now
        return True

    GLib.timeout_add(beat_ms, beat)
    if window is not None:
        began = [0.0]

        def before(_w, _cr):
            began[0] = time.monotonic()
            return False

        def after(_w, cr):
            ms = (time.monotonic() - began[0]) * 1000
            if ms >= 15:
                ok, clip = Gdk.cairo_get_clip_rectangle(cr)
                area = f"{clip.width}x{clip.height}" if ok else "?"
                print(f"[perf] {time.strftime('%H:%M:%S')} repaint {area} {ms:.0f} ms", flush=True)
            return False

        window.connect("draw", before)
        window.connect_after("draw", after)


def set_text(widget, text):
    """Label.set_text only when the text changed, so an unchanged tick costs no layout."""
    if widget.get_text() != text:
        widget.set_text(text)


def read_sysfs(path, default=None):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return default


def run_cmd(args, timeout=3):
    """Run a command and return its stdout ('' on any failure)."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


class Backlight:
    """The panel backlight. The udev rule in system/90-backlight.rules lets the video group write it."""

    def __init__(self):
        dirs = sorted(glob.glob("/sys/class/backlight/*"))
        self.dir = dirs[0] if dirs else None
        self.max = int(read_sysfs(f"{self.dir}/max_brightness", "0")) if self.dir else 0
        self._saved = None

    def get(self):
        return int(read_sysfs(f"{self.dir}/brightness", "0")) if self.dir else 0

    def set(self, value):
        if not self.dir:
            return False
        value = max(0, min(self.max, int(value)))
        try:
            with open(f"{self.dir}/brightness", "w") as fh:
                fh.write(str(value))
            return True
        except OSError:
            # Fall back to sudo if the udev rule isn't in place yet.
            return subprocess.run(
                ["sudo", "-n", "tee", f"{self.dir}/brightness"],
                input=str(value), text=True, capture_output=True,
            ).returncode == 0

    def off(self):
        cur = self.get()
        if cur > 0:
            self._saved = cur
        self.set(0)

    def on(self):
        self.set(self._saved or self.max // 2)


class Module:
    """Base class for a dashboard module.

    A module can give the Home screen widgets, the side menu an entry with a
    full page, or both:
      - `widgets`: {widget id: (title, allowed sizes)}; sizes are "S" (1x1),
        "M" (2x1) and "L" (2x2) cells of the Home grid. widget(wid, size)
        builds a NEW Gtk.Widget and fills it from data the module already has.
        Home calls it once per (widget, size) and keeps the result for good,
        also while that widget is off Home, so keep updating every one you made.
        (forget_widgets() resets the module's own lists in setup(); Home never calls it.)
      - `icon` + `menu_title` + page(): a side-menu entry and its page, built
        once. page_shown() / page_hidden() fire when the user goes to / leaves it.
    setup() runs once, after every module is constructed and before any widget
    or page is built. Set `interval` (seconds) to have update() called.
    """

    name = "module"
    interval = 0
    icon = None
    menu_title = ""
    widgets = {}

    def __init__(self, app):
        self.app = app  # the Dashboard: app.backlight, app.show_page(), app.quit_for_restart()

    def setup(self):
        pass

    def widget(self, wid, size):
        raise NotImplementedError

    def forget_widgets(self):
        pass

    def page(self):
        return None

    def page_shown(self):
        pass

    def page_hidden(self):
        pass

    def page_open(self):
        """True while this module's page is the one on screen."""
        return getattr(self.app, "current", None) == self.name

    def update(self):
        pass

    # Called by the dashboard after build(); wires up the periodic update.
    def start(self):
        with timed(f"{self.name} update"):
            self.update()
        if self.interval:
            GLib.timeout_add_seconds(self.interval, self._tick)

    def _tick(self):
        try:
            with timed(f"{self.name} update"):
                self.update()
        except Exception as exc:  # a broken module must not take the dashboard down
            print(f"[{self.name}] update failed: {exc}", flush=True)
        return True


def label(text, css=None, xalign=0.0, **props):
    widget = Gtk.Label(label=text, xalign=xalign, **props)
    if css:
        for name in css.split():
            widget.get_style_context().add_class(name)
    return widget


def tile(child, on_tap=None, size="S"):
    """A Home widget's card. A tap on it (not on a button inside it) calls on_tap()."""
    box = Gtk.EventBox()
    box.get_style_context().add_class("widget")
    box.get_style_context().add_class(f"widget-{size}")
    body = Gtk.Box()   # an EventBox ignores CSS padding; a Box doesn't
    body.get_style_context().add_class("widget-body")
    body.pack_start(child, True, True, 0)
    box.add(body)
    if on_tap is not None:
        tap = Gtk.GestureMultiPress.new(box)
        tap.connect("released", lambda _g, _n, _x, _y: on_tap())
        box._tap = tap  # keep the gesture alive: PyGObject drops unreferenced ones
    return box


def widget_head(icon_name, title):
    """The small icon + title line at the top of a widget."""
    import icons  # here, not at the top: tests import core without GTK icons
    head = Gtk.Box(spacing=10)
    head.pack_start(icons.Icon(icon_name, 22, "#C4CCD4"), False, False, 0)
    head.pack_start(label(title, "widget-title"), False, False, 0)
    return head


def card(title, child):
    """Wrap a widget in a styled tile with an optional heading."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.get_style_context().add_class("card")
    if title:
        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("card-title")
        box.pack_start(heading, False, False, 0)
    box.pack_start(child, True, True, 0)
    return box
