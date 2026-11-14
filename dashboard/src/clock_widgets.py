"""Cairo-drawn widgets for the clock tile's views: icons, the analog face, the timer
wheels, the progress ring and the world map.

Nothing here animates on its own except a wheel settling after a flick (a few
frames of one small widget); everything else redraws only when its data changes.
"""

import json
import math
import time

import cairo
from gi.repository import Gdk, GLib, Gtk

FG = (0.91, 0.93, 0.94)
DIM = (0.54, 0.59, 0.64)
ORANGE = (1.0, 0.62, 0.04)
YELLOW = (0.98, 0.78, 0.1)
FONT = "sans-serif"


def _square(widget):
    w, h = widget.get_allocated_width(), widget.get_allocated_height()
    return min(w, h), w / 2, h / 2


def _centered_text(cr, text, cx, cy):
    ext = cr.text_extents(text)
    cr.move_to(cx - ext.x_bearing - ext.width / 2, cy - ext.y_bearing - ext.height / 2)
    cr.show_text(text)


# ---- icons -----------------------------------------------------------------------

def _draw_globe(cr, s, cx, cy):
    r = s * 0.42
    cr.set_line_width(s * 0.07)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.stroke()
    cr.save()                      # meridian: the same circle squeezed sideways
    cr.translate(cx, cy)
    cr.scale(0.45, 1)
    cr.arc(0, 0, r, 0, 2 * math.pi)
    cr.restore()
    cr.stroke()
    for dy in (0, -0.5, 0.5):      # equator and two parallels
        half = r * math.sqrt(1 - dy * dy)
        cr.move_to(cx - half, cy + r * dy)
        cr.line_to(cx + half, cy + r * dy)
        cr.stroke()


def _draw_timer(cr, s, cx, cy):
    cy += s * 0.06
    r = s * 0.4
    cr.set_line_width(s * 0.07)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.stroke()
    cr.move_to(cx - s * 0.1, cy - r - s * 0.11)   # crown
    cr.line_to(cx + s * 0.1, cy - r - s * 0.11)
    cr.stroke()
    cr.move_to(cx, cy)                            # the elapsed quarter
    cr.arc(cx, cy, r * 0.68, -math.pi / 2, 0)
    cr.close_path()
    cr.fill()


def _draw_play(cr, s, cx, cy):
    r = s * 0.36
    cr.move_to(cx - r * 0.7, cy - r)
    cr.line_to(cx + r, cy)
    cr.line_to(cx - r * 0.7, cy + r)
    cr.close_path()
    cr.fill()


def _draw_pause(cr, s, cx, cy):
    for dx in (-0.2, 0.2):
        cr.rectangle(cx + s * dx - s * 0.08, cy - s * 0.3, s * 0.16, s * 0.6)
    cr.fill()


def _draw_cross(cr, s, cx, cy):
    r = s * 0.26
    cr.set_line_width(s * 0.1)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for sign in (1, -1):
        cr.move_to(cx - r, cy - sign * r)
        cr.line_to(cx + r, cy + sign * r)
        cr.stroke()


def _draw_minus(cr, s, cx, cy):
    cr.set_line_width(s * 0.12)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.move_to(cx - s * 0.28, cy)
    cr.line_to(cx + s * 0.28, cy)
    cr.stroke()


def _draw_speaker(cr, s, cx, cy):
    x = cx - s * 0.42
    cr.move_to(x, cy - s * 0.13)
    cr.line_to(x + s * 0.18, cy - s * 0.13)
    cr.line_to(x + s * 0.42, cy - s * 0.34)
    cr.line_to(x + s * 0.42, cy + s * 0.34)
    cr.line_to(x + s * 0.18, cy + s * 0.13)
    cr.line_to(x, cy + s * 0.13)
    cr.close_path()
    cr.fill()
    cr.set_line_width(s * 0.07)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for r in (0.2, 0.36):
        cr.arc(cx + s * 0.02, cy, s * r, -math.pi / 4, math.pi / 4)
        cr.stroke()


