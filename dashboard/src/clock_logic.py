"""World-clock, sun and countdown logic for the clock tile. No GTK here, so the Mac can test it."""

import array
import json
import math
import os
import time
import wave
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# name, zone, latitude, longitude (north and east positive)
DEFAULT_CITIES = [
    ["Warsaw", "Europe/Warsaw", 52.23, 21.01],
    ["Los Angeles", "America/Los_Angeles", 34.05, -118.24],
    ["Chicago", "America/Chicago", 41.88, -87.63],
]
DEFAULT_TIMERS = [7, 10, 14, 20]  # minutes
MAX_RECENTS = 8
MAX_SECONDS = 23 * 3600 + 59 * 60 + 59


# ---- the sun ---------------------------------------------------------------------
# NOAA's low-accuracy solar equations: good to about a minute, plenty for a clock.

def _sun(utc):
    """(declination in radians, equation of time in minutes) at an aware datetime."""
    utc = utc.astimezone(timezone.utc)
    g = 2 * math.pi / 365 * (utc.timetuple().tm_yday - 1 + (utc.hour + utc.minute / 60 - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    return decl, eqtime


def subsolar_point(utc):
    """(lat, lon) in degrees of the spot where the sun is overhead."""
    decl, eqtime = _sun(utc)
    utc = utc.astimezone(timezone.utc)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    lon = (720 - minutes - eqtime) / 4
    return math.degrees(decl), (lon + 180) % 360 - 180


def sun_is_up(lat, lon, utc):
    sub_lat, sub_lon = subsolar_point(utc)
    la, dec = math.radians(lat), math.radians(sub_lat)
    sin_alt = (math.sin(la) * math.sin(dec)
               + math.cos(la) * math.cos(dec) * math.cos(math.radians(lon - sub_lon)))
    return sin_alt > math.sin(math.radians(-0.833))


def sun_times(lat, lon, day, tz):
    """(sunrise, sunset) as aware datetimes in `tz` for the local date `day`.

    None when the sun doesn't rise or doesn't set that day.
    """
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    decl, eqtime = _sun(midnight + timedelta(hours=12 - lon / 15))  # local solar noon
    la = math.radians(lat)
    cos_h = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if not -1 <= cos_h <= 1:
        return None
    h = math.degrees(math.acos(cos_h))
    rise = midnight + timedelta(minutes=720 - 4 * (lon + h) - eqtime)
    sets = midnight + timedelta(minutes=720 - 4 * (lon - h) - eqtime)
    return rise.astimezone(tz), sets.astimezone(tz)


def terminator(utc, step=3):
    """The day/night line as [(lon, lat), ...] from -180 to 180, and the dark pole's latitude."""
    sub_lat, sub_lon = subsolar_point(utc)
    dec = math.radians(sub_lat)
    if abs(dec) < 1e-3:  # at an equinox the line is two meridians; nudge off the singularity
        dec = math.copysign(1e-3, dec or 1)
    points = []
    for lon in range(-180, 181, step):
        lat = math.degrees(math.atan(-math.cos(math.radians(lon - sub_lon)) / math.tan(dec)))
        points.append((lon, lat))
    return points, (-90 if dec > 0 else 90)


# ---- cities ----------------------------------------------------------------------

def parse_cities(entries):
    """config "clock.cities" -> [{"name", "tz", "lat", "lon"}]; bad entries are skipped."""
    cities = []
    for entry in entries:
        try:
            name, tz = str(entry[0]), str(entry[1])
            ZoneInfo(tz)
            lat = float(entry[2]) if len(entry) > 3 else None
            lon = float(entry[3]) if len(entry) > 3 else None
        except Exception as exc:
            print(f"[clock] skipping city {entry!r}: {exc}", flush=True)
            continue
        cities.append({"name": name, "tz": tz, "lat": lat, "lon": lon})
    return cities


def city_now(tz_name, now=None, lat=None, lon=None):
    """The time in a zone, compared with local time.

    `now` is an aware datetime in the local zone (default: the current time).
    With coordinates, daytime follows the real sun and sunrise/sunset are filled in.
    Raises if the zone name is unknown.
    """
    local = now or datetime.now().astimezone()
    zone = ZoneInfo(tz_name)
    there = local.astimezone(zone)
    days = (there.date() - local.date()).days
    hours = (there.utcoffset() - local.utcoffset()).total_seconds() / 3600
    city = {
        "time": there.strftime("%H:%M"),
        "hour": there.hour,
        "minute": there.minute,
        "day": {-1: "Yesterday", 0: "Today", 1: "Tomorrow"}.get(days, there.strftime("%A")),
        "offset": f"{hours:+g} HRS",
        "daytime": 6 <= there.hour < 18,
        "sunrise": None,
        "sunset": None,
    }
    if lat is not None and lon is not None:
        city["daytime"] = sun_is_up(lat, lon, local)
        times = sun_times(lat, lon, there.date(), zone)
        if times:
            city["sunrise"], city["sunset"] = (t.strftime("%H:%M") for t in times)
    return city


# ---- durations -------------------------------------------------------------------

def format_hms(seconds):
    """3725 -> '01:02:05'."""
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def format_short(seconds):
    """'7:00', '0:45', or '1:02:05' from an hour up."""
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def duration_name(seconds):
    """450 -> '7 min 30 sec'."""
    seconds = max(0, int(seconds))
    parts = [(seconds // 3600, "hr"), (seconds // 60 % 60, "min"), (seconds % 60, "sec")]
    return " ".join(f"{n} {unit}" for n, unit in parts if n) or "0 sec"


def split_hms(seconds):
    seconds = max(0, int(seconds))
    return seconds // 3600, seconds // 60 % 60, seconds % 60


# ---- recents ---------------------------------------------------------------------

def recents_add(recents, seconds, cap=MAX_RECENTS):
    """A started length moves to the top; the oldest drop off past `cap`."""
    return ([seconds] + [s for s in recents if s != seconds])[:cap]


def recents_sync(recents, old_seed, seed):
    """Keep the saved list unless the presets in config.json changed; then put the new presets first."""
    if seed == old_seed:
        return list(recents)
    return (list(seed) + [s for s in recents if s not in seed])[:max(MAX_RECENTS, len(seed))]


# ---- timers ----------------------------------------------------------------------

class Timer:
    """One countdown, owned by a TimerSet. state is 'running' or 'paused'."""

    def __init__(self, ident, total):
        self.id = ident
        self.total = int(total)   # the length it was started with, seconds
        self.state = "running"
        self.end = 0.0            # running: the monotonic time at which it finishes
        self.left = 0.0           # paused: seconds left


class TimerSet:
    """Any number of countdowns. Monotonic time while running; wall-clock end times when saved."""

    def __init__(self, clock=time.monotonic, wall=time.time):
        self._clock = clock
        self._wall = wall
        self._next_id = 1
        self.timers = []  # in the order they were started

    def _new(self, total):
        timer = Timer(self._next_id, total)
        self._next_id += 1
        self.timers.append(timer)
        return timer

    def add(self, seconds):
        timer = self._new(seconds)
        timer.end = self._clock() + timer.total
        return timer

    def get(self, ident):
        return next((t for t in self.timers if t.id == ident), None)

    def pause(self, timer):
        if timer.state == "running":
            timer.left = max(0.0, timer.end - self._clock())
            timer.state = "paused"

    def resume(self, timer):
        if timer.state == "paused":
            timer.end = self._clock() + timer.left
            timer.state = "running"

    def cancel(self, timer):
        if timer in self.timers:
            self.timers.remove(timer)

    def _left(self, timer):
        return max(0.0, timer.end - self._clock()) if timer.state == "running" else timer.left

    def remaining(self, timer):
        """Whole seconds left, rounded up so the display reaches 0 only at the end."""
        return math.ceil(self._left(timer))

    def fraction(self, timer):
        """How much is left, 1.0 -> 0.0."""
        return min(1.0, self._left(timer) / timer.total) if timer.total else 0.0

    def ends_at(self, timer):
        """The wall-clock time (epoch seconds) at which it will ring if left alone."""
        return self._wall() + self._left(timer)

    def running(self):
        return [t for t in self.timers if t.state == "running"]

    def soonest(self):
        """The timer to show on the tile: the running one ending first, else a paused one."""
        pool = self.running() or self.timers
        return min(pool, key=self._left) if pool else None

    def poll(self):
        """The running timers that have reached zero; they leave the set."""
        now = self._clock()
        done = [t for t in self.timers if t.state == "running" and now >= t.end]
        for timer in done:
            self.timers.remove(timer)
        return done

    def dump(self):
        return [
            {"total": t.total, "state": t.state,
             "end": self.ends_at(t) if t.state == "running" else None,
             "left": None if t.state == "running" else t.left}
            for t in self.timers
        ]

    def load(self, saved):
        """Restore dump() output. A timer that ran out in the meantime is returned by the next poll()."""
        for item in saved:
            try:
                timer = self._new(item["total"])
                if item["state"] == "paused":
                    timer.state, timer.left = "paused", float(item["left"])
                else:
                    timer.end = self._clock() + (float(item["end"]) - self._wall())
            except (KeyError, TypeError, ValueError):
                continue


# ---- saved state -----------------------------------------------------------------

def load_state(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)  # never leaves a half-written file


# ---- the alarm sound -------------------------------------------------------------

def write_chime(path, rate=22050):
    """Write the alarm: a rising two-note chime played twice, then a pause (about 2.4 s)."""
    samples = array.array("h")

    def note(freq, seconds):
        count = int(rate * seconds)
        for i in range(count):
            t = i / rate
            attack = min(1.0, i / (rate * 0.005))            # 5 ms ramp: no click
            envelope = attack * math.exp(-4.5 * t)           # rings out like a bell
            wave_ = math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(4 * math.pi * freq * t)
            value = int(22000 * envelope * wave_ / 1.3)
            samples.extend((value, value))

    def rest(seconds):
        samples.extend([0] * (2 * int(rate * seconds)))

    for _ in range(2):
        note(1047, 0.28)   # C6
        note(1568, 0.52)   # G6
    rest(0.8)
    with wave.open(path, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
