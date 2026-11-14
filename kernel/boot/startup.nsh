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
