# Kernel source provenance and CVE fix preservation

This records the source inputs reviewed on 15 November 2026. It does not certify
all kernel code or establish which binary a particular device is running.

## Pinned inputs

The patch supplier is [nuno407/linux-surface-rt](https://github.com/nuno407/linux-surface-rt),
commit [`6468f0b907c50c071fba54232191e149ff70529a`](https://github.com/nuno407/linux-surface-rt/tree/6468f0b907c50c071fba54232191e149ff70529a).
Our [build wrapper](../scripts/build-kernel.sh) pins that exact commit.

There are **45 patches**, applied in the order of the 45 `apply` commands in the
[pinned series](https://github.com/nuno407/linux-surface-rt/blob/6468f0b907c50c071fba54232191e149ff70529a/surface-rt/series),
from `0001` through `0045`. This order comes from `series`, not directory sorting.
The [checksum inventory](../kernel/source-review.sha256) lists every patch in
that same order, plus the build scripts, base configuration, provenance file and
local overlay. Patch links can be resolved from the
[pinned patch directory](https://github.com/nuno407/linux-surface-rt/tree/6468f0b907c50c071fba54232191e149ff70529a/surface-rt/patches).
No patch copies are needed in this repository.

The supplier's [per-patch provenance](https://github.com/nuno407/linux-surface-rt/blob/6468f0b907c50c071fba54232191e149ff70529a/surface-rt/PROVENANCE.md)
credits the first seven patches to libre-tegra (`v7.0.1-stable`, commit prefix
`bfffc6d6656e`), patches 0009, 0010 and 0014 to
`CoderDennis/nerves_system_surface_rt` (commit prefix `d068902a00ff`), and the
OV9726 register tables to NVIDIA's Tegra Android tree at
`2268683075e741190919217a72fcf13eb174dc57`. It describes the remaining work and
adaptations individually. These are the supplier's attribution claims, not a new
independent audit of every earlier source. “Our own” in that upstream document
means the supplier's work, not this repository author's work.

The [device build script](https://github.com/nuno407/linux-surface-rt/blob/6468f0b907c50c071fba54232191e149ff70529a/surface-rt/build.sh)
pins [Linux 7.2.13](https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.13.tar.xz):

```text
SHA-256 08e7b0c4f2dd1971f972da274b5e589a98989390ac56acd7a1a5af922363ea6c
```

That value also appears in the existing build manifest. The completed source
review compared it with the [kernel.org checksum list](https://cdn.kernel.org/pub/linux/kernel/v7.x/sha256sums.asc).
The verifier below checks bytes against the recorded digest; it does **not**
perform OpenPGP verification or authenticate the Git commit. Reviewers can verify
the signed upstream release separately. A checksum match is not a signature.

## Overlay path

The wrapper sets `OVERLAY` to this repository's `kernel/overlay`. The supplier's
[top-level build script](https://github.com/nuno407/linux-surface-rt/blob/6468f0b907c50c071fba54232191e149ff70529a/build.sh)
mounts it read-only at `/overlay` in the build container. The device build script
sources `surface-rt/overlay.sh` before it applies the series.

Our [overlay.sh](../kernel/overlay/surface-rt/overlay.sh) only appends
`$OVL/surface-rt/rt.config` to `CONFIG_FRAGMENTS`. It adds no patches, replaces no
series and installs no build hooks. After patching, the device script copies the
base configuration, appends `unsigned.config`, then appends our
[rt.config](../kernel/overlay/surface-rt/rt.config). It sets `LOCALVERSION`, runs
`olddefconfig`, and calls the unchanged no-op `config_hook` before compilation.
Our fragment enables autofs and branch-predictor hardening and disables module
compression. See the [build guide](02-kernel-7.2.md#our-config-changes) for why.

The existing manifest has an empty `overlay_commit`. The local build overlay and
public overlay were compared byte for byte; the inventory records their hashes.
This identifies the reviewed overlay bytes but does not retroactively add an
immutable overlay revision to that old manifest.

## Reproduce the source check

Use Python 3.9 or newer, Git, and a `tar` with xz support on a Mac or Linux PC.
Allow about 3 GB of temporary disk space. No compiler, Docker or device access is
needed. From this repository's root, obtain the public inputs once:

```sh
mkdir -p build/source-review
git clone https://github.com/nuno407/linux-surface-rt.git build/source-review/linux-surface-rt
curl -fL https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.13.tar.xz \
  -o build/source-review/linux-7.2.13.tar.xz
```

Then run the offline check (existing local copies can be passed instead):

```sh
python3 scripts/verify-kernel-source.py \
  build/source-review/linux-surface-rt \
  build/source-review/linux-7.2.13.tar.xz
```

The [verifier](../scripts/verify-kernel-source.py) reads the supplied inputs and
writes only an automatically removed temporary directory. It does not check out
or modify the supplier repository, fetch anything, execute upstream shell
scripts, compile, install or connect to a device. It reads Git blobs at the pin,
so unrelated working-tree edits do not alter the checked patches. It rejects
changed locked inputs, a changed overlay, or an unrecognised series command.

It checks the archive hash, extracts a fresh source tree, and checks the exact
reviewed guard sequence in `reparse_buf_ptr()` in `fs/smb/client/smb2inode.c`.
The [kernel CVE advisory](https://kernel.googlesource.com/pub/scm/linux/security/vulns/+/ffaa1b4ec1ea8813a90a5a6f9f577958c848a33c/cve/published/2026/CVE-2026-89632.mbox)
identifies [stable fix `711cf71300d7992f450600df8864917d3538679f`](https://git.kernel.org/stable/c/711cf71300d7992f450600df8864917d3538679f)
as included in Linux 7.2.4. In the pinned 7.2.13 file:

1. Line 43 checks `count < len`, where `len = sizeof(*buf)`, and returns an error
   before accessing a short fixed header.
2. Line 46 reads `buf->ReparseDataLength` only after that check.
3. Line 47 separately checks that `count` covers the header and payload.

The script then runs `git apply --check` and `git apply` for all 45 patches, in
series order, on the temporary tree. It checks the guard sequence again, requires
the affected file to remain byte-identical, and compares hashes of **every file
under `fs/smb/`** before and after. It prints each patch's ordinal and digest.
Unlike the build's reusable-tree path, it never skips a patch using an existing
`.applied` marker or a reverse-application check.

The source file digest before and after must be:

```text
bb829c63b6f5634838dc89d38183c6d2d37f8a42120657100ae1d05811f896ee
```

The local verification run on 15 November 2026 applied all 45 patches, counted
46 distinct touched paths, and found all 182 files under `fs/smb/` unchanged.
The guard-sequence check passed before and after application.

A successful run establishes the presence and preservation of this specific
source fix for these exact inputs. It does not rely on “no patch mentions the
CVE.” The earlier review enumerated 46 distinct paths touched by the series and
found none under `fs/smb/`; actual application and byte comparison make that
preservation claim independently repeatable.

## Source evidence versus device evidence

The completed review also checked build artifact checksums, compared the running
kernel's GNU build ID with the built image, compared the running configuration,
and matched boot-image, device-tree and installed CIFS-module bytes to local
build artifacts. Those were separate observations tying one installation to one
build. This source verifier neither repeats nor proves them.

No private device identifiers, package inventory, device output or separate
redacted review report is included here. A reviewer can reproduce source
preservation without those records. Linking a newly built binary to these
sources, reproducing its exact bytes, and checking a running installation remain
separate steps. This check does not assess the old 5.17 fallback, prove the safety
of every patch, or establish current security support for Linux 7.2.