_ICONS = {
    "globe": _draw_globe, "timer": _draw_timer, "play": _draw_play, "pause": _draw_pause,
    "cross": _draw_cross, "minus": _draw_minus, "speaker": _draw_speaker,
}


class Icon(Gtk.DrawingArea):
    def __init__(self, kind, size, color=FG):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.set_size_request(size, size)
        self.kind, self.color = kind, color
        self.connect("draw", self._draw)

    def set_kind(self, kind):
        if kind != self.kind:
            self.kind = kind
            self.queue_draw()

    def _draw(self, _widget, cr):
        s, cx, cy = _square(self)
        cr.set_source_rgb(*self.color)
        _ICONS[self.kind](cr, s, cx, cy)
        return False


def icon_button(kind, size, css, on_click, color=FG):
    """A round button holding one drawn icon. Returns (button, icon)."""
    button = Gtk.Button(valign=Gtk.Align.CENTER)
    button.get_style_context().add_class(css)
    icon = Icon(kind, size, color)
    button.add(icon)
    button.connect("clicked", lambda _b: on_click())
    return button, icon


# ---- analog face -----------------------------------------------------------------

class Face(Gtk.DrawingArea):
    """An analog clock face without a seconds hand: white by day, black at night."""

    def __init__(self, size):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.set_size_request(size, size)
        self.state = (0, 0, True)
        self.connect("draw", self._draw)

    def set(self, hour, minute, daytime):
        if (hour, minute, daytime) != self.state:
            self.state = (hour, minute, daytime)
            self.queue_draw()

    def _draw(self, _widget, cr):
        hour, minute, daytime = self.state
        s, cx, cy = _square(self)
        r = s * 0.48
        face, ink = ((1, 1, 1), (0, 0, 0)) if daytime else ((0, 0, 0), (1, 1, 1))
        cr.set_source_rgb(*face)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(*ink)
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(s * 0.11)
        for n in range(1, 13):
            angle = n * math.pi / 6
            _centered_text(cr, str(n), cx + r * 0.8 * math.sin(angle), cy - r * 0.8 * math.cos(angle))
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for angle, length, width in (
            ((hour % 12 + minute / 60) * math.pi / 6, 0.5, 0.04),
            (minute * math.pi / 30, 0.82, 0.026),
        ):
            cr.set_line_width(s * width)
            cr.move_to(cx, cy)
            cr.line_to(cx + r * length * math.sin(angle), cy - r * length * math.cos(angle))
            cr.stroke()
        cr.set_source_rgb(*YELLOW)
        cr.arc(cx, cy, s * 0.025, 0, 2 * math.pi)
        cr.fill()
        return False


# ---- progress ring ---------------------------------------------------------------

class Ring(Gtk.DrawingArea):
    """How much of a timer is left: a full ring that empties clockwise."""

    def __init__(self, size):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.set_size_request(size, size)
        self.fraction, self.paused = 1.0, False
        self.connect("draw", self._draw)

    def set(self, fraction, paused):
        fraction = round(fraction, 3)
        if (fraction, paused) != (self.fraction, self.paused):
            self.fraction, self.paused = fraction, paused
            self.queue_draw()

    def _draw(self, _widget, cr):
        s, cx, cy = _square(self)
        r = s * 0.42
        cr.set_line_width(s * 0.1)
        cr.set_source_rgb(0.2, 0.24, 0.28)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if self.fraction > 0:
            cr.set_source_rgb(*(DIM if self.paused else ORANGE))
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            # what is left starts at 12 o'clock and shrinks back toward it
            cr.arc_negative(cx, cy, r, -math.pi / 2, -math.pi / 2 - 2 * math.pi * self.fraction)
            cr.stroke()
        return False


# ---- timer wheel -----------------------------------------------------------------

