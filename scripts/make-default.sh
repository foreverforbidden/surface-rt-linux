#!/bin/sh
# Make the new kernel the default after a good trial boot (see install-kernel.sh).
# Run it while the tablet runs the new kernel. The old kernel stays on /boot as a fallback.
#
# Usage: scripts/make-default.sh [--dry-run] HOST [ARTIFACT_DIR]
# Uses the same NEW_IMAGE, NEW_DTB and KERNEL_ARGS settings as install-kernel.sh.
#
# The new /boot/startup.nsh:
#   - boots the old kernel once if /boot/oldkernel.flag exists (scripts/rollback.sh once HOST),
#   - else boots the new kernel,
#   - and falls through to the old kernel if the new one cannot be started.
set -eu

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
HOST=${1:?usage: make-default.sh [--dry-run] HOST [ARTIFACT_DIR]}
TOP=$(cd "$(dirname "$0")/.." && pwd)
ART=$(cd "${2:-$TOP/out}" && pwd)
NEW_IMAGE=${NEW_IMAGE:-zImage7}
NEW_DTB=${NEW_DTB:-rt7efi.dtb}
KERNEL_ARGS=${KERNEL_ARGS:-rootwait console=tty0 cpuidle.off=1 panic=10}

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

REL=$(cat "$ART/kernel.release")
CUR=$(ssh "$HOST" 'uname -r')
[ "$CUR" = "$REL" ] || die "$HOST runs $CUR, not $REL. Boot the new kernel first (install-kernel.sh)"
ssh "$HOST" 'test -f /boot/startup-old.nsh' || die "$HOST: no /boot/startup-old.nsh"
for f in "$NEW_IMAGE" "$NEW_DTB"; do ssh "$HOST" "test -f /boot/$f" || die "$HOST: no /boot/$f"; done
PARTUUID=$(ssh "$HOST" 'findmnt -no PARTUUID /')

# The old script's commands, without fs0: and the final reset (the new script adds its own).
OLD_BODY=$(ssh "$HOST" 'cat /boot/startup-old.nsh' | tr -d '\r' \
	| grep -v -e '^[[:space:]]*fs0:[[:space:]]*$' -e '^[[:space:]]*reset' -e '^[[:space:]]*#' -e '^[[:space:]]*$')
[ -n "$OLD_BODY" ] || die "$HOST: /boot/startup-old.nsh has no commands"

NEW=$( {
	echo 'fs0:'
	echo '# One-shot return to the old kernel: create oldkernel.flag from Linux, then reboot.'
	echo 'if exist oldkernel.flag then'
	echo '  rm -q oldkernel.flag'
	printf '%s\n' "$OLD_BODY" | sed 's/^/  /'
	echo 'endif'
	echo "$NEW_IMAGE dtb=$NEW_DTB root=PARTUUID=$PARTUUID $KERNEL_ARGS"
	echo '# Only reached if the new kernel could not be started: fall back to the old one.'
	printf '%s\n' "$OLD_BODY"
	echo ''
	echo '# shutdown if something went wrong'
	echo 'reset -s'
} | sed 's/$/\r/')

if [ "$DRY" = 1 ]; then
	say "dry run: nothing changed. New /boot/startup.nsh would be:"
	printf '%s\n' "$NEW" | tr -d '\r' | sed 's/^/    | /'
	echo "  then: disable kernel-trial-check.service, remove it and /etc/kernel-trial"
	exit 0
fi

STAGE=$(mktemp)
printf '%s' "$NEW" > "$STAGE"
ssh "$HOST" "sudo sh -c 'cat > /boot/startup.nsh.new && mv /boot/startup.nsh.new /boot/startup.nsh && sync'" < "$STAGE"
ssh "$HOST" 'sudo cmp -s /boot/startup.nsh -' < "$STAGE" || die "/boot/startup.nsh does not match"
rm -f "$STAGE"
ssh "$HOST" 'sudo systemctl disable kernel-trial-check.service 2>/dev/null || true
	sudo rm -f /etc/kernel-trial /etc/systemd/system/kernel-trial-check.service /usr/local/sbin/kernel-trial-check.sh
	sudo systemctl daemon-reload'
say "$REL is now the default. Fallback: scripts/rollback.sh once $HOST, or Esc at boot and startup-old.nsh"
