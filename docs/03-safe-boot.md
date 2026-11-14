# Safe kernel trials from the UEFI shell

The Surface RT has no boot menu that you can reach over SSH. Wi-Fi is often the only way in, so a kernel that boots without Wi-Fi looks dead. This page shows how to test a new kernel once and fall back to the old one with no keyboard.

## How the tablet boots

The UEFI firmware starts the UEFI shell. The shell runs `/boot/startup.nsh` on the vfat boot partition (`fs0:`). That script starts the kernel with the EFI stub:

```
fs0:
zImage dtb=tegra30-microsoft-surface-rt-efi.dtb root=/dev/mmcblk0p2 rootwait console=tty0 cpuidle.off=1
```

There is no GRUB and no initramfs.

## What the UEFI shell can do

We tested these on the tablet before we tried a new kernel:

- `if exist FILE then ... endif` works in `startup.nsh`.
- `rm -q FILE` works, and it can write to the boot partition. A test script deleted a flag file, and the file was gone after the boot.

The scripts also expect one thing that we did not test: when a kernel line cannot start its image, the shell goes on to the next line. The UEFI shell runs scripts this way, but no kernel of ours has failed to start.

This is enough for a one-shot boot with a fallback. The script never edits itself. Linux creates a flag file, and the shell deletes it before it starts the new kernel.

We gave the new files short names (`zImage7`, `rt7efi.dtb`) as a precaution against FAT name problems in the shell. We did not test long names. The Open Surface RT page [FAT32 isn't FAT32](https://open-rt.gitbook.io/open-surfacert/common/boot-sequence/uefi/fat32-isnt-fat32) explains why the firmware's FAT support needs care.

## The trial boot script

[kernel/boot/startup-trial.nsh](../kernel/boot/startup-trial.nsh) is the script that `install-kernel.sh` writes:

```
fs0:
if exist trynew.flag then
  rm -q trynew.flag
  zImage7 dtb=rt7efi.dtb root=PARTUUID=@ROOT_PARTUUID@ rootwait console=tty0 cpuidle.off=1 panic=10
endif
zImage dtb=tegra30-microsoft-surface-rt-efi.dtb root=/dev/mmcblk0p2 rootwait console=tty0 cpuidle.off=1

# shutdown if something went wrong
reset -s
```

The script does this:

1. If `trynew.flag` exists, the shell deletes it and starts the new kernel.
2. If there is no flag, the shell starts the old kernel. It should also start the old kernel if the new image cannot start.

So every boot after the trial is an old-kernel boot, whatever happens in the trial. The script uses `root=PARTUUID=` for the new kernel. A PARTUUID does not depend on the order in which the kernel numbers the MMC devices. `install-kernel.sh` reads it from the tablet with `findmnt -no PARTUUID /`.

## What can go wrong in the trial

| What happens | What brings the old kernel back |
|---|---|
| The new kernel boots with Wi-Fi | Nothing to do. SSH works on the new kernel |
| The kernel panics | `panic=10` reboots after 10 seconds. The flag is gone, so the old kernel boots |
| The kernel boots, but there is no network | `kernel-trial-check.service` waits 5 minutes, then pings the gateway. If the ping fails, it reboots |
| The tablet hangs | Hold the power button. The next boot is the old kernel |
| Anything else | Press Esc at boot, then run `fs0:` and `startup-old.nsh` |

The trial check is [system/kernel-trial-check.sh](../system/kernel-trial-check.sh) and its unit file. It only acts when `uname -r` is the new release and `/etc/kernel-trial` exists. `make-default.sh` removes both files.

## Step by step

1. Look at every change first. The dry run reads from the tablet and changes nothing:

   ```bash
   scripts/install-kernel.sh --dry-run rt out/
   ```

2. Install. The script checks the artifact checksums and copies the boot partition to `boot-backup/` on your PC. It copies the kernel and device tree to `/boot` under new names, the modules to `/lib/modules/<release>/`, and arms the trial check. Then it writes the trial `startup.nsh` and creates `/boot/trynew.flag`. It stops if any file it would write already exists.

   ```bash
   scripts/install-kernel.sh rt out/
   ```

3. Go to the tablet and reboot it:

   ```bash
   ssh rt sudo reboot
   ```

4. Check the new kernel:

   ```bash
   ssh rt 'uname -r; nproc; systemctl --failed; dmesg --level=err,warn | tail -20'
   ```

   Expect `7.2.13-surface`, 4 CPUs and no failed units. [04-hardware-status.md](04-hardware-status.md) lists the warnings that are normal.

5. Make it the default:

   ```bash
   scripts/make-default.sh rt out/
   ```

   This writes [kernel/boot/startup.nsh](../kernel/boot/startup.nsh) and removes the trial check. The old kernel, its device tree and `startup-old.nsh` stay on `/boot`.

On our tablet, the trial boot worked the first time, and SSH was back in less than a minute. A `reboot` from 7.2.13 then came back on 5.17 after 21 seconds, as planned. That proved the reboot path and the one-shot fallback.

## The default boot script

```
fs0:
# One-shot return to the old 5.17 kernel: create oldkernel.flag from Linux, then reboot.
if exist oldkernel.flag then
  rm -q oldkernel.flag
  zImage dtb=tegra30-microsoft-surface-rt-efi.dtb root=/dev/mmcblk0p2 rootwait console=tty0 cpuidle.off=1
endif
zImage7 dtb=rt7efi.dtb root=PARTUUID=@ROOT_PARTUUID@ rootwait console=tty0 cpuidle.off=1 panic=10
# Only reached if the 7.2 kernel could not be started: fall back to 5.17.
zImage dtb=tegra30-microsoft-surface-rt-efi.dtb root=/dev/mmcblk0p2 rootwait console=tty0 cpuidle.off=1

# shutdown if something went wrong
reset -s
```

## Going back

| You want | Do this |
|---|---|
| The old kernel for one boot | `scripts/rollback.sh once rt` (creates `/boot/oldkernel.flag` and reboots). We did not test this path |
| The old kernel as the default again | `scripts/rollback.sh restore rt`, then reboot |
| The old kernel with no network | Press Esc at boot, then run `fs0:` and `startup-old.nsh` |
| To remove the new kernel | Restore first, then delete `/boot/zImage7`, `/boot/rt7efi.dtb` and `/lib/modules/7.2.13-surface/` |

Never overwrite `zImage`, its `.dtb` or `startup-old.nsh`. They are your way back.

`startup-old.nsh` is saved once, at the first install. A later upgrade (for example from 7.2.13 to a newer kernel) still falls back to that original kernel, not to the kernel before it. Give each new kernel its own names with `NEW_IMAGE` and `NEW_DTB`.

## Doing it by hand

The scripts only automate these steps. Without them:

1. Back up `/boot` to another machine.
2. Copy the modules into `/lib/modules/<release>/`. On Raspberry Pi OS, `/lib` can be a symlink, so copy the directory. Do not untar the archive over `/`.
3. Copy `zImage` and the EFI `.dtb` to `/boot` under names that do not exist yet.
4. Save the current `startup.nsh` as `startup-old.nsh`.
5. Write a trial `startup.nsh` like the one above, then `touch /boot/trynew.flag`.
6. Reboot, check, and write the default script.
