#!/usr/bin/env python3
"""Manual One Punch Man single source chapter import to R2."""

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
    next_global_chapter,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import one One Punch Man source chapter to R2.")
    parser.add_argument("--source-base-url", default=os.environ.get("OPM_AUTHORIZED_MANGA_BASE_URL", OPM_DEFAULT_BASE_URL))
    parser.add_argument("--source-template", default=os.environ.get("OPM_AUTHORIZED_MANGA_SOURCE_TEMPLATE", OPM_DEFAULT_TEMPLATE))
    parser.add_argument("--source-volume", type=int, required=True)
    parser.add_argument("--source-chapter", type=int, required=True)
    parser.add_argument("--global-chapter", type=int, help="Reader/global chapter number. Empty = latest OPM chapter + 1.")
    parser.add_argument("--extensions", default=os.environ.get("IMAGE_EXTENSIONS", "jpg,jpeg"))
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "45")))
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
    parser.add_argument("--report", default="reports/opm-manual-import-result.json")
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
        global_chapter = args.global_chapter or next_global_chapter(content_dir, OPM_SERIES_ID)
        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
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
            source_volume=args.source_volume,
            source_chapter=args.source_chapter,
            max_pages=args.max_pages,
            min_pages=args.min_pages,
            stop_after_missing=args.stop_after_missing,
            timeout=args.timeout,
            delay=args.delay,
            webp_quality=args.webp_quality,
            image_strategy=args.image_strategy,
            overwrite=args.overwrite,
        )
        payload = {
            "imported": result.imported,
            "skipped": result.skipped,
            "chapter": result.chapter,
            "volume": result.volume,
            "sourceVolume": args.source_volume,
            "sourceChapter": args.source_chapter,
            "pages": len(result.pages),
            "reason": result.reason,
        }
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if (result.imported or result.skipped) else 1
    except Exception as exc:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({"imported": False, "error": str(exc)}, indent=2) + "\n", encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
