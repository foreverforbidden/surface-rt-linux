"""Stroke icons for the shell and widgets (24x24 SVG paths, drawn by librsvg via GdkPixbuf).

Icon(name, size, color) is a Gtk.Image; set_color() repaints it (e.g. the side
menu's active entry). Rendered pixbufs are cached, so repeats cost nothing.
"""

from gi.repository import GdkPixbuf, GLib, Gtk

FG = "#E8ECF0"

PATHS = {
    "home": '<path d="M3 10.5L12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "timer": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5M9 2h6"/>',
    "globe": ('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9'
              's-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>'),
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "airplay": ('<path d="M5 17H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-1"/>'
                '<path d="M12 15l5 6H7z"/>'),
    "chip": ('<rect x="5" y="5" width="14" height="14" rx="2"/>'
             '<path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sun": ('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
            'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    "speaker": '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
    "wifi": '<path d="M2 8.8a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1"/>',
    "battery": ('<rect x="2" y="7" width="18" height="10" rx="2"/><path d="M22 11v2"/>'
                '<rect x="4" y="9" width="9" height="6" rx="1" fill="{color}" stroke="none"/>'),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "warn": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.01"/>',
    "cross": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "pencil": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    "left": '<path d="M15 6l-6 6 6 6"/>',
    "right": '<path d="M9 6l6 6-6 6"/>',
    "back": '<path d="M15 6l-6 6 6 6"/>',
    "play": '<path d="M7 5l12 7-12 7z" fill="{color}"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="{color}"/>',
}

_cache = {}


def svg(name, color=FG, stroke=1.8):
    body = PATHS[name].replace("{color}", color)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>')


def pixbuf(name, size, color=FG, stroke=1.8):
    key = (name, size, color, stroke)
    if key not in _cache:
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.set_size(size, size)
            loader.write(svg(name, color, stroke).encode())
            loader.close()
            _cache[key] = loader.get_pixbuf()
        except GLib.Error as exc:
            print(f"[icons] {name} failed: {exc}", flush=True)
            _cache[key] = None
    return _cache[key]


class Icon(Gtk.Image):
    def __init__(self, name, size, color=FG, stroke=1.8):
        super().__init__()
        self.name_, self.size_, self.stroke_ = name, size, stroke
        self._shown = None      # (name, color) on screen: repeats don't repaint
        self.set_size_request(size, size)
        self.set_color(color)

    def set_color(self, color):
        if (self.name_, color) == self._shown:
            return
        pb = pixbuf(self.name_, self.size_, color, self.stroke_)
        if pb is not None:
            self._shown = (self.name_, color)
            self.set_from_pixbuf(pb)

    def set_name_(self, name, color=FG):
        self.name_ = name
        self.set_color(color)
