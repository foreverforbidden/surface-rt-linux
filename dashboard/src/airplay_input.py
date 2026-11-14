"""An invisible X11 input window above UxPlay, with no video compositing.

Uses its own X connection, so GTK retains ownership of its event queue. All
Xlib calls run on the GTK main thread. XI2 touch selection consumes every
finger, rather than relying only on the touchscreen's emulated mouse.
"""

import ctypes as C

from gi.repository import GLib

Window = C.c_ulong
Display = C.c_void_p


class Attributes(C.Structure):
    _fields_ = [("background_pixmap", Window), ("background_pixel", C.c_ulong),
                ("border_pixmap", Window), ("border_pixel", C.c_ulong),
                ("bit_gravity", C.c_int), ("win_gravity", C.c_int),
                ("backing_store", C.c_int), ("backing_planes", C.c_ulong),
                ("backing_pixel", C.c_ulong), ("save_under", C.c_int),
                ("event_mask", C.c_long), ("do_not_propagate_mask", C.c_long),
                ("override_redirect", C.c_int), ("colormap", Window), ("cursor", Window)]


class PointerEvent(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", Display), ("window", Window), ("root", Window),
                ("subwindow", Window), ("time", C.c_ulong), ("x", C.c_int),
                ("y", C.c_int), ("x_root", C.c_int), ("y_root", C.c_int),
                ("state", C.c_uint), ("button", C.c_uint), ("same_screen", C.c_int)]


class Cookie(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", Display), ("extension", C.c_int), ("evtype", C.c_int),
                ("cookie", C.c_uint), ("data", C.c_void_p)]


class Event(C.Union):
    _fields_ = [("type", C.c_int), ("pointer", PointerEvent),
                ("cookie", Cookie), ("pad", C.c_long * 24)]


class TouchEvent(C.Structure):
    # Only the common XIDeviceEvent prefix through coordinates is needed.
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", Display), ("extension", C.c_int), ("evtype", C.c_int),
                ("time", C.c_ulong), ("deviceid", C.c_int), ("sourceid", C.c_int),
                ("detail", C.c_int), ("root", Window), ("event", Window),
                ("child", Window), ("root_x", C.c_double), ("root_y", C.c_double),
                ("event_x", C.c_double), ("event_y", C.c_double)]


class EventMask(C.Structure):
    _fields_ = [("deviceid", C.c_int), ("mask_len", C.c_int),
                ("mask", C.POINTER(C.c_ubyte))]


