#!/bin/sh
# Install a new kernel on a Surface RT next to the old one, and arm ONE trial boot of it.
# Runs on your PC and drives the tablet over ssh. Nothing that exists on /boot is overwritten.
#
# Usage: scripts/install-kernel.sh [--dry-run] HOST [ARTIFACT_DIR]
#   HOST          ssh destination of the tablet (user@host or a ~/.ssh/config alias).
#                 The user needs passwordless sudo.
#   ARTIFACT_DIR  output of build-kernel.sh or an unpacked release (default: out/)
#
# Settings (environment):
#   NEW_IMAGE    name of the kernel on /boot      (default zImage7)
#   NEW_DTB      name of the device tree on /boot (default rt7efi.dtb)
#   KERNEL_ARGS  arguments after root=...         (default "rootwait console=tty0 cpuidle.off=1 panic=10")
#   TRIAL_WAIT   seconds the trial check waits for a network before it reboots (default 300)
#
# After this script: be at the tablet, then `ssh HOST sudo reboot`.
#   - Boots with network: run scripts/make-default.sh HOST to keep it.
#   - Panics: reboots after 10 s into the old kernel (panic=10).
#   - No network after TRIAL_WAIT: the trial check reboots into the old kernel.
#   - Hangs: hold the power button. The next boot is the old kernel.
set -eu

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
HOST=${1:?usage: install-kernel.sh [--dry-run] HOST [ARTIFACT_DIR]}
TOP=$(cd "$(dirname "$0")/.." && pwd)
ART=$(cd "${2:-$TOP/out}" && pwd)
NEW_IMAGE=${NEW_IMAGE:-zImage7}
NEW_DTB=${NEW_DTB:-rt7efi.dtb}
KERNEL_ARGS=${KERNEL_ARGS:-rootwait console=tty0 cpuidle.off=1 panic=10}
TRIAL_WAIT=${TRIAL_WAIT:-300}

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
ro() { ssh "$HOST" "$@"; }   # read-only probes: these also run in --dry-run

# 1. Artifacts are complete and match their checksums.
for f in zImage tegra30-microsoft-surface-rt-efi.dtb modules.tar.gz kernel.release SHA256SUMS; do
	[ -f "$ART/$f" ] || die "$ART/$f is missing"
done
(cd "$ART" && shasum -a 256 -c SHA256SUMS >/dev/null) || die "checksums in $ART do not match"
REL=$(cat "$ART/kernel.release")
case "$NEW_IMAGE$NEW_DTB" in *[!A-Za-z0-9._-]*) die "NEW_IMAGE/NEW_DTB: use letters, digits, dot, dash" ;; esac
say "kernel $REL from $ART"

# 2. The tablet looks like we expect.
ro true || die "cannot ssh to $HOST"
ro 'sudo -n true' || die "$HOST: sudo needs a password"
[ "$(ro 'findmnt -no FSTYPE /boot')" = vfat ] || die "$HOST: /boot is not the vfat boot partition"
ro 'test -f /boot/startup.nsh' || die "$HOST: no /boot/startup.nsh (is this a UEFI-shell setup?)"
CUR=$(ro 'uname -r')
[ "$CUR" != "$REL" ] || die "$HOST already runs $REL"
for f in "$NEW_IMAGE" "$NEW_DTB"; do
	ro "test ! -e /boot/$f" || die "$HOST: /boot/$f exists. Pick other names with NEW_IMAGE/NEW_DTB"
done
ro "test ! -e /lib/modules/$REL" || die "$HOST: /lib/modules/$REL exists"
ro 'test ! -e /boot/trynew.flag' || die "$HOST: a trial is already armed (/boot/trynew.flag)"
PARTUUID=$(ro 'findmnt -no PARTUUID /')
[ -n "$PARTUUID" ] || die "$HOST: cannot read the PARTUUID of /"
FREE=$(ro "df -k --output=avail /boot | tail -1")
NEED=$(( ($(wc -c < "$ART/zImage") + $(wc -c < "$ART/tegra30-microsoft-surface-rt-efi.dtb")) / 1024 + 1024 ))
[ "$FREE" -gt "$NEED" ] || die "$HOST: /boot has ${FREE} KiB free, needs ${NEED} KiB"

