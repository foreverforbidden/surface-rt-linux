import importlib
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from airplay_controls import Controls
from airplay_settings import receiver_args


class Scheduler:
    def __init__(self):
        self.pending = {}
        self.serial = 0

    def timeout_add(self, _ms, callback, *args):
        self.serial += 1
        self.pending[self.serial] = lambda: callback(*args)
        return self.serial

    def source_remove(self, timer):
        self.pending.pop(timer)

    def expire(self):
        for timer in list(self.pending):
            self.pending.pop(timer)()


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.clock = Scheduler()
        self.show, self.hide = Mock(), Mock()
        self.controls = Controls(self.clock, self.show, self.hide)
        self.controls.start()
        self.controls.set_waiting(False)

    def test_revealing_tap_only_shows_on_release(self):
        self.clock.expire()
        self.show.reset_mock()
        self.controls.gesture("begin", 1, 30, 40)
        self.show.assert_not_called()
        self.controls.gesture("end", 1, 30, 40)
        self.show.assert_called_once()
        self.assertTrue(self.controls.visible)
        self.assertEqual(len(self.clock.pending), 1)

    def test_drag_and_multitouch_do_not_reveal(self):
        self.controls.dismiss()
        self.show.reset_mock()
        self.controls.gesture("begin", 1, 0, 0)
        self.controls.gesture("move", 1, 100, 0)
        self.controls.gesture("end", 1, 0, 0)
        self.controls.gesture("begin", 1, 0, 0)
        self.controls.gesture("begin", 2, 0, 0)
        self.controls.gesture("end", 1, 0, 0)
        self.controls.gesture("end", 2, 0, 0)
        self.show.assert_not_called()
        self.assertFalse(self.controls.presses)

    def test_press_pauses_timeout_until_release(self):
        self.controls.press("button")
        self.assertFalse(self.clock.pending)
        self.clock.expire()
        self.assertTrue(self.controls.visible)
        self.controls.release("button")
        self.clock.expire()
        self.assertFalse(self.controls.visible)

    def test_waiting_keeps_controls_visible(self):
        self.controls.set_waiting(True)
        self.assertFalse(self.clock.pending)
        self.controls.dismiss()
        self.assertTrue(self.controls.visible)

    def test_stop_cleans_timers_and_pending_gestures(self):
        self.controls.gesture("begin", 1, 0, 0)
        self.controls.stop()
        self.controls.gesture("end", 1, 0, 0)
        self.assertFalse(self.controls.active)
        self.assertFalse(self.controls.visible)
        self.assertFalse(self.controls.gestures)
        self.assertFalse(self.clock.pending)
        self.controls.start()
        self.assertTrue(self.controls.visible)


