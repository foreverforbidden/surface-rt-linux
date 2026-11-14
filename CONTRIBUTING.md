# Contributing

The most useful contribution is a report from another Surface RT. One tablet is a small sample.

## Reports

Open an issue with the "Hardware report" template if you tried anything here, even if it all worked. Say what you tested and what you did not. "Not tested" is useful information too.

For a boot problem, use the "Boot problem" template. Include your `startup.nsh`, the kernel release and what the screen showed.

## Changes

- Keep the source on your PC. Scripts must run over SSH with no prompts: use `-y`, no editors, `sudo -n`.
- Do not change files that a fallback depends on: the old `zImage`, its `.dtb` and `startup-old.nsh`.
- Run `shellcheck` on shell scripts and `python3 -m unittest discover -s tests` in `dashboard/`.
- In docs, write what you measured and say what you did not test. Keep numbers exact.
- Kernel patches belong in [linux-surface-rt](https://github.com/nuno407/linux-surface-rt). Config changes for Raspberry Pi OS belong in `kernel/overlay/`.

## Style

Docs use short sentences, active voice and one idea per sentence, about 80% of the way to ASD-STE100 (Simplified Technical English). Use sentence case for headings. Do not use em dashes.
