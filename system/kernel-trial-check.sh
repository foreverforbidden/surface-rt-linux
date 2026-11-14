#!/bin/sh
# Trial-boot safety net, installed by scripts/install-kernel.sh as /usr/local/sbin/kernel-trial-check.sh.
# If this is a trial boot of the new kernel and there is no working network @WAIT@ seconds after
# boot, reboot. /boot/startup.nsh has already deleted its one-shot flag, so the reboot lands
# on the old kernel. Does nothing on the old kernel or once /etc/kernel-trial is removed.
[ "$(uname -r)" = "@RELEASE@" ] || exit 0
[ -e /etc/kernel-trial ] || exit 0
sleep @WAIT@
GW=$(ip route | awk '/^default/{print $3; exit}')
if [ -n "$GW" ] && ping -c 3 -W 5 "$GW" >/dev/null 2>&1; then
	echo "kernel-trial: network is up, leaving the new kernel running" > /dev/kmsg
	exit 0
fi
echo "kernel-trial: no network after @WAIT@ seconds, rebooting to the old kernel" > /dev/kmsg
sync
systemctl reboot --force
