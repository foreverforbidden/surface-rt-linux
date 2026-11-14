import os
import pathlib
import sys
import tempfile
import unittest
import wave
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import clock_logic  # noqa: E402

WARSAW = ZoneInfo("Europe/Warsaw")
NOV14 = datetime(2026, 11, 14, 14, 56, tzinfo=WARSAW)


def minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


class CityNow(unittest.TestCase):
    def test_same_zone(self):
        city = clock_logic.city_now("Europe/Warsaw", NOV14)
        self.assertEqual(city["time"], "14:56")
        self.assertEqual((city["day"], city["offset"]), ("Today", "+0 HRS"))
        self.assertTrue(city["daytime"])
        self.assertIsNone(city["sunrise"])

    def test_west(self):
        la = clock_logic.city_now("America/Los_Angeles", NOV14)
        self.assertEqual((la["time"], la["day"], la["offset"]), ("05:56", "Today", "-9 HRS"))
        self.assertFalse(la["daytime"])
        chicago = clock_logic.city_now("America/Chicago", NOV14)
        self.assertEqual((chicago["time"], chicago["offset"]), ("07:56", "-7 HRS"))

    def test_other_day_and_half_hour(self):
        now = datetime(2026, 11, 14, 2, 0, tzinfo=WARSAW)
        self.assertEqual(clock_logic.city_now("America/Chicago", now)["day"], "Yesterday")
        late = datetime(2026, 11, 14, 22, 0, tzinfo=WARSAW)
        india = clock_logic.city_now("Asia/Kolkata", late)
        self.assertEqual((india["time"], india["day"], india["offset"]), ("02:30", "Tomorrow", "+4.5 HRS"))

    def test_unknown_zone_raises(self):
        with self.assertRaises(Exception):
            clock_logic.city_now("Nowhere/Atlantis")

    def test_sun_times_match_the_reference_screenshot(self):
        # Apple's Clock on 14 November: Warsaw 06:54/15:45, Los Angeles 06:24/16:49, Chicago 06:39/16:31
        expected = {"Warsaw": ("06:54", "15:45"), "Los Angeles": ("06:24", "16:49"), "Chicago": ("06:39", "16:31")}
        for name, tz, lat, lon in clock_logic.DEFAULT_CITIES:
            city = clock_logic.city_now(tz, NOV14, lat, lon)
            for got, want in zip((city["sunrise"], city["sunset"]), expected[name]):
                self.assertLessEqual(abs(minutes(got) - minutes(want)), 3, f"{name}: {got} vs {want}")

    def test_daytime_follows_the_sun(self):
        # 14:56 in Warsaw: day there; 05:56 in Los Angeles: before sunrise; 07:56 in Chicago: after it
        up = {name: clock_logic.city_now(tz, NOV14, lat, lon)["daytime"]
              for name, tz, lat, lon in clock_logic.DEFAULT_CITIES}
        self.assertEqual(up, {"Warsaw": True, "Los Angeles": False, "Chicago": True})

    def test_polar_night_has_no_sun_times(self):
        self.assertIsNone(clock_logic.sun_times(78.2, 15.6, date(2026, 12, 21), timezone.utc))

    def test_parse_cities(self):
        cities = clock_logic.parse_cities([["A", "Europe/Warsaw", 1, 2], ["B", "Europe/Paris"], ["C", "No/Zone"], 5])
        self.assertEqual([c["name"] for c in cities], ["A", "B"])
        self.assertEqual((cities[0]["lat"], cities[1]["lat"]), (1.0, None))


class Sun(unittest.TestCase):
    def test_subsolar_point(self):
        noon = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        lat, lon = clock_logic.subsolar_point(noon)
        self.assertAlmostEqual(lat, 23.44, delta=0.1)
        self.assertAlmostEqual(lon, 0, delta=1)   # the equation of time moves it under a degree

    def test_terminator(self):
        points, dark_pole = clock_logic.terminator(NOV14)
        self.assertEqual((points[0][0], points[-1][0]), (-180, 180))
        self.assertEqual(dark_pole, 90)   # northern winter: the north pole is dark
        self.assertTrue(all(-90 < lat < 90 for _lon, lat in points))
        # a point just on the dark-pole side of the line is in the night
        lon, lat = points[len(points) // 2]
        self.assertFalse(clock_logic.sun_is_up(lat + 2, lon, NOV14))
        self.assertTrue(clock_logic.sun_is_up(lat - 2, lon, NOV14))

    def test_terminator_at_equinox_does_not_blow_up(self):
        clock_logic.terminator(datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc))


