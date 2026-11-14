fs0:
if exist trynew.flag then
  rm -q trynew.flag
  zImage7 dtb=rt7efi.dtb root=PARTUUID=@ROOT_PARTUUID@ rootwait console=tty0 cpuidle.off=1 panic=10
endif
zImage dtb=tegra30-microsoft-surface-rt-efi.dtb root=/dev/mmcblk0p2 rootwait console=tty0 cpuidle.off=1

# shutdown if something went wrong
reset -s