# The old boot script, without its fs0: line: the trial script falls through to it.
if ro 'test -e /boot/startup-old.nsh'; then OLD=/boot/startup-old.nsh; else OLD=/boot/startup.nsh; fi
OLD_BODY=$(ro "cat $OLD" | tr -d '\r' | grep -v '^[[:space:]]*fs0:[[:space:]]*$')
[ -n "$OLD_BODY" ] || die "$HOST: $OLD is empty"
say "$HOST runs $CUR; root PARTUUID=$PARTUUID; fallback is $OLD"

NEW_LINE="$NEW_IMAGE dtb=$NEW_DTB root=PARTUUID=$PARTUUID $KERNEL_ARGS"
TRIAL=$(printf 'fs0:\r\nif exist trynew.flag then\r\n  rm -q trynew.flag\r\n  %s\r\nendif\r\n' "$NEW_LINE"
	printf '%s\n' "$OLD_BODY" | sed 's/$/\r/')

# 3. Back up the boot files to this PC.
BACKUP="$TOP/boot-backup/$(date +%Y%m%d-%H%M%S)"
if [ "$DRY" = 0 ]; then
	mkdir -p "$BACKUP"
	ssh "$HOST" 'cd /boot && tar -cf - $(ls -A)' | tar -xf - -C "$BACKUP"
	(cd "$BACKUP" && find . -type f -exec shasum -a 256 {} + > SHA256SUMS)
	say "boot partition backed up to $BACKUP"
fi

# 4. Everything that changes the tablet, as one script run with sudo.
TMP=/tmp/surface-rt-modules-$REL.tar.gz
REMOTE=$(cat <<EOF
set -eu
T=\$(mktemp -d)
trap 'rm -rf "\$T" $TMP' EXIT
tar -xzf $TMP -C "\$T"
# /lib can be a symlink to /usr/lib: copy into it instead of untarring over /.
cp -a "\$T/lib/modules/$REL" /lib/modules/
depmod -a "$REL"
[ -e /boot/startup-old.nsh ] || cp /boot/startup.nsh /boot/startup-old.nsh
cat > /usr/local/sbin/kernel-trial-check.sh <<'SCRIPT'
$(sed -e "s/@RELEASE@/$REL/" -e "s/@WAIT@/$TRIAL_WAIT/" "$TOP/system/kernel-trial-check.sh")
SCRIPT
chmod 755 /usr/local/sbin/kernel-trial-check.sh
cat > /etc/systemd/system/kernel-trial-check.service <<'UNIT'
$(cat "$TOP/system/kernel-trial-check.service")
UNIT
systemctl daemon-reload
systemctl enable kernel-trial-check.service
touch /etc/kernel-trial
sync
EOF
)

if [ "$DRY" = 1 ]; then
	say "dry run: nothing changed. These steps would run:"
	echo "  copy zImage -> $HOST:/boot/$NEW_IMAGE"
	echo "  copy tegra30-microsoft-surface-rt-efi.dtb -> $HOST:/boot/$NEW_DTB"
	echo "  copy modules.tar.gz -> $HOST:$TMP"
	echo "  remote script (as root):"
	printf '%s\n' "$REMOTE" | sed 's/^/    | /'
	echo "  new /boot/startup.nsh:"
	printf '%s\n' "$TRIAL" | tr -d '\r' | sed 's/^/    | /'
	echo "  create /boot/trynew.flag"
	exit 0
fi

put() {  # put LOCAL_FILE REMOTE_PATH: copy as root, then compare
	ssh "$HOST" "sudo sh -c 'cat > $2'" < "$1"
	ssh "$HOST" "sudo cmp -s $2 -" < "$1" || die "copy to $HOST:$2 does not match"
}
put "$ART/zImage" "/boot/$NEW_IMAGE"
put "$ART/tegra30-microsoft-surface-rt-efi.dtb" "/boot/$NEW_DTB"
put "$ART/modules.tar.gz" "$TMP"
printf '%s\n' "$REMOTE" | ssh "$HOST" 'sudo sh -s' || die "installing modules or the trial check failed"
say "modules in /lib/modules/$REL, trial check armed"

# 5. The trial boot script, then the flag that arms it. Without the flag it boots the old kernel.
STAGE=$(mktemp)
printf '%s' "$TRIAL" > "$STAGE"
put "$STAGE" /boot/startup.nsh
rm -f "$STAGE"
ssh "$HOST" 'sudo touch /boot/trynew.flag && sync'

say "ready. Be at the tablet, then: ssh $HOST sudo reboot"
say "afterwards: ssh $HOST uname -r   (expect $REL), then scripts/make-default.sh $HOST $ART"
