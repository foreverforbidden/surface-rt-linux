"""AirPlay screen: tap Start and the tablet becomes an AirPlay mirroring target.

Start from the AirPlay widget on Home or from the AirPlay page (side menu), which
also explains how to connect and shows the receiver's settings.

Runs uxplay (built from third_party/UxPlay, installed in /usr/local/bin) with
audio off. While it runs, a fullscreen "ready" screen covers
the dashboard; uxplay's own fullscreen video window opens on top of it when a
Mac or iPad starts mirroring, and closes again when they stop.

Tap the stream to reveal controls. Configuration supports name, resolution,
fps, and trailing args overrides; see airplay_settings.py.
"""

import ctypes
import fcntl
import math
import os
import re
import signal
import subprocess

from gi.repository import Gdk, GLib, Gtk

import core
from airplay_controls import Controls
from airplay_settings import decoder_name, receiver_args, receiver_env, receiver_executable
PR_SET_PDEATHSIG = 1


def _die_with_parent():
    # If the dashboard dies (crash, pkill), take uxplay with it so run.sh's
    # respawn doesn't leave a second receiver advertising.
    ctypes.CDLL("libc.so.6").prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def _draw_icon(widget, cr):
    """The AirPlay mark: a screen with a triangle rising into its bottom edge."""
    w, h = widget.get_allocated_width(), widget.get_allocated_height()
    s = min(w, h)
    x0, y0 = (w - s) / 2, (h - s) / 2
    cr.set_source_rgb(0.91, 0.93, 0.94)
    cr.set_line_width(s * 0.07)
    # screen outline, open at the bottom middle
    r = s * 0.08
    left, right, top, bottom = x0 + s * 0.08, x0 + s * 0.92, y0 + s * 0.12, y0 + s * 0.72
    cr.move_to(x0 + s * 0.32, bottom)
    cr.line_to(left + r, bottom)
    cr.arc(left + r, bottom - r, r, math.pi / 2, math.pi)
    cr.line_to(left, top + r)
    cr.arc(left + r, top + r, r, math.pi, 1.5 * math.pi)
    cr.line_to(right - r, top)
    cr.arc(right - r, top + r, r, 1.5 * math.pi, 2 * math.pi)
    cr.line_to(right, bottom - r)
    cr.arc(right - r, bottom - r, r, 0, math.pi / 2)
    cr.line_to(x0 + s * 0.68, bottom)
    cr.stroke()
    # triangle
    cr.move_to(x0 + s * 0.5, y0 + s * 0.56)
    cr.line_to(x0 + s * 0.76, y0 + s * 0.9)
    cr.line_to(x0 + s * 0.24, y0 + s * 0.9)
    cr.close_path()
    cr.fill()
    return False


def _icon(size):
    area = Gtk.DrawingArea()
    area.set_size_request(size, size)
    area.connect("draw", _draw_icon)
    return area


def _label(text, css_class):
    label = Gtk.Label(label=text, justify=Gtk.Justification.CENTER)
    label.set_line_wrap(True)
    label.get_style_context().add_class(css_class)
    return label


