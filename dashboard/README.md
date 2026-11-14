# Dashboard

A fullscreen touch dashboard for the Surface RT, in Python 3.9 and GTK 3. See [docs/09-dashboard.md](../docs/09-dashboard.md).

- `src/`: the app. Deploy it with `rsync -av --delete src/ rt:~/app/`.
- `tests/`: unit tests that run on any PC: `python3 -m unittest discover -s tests -v`.
- `tools/make-world-map.py`: makes `src/assets/world-land.json` from Natural Earth.
