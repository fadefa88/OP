#!/usr/bin/env python3
"""Mass-import One Punch Man from volumeXX/capitoloYY source paths to R2.

It does not need a predefined chapter-per-volume map. It scans source volumes and
local chapter numbers, assigns sequential reader chapter numbers, and stores
sourceVolume/sourceChapter in the manifest for future hourly checks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from op_importer_common import (
    DEFAULT_CONTENT_DIR,
    build_r2_client,
    make_session,
    parse_extensions,
    require_env,
    validate_confirmation,
)
from import_opm_common import (
    OPM_DEFAULT_BASE_URL,
    OPM_DEFAULT_TEMPLATE,
    OPM_SERIES_ID,
    existing_source_pairs,
    import_opm_source_chapter_to_r2,
    next_global_chapter,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mass import One Punch Man archive to R2.")
    parser.add_argument("--source-base-url", default=os.environ.get("OPM_AUTHORIZED_MANGA_BASE_URL", OPM_DEFAULT_BASE_URL))
    parser.add_argument("--source-template", default=os.environ.get("OPM_AUTHORIZED_MANGA_SOURCE_TEMPLATE", OPM_DEFAULT_TEMPLATE))
    parser.add_argument("--from-source-volume", type=int, default=1)
    parser.add_argument("--to-source-volume", type=int, default=37)
    parser.add_argument("--total-chapters", type=int, default=236)
    parser.add_argument("--max-source-chapters-per-volume", type=int, default=30)
    parser.add_argument("--missing-chapters-to-next-volume", type=int, default=int(os.environ.get("OPM_MISSING_CHAPTERS_TO_NEXT_VOLUME", "3")))
    parser.add_argument("--extensions", default=os.environ.get("IMAGE_EXTENSIONS", "jpg,jpeg"))
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "80")))
    parser.add_argument("--min-pages", type=int, default=int(os.environ.get("MIN_PAGES", "3")))
    parser.add_argument("--stop-after-missing", type=int, default=int(os.environ.get("STOP_AFTER_MISSING", "3")))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("IMPORT_TIMEOUT", "15")))
    parser.add_argument("--delay", type=float, default=float(os.environ.get("IMPORT_DELAY", "0.25")))
    parser.add_argument("--webp-quality", type=int, default=int(os.environ.get("WEBP_QUALITY", "82")))
    parser.add_argument("--image-strategy", choices=["best-size", "webp", "original"], default=os.environ.get("IMAGE_STRATEGY", "best-size"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--i-confirm-rights", action="store_true", default=os.environ.get("I_CONFIRM_RIGHTS", "").lower() == "true")
    parser.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    parser.add_argument("--bucket", default=os.environ.get("R2_BUCKET_NAME", ""))
    parser.add_argument("--access-key-id", default=os.environ.get("R2_ACCESS_KEY_ID", ""))
    parser.add_argument("--secret-access-key", default=os.environ.get("R2_SECRET_ACCESS_KEY", ""))
    parser.add_argument("--public-base-url", default=os.environ.get("R2_PUBLIC_BASE_URL", "https://static.lucahome.uk"))
    parser.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR))
    parser.add_argument("--report", default="reports/opm-mass-import-summary.json")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    content_dir = Path(args.content_dir)
    try:
        validate_confirmation(bool(args.i_confirm_rights))
        account_id = args.account_id or require_env("CLOUDFLARE_ACCOUNT_ID")
        bucket = args.bucket or require_env("R2_BUCKET_NAME")
        access_key_id = args.access_key_id or require_env("R2_ACCESS_KEY_ID")
        secret_access_key = args.secret_access_key or require_env("R2_SECRET_ACCESS_KEY")
        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
        extensions = parse_extensions(args.extensions)
        existing_pairs = existing_source_pairs(content_dir, OPM_SERIES_ID)
        imported = 0
        skipped_pairs = 0
        failed = 0
        attempts = []
        global_chapter = next_global_chapter(content_dir, OPM_SERIES_ID)
        imported_or_existing_total = len(existing_pairs)

        print(f"Existing OPM source pairs in manifest: {len(existing_pairs)}")
        print(f"Next reader/global chapter: {global_chapter}")
        print(f"Scanning source volumes {args.from_source_volume}-{args.to_source_volume}, target total {args.total_chapters} chapters")
        print(f"Source template: {args.source_template}")

        # OPM source capitoloYY numbering is effectively continuous across
        # source volumes in some areas. When a volume ends after three missing
        # chapters, the next source volume must resume from the last valid
        # source chapter number, not from capitolo01.
        next_volume_start_chapter = 1

        for source_volume in range(args.from_source_volume, args.to_source_volume + 1):
            consecutive_missing_chapters = 0
            last_valid_source_chapter = max(1, next_volume_start_chapter)
            start_source_chapter = max(1, next_volume_start_chapter)
            print(f"\n--- Scanning OPM source volume {source_volume:02d} from capitolo {start_source_chapter:02d} ---")

            for source_chapter in range(start_source_chapter, args.max_source_chapters_per_volume + 1):
                if imported_or_existing_total >= args.total_chapters:
                    break
                pair = (source_volume, source_chapter)
                if pair in existing_pairs and not args.overwrite:
                    skipped_pairs += 1
                    last_valid_source_chapter = source_chapter
                    consecutive_missing_chapters = 0
                    continue
                print(f"\n=== OPM source volume {source_volume:02d} / capitolo {source_chapter:02d} → reader chapter {global_chapter} ===")
                result = import_opm_source_chapter_to_r2(
                    session=session,
                    r2_client=r2_client,
                    bucket=bucket,
                    public_base_url=args.public_base_url.rstrip("/"),
                    source_base_url=args.source_base_url,
                    source_template=args.source_template,
                    source_extensions=extensions,
                    content_dir=content_dir,
                    global_chapter=global_chapter,
                    source_volume=source_volume,
                    source_chapter=source_chapter,
                    max_pages=args.max_pages,
                    min_pages=args.min_pages,
                    stop_after_missing=args.stop_after_missing,
                    timeout=args.timeout,
                    delay=args.delay,
                    webp_quality=args.webp_quality,
                    image_strategy=args.image_strategy,
                    overwrite=args.overwrite,
                )
                attempts.append({
                    "globalChapter": result.chapter,
                    "sourceVolume": source_volume,
                    "sourceChapter": source_chapter,
                    "imported": result.imported,
                    "skipped": result.skipped,
                    "pages": len(result.pages),
                    "reason": result.reason,
                })
                if result.imported:
                    imported += 1
                    imported_or_existing_total += 1
                    existing_pairs.add(pair)
                    global_chapter += 1
                    last_valid_source_chapter = source_chapter
                    consecutive_missing_chapters = 0
                elif result.skipped:
                    skipped_pairs += 1
                    last_valid_source_chapter = source_chapter
                    consecutive_missing_chapters = 0
                else:
                    failed += 1
                    consecutive_missing_chapters += 1
                    print(f"  source chapter not accepted: {result.reason}")
                    if consecutive_missing_chapters >= args.missing_chapters_to_next_volume:
                        next_volume_start_chapter = max(1, last_valid_source_chapter)
                        print(
                            f"  {consecutive_missing_chapters} consecutive missing source chapters. "
                            f"Moving to next source volume from capitolo {next_volume_start_chapter:02d}."
                        )
                        break
            else:
                # Reached max_source_chapters_per_volume without hitting the missing threshold.
                next_volume_start_chapter = max(1, last_valid_source_chapter)

            if imported_or_existing_total >= args.total_chapters:
                break

        payload = {
            "imported": imported,
            "skippedPairs": skipped_pairs,
            "failedOrMissing": failed,
            "targetTotalChapters": args.total_chapters,
            "knownSourcePairsAfterRun": imported_or_existing_total,
            "attempts": attempts,
        }
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("\nSummary")
        print(json.dumps({k: v for k, v in payload.items() if k != "attempts"}, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({"imported": 0, "error": str(exc)}, indent=2) + "\n", encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
