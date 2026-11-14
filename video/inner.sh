#!/bin/sh
# Runs inside the build container (see build.sh). Builds a minimal GStreamer for armhf with the
# V4L2 stateless decoders (tegra-vde), installed under PREFIX on the tablet.
set -eu
VERSION=1.26.11
PREFIX=${PREFIX:-/opt/gst-hw}  # baked into the build: install the output at this same path
cd /work
[ -d src ] || git clone --depth 1 --branch "$VERSION" https://gitlab.freedesktop.org/gstreamer/gstreamer.git src
[ -d build ] && [ inner.sh -nt build/build.ninja ] && rm -rf build  # options changed: reconfigure
[ -d build ] || meson setup build src --cross-file armhf.cross --force-fallback-for=libdrm \
    --prefix="$PREFIX" --libdir=lib --buildtype=release -Db_lto=false \
    -Dauto_features=disabled -Dbase=enabled -Dgood=enabled -Dbad=enabled \
    -Dlibav=disabled -Dugly=disabled -Ddevtools=disabled -Dges=disabled -Drtsp_server=disabled \
    -Dpython=disabled -Dintrospection=disabled -Ddoc=disabled -Dtests=disabled -Dexamples=disabled \
    -Dnls=disabled -Dtools=enabled -Dgst-examples=disabled \
    -Dgstreamer:tools=enabled -Dgstreamer:coretracers=enabled \
    -Dgst-plugins-base:app=enabled -Dgst-plugins-base:videoconvertscale=enabled \
    -Dgst-plugins-base:videotestsrc=enabled -Dgst-plugins-base:typefind=enabled \
    -Dgst-plugins-base:drm=enabled \
    -Dgst-plugins-base:x11=enabled -Dgst-plugins-base:xvideo=enabled -Dgst-plugins-base:xshm=enabled \
    -Dgst-plugins-good:isomp4=enabled \
    -Dgst-plugins-bad:v4l2codecs=enabled -Dgst-plugins-bad:videoparsers=enabled \
    -Dgst-plugins-bad:kms=enabled -Dgst-plugins-bad:debugutils=enabled
ninja -C build
rm -rf out && DESTDIR=/work/out meson install -C build --no-rebuild --strip
echo "installed: $(du -sh out | cut -f1)"
