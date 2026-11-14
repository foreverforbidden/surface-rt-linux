#!/usr/bin/env python3
"""Rescue screen: run.sh shows it when the dashboard keeps crashing.

Loads only core and sysfix (never modules/), so a broken tile can't take it
down. Shows the end of the log, the tap-to-fix panel, and buttons to retry the
dashboard or reboot. Exiting returns to run.sh, which starts the dashboard again.
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sysfix  # noqa: E402

LOG = os.path.expanduser("~/app.log")
LOG_LINES = 8


def log_tail(path=LOG, lines=LOG_LINES):
    try:
        with open(path, errors="replace") as fh:
            tail = fh.readlines()[-lines:]
    except OSError as exc:
        return f"(no log: {exc})"
    return "".join(tail).rstrip() or "(log is empty)"


def main():
    css = Gtk.CssProvider()
    try:
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    except GLib.Error as exc:  # an unstyled rescue screen still beats none
        print(f"[rescue] style.css: {exc}", flush=True)

    win = Gtk.Window(title="Rescue")
    win.get_style_context().add_class("fix-overlay")
    win.connect("destroy", Gtk.main_quit)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.set_border_width(16)

    header = Gtk.Box(spacing=14)
    header.pack_start(sysfix.label("Dashboard keeps crashing", "rescue-heading"), False, False, 0)
    reboot = Gtk.Button()
    reboot.get_style_context().add_class("danger")
    reboot.get_style_context().add_class("fix-close")
    sysfix.arm_button(reboot, "Reboot", lambda: (
        reboot.set_label("Rebooting…"), subprocess.Popen(["sudo", "-n", "systemctl", "reboot"])))
    retry = Gtk.Button(label="Try dashboard again")
    retry.get_style_context().add_class("fix-close")
    retry.get_style_context().add_class("rescue-retry")
    retry.connect("clicked", lambda _b: Gtk.main_quit())
    header.pack_end(retry, False, False, 0)
    header.pack_end(reboot, False, False, 0)
    root.pack_start(header, False, False, 0)

    log = sysfix.label(log_tail(), "rescue-log")
    log.set_line_wrap(False)
    log.set_selectable(False)
    scroll = Gtk.ScrolledWindow()
    scroll.set_size_request(-1, 110)
    scroll.add(log)
    # The traceback is at the end of the log: keep the view pinned to the bottom.
    vadj = scroll.get_vadjustment()
    vadj.connect("changed", lambda a: a.set_value(a.get_upper() - a.get_page_size()))
    root.pack_start(scroll, False, False, 0)

    panel = sysfix.FixPanel()
    root.pack_start(panel, True, True, 0)
    GLib.timeout_add_seconds(10, lambda: panel.refresh() or True)

    win.add(root)
    win.fullscreen()
    win.show_all()
    panel.refresh()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
