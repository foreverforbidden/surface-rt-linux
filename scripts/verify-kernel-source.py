#!/usr/bin/env python3
"""Offline source check. Read inputs; patch only an automatically removed temp tree."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PIN = '6468f0b907c50c071fba54232191e149ff70529a'
ARCHIVE_SHA = '08e7b0c4f2dd1971f972da274b5e589a98989390ac56acd7a1a5af922363ea6c'
SMB_FILE = 'fs/smb/client/smb2inode.c'
SMB_SHA = 'bb829c63b6f5634838dc89d38183c6d2d37f8a42120657100ae1d05811f896ee'
TOP = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run(*args, cwd=None):
    # Do not let an inherited Git worktree/index override the temporary tree.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.check_output(args, cwd=cwd, env=env)


def check_fix(data):
    require(sha(data) == SMB_SHA, 'unexpected smb2inode.c bytes')
    # Exact, reviewed guard sequence, not merely the presence of a CVE string.
    text = data.decode()
    start = text.index('reparse_buf_ptr(')
    end = text.index('\n}', start)
    body = text[start:end]
    guard = re.compile(
        r'len = sizeof\(\*buf\);\s*'
        r'if \(count < len\)\s*'
        r'return ERR_PTR\(smb_EIO2\(smb_eio_trace_reparse_rdlen, count, 0\)\);\s*'
        r'rdlen = le16_to_cpu\(buf->ReparseDataLength\);\s*'
        r'if \(count < rdlen \+ len\)\s*'
        r'return ERR_PTR\(smb_EIO2\(smb_eio_trace_reparse_rdlen, count, rdlen\)\);')
    require(guard.search(body), 'fixed-header/read/payload guard sequence missing')


def smb_snapshot(tree):
    return {str(p.relative_to(tree)): file_sha(p)
            for p in sorted((tree / 'fs/smb').rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream', type=Path, help='local linux-surface-rt Git repository')
    parser.add_argument('tarball', type=Path, help='local linux-7.2.13.tar.xz')
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    tarball = args.tarball.resolve()
    require(file_sha(tarball) == ARCHIVE_SHA, 'Linux archive SHA-256 mismatch')
    require(run('git', '-C', str(upstream), 'rev-parse', PIN + '^{commit}').decode().strip()
            == PIN, 'pinned commit unavailable')
    require('PIN=' + PIN in (TOP / 'scripts/build-kernel.sh').read_text(),
            'public build script no longer uses the reviewed pin')

    # Read committed blobs, never execute the upstream series/build/overlay shell.
    locked = {}
    for line in (TOP / 'kernel/source-review.sha256').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        expected, name = line.split('  ', 1)
        require(name not in locked, 'duplicate checksum entry: ' + name)
        if name.startswith('upstream/'):
            data = run('git', '-C', str(upstream), 'show', PIN + ':' + name[9:])
        elif name.startswith('local/'):
            data = (TOP / name[6:]).read_bytes()
        else:
            raise ValueError('unknown checksum namespace: ' + name)
        require(sha(data) == expected, 'checksum mismatch: ' + name)
        locked[name] = data

    series = locked['upstream/surface-rt/series'].decode()
    patches = []
    for line in series.splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'apply "\$PUB/(patches/[A-Za-z0-9_.-]+\.patch)"', line)
        require(match is not None, 'unsupported series step: ' + line)
        patches.append('upstream/surface-rt/' + match[1])
    require(len(patches) == len(set(patches)) == 45, 'expected 45 distinct patches')
    require(patches == [p for p in locked if p.startswith('upstream/surface-rt/patches/')],
            'checksum list and series order differ')
    build = locked['upstream/surface-rt/build.sh'].decode()
    require('KVER=7.2.13' in build and 'KSHA256=' + ARCHIVE_SHA in build,
            'upstream build source pin differs')
    overlay = locked['local/kernel/overlay/surface-rt/overlay.sh'].decode()
    require([l for l in overlay.splitlines() if l and not l.startswith('#')]
            == ['CONFIG_FRAGMENTS+=("$OVL/surface-rt/rt.config")'],
            'overlay is no longer configuration-only')
    print('PASS: archive, pinned build inputs, ordered series and local overlay hashes', flush=True)

    with tempfile.TemporaryDirectory(prefix='surface-rt-source-') as tmp:
        work = Path(tmp)
        print('Extracting verified archive into temporary storage...', flush=True)
        run('tar', '-xJf', str(tarball), '-C', str(work))
        tree = work / 'linux-7.2.13'
        # Isolate git apply from any enclosing repository. No commits/index needed.
        run('git', 'init', '-q', str(tree))
        original = (tree / SMB_FILE).read_bytes()
        check_fix(original)
        before = smb_snapshot(tree)
        touched = set()
        for number, name in enumerate(patches, 1):
            patch = work / 'step.patch'
            patch.write_bytes(locked[name])
            stats = run('git', 'apply', '--numstat', str(patch), cwd=tree).decode()
            touched.update(line.split('\t', 2)[2] for line in stats.splitlines())
            run('git', 'apply', '--check', str(patch), cwd=tree)
            run('git', 'apply', str(patch), cwd=tree)
            print(f'{number:02d} {sha(locked[name])} {Path(name).name}', flush=True)
        after = (tree / SMB_FILE).read_bytes()
        check_fix(after)
        require(after == original, 'affected source changed after patch application')
        require(smb_snapshot(tree) == before, 'fs/smb contents changed')
        print(f'PASS: {len(patches)} patches applied in series order; {len(touched)} distinct paths')
        print(f'PASS: fixed guard sequence before and after; {SMB_FILE} SHA-256 {SMB_SHA}')
        print(f'PASS: all {len(before)} fs/smb files unchanged after application')
        print('Source-only result. No build, device check or signature verification performed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        sys.exit(1)
