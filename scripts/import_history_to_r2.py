#!/usr/bin/env python3
"""
One-time historical importer to Cloudflare R2.

Run from your PC. It downloads only from a source you are allowed to copy from,
uses best-size image selection by default (WebP quality 82 only when smaller), uploads pages to R2,
and commits no images to Git. Only JSON manifests are written locally.
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
    chapter_range_for_volume,
    find_volume_for_chapter,
    import_single_chapter_to_r2,
    iter_chapters_from_args,
    make_session,
    parse_extensions,
    rebuild_index_from_volumes,
    require_env,
    validate_confirmation,
    write_legacy_combined_manifest,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time historical legal import to Cloudflare R2.")

    source = parser.add_argument_group("source")
    source.add_argument("--source-base-url", default=os.environ.get("AUTHORIZED_MANGA_BASE_URL", ""), help="Authorized source base URL. Can also be AUTHORIZED_MANGA_BASE_URL.")
    source.add_argument("--source-template", default=os.environ.get("AUTHORIZED_MANGA_SOURCE_TEMPLATE", ""), help="Optional format template. Placeholders: {base_url}, {volume_padded}, {chapter_padded}, {page_padded}, {extension}.")
    source.add_argument("--extensions", default="jpg,jpeg", help="Comma-separated source extensions to try. Default: jpg,jpeg")

    target = parser.add_mutually_exclusive_group(required=False)
    target.add_argument("--chapter", type=int, help="Import a single chapter.")
    target.add_argument("--volume", type=int, help="Import a whole volume.")
    target.add_argument("--from-chapter", type=int, default=1, help="First chapter to import. Default: 1")
    parser.add_argument("--to-chapter", type=int, default=1185, help="Last historical chapter to import. Default: 1185")

    parser.add_argument("--max-pages", type=int, default=45, help="Max pages to probe per chapter. Default: 45")
    parser.add_argument("--min-pages", type=int, default=3, help="Minimum pages to accept chapter. Default: 3")
    parser.add_argument("--stop-after-missing", type=int, default=3, help="Stop after N consecutive missing pages. Default: 3")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout seconds. Default: 15")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between page requests. Default: 0.25")
    parser.add_argument("--webp-quality", type=int, default=82, help="WebP quality used when WebP is selected. Default: 82")
    parser.add_argument("--image-strategy", choices=["best-size", "webp", "original"], default=os.environ.get("IMAGE_STRATEGY", "best-size"), help="best-size keeps JPG/JPEG when WebP is larger. Default: best-size")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing manifest entries and R2 objects.")
    parser.add_argument("--dry-run", action="store_true", help="Check and convert but do not upload or write manifests.")
    parser.add_argument("--i-confirm-rights", action="store_true", default=os.environ.get("I_CONFIRM_RIGHTS", "").lower() == "true", help="Required: confirms you can legally copy and host the images.")

    r2 = parser.add_argument_group("cloudflare r2")
    r2.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""), help="Cloudflare Account ID. Can also be CLOUDFLARE_ACCOUNT_ID.")
    r2.add_argument("--bucket", default=os.environ.get("R2_BUCKET_NAME", ""), help="R2 bucket name. Can also be R2_BUCKET_NAME.")
    r2.add_argument("--access-key-id", default=os.environ.get("R2_ACCESS_KEY_ID", ""), help="R2 Access Key ID. Can also be R2_ACCESS_KEY_ID.")
    r2.add_argument("--secret-access-key", default=os.environ.get("R2_SECRET_ACCESS_KEY", ""), help="R2 Secret Access Key. Can also be R2_SECRET_ACCESS_KEY.")
    r2.add_argument("--public-base-url", default=os.environ.get("R2_PUBLIC_BASE_URL", "https://static.lucahome.uk"), help="Public R2 custom domain. Default: https://static.lucahome.uk")

    manifest = parser.add_argument_group("manifest")
    manifest.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR), help="Manifest content dir. Default: public/content")
    manifest.add_argument("--series-id", default=DEFAULT_SERIES_ID)
    manifest.add_argument("--series-title", default=DEFAULT_SERIES_TITLE)
    manifest.add_argument("--series-description", default=DEFAULT_SERIES_DESCRIPTION)
    manifest.add_argument("--rebuild-only", action="store_true", help="Only rebuild index/legacy manifest from volume manifests. No network/R2 upload.")

    args = parser.parse_args(argv)

    if args.chapter is not None:
        args.from_chapter = None
        args.to_chapter = None
    elif args.volume is not None:
        args.from_chapter = None
        args.to_chapter = None
    elif args.from_chapter is None or args.to_chapter is None:
        parser.error("Provide --chapter, --volume, or --from-chapter + --to-chapter")

    if not (1 <= args.webp_quality <= 100):
        parser.error("--webp-quality must be 1-100")
    if args.max_pages < 1:
        parser.error("--max-pages must be >= 1")
    if args.min_pages < 1:
        parser.error("--min-pages must be >= 1")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    content_dir = Path(args.content_dir)

    if args.rebuild_only:
        index = rebuild_index_from_volumes(content_dir, args.series_id, args.series_title, args.series_description)
        write_legacy_combined_manifest(content_dir, index)
        print("Rebuilt split manifest index and compatibility manifest.")
        return 0

    try:
        validate_confirmation(bool(args.i_confirm_rights))
        if not args.source_base_url:
            raise RuntimeError("Missing --source-base-url or AUTHORIZED_MANGA_BASE_URL")
        account_id = args.account_id or require_env("CLOUDFLARE_ACCOUNT_ID")
        bucket = args.bucket or require_env("R2_BUCKET_NAME")
        access_key_id = args.access_key_id or require_env("R2_ACCESS_KEY_ID")
        secret_access_key = args.secret_access_key or require_env("R2_SECRET_ACCESS_KEY")
        public_base_url = args.public_base_url.rstrip("/")

        chapters = iter_chapters_from_args(args.chapter, args.volume, args.from_chapter, args.to_chapter, args.series_id)
        print(f"Historical import plan: {chapters[0]}-{chapters[-1]} ({len(chapters)} chapter(s))")
        print(f"Source base URL: {args.source_base_url}")
        print(f"R2 bucket: {bucket}")
        print(f"Public base URL: {public_base_url}")
        print(f"WebP quality: {args.webp_quality}")
        print(f"Image strategy: {args.image_strategy}")

        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
        source_template = args.source_template or None
        extensions = parse_extensions(args.extensions)

        imported = 0
        skipped = 0
        failed = 0
        results = []

        for chapter in chapters:
            volume = find_volume_for_chapter(chapter, args.series_id)
            print(f"\n=== Volume {volume} / Chapter {chapter} ===")
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
                dry_run=args.dry_run,
            )
            if result.imported:
                imported += 1
            elif result.skipped:
                skipped += 1
            else:
                failed += 1
            results.append({
                "chapter": result.chapter,
                "volume": result.volume,
                "imported": result.imported,
                "skipped": result.skipped,
                "pages": len(result.pages),
                "reason": result.reason,
            })
            print(f"Result: imported={result.imported}, skipped={result.skipped}, pages={len(result.pages)}, reason={result.reason or '-'}")

        Path("reports").mkdir(exist_ok=True)
        Path("reports/history-import-summary.json").write_text(json.dumps({
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "results": results,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        print("\nSummary")
        print(f"Imported chapters: {imported}")
        print(f"Skipped chapters: {skipped}")
        print(f"Failed/incomplete chapters: {failed}")
        print("Report: reports/history-import-summary.json")
        return 0 if failed == 0 else 1

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
