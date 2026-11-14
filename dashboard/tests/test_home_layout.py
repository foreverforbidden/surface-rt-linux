import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import home_layout as hl  # noqa: E402

AVAILABLE = {"clock": ("S", "M", "L"), "timers": ("S", "M"), "controls": ("S",),
             "notes": ("S", "M"), "airplay": ("S", "M"), "system": ("S", "M")}
PREFERRED = [("clock", "M"), ("timers", "S"), ("controls", "S"),
             ("notes", "S"), ("airplay", "S"), ("system", "M")]


def spots(items):
    return [(i["widget"], page, col, row) for i, page, col, row, _w, _h in hl.pack(items)]


class PackTests(unittest.TestCase):
    def test_default_fills_one_page_like_the_mockup(self):
        items = hl.default_layout(AVAILABLE, PREFERRED)
        self.assertEqual(spots(items), [
            ("clock", 0, 0, 0), ("timers", 0, 2, 0), ("controls", 0, 3, 0),
            ("notes", 0, 0, 1), ("airplay", 0, 1, 1), ("system", 0, 2, 1),
        ])
        self.assertEqual(hl.page_count(items), 1)

    def test_overflow_goes_to_page_two(self):
        items = [{"widget": f"w{i}", "size": "L"} for i in range(3)]
        self.assertEqual([p for _w, p, _c, _r in spots(items)], [0, 0, 1])
        self.assertEqual(hl.page_count(items), 2)

    def test_small_widget_fills_an_earlier_gap(self):
        items = [{"widget": "a", "size": "M"}, {"widget": "b", "size": "L"},
                 {"widget": "c", "size": "S"}]
        self.assertEqual(spots(items), [("a", 0, 0, 0), ("b", 0, 2, 0), ("c", 0, 0, 1)])

    def test_empty(self):
        self.assertEqual(hl.pack([]), [])
        self.assertEqual(hl.page_count([]), 1)


class EditTests(unittest.TestCase):
    def test_next_size_cycles_through_allowed(self):
        self.assertEqual(hl.next_size("S", ("S", "M", "L")), "M")
        self.assertEqual(hl.next_size("L", ("S", "M", "L")), "S")
        self.assertEqual(hl.next_size("M", ("S", "M")), "S")
        self.assertEqual(hl.next_size("S", ("S",)), "S")
        self.assertEqual(hl.next_size("L", ("S", "M")), "S")

    def test_move_swaps_and_stops_at_the_ends(self):
        items = ["a", "b", "c"]
        self.assertEqual(hl.move(items, 1, -1), ["b", "a", "c"])
        self.assertEqual(hl.move(items, 0, -1), items)
        self.assertEqual(hl.move(items, 2, 1), items)

    def test_clean_drops_unknown_duplicates_and_fixes_sizes(self):
        items = [{"widget": "clock", "size": "L"}, {"widget": "gone", "size": "S"},
                 {"widget": "clock", "size": "S"}, {"widget": "controls", "size": "L"}, "junk"]
        self.assertEqual(hl.clean(items, AVAILABLE), [
            {"widget": "clock", "size": "L"}, {"widget": "controls", "size": "S"}])


class StorageTests(unittest.TestCase):
    def test_round_trip_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "home.json")
            self.assertEqual(hl.load(path, AVAILABLE, PREFERRED), hl.default_layout(AVAILABLE, PREFERRED))
            items = [{"widget": "system", "size": "S"}]
            hl.save(path, items)
            self.assertEqual(hl.load(path, AVAILABLE, PREFERRED), items)
            hl.save(path, [])   # an emptied home stays empty
            self.assertEqual(hl.load(path, AVAILABLE, PREFERRED), [])
            with open(path, "w") as fh:
                fh.write("{not json")
            self.assertEqual(hl.load(path, AVAILABLE, PREFERRED), hl.default_layout(AVAILABLE, PREFERRED))


if __name__ == "__main__":
    unittest.main()
