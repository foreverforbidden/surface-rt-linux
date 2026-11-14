# Audio, input and display

## Speakers

The sound card is a Wolfson WM8962 (ALSA card `WM8962`). On our tablet the card was there after boot, but the speaker path was off: the DAC was not routed to the speaker amplifier.

[system/speaker-on.sh](../system/speaker-on.sh) sets the route once and saves it with `alsactl store`:

```bash
sh system/speaker-on.sh          # default volume 80%
sh system/speaker-on.sh 60%      # or another volume
```

It sets these controls:

| Control | Value | Why |
|---|---|---|
| `SPKOUTL PGA`, `SPKOUTR PGA` | `DAC` | The DAC feeds the speaker amplifier directly, not through the mixer |
| `Speaker Switch` | `on,on` | |
| `Speaker Volume` | 80% | The amplifier level |
| `Int Spk Switch`, `Speakers Switch` | `on` | |
| `Digital Playback Volume` | `96,96` | 0 dB, the driver default |

Save your mixer state before you run it, so that you can go back:

```bash
sudo alsactl store -f ~/asound.state.before-speaker
```

Then test it, and listen. An exit code of 0 from `aplay` does not prove that you can hear anything:

```bash
speaker-test -c 2 -t wav -l 1
```

`alsa-restore` saves the level at shutdown and restores it at boot.

## Volume buttons

The volume buttons are a `gpio-keys` input device:

```
/dev/input/by-path/platform-gpio-keys-event
```

They send `KEY_VOLUMEUP` (115) and `KEY_VOLUMEDOWN` (114). A program can read them directly, without X, if its user is in the `input` group. Then the buttons work whichever window has focus, and also while the screen is off:

```bash
sudo usermod -aG input "$USER"
sudo evtest /dev/input/by-path/platform-gpio-keys-event     # to see the events
```

The dashboard maps them to 16 steps on the ALSA control `Speaker Volume`, capped at 0 dB ([dashboard/src/volume.py](../dashboard/src/volume.py)).

## Backlight

The backlight is in `/sys/class/backlight/`. Only root can write `brightness` by default. [system/90-backlight.rules](../system/90-backlight.rules) gives the `video` group write access:

```bash
sudo cp system/90-backlight.rules /etc/udev/rules.d/
sudo usermod -aG video "$USER"
```

The rule runs when the device appears, so reboot after you install it. Then:

```bash
cat /sys/class/backlight/*/max_brightness
echo 0 > /sys/class/backlight/*/brightness       # screen off
```

linux-surface-rt has two backlight patches: a lower minimum brightness, and linear levels at 1 kHz (`0037` and `0044`).

The `backlight-toggle.service` from our older image did not work on 7.2, so we disabled it. The dashboard's Sleep button sets the brightness to 0, and the next tap turns it back on.

## Keep the screen on

By default, X blanks the screen after some minutes with no input. For a kiosk, turn that off in the session's autostart:

```bash
xset -dpms
xset s off
xset s noblank
```

[system/openbox-autostart](../system/openbox-autostart) does this.

## Touchscreen

The touch controller is an Atmel mXT1386E. It works as an X input device with no extra setup. Programs that use XInput 2.2 get real multi-touch contacts. Programs that do not get emulated mouse events from the first finger.

Two tools help when you test touch interfaces without touching the screen:

```bash
sudo apt-get -y install xdotool scrot
DISPLAY=:0 xdotool mousemove 600 400 click 1     # a synthetic tap
DISPLAY=:0 scrot /tmp/screen.png                 # a screenshot
```

Synthetic events are mouse events, not touch events, so they do not prove that the touchscreen works.
