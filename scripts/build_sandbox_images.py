#!/usr/bin/env python
"""Build the DualCore sandbox Docker images.

Usage:
    python scripts/build_sandbox_images.py          # build all
    python scripts/build_sandbox_images.py basic    # build only the basic image
    python scripts/build_sandbox_images.py ml       # build only the ml image
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IMAGES = {
    "basic": ("dualcore-sandbox:basic", "sandbox-images/Dockerfile.basic"),
    "ml": ("dualcore-sandbox:ml", "sandbox-images/Dockerfile.ml"),
}


def build(tag: str, dockerfile: str) -> int:
    print(f"\n=== Building {tag} from {dockerfile} ===", flush=True)
    return subprocess.run(
        ["docker", "build", "-t", tag, "-f", str(ROOT / dockerfile), str(ROOT)],
        check=False,
    ).returncode


def main() -> int:
    which = sys.argv[1:] or list(IMAGES)
    unknown = [w for w in which if w not in IMAGES]
    if unknown:
        print(f"Unknown image(s): {unknown}. Choose from {list(IMAGES)}.")
        return 2

    rc = 0
    for name in which:
        tag, dockerfile = IMAGES[name]
        rc |= build(tag, dockerfile)
    if rc == 0:
        print("\nAll requested images built successfully.")
    else:
        print("\nOne or more builds failed (is Docker running?).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
