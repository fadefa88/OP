#!/usr/bin/env python3
"""Hourly One Punch Man checker using sourceVolume/sourceChapter from manifest."""

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
    import_opm_source_chapter_to_r2,
    latest_opm_source_position,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check and import next One Punch Man chapter to R2.")
    parser.add_argument("--source-base-url", default=os.environ.get("OPM_AUTHORIZED_MANGA_BASE_URL", OPM_DEFAULT_BASE_URL))
    parser.add_argument("--source-template", default=os.environ.get("OPM_AUTHORIZED_MANGA_SOURCE_TEMPLATE", OPM_DEFAULT_TEMPLATE))
    parser.add_argument("--source-volume", type=int, help="Force source volume, e.g. 37.")
    parser.add_argument("--source-chapter", type=int, help="Force source-local chapter, e.g. 6.")
    parser.add_argument("--global-chapter", type=int, help="Force reader/global chapter number.")
    parser.add_argument("--scan-ahead-volumes", type=int, default=int(os.environ.get("OPM_SCAN_AHEAD_VOLUMES", "3")))
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
    parser.add_argument("--report", default="reports/opm-new-chapter-result.json")
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
        account_id = args.account_id or require_env("CLOUDFLARE_ACCOUNT_ID")
        bucket = args.bucket or require_env("R2_BUCKET_NAME")
        access_key_id = args.access_key_id or require_env("R2_ACCESS_KEY_ID")
        secret_access_key = args.secret_access_key or require_env("R2_SECRET_ACCESS_KEY")
        latest = latest_opm_source_position(content_dir, OPM_SERIES_ID)
        candidates: list[tuple[int, int, int]] = []

        if args.source_volume and args.source_chapter:
            global_chapter = args.global_chapter or ((latest[0] + 1) if latest else 1)
            candidates.append((global_chapter, args.source_volume, args.source_chapter))
        elif latest:
            latest_global, latest_source_volume, latest_source_chapter = latest
            next_global = (args.global_chapter or latest_global + 1)
            candidates.append((next_global, latest_source_volume, latest_source_chapter + 1))
            for offset in range(1, max(1, args.scan_ahead_volumes) + 1):
                candidates.append((next_global, latest_source_volume + offset, 1))
        else:
            candidates.append((args.global_chapter or 1, args.source_volume or 1, args.source_chapter or 1))

        print(f"OPM candidates: {candidates}")
        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
        attempts = []

        for global_chapter, source_volume, source_chapter in candidates:
            print(f"\n=== OPM candidate: source volume {source_volume:02d} / capitolo {source_chapter:02d} → reader chapter {global_chapter} ===")
            result = import_opm_source_chapter_to_r2(
                session=session,
                r2_client=r2_client,
                bucket=bucket,
                public_base_url=args.public_base_url.rstrip("/"),
                source_base_url=args.source_base_url,
                source_template=args.source_template,
                source_extensions=parse_extensions(args.extensions),
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
                "chapter": result.chapter,
                "volume": result.volume,
                "sourceVolume": source_volume,
                "sourceChapter": source_chapter,
                "imported": result.imported,
                "skipped": result.skipped,
                "pages": len(result.pages),
                "reason": result.reason,
            })
            if result.imported:
                write_report(args.report, {
                    "imported": True,
                    "chapter": result.chapter,
                    "volume": result.volume,
                    "sourceVolume": source_volume,
                    "sourceChapter": source_chapter,
                    "pages": len(result.pages),
                    "attempts": attempts,
                })
                print(f"Imported OPM reader chapter {result.chapter} from source volume {source_volume} capitolo {source_chapter}.")
                return 0
            print(f"No accepted chapter: imported={result.imported}, skipped={result.skipped}, pages={len(result.pages)}, reason={result.reason or '-'}")

        write_report(args.report, {"imported": False, "attempts": attempts})
        print("No new One Punch Man chapter found.")
        return 0
    except Exception as exc:
        write_report(args.report, {"imported": False, "error": str(exc)})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
