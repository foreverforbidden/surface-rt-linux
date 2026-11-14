# Raspbian upkeep

Raspberry Pi OS 11 (bullseye, armhf) runs well on the Surface RT, but it thinks that it runs on a Raspberry Pi. These rules keep upgrades from breaking the boot.

## Hold the Pi kernel packages

The packages `raspberrypi-kernel` and `raspberrypi-bootloader` write Raspberry Pi kernels and firmware to `/boot`. On the Surface RT, `/boot` is the UEFI boot partition. Hold both packages before your first upgrade:

```bash
sudo apt-mark hold raspberrypi-kernel raspberrypi-bootloader
apt-mark showhold
```

Do not install or upgrade any other kernel or bootloader package. No package manages the Surface RT kernel. You install it by hand or with [scripts/install-kernel.sh](../scripts/install-kernel.sh).

## Upgrade without prompts

Over SSH there is nobody to answer `dpkg` questions. This command keeps your changed config files and never stops to ask:

```bash
sudo nohup sh -c 'DEBIAN_FRONTEND=noninteractive apt-get -y \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade' \
    > ~/upgrade.log 2>&1 &
tail -f ~/upgrade.log
```

`nohup` keeps the upgrade running if the SSH connection drops.

On our image, every upgrade printed an error about the `samba-ad-dc` preset. It is expected and harmless.

## Low memory

The tablet has 2 GB of RAM, and our image had about 100 MB of swap. A process that needs more memory gets killed by the OOM killer. It does not slow down first.

- Do not compile large programs on the tablet. Cross-compile on your PC. [video/](../video/) and [scripts/build-kernel.sh](../scripts/build-kernel.sh) show how.
- Small C programs are fine with `make -j2`.
- Large `npm install` runs can fail. Install on another armhf machine or vendor pure-JavaScript `node_modules`.

## 32-bit ARM packages

The tablet is armhf (armv7l). Many projects have stopped making 32-bit ARM builds, so check before you choose a package or a binary.

Node.js is an example. The NodeSource `node_22.x` repository has armhf builds up to 22.15.0, the last one there.

## Run things in the background

A program in the foreground of an SSH session stops when the session ends. Start long-running programs as system units:

```bash
sudo systemd-run --unit=myjob --collect --uid="$USER" /path/to/program
journalctl -u myjob -f
```

When user lingering is off (the default), systemd user units stop when the SSH session ends. Use system units, or `nohup` for one-off jobs.

## Kill only what you mean to kill

`pkill -f` matches the full command line. Over SSH, your own command runs as `bash -c '...pkill -f dashboard...'`, so an unanchored pattern also matches the SSH session and kills it. Anchor the pattern:

```bash
pkill -f '^python3 dashboard.py'
```

## Deploy from your PC

Keep the source on your PC and copy it to the tablet. Do not edit files on the tablet:

```bash
rsync -av --delete ./src/ rt:~/app/
```

`--delete` removes files on the tablet that are not in `src/`. Keep runtime data outside the deploy directory, for example in `~/.local/state/` or `/var/lib/`.

A running shell script keeps its old copy after rsync replaces the file. Restart the program to use the new copy.