class SettingsTests(unittest.TestCase):
    def test_defaults_and_trailing_overrides(self):
        args = receiver_args("uxplay", {"resolution": "960x540", "fps": 30,
                                       "args": ["-fps", "24"]})
        self.assertEqual(args[args.index("-s") + 1], "960x540")
        self.assertEqual(args[-2:], ["-fps", "24"])
        self.assertIn("leaky=downstream", args[args.index("-vd") + 1])
        self.assertEqual(args[args.index("-vc") + 1], "videoconvert n-threads=2")

    def test_hw_env_uses_private_build_only(self):
        from airplay_settings import HW_PREFIX, hw_env
        env = hw_env({"LD_LIBRARY_PATH": "/x", "GST_PLUGIN_PATH": "/usr/lib", "HOME": "/h"})
        self.assertEqual(env["LD_LIBRARY_PATH"], HW_PREFIX + "/lib:/x")
        self.assertEqual(env["GST_PLUGIN_SYSTEM_PATH"], HW_PREFIX + "/lib/gstreamer-1.0")
        self.assertNotIn("GST_PLUGIN_PATH", env)
        self.assertNotIn("1.18", env["GST_REGISTRY"])

    def test_hw_decoder_uses_kms_overlay_without_fullscreen(self):
        from airplay_settings import HW_UXPLAY, receiver_env, receiver_executable
        config = {"decoder": "hw", "resolution": "1280x720", "fps": 60}
        self.assertEqual(receiver_executable(config), HW_UXPLAY)
        args = receiver_args(HW_UXPLAY, config)
        self.assertNotIn("-fs", args)  # -fs would make uxplay force a modeset over X
        self.assertEqual(args[args.index("-vd") + 1], "v4l2slh264dec")
        self.assertNotIn("leaky", " ".join(args))
        self.assertTrue(args[args.index("-vs") + 1].startswith("kmssink "))
        env = receiver_env(config, {"UXPLAY_RECT_SIGUSR2": "1,2,3,4"}, (0, 0, 1366, 680))
        self.assertEqual(env["UXPLAY_RECT_SIGUSR1"], "0,0,1366,680")
        self.assertNotIn("UXPLAY_RECT_SIGUSR2", env)  # unset = full display
        self.assertEqual(env["LD_HWCAP_MASK"], "0")

    def test_slice_decoder_keeps_system_receiver(self):
        from airplay_settings import SYSTEM_UXPLAY, receiver_env, receiver_executable
        self.assertEqual(receiver_executable({}), SYSTEM_UXPLAY)
        self.assertIn("-fs", receiver_args(SYSTEM_UXPLAY, {}))
        self.assertNotIn("LD_LIBRARY_PATH", receiver_env({}, {}))

    def test_invalid_config(self):
        for config in ({"resolution": "bad"}, {"fps": 0}, {"fps": True}, {"args": "-avdec"},
                       {"decoder": "vaapi"}):
            with self.assertRaises(ValueError):
                receiver_args("uxplay", config)


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These tests exercise process ownership without requiring GTK on the Mac.
        core = Mock()
        core.Module = object
        with patch.dict(sys.modules, {"gi": Mock(), "gi.repository": Mock(), "core": core}):
            cls.module = importlib.import_module("modules.airplay")

    def setUp(self):
        self.m = self.module.Module.__new__(self.module.Module)
        self.m.proc = Mock()
        self.m._kill_timer = 99
        self.m._output_watch = 88
        self.m._stopping = False
        self.m._finish_ui = Mock()
        self.m._set_status = Mock()

    def test_stale_callbacks_cannot_touch_new_receiver(self):
        old = Mock()
        self.assertFalse(self.m._on_output(-1, 0, old))
        self.m._force_kill(old)
        self.m._on_exit(1, 0, old)
        self.assertEqual(self.m._kill_timer, 99)
        self.assertEqual(self.m._output_watch, 88)
        self.m.proc.kill.assert_not_called()
        self.m._finish_ui.assert_not_called()

    def test_crash_cleans_output_timer_and_ui(self):
        proc = self.m.proc
        with patch.object(self.module, "GLib", Scheduler()) as clock:
            clock.pending = {99: None, 88: None}
            self.m._on_exit(1, 9, proc)
            self.assertFalse(clock.pending)
        self.assertEqual(proc.returncode, -9)
        proc.stdout.close.assert_called_once()
        self.assertIsNone(self.m.proc)
        self.m._finish_ui.assert_called_once()

    def test_repeated_stop_has_one_kill_timer(self):
        self.m.controls = Mock()
        self.m.exit_button = Mock()
        self.m.hide_button = Mock()
        with patch.object(self.module, "GLib", Mock()) as glib:
            self.m.stop()
            self.m.stop()
            self.m.proc.terminate.assert_called_once()
            glib.timeout_add_seconds.assert_called_once()

    def test_controls_signal_video_plane_only_for_hw(self):
        self.m.proc.returncode = None
        self.m.bar = Mock()
        for hw, calls in ((False, 0), (True, 1)):
            self.m._hw = hw
            self.m.proc.send_signal.reset_mock()
            self.m._hide_controls()
            self.assertEqual(self.m.proc.send_signal.call_count, calls)
        self.m.proc.send_signal.assert_called_with(self.module.signal.SIGUSR2)

    def test_generic_button_events_use_numeric_button_identity(self):
        self.m.controls = Controls(Scheduler(), Mock(), Mock())
        self.m.controls.start()
        self.m.controls.set_waiting(False)
        kinds = self.module.Gdk.EventType
        down = Mock(type=kinds.BUTTON_PRESS)
        up = Mock(type=kinds.BUTTON_RELEASE)
        down.get_button.return_value = up.get_button.return_value = (True, 1)
        self.m._control_event(None, down)
        self.assertEqual(self.m.controls.presses, {("bar-button", 1)})
        self.m._control_event(None, up)
        self.assertFalse(self.m.controls.presses)


if __name__ == "__main__":
    unittest.main()
