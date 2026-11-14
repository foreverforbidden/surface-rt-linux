"""Screen off: blanks the backlight; the next tap anywhere turns it back on.

The dashboard always loads this module: it is the Sleep button at the bottom of
the side menu, and an optional small Home widget.
"""

from gi.repository import Gdk, Gtk

import core
import icons


class Module(core.Module):
    name = "screen_off"
    widgets = {"screen_off": ("Screen off", ("S",), "moon")}

    def setup(self):
        # Fullscreen black window that swallows the wake tap, so it can't press anything.
        self.overlay = Gtk.Window()
        self.overlay.get_style_context().add_class("blackout")
        self.overlay.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
        self.overlay.connect("button-press-event", self._wake)
        self.overlay.connect("touch-event", self._wake)
        self.overlay.connect("realize", self._hide_cursor)

    def widget(self, wid, size):
        button = Gtk.Button()
        button.get_style_context().add_class("screen-off")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        inner.pack_start(icons.Icon("moon", 48, "#C4CCD4", 1.6), False, False, 0)
        inner.pack_start(core.label("Screen off", "screen-off-text", xalign=0.5), False, False, 0)
        inner.pack_start(core.label("tap anywhere to wake", "screen-off-hint", xalign=0.5), False, False, 0)
        button.add(inner)
        button.connect("clicked", lambda _b: self.sleep())
        return button

    @staticmethod
    def _hide_cursor(widget):
        widget.get_window().set_cursor(
            Gdk.Cursor.new_for_display(widget.get_display(), Gdk.CursorType.BLANK_CURSOR)
        )

    def sleep(self):
        self.overlay.fullscreen()
        self.overlay.show_all()
        self.overlay.present()
        self.app.backlight.off()

    def _wake(self, _widget, event):
        if not self.overlay.get_visible():
            return False
        self.app.backlight.on()
        self.overlay.hide()
        return True
