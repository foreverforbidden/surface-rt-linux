"""Control-bar timing and gesture policy, independent of GTK/X11."""

import time


class Controls:
    def __init__(self, scheduler, show, hide):
        self.scheduler, self.show, self.hide = scheduler, show, hide
        self.active = False
        self.waiting = True
        self.visible = False
        self.timer = 0
        self.presses = set()
        self.gestures = {}

    def cancel_timer(self):
        if self.timer:
            self.scheduler.source_remove(self.timer)
            self.timer = 0

    def start(self):
        self.active = True
        self.set_waiting(True)

    def stop(self):
        self.active = False
        self.cancel_timer()
        self.presses.clear()
        self.gestures.clear()
        self.visible = False
        self.hide()

    def set_waiting(self, waiting):
        self.waiting = waiting
        if self.active:
            if waiting:
                self.reveal()
            else:
                self.arm_timer()

    def reveal(self):
        if self.active:
            self.visible = True
            self.show()
            self.arm_timer()

    def dismiss(self):
        # An active press must finish before its window is hidden.
        if not self.waiting and not self.presses:
            self.cancel_timer()
            self.visible = False
            self.hide()

    def arm_timer(self):
        self.cancel_timer()
        if self.active and self.visible and not self.waiting and not self.presses:
            self.timer = self.scheduler.timeout_add(4000, self._expire)

    def _expire(self):
        self.timer = 0
        self.dismiss()
        return False

    def press(self, key):
        self.presses.add(key)
        self.cancel_timer()

    def release(self, key):
        self.presses.discard(key)
        self.arm_timer()

    def gesture(self, phase, key, x, y):
        if not self.active:
            return
        if phase == "begin":
            # Multiple fingers swallow the whole gesture, including its final release.
            for item in self.gestures.values():
                item[3] = False
            self.gestures[key] = [x, y, time.monotonic(), not self.gestures]
            self.press(key)
        elif key in self.gestures:
            item = self.gestures[key]
            if (x - item[0]) ** 2 + (y - item[1]) ** 2 > 18 ** 2:
                item[3] = False
            if phase == "end":
                del self.gestures[key]
                self.release(key)
                if item[3] and time.monotonic() - item[2] < 1 and not self.gestures:
                    self.reveal()
