#!/usr/bin/env python3
"""
Hourly importer for the next chapter only.

Used by GitHub Actions. It uploads images to R2 and writes only JSON manifests
under public/content. If no new chapter is found, it exits 0 and changes no file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from op_importer_common import (
    DEFAULT_CONTENT_DIR,
    DEFAULT_SERIES_DESCRIPTION,
    DEFAULT_SERIES_ID,
    DEFAULT_SERIES_TITLE,
    build_r2_client,
    find_volume_for_chapter,
    import_single_chapter_to_r2,
    latest_chapter_from_index,
    make_session,
    parse_extensions,
    require_env,
    validate_confirmation,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check/import next chapter to Cloudflare R2.")
    parser.add_argument("--source-base-url", default=os.environ.get("AUTHORIZED_MANGA_BASE_URL", ""))
    parser.add_argument("--source-template", default=os.environ.get("AUTHORIZED_MANGA_SOURCE_TEMPLATE", ""))
    parser.add_argument("--extensions", default=os.environ.get("IMAGE_EXTENSIONS", "jpg,jpeg"))
    parser.add_argument("--chapter", type=int, help="Force a specific chapter. Empty = latest+1.")
    parser.add_argument("--scan-ahead", type=int, default=int(os.environ.get("SCAN_AHEAD", "3")), help="How many chapters to try from latest+1. Default: 3")
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "45")))
    parser.add_argument("--min-pages", type=int, default=int(os.environ.get("MIN_PAGES", "3")))
    parser.add_argument("--stop-after-missing", type=int, default=int(os.environ.get("STOP_AFTER_MISSING", "3")))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("IMPORT_TIMEOUT", "15")))
    parser.add_argument("--delay", type=float, default=float(os.environ.get("IMPORT_DELAY", "0.25")))
    parser.add_argument("--webp-quality", type=int, default=int(os.environ.get("WEBP_QUALITY", "82")))
    parser.add_argument("--image-strategy", choices=["best-size", "webp", "original"], default=os.environ.get("IMAGE_STRATEGY", "best-size"), help="best-size keeps JPG/JPEG when WebP is larger. Default: best-size")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--i-confirm-rights", action="store_true", default=os.environ.get("I_CONFIRM_RIGHTS", "").lower() == "true")

    parser.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    parser.add_argument("--bucket", default=os.environ.get("R2_BUCKET_NAME", ""))
    parser.add_argument("--access-key-id", default=os.environ.get("R2_ACCESS_KEY_ID", ""))
    parser.add_argument("--secret-access-key", default=os.environ.get("R2_SECRET_ACCESS_KEY", ""))
    parser.add_argument("--public-base-url", default=os.environ.get("R2_PUBLIC_BASE_URL", "https://static.lucahome.uk"))

    parser.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR))
    parser.add_argument("--series-id", default=DEFAULT_SERIES_ID)
    parser.add_argument("--series-title", default=DEFAULT_SERIES_TITLE)
    parser.add_argument("--series-description", default=DEFAULT_SERIES_DESCRIPTION)
    parser.add_argument("--report", default="reports/new-chapter-result.json")
    return parser.parse_args(argv)


def write_report(path: str, payload: dict) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    content_dir = Path(args.content_dir)

    try:
        validate_confirmation(bool(args.i_confirm_rights))
        if not args.source_base_url:
            raise RuntimeError("Missing --source-base-url or AUTHORIZED_MANGA_BASE_URL")
        account_id = args.account_id or require_env("CLOUDFLARE_ACCOUNT_ID")
        bucket = args.bucket or require_env("R2_BUCKET_NAME")
        access_key_id = args.access_key_id or require_env("R2_ACCESS_KEY_ID")
        secret_access_key = args.secret_access_key or require_env("R2_SECRET_ACCESS_KEY")
        public_base_url = args.public_base_url.rstrip("/")

        if args.chapter:
            chapters_to_try = [args.chapter]
            latest = latest_chapter_from_index(content_dir, args.series_id)
        else:
            latest = latest_chapter_from_index(content_dir, args.series_id)
            if latest < 1:
                raise RuntimeError("No latestChapter found. Run historical import first or pass --chapter manually.")
            chapters_to_try = list(range(latest + 1, latest + 1 + max(1, args.scan_ahead)))

        print(f"Latest chapter in manifest: {latest}")
        print(f"Chapters to try: {chapters_to_try}")

        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
        extensions = parse_extensions(args.extensions)
        source_template = args.source_template or None

        attempts = []
        for chapter in chapters_to_try:
            volume = find_volume_for_chapter(chapter, args.series_id)
            print(f"\n=== Probing Volume {volume} / Chapter {chapter} ===")
            result = import_single_chapter_to_r2(
                session=session,
                r2_client=r2_client,
                bucket=bucket,
                public_base_url=public_base_url,
                source_base_url=args.source_base_url,
                source_template=source_template,
                source_extensions=extensions,
                content_dir=content_dir,
                series_id=args.series_id,
                series_title=args.series_title,
                series_description=args.series_description,
                chapter=chapter,
                volume_override=None,
                max_pages=args.max_pages,
                min_pages=args.min_pages,
                stop_after_missing=args.stop_after_missing,
                timeout=args.timeout,
                delay=args.delay,
                webp_quality=args.webp_quality,
                image_strategy=args.image_strategy,
                overwrite=args.overwrite,
                dry_run=False,
            )
            attempts.append({
                "chapter": result.chapter,
                "volume": result.volume,
                "imported": result.imported,
                "skipped": result.skipped,
                "pages": len(result.pages),
                "reason": result.reason,
            })
            if result.imported:
                write_report(args.report, {"imported": True, "chapter": result.chapter, "volume": result.volume, "pages": len(result.pages), "attempts": attempts})
                print(f"Imported chapter {result.chapter}. Manifest JSON changed.")
                return 0
            print(f"No accepted chapter: imported={result.imported}, skipped={result.skipped}, pages={len(result.pages)}, reason={result.reason or '-'}")

        write_report(args.report, {"imported": False, "attempts": attempts})
        print("No new chapter found. No manifest change should be committed.")
        return 0

    except Exception as exc:
        write_report(args.report, {"imported": False, "error": str(exc)})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
