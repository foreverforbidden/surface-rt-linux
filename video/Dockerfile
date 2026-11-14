# Cross-build container for GStreamer on the Surface RT: Debian 11 (bullseye) on the Mac's own
# arch, with Debian's armhf cross compiler and armhf -dev packages. Same glibc (2.31) and glib
# (2.66) as the tablet's Raspbian 11. No emulation.
FROM debian:bullseye-slim
ENV DEBIAN_FRONTEND=noninteractive
# Bullseye is end-of-life: its packages (including security updates) live on archive.debian.org.
RUN printf '%s\n' \
      'deb http://archive.debian.org/debian bullseye main' \
      'deb http://archive.debian.org/debian-security bullseye-security main' \
      > /etc/apt/sources.list && rm -f /etc/apt/sources.list.d/* \
    && dpkg --add-architecture armhf && apt-get update && apt-get install -y --no-install-recommends \
    crossbuild-essential-armhf pkg-config ninja-build flex bison git ca-certificates \
    python3 python3-pip python3-setuptools libglib2.0-dev-bin \
    libglib2.0-dev:armhf libgudev-1.0-dev:armhf libdrm-dev:armhf \
    libx11-dev:armhf libxext-dev:armhf libxv-dev:armhf \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir meson==1.5.2
WORKDIR /work
