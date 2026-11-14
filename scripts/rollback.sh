#!/bin/sh
# Go back to the old kernel.
#
# Usage:
#   scripts/rollback.sh once HOST      boot the old kernel on the next boot only, then reboot
#   scripts/rollback.sh restore HOST   make the old boot script the default again (no reboot)
#
# Without Linux: at the tablet, press Esc during boot and run startup-old.nsh in the UEFI shell.
set -eu

MODE=${1:?usage: rollback.sh once|restore HOST}
HOST=${2:?usage: rollback.sh once|restore HOST}

ssh "$HOST" 'test -f /boot/startup-old.nsh' || { echo "$HOST: no /boot/startup-old.nsh" >&2; exit 1; }
case "$MODE" in
once)
	# Works only with a startup.nsh from make-default.sh (it checks for oldkernel.flag).
	ssh "$HOST" 'grep -q oldkernel.flag /boot/startup.nsh' \
		|| { echo "$HOST: /boot/startup.nsh does not check oldkernel.flag; use restore" >&2; exit 1; }
	ssh "$HOST" 'sudo touch /boot/oldkernel.flag && sync && sudo systemctl reboot'
	;;
restore)
	ssh "$HOST" 'sudo cp /boot/startup.nsh /boot/startup-new.nsh \
		&& sudo cp /boot/startup-old.nsh /boot/startup.nsh && sync'
	echo "old boot script restored; the previous one is /boot/startup-new.nsh. Reboot when ready."
	;;
*)
	echo "usage: rollback.sh once|restore HOST" >&2
	exit 1
	;;
esac