class Module(core.Module):
    name = "airplay"
    icon = "airplay"
    menu_title = "AirPlay"
    widgets = {"airplay": ("AirPlay", ("S", "M"), "airplay")}

    def __init__(self, app):
        super().__init__(app)
        cfg = app.config.get("airplay", {})
        self.config = cfg
        self.server_name = cfg.get("name", "Surface RT")
        self.proc = None
        self._buf = b""
        self._kill_timer = 0
        self._output_watch = 0
        self._stopping = False
        self.shield = None
        self._hw = False
        self._status = "Off"
        self._status_labels = []
        self._start_buttons = []

    # ---- setup, Home widget, page --------------------------------------------

    def setup(self):
        self.overlay = self._build_overlay()
        self.bar = self._build_controls()
        self.controls = Controls(GLib, self._show_controls, self._hide_controls)
        self.app.window.connect("destroy", self._dashboard_destroyed)

    def build(self):
        """The old one-tile API, kept for diagnostics/airplay_smoke.py."""
        self.setup()
        return self.widget("airplay", "M")

    def forget_widgets(self):
        # the page's label and button stay; drop the Home widget's
        self._status_labels = self._status_labels[:1] if getattr(self, "_page_built", False) else []
        self._start_buttons = self._start_buttons[:1] if getattr(self, "_page_built", False) else []

    def _start_button(self):
        button = Gtk.Button(label="Start")
        button.get_style_context().add_class("primary")
        button.connect("clicked", self._on_tap)
        self._start_buttons.append(button)
        return button

    def widget(self, wid, size):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(core.widget_head("airplay", "AirPlay"), False, False, 0)
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER, vexpand=True)
        mid.pack_start(core.label(self.server_name, "airplay-w-name"), False, False, 0)
        status = core.label(self._status, "widget-sub", wrap=True)
        self._status_labels.append(status)
        mid.pack_start(status, False, False, 0)
        box.pack_start(mid, True, True, 0)
        box.pack_start(self._start_button(), False, False, 0)
        return core.tile(box, None, size)

    def page(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        root.pack_start(_icon(120), False, False, 0)
        root.pack_start(_label(f"AirPlay to “{self.server_name}”", "airplay-heading"), False, False, 0)
        status = _label(self._status, "airplay-status")
        self._status_labels.insert(0, status)
        root.pack_start(status, False, False, 0)
        start = self._start_button()
        self._start_buttons.remove(start)
        self._start_buttons.insert(0, start)
        start.set_halign(Gtk.Align.CENTER)
        start.set_size_request(320, -1)
        root.pack_start(start, False, False, 0)
        root.pack_start(_label(
            "Mac: Control Center → Screen Mirroring → " + self.server_name +
            ", then choose “Use As Separate Display” to extend.\n"
            "iPad / iPhone: Control Center → Screen Mirroring → " + self.server_name + ".",
            "airplay-help"), False, False, 0)
        cfg = self.config
        root.pack_start(_label(
            f"{cfg.get('resolution', '1280x720')} · {cfg.get('fps', 30)} fps · decoder "
            f"{cfg.get('decoder', 'default')}   (change in config.json)", "airplay-tile-hint"), False, False, 0)
        self._page_built = True
        return root

    def _build_overlay(self):
        win = Gtk.Window()
        win.get_style_context().add_class("airplay-overlay")
        win.connect("realize", self._hide_cursor)
        win.connect("delete-event", lambda *_: True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        box.pack_start(_icon(140), False, False, 0)
        box.pack_start(_label(f"AirPlay to “{self.server_name}”", "airplay-heading"), False, False, 0)
        box.pack_start(_label(
            "Mac: Control Center → Screen Mirroring → " + self.server_name +
            ", then choose “Use As Separate Display” to extend.\n"
            "iPad / iPhone: Control Center → Screen Mirroring → " + self.server_name + ".",
            "airplay-help"), False, False, 0)
        self.overlay_status = _label("", "airplay-status")
        box.pack_start(self.overlay_status, False, False, 0)

        win.add(box)
        return win

    def _build_controls(self):
        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.get_style_context().add_class("airplay-controls")
        win.connect("realize", self._hide_cursor)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_border_width(12)
        self.hide_button = Gtk.Button(label="Hide controls")
        self.hide_button.connect("clicked", lambda _b: self.controls.dismiss())
        self.exit_button = Gtk.Button(label="Exit AirPlay")
        self.exit_button.get_style_context().add_class("airplay-stop")
        self.exit_button.connect("clicked", lambda _b: self.stop())
        for button in (self.hide_button, self.exit_button):
            button.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                              Gdk.EventMask.TOUCH_MASK)
            button.connect("event", self._control_event)
            box.pack_start(button, True, True, 0)
        win.add(box)
        return win

    def _control_event(self, _widget, event):
        kind = event.type
        if kind in (Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
            key = ("bar-touch", event.get_event_sequence())
            if kind == Gdk.EventType.TOUCH_BEGIN:
                self.controls.press(key)
            else:
                self.controls.release(key)
        elif kind in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
            # The generic GTK "event" signal supplies a Gdk.Event union;
            # event.button is an EventButton object, not the button number.
            key = ("bar-button", event.get_button()[1])
            if kind == Gdk.EventType.BUTTON_PRESS:
                self.controls.press(key)
            else:
                self.controls.release(key)
        return False  # GTK still handles explicit control-button activation.

    def _show_controls(self):
        self.hide_button.set_sensitive(not self.controls.waiting and not self._stopping)
        self.bar.show_all()
        screen = self.overlay.get_screen()
        _minimum, natural = self.bar.get_preferred_size()
        self.bar.move((screen.get_width() - natural.width) // 2,
                      screen.get_height() - natural.height - 20)
        if self.shield:
            self.shield.restack()
        self._signal_video(signal.SIGUSR1)

    def _hide_controls(self):
        self.bar.hide()
        self._signal_video(signal.SIGUSR2)

    def _signal_video(self, signum):
        # hw decoder: the video is on a DRM plane above X and would cover the bar, so the patched
        # uxplay shrinks it while the controls show (SIGUSR1) and restores it (SIGUSR2).
        if self.proc is not None and self.proc.returncode is None and self._hw:
            try:
                self.proc.send_signal(signum)
            except OSError:
                pass

    def _controls_rect(self):
        screen = self.overlay.get_screen()
        _minimum, natural = self.bar.get_preferred_size()
        return (0, 0, screen.get_width(), screen.get_height() - natural.height - 40)

    def _control_xid(self, include_hidden=False):
        if not self.bar.get_realized() or (not include_hidden and not self.bar.get_visible()):
            return 0
        return self.bar.get_window().get_xid()

    def _input_failed(self, message):
        print(f"[airplay] touch controls failed: {message}", flush=True)
        self.stop()

    def _finish_ui(self):
        self.controls.stop()
        if self.shield:
            self.shield.close()
            self.shield = None
        self.overlay.hide()

    def _dashboard_destroyed(self, *_args):
        self.stop()
        self._finish_ui()

    @staticmethod
    def _hide_cursor(widget):
        widget.get_window().set_cursor(
            Gdk.Cursor.new_for_display(widget.get_display(), Gdk.CursorType.BLANK_CURSOR)
        )

    def _set_status(self, text):
        self._status = text
        for label in self._status_labels:
            label.set_text(text)
        self.overlay_status.set_text(text)

    def _show_overlay(self):
        self.overlay.fullscreen()
        self.overlay.show_all()
        self.overlay.present()

    # ---- uxplay process -----------------------------------------------------

    def _on_tap(self, _button):
        if self._stopping:
            return
        if self.proc is not None:
            self.controls.reveal()
            return
        self.start_receiver()

    def start_receiver(self):
        try:
            executable = receiver_executable(self.config)
        except ValueError as exc:
            self._set_status(f"couldn't start AirPlay: {exc}")
            return
        if not os.path.exists(executable):
            self._set_status("uxplay is not installed")
            return
        try:
            args = receiver_args(executable, self.config)
            self._hw = decoder_name(self.config) == "hw"
            # GdkX11 provides get_xid()/get_xcursor() on GTK's X11 objects.
            import gi
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11  # noqa: F401
            from airplay_input import InputShield
            self._show_overlay()
            self.controls.start()
            self.exit_button.set_sensitive(True)
            self.shield = InputShield(self.controls.gesture, self._control_xid, self._input_failed)
            cursor = Gdk.Cursor.new_for_display(self.overlay.get_display(), Gdk.CursorType.BLANK_CURSOR)
            self.shield.start(cursor.get_xcursor())
        except (OSError, RuntimeError, ValueError, AttributeError) as exc:
            self._finish_ui()
            self._set_status(f"couldn't start AirPlay: {exc}")
            return
        # Clear any receiver left by an earlier dashboard run.
        subprocess.run(["pkill", "-x", "uxplay"], capture_output=True)
        print(f"[airplay] starting: {' '.join(args)}", flush=True)
        # LD_HWCAP_MASK and, for the hw decoder, the private GStreamer: see airplay_settings.
        env = receiver_env(self.config, controls_rect=self._controls_rect())
        try:
            self.proc = subprocess.Popen(
                args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, preexec_fn=_die_with_parent,
            )
        except OSError as exc:
            self._finish_ui()
            self._set_status(f"couldn't start uxplay: {exc}")
            return
        self._buf = b""
        fd = self.proc.stdout.fileno()
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        self._output_watch = GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_output, self.proc)
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self.proc.pid, self._on_exit, self.proc)
        self._set_status("waiting for a Mac or iPad")

    def stop(self):
        proc = self.proc
        if proc is None:
            self._finish_ui()
            return
        if self._stopping:
            return
        self._stopping = True
        self.controls.cancel_timer()
        self.exit_button.set_sensitive(False)
        self.hide_button.set_sensitive(False)
        try:
            proc.terminate()
        except OSError:
            pass
        # Escalate if it doesn't exit promptly.
        self._kill_timer = GLib.timeout_add_seconds(3, self._force_kill, proc)

    def _force_kill(self, proc):
        if self.proc is proc:
            self._kill_timer = 0
            try:
                proc.kill()
            except OSError:
                pass
        return False

    def _on_exit(self, _pid, status, proc):
        proc.returncode = os.waitstatus_to_exitcode(status)  # GLib has reaped it.
        if self.proc is not proc:
            return
        print(f"[airplay] uxplay exited (status {status})", flush=True)
        self.proc = None
        if self._output_watch:
            GLib.source_remove(self._output_watch)
            self._output_watch = 0
        proc.stdout.close()
        if self._kill_timer:
            GLib.source_remove(self._kill_timer)
            self._kill_timer = 0
        expected = self._stopping
        self._stopping = False
        self._finish_ui()
        self._set_status("tap to start" if expected else "AirPlay stopped. Tap to retry.")

    def _on_output(self, fd, condition, proc):
        if self.proc is not proc:
            return False
        try:
            chunk = os.read(fd, 8192)
        except BlockingIOError:
            return True
        except OSError:
            chunk = b""
        if not chunk:
            self._output_watch = 0
            return False  # EOF: uxplay closed its output
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            self._handle_line(raw.decode("utf-8", "replace").rstrip())
        return True

    def _handle_line(self, line):
        m = re.search(r"connection request from (.+?) \(([^)]*)\)", line)
        if m:
            self._set_status(f"mirroring from {m.group(1)}")
        # UxPlay may open several control connections before delivering video.
        if "width_source" in line or "begin video stream wxh" in line:
            self.controls.set_waiting(False)
            self.hide_button.set_sensitive(True)
        m = re.search(r"Open connections: (\d+)", line)
        if m and int(m.group(1)) == 0:
            self._set_status("waiting for a Mac or iPad")
            self.controls.set_waiting(True)
        # Debug output is chatty; log only what helps diagnose problems.
        if re.search(r"connection request|Open connections|width_source|ERROR|error|rror:|decoder|videosink|GStreamer|Initialized|Using", line):
            print(f"[airplay] {line}", flush=True)