class Wheel(Gtk.DrawingArea):
    """One column of the hr / min / sec picker.

    Drag it and it follows the finger; let go and it snaps to the nearest value,
    carrying on a little after a flick. Tap the row above or below to step to it;
    tap the middle to select the column for the number pad.
    """

    ROW = 92          # px between values
    TAP_SLOP = 10     # px: a shorter drag is a tap

    def __init__(self, count, on_change, on_select):
        super().__init__()
        self.count = count
        self.on_change, self.on_select = on_change, on_select
        self.pos = 0.0            # fractional index of the value at the centre line
        self.selected = False
        self._value = 0
        self._anim = 0
        self._samples = []
        self.set_size_request(150, self.ROW * 3)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.TOUCH_MASK)
        self.connect("draw", self._draw)
        self.connect("destroy", lambda _w: self._stop())
        self._drag = Gtk.GestureDrag.new(self)
        self._drag.connect("drag-begin", self._on_begin)
        self._drag.connect("drag-update", self._on_update)
        self._drag.connect("drag-end", self._on_end)

    # ---- value ----

    def get_value(self):
        return self._value

    def set_value(self, value):
        self._stop()
        self.pos = float(value % self.count)
        self._settled()
        self.queue_draw()

    def set_selected(self, selected):
        if selected != self.selected:
            self.selected = selected
            self.queue_draw()

    def _settled(self):
        value = int(round(self.pos)) % self.count
        if value != self._value:
            self._value = value
            self.on_change()

    # ---- gesture ----

    def _on_begin(self, _gesture, _x, _y):
        self._stop()
        self._start = self.pos
        self._samples = [(time.monotonic(), self.pos)]

    def _on_update(self, _gesture, _dx, dy):
        self.pos = self._start - dy / self.ROW
        self._samples.append((time.monotonic(), self.pos))
        del self._samples[:-6]
        self._settled()   # Start enables as soon as the value under the line changes
        self.queue_draw()

    def _on_end(self, gesture, dx, dy):
        self.on_select(self)
        if abs(dy) < self.TAP_SLOP and abs(dx) < self.TAP_SLOP:
            _ok, _x, y = gesture.get_start_point()
            rows = round((y - self.get_allocated_height() / 2) / self.ROW)
            self._glide(round(self._start) + rows, 0.12)
            return
        t1, p1 = self._samples[-1]
        t0, p0 = next(((t, p) for t, p in self._samples if t1 - t <= 0.12), self._samples[0])
        velocity = (p1 - p0) / (t1 - t0) if t1 > t0 else 0.0   # values per second
        if abs(velocity) > 3:
            carry = max(-20.0, min(20.0, velocity * 0.22))
            self._glide(round(self.pos + carry), 0.45)
        else:
            self._glide(round(self.pos), 0.1)

    def _glide(self, target, seconds):
        self._stop()
        start, t0 = self.pos, time.monotonic()
        if target == start:
            self._finish(target)
            return

        def step():
            k = min(1.0, (time.monotonic() - t0) / seconds)
            self.pos = start + (target - start) * (1 - (1 - k) ** 3)   # ease out
            self._settled()
            self.queue_draw()
            if k >= 1.0:
                self._anim = 0
                self._finish(target)
                return False
            return True

        self._anim = GLib.timeout_add(16, step)

    def _finish(self, target):
        self.pos = float(target % self.count)
        self._settled()
        self.queue_draw()

    def _stop(self):
        if self._anim:
            GLib.source_remove(self._anim)
            self._anim = 0

    # ---- drawing ----

    def _draw(self, _widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cx, cy = w / 2, h / 2
        if self.selected:
            cr.set_source_rgb(0.16, 0.2, 0.24)
            _rounded(cr, 4, cy - self.ROW / 2 + 2, w - 8, self.ROW - 4, 18)
            cr.fill()
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(76)
        nearest = int(round(self.pos))
        for index in range(nearest - 2, nearest + 3):
            distance = abs(index - self.pos)
            alpha = max(0.0, 1.0 - 0.72 * distance) if distance < 1 else max(0.0, 0.42 - 0.17 * distance)
            cr.set_source_rgba(*FG, alpha)
            _centered_text(cr, f"{index % self.count:02d}", cx, cy + (index - self.pos) * self.ROW)
        return False


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


# ---- world map -------------------------------------------------------------------

class WorldMap(Gtk.DrawingArea):
    """Land, the night side with the day/night line, hour lines and a dot per city.

    Plain latitude/longitude grid, cropped to the latitudes people live at. The land
    is drawn once into an image; set() only repaints the cheap parts over it.
    """

    LAT_CENTER = 14   # the map is cropped symmetrically around this latitude

    def __init__(self, land_path):
        super().__init__()
        try:
            with open(land_path) as fh:
                self.land = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"[clock] no map data: {exc}", flush=True)
            self.land = []
        self.cities = []         # (name, time text, lat, lon)
        self.night = None        # (terminator points, dark pole latitude)
        self._cache = None
        self._cache_size = None
        self.connect("draw", self._draw)

    def set(self, cities, night):
        self.cities, self.night = cities, night
        self.queue_draw()

    def _xy(self, lon, lat):
        ppd = self._w / 360
        top = self.LAT_CENTER + self._h / ppd / 2
        return (lon + 180) * ppd, (top - lat) * ppd

    def _land_image(self, cr):
        size = (self._w, self._h)
        if self._cache is None or self._cache_size != size:
            self._cache = cr.get_target().create_similar(cairo.CONTENT_COLOR, *size)
            self._cache_size = size
            c = cairo.Context(self._cache)
            c.set_source_rgb(0, 0, 0)
            c.paint()
            c.set_source_rgb(0.3, 0.3, 0.3)
            c.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)   # holes (the Caspian) stay sea
            for rings in self.land:
                for ring in rings:
                    c.move_to(*self._xy(ring[0] / 10, ring[1] / 10))
                    for i in range(2, len(ring), 2):
                        c.line_to(*self._xy(ring[i] / 10, ring[i + 1] / 10))
                    c.close_path()
                c.fill()
        return self._cache

    def _draw(self, _widget, cr):
        self._w, self._h = self.get_allocated_width(), self.get_allocated_height()
        w, h = self._w, self._h
        _rounded(cr, 0, 0, w, h, 18)
        cr.clip()
        cr.set_source_surface(self._land_image(cr), 0, 0)
        cr.paint()
        if self.night:
            points, pole = self.night
            cr.move_to(*self._xy(*points[0]))
            for point in points[1:]:
                cr.line_to(*self._xy(*point))
            line = cr.copy_path()
            cr.line_to(*self._xy(180, pole * 2))    # well past the edge of the widget
            cr.line_to(*self._xy(-180, pole * 2))
            cr.close_path()
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.fill()
            cr.new_path()
            cr.append_path(line)
            cr.set_source_rgba(1, 1, 1, 0.6)
            cr.set_line_width(1.5)
            cr.stroke()
        cr.set_source_rgba(1, 1, 1, 0.12)             # hour lines
        cr.set_line_width(1)
        for lon in range(-165, 180, 30):
            x = round(self._xy(lon, 0)[0]) + 0.5
            cr.move_to(x, 0)
            cr.line_to(x, h)
        cr.stroke()
        for name, text, lat, lon in self.cities:
            x, y = self._xy(lon, lat)
            cr.set_source_rgb(*YELLOW)
            cr.arc(x, y, 6, 0, 2 * math.pi)
            cr.fill()
            cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(17)
            width = cr.text_extents(name).width
            tx = x + 12 if x + 24 + width < w else x - 12 - width
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(tx, y + 6)
            cr.show_text(name)
            cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(14)
            cr.move_to(tx, y + 24)
            cr.show_text(text)
        return False
