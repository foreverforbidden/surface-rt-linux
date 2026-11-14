# Kernel files

- `overlay/`: our config for Raspberry Pi OS 11, as a linux-surface-rt overlay. `scripts/build-kernel.sh` uses it.
- `boot/`: the UEFI shell scripts from our tablet, as examples. `@ROOT_PARTUUID@` is the PARTUUID of your root partition (`findmnt -no PARTUUID /`). The install scripts write these files for you.
  - `startup-old.nsh`: the original script that boots the 5.17 kernel.
  - `startup-trial.nsh`: one trial boot of the new kernel if `trynew.flag` exists.
  - `startup.nsh`: the default after a good trial, with a one-shot `oldkernel.flag` fallback.

See [docs/03-safe-boot.md](../docs/03-safe-boot.md).
