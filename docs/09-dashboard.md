# Touch dashboard

[dashboard/](../dashboard/) is the fullscreen touch app that runs on our tablet all day. It is Python 3.9 and GTK 3 with no build step. Use it as it is, or as an example of a kiosk app that fits this hardware.

It has:

- A side menu with large buttons and an editable Home page: a 4×2 grid of widgets per page, in sizes S, M and L. Swipe sideways to change the page.
- A clock with world cities on a map, and timers with an audible alarm.
- System: battery, network, CPU and RAM, brightness and volume sliders, restart and reboot.
- A tap-to-fix panel for Wi-Fi and services.
- Sleep: turns the backlight off. The next tap turns it on and does not press anything.
- An AirPlay receiver tile with touch controls ([07-video-airplay.md](07-video-airplay.md)).
- Hardware volume buttons with an on-screen level bar.

## How it starts

```
LightDM (autologin) -> Openbox -> ~/.config/openbox/autostart -> ~/app/run.sh -> dashboard.py
```

[run.sh](../dashboard/src/run.sh) restarts the dashboard when it exits. If it crashes within 30 seconds three times in a row, `run.sh` opens [rescue.py](../dashboard/src/rescue.py) instead. The rescue screen loads only `core` and `sysfix`, so a broken widget cannot take it down. It shows the end of the log, the tap-to-fix panel, and buttons to retry or reboot. Exit code 143 (SIGTERM, for example from a redeploy) does not count as a crash.

To test the rescue path, run a script that crashes:

```bash
echo 'raise SystemExit(1)' > /tmp/crash.py
DASHBOARD=/tmp/crash.py ~/app/run.sh
```

## Install

On the tablet:

```bash
sudo apt-get -y install lightdm openbox python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-gstreamer-1.0 alsa-utils iw fonts-inter ffmpeg
sudo usermod -aG video,input "$USER"        # backlight and volume buttons
sudo cp system/90-backlight.rules /etc/udev/rules.d/
```

The Wi-Fi fixes, service restarts and the Reboot button run `sudo -n`, so the user needs passwordless `sudo`.

Set LightDM to log your user in automatically into an Openbox session. On Raspberry Pi OS, set `autologin-user=` and `autologin-session=openbox` in the `[Seat:*]` section of `/etc/lightdm/lightdm.conf`. Then enable it:

```bash
sudo systemctl enable lightdm
```

From your PC:

```bash
rsync -av --delete dashboard/src/ rt:~/app/
ssh rt mkdir -p .config/openbox
scp system/openbox-autostart rt:.config/openbox/autostart
ssh rt sudo reboot
```

The log is `~/app.log`. To restart only the dashboard, run `pkill -f '^python3 dashboard.py'`. `run.sh` starts it again.

## Configure

[config.json](../dashboard/src/config.json) lists the modules, the clock cities and timer presets, and the AirPlay settings. Each module is a file in `modules/` with a `Module` class (see `core.Module`). The Sleep module always loads.

The dashboard keeps its state in `~/.local/state/dashboard/`, outside the deploy directory, so `rsync --delete` does not remove it:

- `home.json`: the Home layout. Delete it to get the default layout back.
- Clock timers, recent timers and the alarm sound.

## Tests

The logic modules do not need GTK or the tablet, so you can test them on your PC:

```bash
cd dashboard && python3 -m unittest discover -s tests -v
```

## What we learned about GTK on this tablet

These cost us time:

- The whole window must fit the screen. If one page is wider than the screen, the fullscreen window becomes wider than the screen, and every page loses its right edge. With a side menu, our pages had about 1253 px of width (1366 minus the menu). Check with `xdotool search --name "^Dashboard$" getwindowgeometry`.
- A `Gtk.EventBox` ignores CSS padding. Put the padding on an inner `Gtk.Box`.
- From PyGObject, the `get-child-position` signal of `Gtk.Overlay` returned garbage. We placed moving rows in a `Gtk.Layout` with `move()` instead.
- Put a drag gesture on a widget that does not move. On the moving widget, the offsets came out halved.
- `GestureSwipe` never reported a velocity with synthetic `xdotool` drags. A `GestureDrag` in the capture phase worked for the Home swipe.
- Popups have no transparent corners without a compositor. Use square popups.
- Run slow commands (ping, `systemctl restart`) off the GTK thread, or the screen freezes.
- There is no accessibility bus. Set `NO_AT_BRIDGE=1` to skip the failing lookup at startup.

## Big touch targets

The screen is 10.6 inches at 1366×768. Buttons of at least 56 to 60 px are easy to hit with a finger. The side menu buttons are about 88 px high.
