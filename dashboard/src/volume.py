"""Speaker volume: the tablet's hardware volume buttons, an on-screen level bar, and
the level itself (ALSA "Speaker Volume" on the WM8962).

The buttons are read straight from the gpio-keys input device (the user is in the
`input` group), so they work whichever window has focus and while the screen is off.
ALSA is the source of truth: alsa-restore saves the level at shutdown and restores it
at boot. GTK is imported only inside Volume, so the Mac can test the rest.
"""

import os
import struct
import subprocess

CARD = "WM8962"
CONTROL = "Speaker Volume"
KEYS_DEVICE = "/dev/input/by-path/platform-gpio-keys-event"

STEPS = 16       # like the Mac's volume keys
RAW_TOP = 121    # 0 dB; the control goes to 127 (+6 dB), which only distorts these speakers
RAW_PER_STEP = 3  # 3 dB a step, so step 1 is -45 dB

EVENT = struct.Struct("llHHi")   # struct input_event: time (2 longs), type, code, value
EV_KEY, KEY_VOLUMEDOWN, KEY_VOLUMEUP = 1, 114, 115
REPEAT_DELAY, REPEAT_EVERY = 400, 110   # ms, while a button is held


def step_to_raw(step):
    step = max(0, min(STEPS, int(step)))
    return 0 if step == 0 else RAW_TOP - RAW_PER_STEP * (STEPS - step)


def raw_to_step(raw):
    if raw <= 0:
        return 0
    return max(1, min(STEPS, STEPS - round((RAW_TOP - raw) / RAW_PER_STEP)))


def parse_raw(amixer_output):
    """The left channel's value from `amixer cget` output, or None."""
    for line in amixer_output.splitlines():
        line = line.strip()
        if line.startswith(": values="):
            try:
                return int(line[len(": values="):].split(",")[0])
            except ValueError:
                return None
    return None


def parse_keys(data):
    """Raw input events -> [(+1 or -1, pressed)] for the volume buttons (autorepeat ignored)."""
    keys = []
    for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
        _sec, _usec, kind, code, value = EVENT.unpack_from(data, offset)
        if kind == EV_KEY and code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN) and value in (0, 1):
            keys.append((1 if code == KEY_VOLUMEUP else -1, value == 1))
    return keys


def read_step():
    try:
        out = subprocess.run(["amixer", "-c", CARD, "cget", f"name={CONTROL}"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    raw = parse_raw(out)
    return None if raw is None else raw_to_step(raw)


_pipe = None   # a long-lived `amixer -s`: a level change is one line to it, not a new process


def _send(line):
    """Hand one command to the long-lived amixer. False when it could not be started or written."""
    global _pipe
    try:
        if _pipe is None or _pipe.poll() is not None:
            _pipe = subprocess.Popen(["amixer", "-q", "-c", CARD, "-s"], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _pipe.stdin.write(line.encode() + b"\n")
        _pipe.stdin.flush()
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        _pipe = None
        return False


def write_step(step):
    raw = step_to_raw(step)
    if _send(f'cset "name={CONTROL}" {raw},{raw}'):
        return
    try:
        subprocess.run(["amixer", "-q", "-c", CARD, "cset", f"name={CONTROL}", f"{raw},{raw}"],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[volume] could not set the level: {exc}", flush=True)


class Volume:
    """Owned by the Dashboard as app.volume."""

    def __init__(self):
        from gi.repository import GLib, Gtk
        self._GLib, self._Gtk = GLib, Gtk
        step = read_step()
        self.available = step is not None
        self.step = step or 0
        self.listeners = []      # called with the new step after every change
        self._hide_id = 0
        self._repeat_id = 0
        self._hud = None
        self._fd = None
        try:
            self._fd = os.open(KEYS_DEVICE, os.O_RDONLY | os.O_NONBLOCK)
            GLib.io_add_watch(self._fd, GLib.IO_IN, self._on_keys)
        except OSError as exc:
            print(f"[volume] volume buttons unavailable: {exc}", flush=True)

    # ---- level ----

    def set(self, step, show=True):
        step = max(0, min(STEPS, int(step)))
        if step != self.step:
            self.step = step
            write_step(step)
            for listener in list(self.listeners):
                listener(step)
        if show:
            self._show()

    # ---- buttons ----

    def _on_keys(self, fd, _condition):
        try:
            data = os.read(fd, EVENT.size * 32)
        except BlockingIOError:
            return True
        except OSError as exc:
            print(f"[volume] volume buttons lost: {exc}", flush=True)
            return False
        for direction, pressed in parse_keys(data):
            self._stop_repeat()
            if pressed:
                self.set(self.step + direction)
                self._repeat_id = self._GLib.timeout_add(REPEAT_DELAY, self._repeat_start, direction)
        return True

    def _repeat_start(self, direction):
        self.set(self.step + direction)
        self._repeat_id = self._GLib.timeout_add(REPEAT_EVERY, self._repeat, direction)
        return False

    def _repeat(self, direction):
        self.set(self.step + direction)
        return True

    def _stop_repeat(self):
        if self._repeat_id:
            self._GLib.source_remove(self._repeat_id)
            self._repeat_id = 0

    # ---- the level bar ----

    def _build_hud(self):
        import clock_widgets
        Gtk = self._Gtk
        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.get_style_context().add_class("volume-hud")
        win.set_keep_above(True)
        box = Gtk.Box(spacing=18)
        box.set_border_width(18)
        box.pack_start(clock_widgets.Icon("speaker", 44), False, False, 0)
        self._bar = Gtk.DrawingArea(valign=Gtk.Align.CENTER)
        self._bar.set_size_request(STEPS * 20 - 6, 18)
        self._bar.connect("draw", self._draw_bar)
        box.pack_start(self._bar, False, False, 0)
        win.add(box)
        box.show_all()
        return win

    def _draw_bar(self, _widget, cr):
        for i in range(STEPS):
            cr.set_source_rgb(*((0.91, 0.93, 0.94) if i < self.step else (0.23, 0.27, 0.32)))
            cr.rectangle(i * 20, 0, 14, 18)
            cr.fill()
        return False

    def _show(self):
        if self._hud is None:
            self._hud = self._build_hud()
        hud = self._hud
        self._bar.queue_draw()
        width = hud.get_preferred_size()[1].width
        hud.move((hud.get_screen().get_width() - width) // 2, 48)
        hud.show()
        if hud.get_window():
            hud.get_window().raise_()   # above whichever fullscreen view is open
        if self._hide_id:
            self._GLib.source_remove(self._hide_id)
        self._hide_id = self._GLib.timeout_add(1600, self._hide)

    def _hide(self):
        self._hide_id = 0
        self._hud.hide()
        return False
