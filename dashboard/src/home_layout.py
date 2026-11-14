"""The Home screen's widget layout: which widgets, what size, in what order.

Pure Python (no GTK) so the Mac can test it (tests/test_home_layout.py).

Widgets flow into pages of COLS x ROWS cells in list order, each one taking the
first free spot that fits (scanning pages, then rows, then columns), so a small
widget can fill a gap an earlier big one left. Moving a widget swaps it with its
neighbour in the list. The layout is kept in ~/.local/state/dashboard/home.json,
outside ~/app, so a deploy leaves it alone.
"""

import json
import os

COLS, ROWS = 4, 2
SIZES = {"S": (1, 1), "M": (2, 1), "L": (2, 2)}
SIZE_ORDER = ("S", "M", "L")
VERSION = 1


def pack(items, cols=COLS, rows=ROWS):
    """[(item, page, col, row, w, h)] for items like {"widget": ..., "size": ...}."""
    pages = []          # one set of occupied (col, row) cells per page
    placed = []
    for item in items:
        w, h = SIZES.get(item.get("size"), SIZES["S"])
        w, h = min(w, cols), min(h, rows)
        spot = None
        page = 0
        while spot is None:
            if page == len(pages):
                pages.append(set())
            used = pages[page]
            for row in range(rows - h + 1):
                for col in range(cols - w + 1):
                    cells = {(col + dx, row + dy) for dx in range(w) for dy in range(h)}
                    if not cells & used:
                        spot = (col, row, cells)
                        break
                if spot:
                    break
            if spot is None:
                page += 1
        col, row, cells = spot
        pages[page] |= cells
        placed.append((item, page, col, row, w, h))
    return placed


def page_count(items):
    placed = pack(items)
    return max((p[1] for p in placed), default=0) + 1


def next_size(size, allowed):
    """The size after `size` among `allowed`, wrapping around (S -> M -> L -> S)."""
    allowed = [s for s in SIZE_ORDER if s in allowed]
    if not allowed:
        return size
    if size not in allowed:
        return allowed[0]
    return allowed[(allowed.index(size) + 1) % len(allowed)]


def move(items, index, step):
    """A copy of items with items[index] swapped with its neighbour `step` (-1 / +1) away."""
    items = list(items)
    other = index + step
    if 0 <= index < len(items) and 0 <= other < len(items):
        items[index], items[other] = items[other], items[index]
    return items


def clean(items, available):
    """Drop widgets that no longer exist, duplicates and bad sizes.

    available: {widget id: allowed sizes}.
    """
    seen, out = set(), []
    for item in items:
        if not isinstance(item, dict):
            continue
        wid, size = item.get("widget"), item.get("size")
        if wid not in available or wid in seen:
            continue
        allowed = available[wid]
        if size not in allowed:
            size = allowed[0]
        seen.add(wid)
        out.append({"widget": wid, "size": size})
    return out


def default_layout(available, preferred):
    """The first-run Home: the `preferred` [(widget id, size)] that exist.

    Widgets not listed start off Home; the Add sheet offers them.
    """
    return clean([{"widget": w, "size": s} for w, s in preferred], available)


def load(path, available, preferred):
    try:
        with open(path) as fh:
            data = json.load(fh)
        items = clean(data.get("items", []), available)
        if items or data.get("items") == []:
            return items
    except (OSError, ValueError, AttributeError):
        pass
    return default_layout(available, preferred)


def save(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"v": VERSION, "items": items}, fh, indent=1)
    os.replace(tmp, path)