class InputShield:
    def __init__(self, gesture, control_window, failed):
        self.gesture, self.control_window, self.failed = gesture, control_window, failed
        self.display = None
        self.window = 0
        self.watch = self.poll = 0
        self.mouse_down = False
        self.touch_ids = set()
        self.x = C.CDLL("libX11.so.6")
        self.xi = C.CDLL("libXi.so.6")
        signatures = {
            "XOpenDisplay": (Display, [C.c_char_p]),
            "XDefaultRootWindow": (Window, [Display]),
            "XDefaultScreen": (C.c_int, [Display]),
            "XDisplayWidth": (C.c_int, [Display, C.c_int]),
            "XDisplayHeight": (C.c_int, [Display, C.c_int]),
            "XCreateWindow": (Window, [Display, Window, C.c_int, C.c_int,
                C.c_uint, C.c_uint, C.c_uint, C.c_int, C.c_uint, C.c_void_p,
                C.c_ulong, C.POINTER(Attributes)]),
            "XSelectInput": (C.c_int, [Display, Window, C.c_long]),
            "XMapWindow": (C.c_int, [Display, Window]),
            "XRaiseWindow": (C.c_int, [Display, Window]),
            "XDestroyWindow": (C.c_int, [Display, Window]),
            "XCloseDisplay": (C.c_int, [Display]),
            "XFlush": (C.c_int, [Display]),
            "XConnectionNumber": (C.c_int, [Display]),
            "XPending": (C.c_int, [Display]),
            "XNextEvent": (C.c_int, [Display, C.POINTER(Event)]),
            "XQueryTree": (C.c_int, [Display, Window, C.POINTER(Window),
                C.POINTER(Window), C.POINTER(C.POINTER(Window)), C.POINTER(C.c_uint)]),
            "XFree": (C.c_int, [C.c_void_p]),
            "XQueryExtension": (C.c_int, [Display, C.c_char_p, C.POINTER(C.c_int),
                C.POINTER(C.c_int), C.POINTER(C.c_int)]),
            "XGetEventData": (C.c_int, [Display, C.POINTER(Cookie)]),
            "XFreeEventData": (None, [Display, C.POINTER(Cookie)]),
            "XDefineCursor": (C.c_int, [Display, Window, Window]),
        }
        for name, (result, args) in signatures.items():
            func = getattr(self.x, name)
            func.restype, func.argtypes = result, args
        self.xi.XIQueryVersion.argtypes = [Display, C.POINTER(C.c_int), C.POINTER(C.c_int)]
        self.xi.XISelectEvents.argtypes = [Display, Window, C.POINTER(EventMask), C.c_int]

    def start(self, cursor_id=0):
        try:
            self.display = self.x.XOpenDisplay(None)
            if not self.display:
                raise RuntimeError("could not open X11 display")
            self.root = self.x.XDefaultRootWindow(self.display)
            screen = self.x.XDefaultScreen(self.display)
            self.width = self.x.XDisplayWidth(self.display, screen)
            self.height = self.x.XDisplayHeight(self.display, screen)
            opcode, event, error = C.c_int(), C.c_int(), C.c_int()
            if not self.x.XQueryExtension(self.display, b"XInputExtension",
                                         C.byref(opcode), C.byref(event), C.byref(error)):
                raise RuntimeError("XInput extension unavailable")
            self.opcode = opcode.value
            major, minor = C.c_int(2), C.c_int(2)
            if self.xi.XIQueryVersion(self.display, C.byref(major), C.byref(minor)) != 0 or (major.value, minor.value) < (2, 2):
                raise RuntimeError("XInput 2.2 touch support is required")
            # ButtonPress, ButtonRelease, PointerMotion; prevent propagation too.
            pointer_mask = (1 << 2) | (1 << 3) | (1 << 6)
            attrs = Attributes(event_mask=pointer_mask, do_not_propagate_mask=pointer_mask,
                               override_redirect=1)
            self.window = self.x.XCreateWindow(self.display, self.root, 0, 0,
                self.width, self.height, 0, 0, 2, None,
                (1 << 9) | (1 << 11) | (1 << 12), C.byref(attrs))
            # XIAllMasterDevices; select TouchBegin/Update/End (18, 19, 20).
            mask = (C.c_ubyte * 3)(0, 0, 0x1c)
            selection = EventMask(1, 3, mask)
            if self.xi.XISelectEvents(self.display, self.window, C.byref(selection), 1):
                raise RuntimeError("could not select touchscreen events")
            if cursor_id:
                self.x.XDefineCursor(self.display, self.window, cursor_id)
            self.x.XSelectInput(self.display, self.root, 1 << 19)  # SubstructureNotify
            self.x.XMapWindow(self.display, self.window)
            self.x.XFlush(self.display)
            self.watch = GLib.io_add_watch(self.x.XConnectionNumber(self.display),
                GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._read)
            # Also drain events buffered by synchronous XQueryTree replies.
            self.poll = GLib.timeout_add(250, self._poll)
            self.restack()
        except Exception:
            self.close()
            raise

    def restack(self):
        if not self.display:
            return
        root, parent, count = Window(), Window(), C.c_uint()
        children = C.POINTER(Window)()
        if not self.x.XQueryTree(self.display, self.root, C.byref(root), C.byref(parent),
                                C.byref(children), C.byref(count)):
            return
        try:
            order = list(children[:count.value])
        finally:
            if children:
                self.x.XFree(children)
        bar = self.control_window()
        wanted = [self.window] + ([bar] if bar else [])
        # Ignore unmapped windows (GTK retains its popup when hidden). It is
        # safe for the hidden popup to remain above us, so omit it here.
        hidden_bar = self.control_window(include_hidden=True)
        if not bar:
            order = [w for w in order if w != hidden_bar]
        if order[-len(wanted):] != wanted:
            for window in wanted:
                self.x.XRaiseWindow(self.display, window)
            self.x.XFlush(self.display)

    def _read(self, _fd, condition):
        if condition & (GLib.IO_ERR | GLib.IO_HUP):
            self.watch = 0
            self.failed("X11 input connection closed")
            return False
        keep = self._tick()
        if not keep:
            self.watch = 0
        return keep

    def _poll(self):
        keep = self._tick()
        if not keep:
            self.poll = 0
        return keep

    def _tick(self):
        if not self.display:
            return False
        try:
            event = Event()
            # Bound each drain so touch bursts cannot starve GTK button events.
            for _ in range(256):
                if not self.x.XPending(self.display):
                    break
                self.x.XNextEvent(self.display, C.byref(event))
                if event.type == 35 and event.cookie.extension == self.opcode:
                    cookie = event.cookie
                    if self.x.XGetEventData(self.display, C.byref(cookie)):
                        try:
                            if cookie.evtype in (18, 19, 20):
                                touch = C.cast(cookie.data, C.POINTER(TouchEvent)).contents
                                key = ("touch", touch.deviceid, touch.detail)
                                phase = {18: "begin", 19: "move", 20: "end"}[cookie.evtype]
                                if phase == "begin":
                                    self.touch_ids.add(key)
                                self.gesture(phase, key, touch.root_x, touch.root_y)
                                if phase == "end":
                                    self.touch_ids.discard(key)
                        finally:
                            self.x.XFreeEventData(self.display, C.byref(cookie))
                elif event.type in (4, 5, 6) and not self.touch_ids:
                    pointer = event.pointer
                    if event.type == 4 and pointer.button == 1:
                        self.mouse_down = True
                        self.gesture("begin", "mouse", pointer.x_root, pointer.y_root)
                    elif event.type == 6 and self.mouse_down:
                        self.gesture("move", "mouse", pointer.x_root, pointer.y_root)
                    elif event.type == 5 and pointer.button == 1 and self.mouse_down:
                        self.mouse_down = False
                        self.gesture("end", "mouse", pointer.x_root, pointer.y_root)
            self.restack()
        except Exception as exc:
            self.failed(str(exc))
            return False
        return bool(self.display)

    def close(self):
        for source in (self.watch, self.poll):
            if source:
                GLib.source_remove(source)
        self.watch = self.poll = 0
        if self.display:
            # Closing this connection destroys the input window even on failure.
            self.x.XCloseDisplay(self.display)
        self.display = None
        self.window = 0
        self.touch_ids.clear()
