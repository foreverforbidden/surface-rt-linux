#!/usr/bin/env python3
"""On-device GTK/X11 integration checks using synthetic mouse input.

Run on DISPLAY=:0 as the kiosk user, under systemd. Temporarily opens a test window and
receiver; always stops its receiver and closes its input layer in finally.
Physical multitouch and actual mirroring still need a real-device session.
"""
import ctypes as C
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk
from modules.airplay import Module


def drain(seconds=.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)


def main():
    app = SimpleNamespace(window=Gtk.Window(), config=json.loads(
        (Path(__file__).resolve().parents[1] / "config.json").read_text()))
    css = Gtk.CssProvider()
    css.load_from_path(str(Path(__file__).resolve().parents[1] / "style.css"))
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    module = Module(app)
    app.window.add(module.build())
    app.window.fullscreen()
    app.window.show_all()
    underlying = []
    app.window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    app.window.connect("button-press-event", lambda *_: underlying.append(1))
    video = Gtk.Window(title="AirPlay smoke test stream stand-in")
    video.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    video.connect("button-press-event", lambda *_: underlying.append(1))
    x = C.CDLL("libX11.so.6")
    xtest = C.CDLL("libXtst.so.6")
    x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [C.c_char_p], C.c_void_p
    x.XFlush.argtypes = [C.c_void_p]
    x.XCloseDisplay.argtypes = [C.c_void_p]
    xtest.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
    xtest.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
    display = x.XOpenDisplay(None)

    def pointer(xpos, ypos, down):
        xtest.XTestFakeMotionEvent(display, -1, int(xpos), int(ypos), 0)
        xtest.XTestFakeButtonEvent(display, 1, down, 0)
        x.XFlush(display)
        drain()

    def click(xpos, ypos):
        pointer(xpos, ypos, 1)
        pointer(xpos, ypos, 0)

    def button_center(button):
        translated = button.translate_coordinates(module.bar, 0, 0)
        pos = module.bar.get_position()
        alloc = button.get_allocation()
        return pos.root_x + translated[0] + alloc.width // 2, pos.root_y + translated[1] + alloc.height // 2

    try:
        drain()
        module.start_receiver()
        drain(1)
        assert module.proc is not None, module.tile_status.get_text()
        assert module.shield and module.shield.window
        assert module.bar.get_visible()
        assert not module.controls.timer, "waiting controls must stay visible"
        module.controls.set_waiting(False)
        module.hide_button.set_sensitive(True)
        drain(4.2)
        assert not module.bar.get_visible(), f"autohide failed: {vars(module.controls)}"
        # A window appearing above the receiver must not steal touch input.
        video.fullscreen()
        video.show_all()
        video.present()
        drain(.5)
        # Tap exactly where Exit will appear: first tap must only reveal it.
        exit_position = button_center(module.exit_button)
        pointer(*exit_position, 1)
        assert not module.bar.get_visible(), "controls appeared before release"
        pointer(*exit_position, 0)
        assert module.bar.get_visible(), "release did not reveal controls"
        if "--screenshot" in sys.argv:
            root = Gdk.get_default_root_window()
            Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height()).savev(
                "/tmp/airplay-controls.png", "png", [], [])
        assert not module._stopping, "revealing tap clicked Exit"
        assert not underlying, "tap passed through to video/dashboard"
        # Holding a control pauses the timer.
        hide_position = button_center(module.hide_button)
        pointer(*hide_position, 1)
        drain(4.2)
        assert module.bar.get_visible() and not module.controls.timer
        pointer(*hide_position, 0)
        assert not module.bar.get_visible(), f"Hide controls failed: presses={module.controls.presses}, waiting={module.controls.waiting}, sensitive={module.hide_button.get_sensitive()}"
        click(100, 100)
        assert module.bar.get_visible()
        module._handle_line("Open connections: 0")
        drain(4.2)
        assert module.bar.get_visible() and module.controls.waiting
        module._handle_line("width_source = 1366 height_source = 768")
        click(*button_center(module.exit_button))
        drain(1)
        assert module.proc is None and module.shield is None
        assert not module.bar.get_visible() and not module.overlay.get_visible()
        for _ in range(2):
            module.start_receiver()
            drain(.5)
            assert module.proc is not None
            module.proc.kill()
            drain(.5)
            assert module.proc is None and module.shield is None
            assert not module.controls.timer and not module._output_watch
        print("PASS: startup, tap isolation, restacking, hold, hide, timeout, reconnect state, exit, crash, restart", flush=True)
    finally:
        module.stop()
        drain(3.5)
        module._finish_ui()
        video.destroy()
        app.window.destroy()
        x.XCloseDisplay(display)


if __name__ == "__main__":
    main()
