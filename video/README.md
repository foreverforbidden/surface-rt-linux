# Video

- `build.sh`, `inner.sh`, `Dockerfile`, `armhf.cross`: cross-build GStreamer 1.26.11 for armhf with the V4L2 stateless decoders (`tegra-vde`) and `kmssink`. Run `./build.sh` with Docker running. The result is in `out/opt/gst-hw` (set `PREFIX` for another path).
- `uxplay-1.73.7-render-rect.patch`: render-rectangle signals and a plugin-check switch for UxPlay 1.73.7.

See [docs/07-video-airplay.md](../docs/07-video-airplay.md).
