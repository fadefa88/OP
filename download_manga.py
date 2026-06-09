#!/usr/bin/env python3
"""
Compatibility wrapper.

The production import flow now stores images in Cloudflare R2 and commits only
JSON manifests. Use:

  python scripts/import_history_to_r2.py   # one-time historical import
  python scripts/import_new_chapter_to_r2.py  # hourly/new chapter import
"""

from __future__ import annotations

import sys


def main() -> int:
    print("download_manga.py has been replaced by the R2 importers.")
    print("Historical one-time import:")
    print("  python scripts/import_history_to_r2.py --from-chapter 1 --to-chapter 1184 --webp-quality 90 --i-confirm-rights")
    print("New chapter import:")
    print("  python scripts/import_new_chapter_to_r2.py --i-confirm-rights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