class Formats(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(clock_logic.format_hms(420), "00:07:00")
        self.assertEqual(clock_logic.format_hms(3725), "01:02:05")
        self.assertEqual(clock_logic.format_short(420), "7:00")
        self.assertEqual(clock_logic.format_short(45), "0:45")
        self.assertEqual(clock_logic.format_short(3725), "1:02:05")
        self.assertEqual(clock_logic.format_short(-3), "0:00")

    def test_names(self):
        self.assertEqual(clock_logic.duration_name(420), "7 min")
        self.assertEqual(clock_logic.duration_name(450), "7 min 30 sec")
        self.assertEqual(clock_logic.duration_name(3900), "1 hr 5 min")
        self.assertEqual(clock_logic.duration_name(45), "45 sec")
        self.assertEqual(clock_logic.split_hms(3725), (1, 2, 5))


class Recents(unittest.TestCase):
    def test_add_moves_to_top_and_caps(self):
        self.assertEqual(clock_logic.recents_add([420, 600], 600), [600, 420])
        self.assertEqual(clock_logic.recents_add([420, 600], 90), [90, 420, 600])
        self.assertEqual(clock_logic.recents_add(list(range(1, 9)), 99), [99, 1, 2, 3, 4, 5, 6, 7])

    def test_sync_keeps_edits_until_the_presets_change(self):
        seed = [420, 600]
        self.assertEqual(clock_logic.recents_sync([90, 600], seed, seed), [90, 600])  # 420 was deleted: stays gone
        self.assertEqual(clock_logic.recents_sync([90, 600], seed, [300, 600]), [300, 600, 90])
        self.assertEqual(clock_logic.recents_sync([], None, seed), seed)


class Timers(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.wall = 5000.0
        self.set = clock_logic.TimerSet(clock=lambda: self.now, wall=lambda: self.wall)

    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds

    def test_runs_to_zero_once(self):
        timer = self.set.add(60)
        self.assertEqual(self.set.remaining(timer), 60)
        self.advance(59.5)
        self.assertEqual(self.set.remaining(timer), 1)
        self.assertEqual(self.set.poll(), [])
        self.advance(0.5)
        self.assertEqual(self.set.poll(), [timer])
        self.assertEqual((self.set.poll(), self.set.timers), ([], []))

    def test_several_at_once(self):
        long, short = self.set.add(600), self.set.add(30)
        self.assertIs(self.set.soonest(), short)
        self.advance(30)
        self.assertEqual(self.set.poll(), [short])
        self.assertIs(self.set.soonest(), long)
        self.assertEqual(self.set.remaining(long), 570)
        self.assertAlmostEqual(self.set.fraction(long), 0.95)
        self.assertEqual(self.set.ends_at(long), self.wall + 570)

    def test_pause_stops_the_countdown(self):
        timer = self.set.add(60)
        other = self.set.add(300)
        self.advance(20)
        self.set.pause(timer)
        self.advance(100)
        self.assertEqual((timer.state, self.set.remaining(timer)), ("paused", 40))
        self.assertEqual(self.set.poll(), [])
        self.assertIs(self.set.soonest(), other)   # a running timer is shown before a paused one
        self.set.resume(timer)
        self.advance(40)
        self.assertEqual(self.set.poll(), [timer])

    def test_cancel(self):
        timer = self.set.add(60)
        self.set.cancel(timer)
        self.advance(100)
        self.assertEqual((self.set.poll(), self.set.soonest()), ([], None))

    def test_survives_a_restart(self):
        running, paused, short = self.set.add(600), self.set.add(300), self.set.add(30)
        self.advance(10)
        self.set.pause(paused)
        saved = self.set.dump()
        # the dashboard is down for 50 s; the new process has an unrelated monotonic clock
        self.wall += 50
        self.now = 7.0
        fresh = clock_logic.TimerSet(clock=lambda: self.now, wall=lambda: self.wall)
        fresh.load(saved)
        done = fresh.poll()
        self.assertEqual([t.total for t in done], [30])           # ran out while down: rings at once
        left = {t.total: (t.state, fresh.remaining(t)) for t in fresh.timers}
        self.assertEqual(left, {600: ("running", 540), 300: ("paused", 290)})

    def test_load_ignores_junk(self):
        self.set.load([{"total": 5}, "x", {"total": 60, "state": "paused", "left": 12}])
        self.assertEqual([(t.total, t.state) for t in self.set.timers if t.state == "paused"], [(60, "paused")])


class State(unittest.TestCase):
    def test_round_trip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deep", "clock.json")
            self.assertEqual(clock_logic.load_state(path), {})
            clock_logic.save_state(path, {"recents": [420]})
            self.assertEqual(clock_logic.load_state(path), {"recents": [420]})
            with open(path, "w") as fh:
                fh.write("{broken")
            self.assertEqual(clock_logic.load_state(path), {})


class Chime(unittest.TestCase):
    def test_writes_a_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chime.wav")
            clock_logic.write_chime(path)
            with wave.open(path) as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth()), (2, 2))
                self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 2.4, places=1)


if __name__ == "__main__":
    unittest.main()
