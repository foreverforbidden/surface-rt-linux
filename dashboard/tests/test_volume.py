import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import volume  # noqa: E402  (GTK is only imported inside Volume, so the Mac can run these)

CGET = """numid=63,iface=MIXER,name='Speaker Volume'
  ; type=INTEGER,access=rw---R--,values=2,min=0,max=127,step=0
  : values=102,102
  | dBscale-min=-121.00dB,step=1.00dB,mute=1
"""


def event(kind, code, value):
    return volume.EVENT.pack(0, 0, kind, code, value)


class Levels(unittest.TestCase):
    def test_steps_map_to_the_mixer_and_back(self):
        self.assertEqual(volume.step_to_raw(0), 0)
        self.assertEqual(volume.step_to_raw(16), 121)
        self.assertEqual(volume.step_to_raw(1), 76)
        self.assertEqual(volume.step_to_raw(99), 121)
        for step in range(17):
            self.assertEqual(volume.raw_to_step(volume.step_to_raw(step)), step)

    def test_levels_set_by_other_tools_land_on_the_nearest_step(self):
        self.assertEqual(volume.raw_to_step(127), 16)
        self.assertEqual(volume.raw_to_step(102), 10)
        self.assertEqual(volume.raw_to_step(5), 1)

    def test_parse_raw(self):
        self.assertEqual(volume.parse_raw(CGET), 102)
        self.assertIsNone(volume.parse_raw("amixer: Cannot find the given element"))


class Keys(unittest.TestCase):
    def test_volume_buttons(self):
        data = (event(1, 115, 1) + event(0, 0, 0) + event(1, 115, 2) + event(1, 115, 0)
                + event(1, 114, 1) + event(1, 116, 1))
        self.assertEqual(volume.parse_keys(data), [(1, True), (1, False), (-1, True)])

    def test_partial_event_is_ignored(self):
        self.assertEqual(volume.parse_keys(event(1, 114, 1)[:-3]), [])


if __name__ == "__main__":
    unittest.main()
