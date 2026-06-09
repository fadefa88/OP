#!/usr/bin/env python3
"""
Mass one-time importer to Cloudflare R2.

Use this for the first historical load of the full authorized archive. It uploads
image assets to R2 and writes only JSON manifests under public/content.

Safety model:
- Requires I_CONFIRM_RIGHTS=true or --i-confirm-rights.
- Uses best-size by default: WebP quality 82 only when smaller than the source JPG/JPEG.
- Never writes downloaded images into the Git repository.
- Can resume: already-imported chapters are skipped if manifest + R2 objects exist.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from op_importer_common import (
    DEFAULT_CONTENT_DIR,
    DEFAULT_SERIES_DESCRIPTION,
    DEFAULT_SERIES_ID,
    DEFAULT_SERIES_TITLE,
    build_r2_client,
    find_volume_for_chapter,
    import_single_chapter_to_r2,
    make_session,
    parse_extensions,
    rebuild_index_from_volumes,
    require_env,
    validate_confirmation,
    write_legacy_combined_manifest,
)

DEFAULT_LATEST_CHAPTER = int(os.environ.get("LATEST_CHAPTER_TO_IMPORT", "1185"))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mass import all authorized historical chapters to Cloudflare R2."
    )

    source = parser.add_argument_group("source")
    source.add_argument(
        "--source-base-url",
        default=os.environ.get("AUTHORIZED_MANGA_BASE_URL", ""),
        help="Authorized source base URL. Can also be AUTHORIZED_MANGA_BASE_URL.",
    )
    source.add_argument(
        "--source-template",
        default=os.environ.get("AUTHORIZED_MANGA_SOURCE_TEMPLATE", ""),
        help=(
            "Optional URL template. Placeholders: {base_url}, {volume}, {volume_padded}, "
            "{chapter}, {chapter_padded}, {chapter_4}, {page}, {page_padded}, {page_3}, {extension}."
        ),
    )
    source.add_argument(
        "--extensions",
        default=os.environ.get("IMAGE_EXTENSIONS", "jpg,jpeg"),
        help="Comma-separated source extensions to try. Default: jpg,jpeg",
    )

    scope = parser.add_argument_group("import scope")
    scope.add_argument("--from-chapter", type=int, default=1, help="First chapter to import. Default: 1")
    scope.add_argument(
        "--to-chapter",
        type=int,
        default=DEFAULT_LATEST_CHAPTER,
        help=f"Last chapter to import. Default: env LATEST_CHAPTER_TO_IMPORT or {DEFAULT_LATEST_CHAPTER}",
    )
    scope.add_argument(
        "--resume-from-checkpoint",
        action="store_true",
        help="Resume from checkpoint file by starting after the last attempted chapter.",
    )
    scope.add_argument(
        "--checkpoint",
        default="reports/import-all-progress.json",
        help="Checkpoint/progress file. Default: reports/import-all-progress.json",
    )
    scope.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop at the first incomplete/failed chapter. Default: continue and write a report.",
    )
    scope.add_argument(
        "--pause-every",
        type=int,
        default=0,
        help="Pause every N attempted chapters. 0 disables. Useful for long runs.",
    )
    scope.add_argument(
        "--pause-seconds",
        type=float,
        default=30.0,
        help="Seconds to pause when --pause-every is reached. Default: 30.",
    )

    pages = parser.add_argument_group("page probing")
    pages.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "45")))
    pages.add_argument("--min-pages", type=int, default=int(os.environ.get("MIN_PAGES", "3")))
    pages.add_argument("--stop-after-missing", type=int, default=int(os.environ.get("STOP_AFTER_MISSING", "3")))
    pages.add_argument("--timeout", type=float, default=float(os.environ.get("IMPORT_TIMEOUT", "15")))
    pages.add_argument("--delay", type=float, default=float(os.environ.get("IMPORT_DELAY", "0.25")))

    images = parser.add_argument_group("image handling")
    images.add_argument(
        "--webp-quality",
        type=int,
        default=int(os.environ.get("WEBP_QUALITY", "82")),
        help="WebP quality used when WebP is selected. Default: 82",
    )
    images.add_argument(
        "--image-strategy",
        choices=["best-size", "webp", "original"],
        default=os.environ.get("IMAGE_STRATEGY", "best-size"),
        help="best-size keeps JPG/JPEG when WebP is larger. Default: best-size",
    )
    images.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing manifest entries and R2 objects.",
    )
    images.add_argument("--dry-run", action="store_true", help="Probe/convert only. Do not upload or write manifests.")

    r2 = parser.add_argument_group("cloudflare r2")
    r2.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    r2.add_argument("--bucket", default=os.environ.get("R2_BUCKET_NAME", ""))
    r2.add_argument("--access-key-id", default=os.environ.get("R2_ACCESS_KEY_ID", ""))
    r2.add_argument("--secret-access-key", default=os.environ.get("R2_SECRET_ACCESS_KEY", ""))
    r2.add_argument("--public-base-url", default=os.environ.get("R2_PUBLIC_BASE_URL", "https://static.lucahome.uk"))

    manifest = parser.add_argument_group("manifest")
    manifest.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR))
    manifest.add_argument("--series-id", default=DEFAULT_SERIES_ID)
    manifest.add_argument("--series-title", default=DEFAULT_SERIES_TITLE)
    manifest.add_argument("--series-description", default=DEFAULT_SERIES_DESCRIPTION)
    manifest.add_argument(
        "--rebuild-only",
        action="store_true",
        help="Only rebuild index/legacy manifest from split volume manifests. No network/R2 upload.",
    )

    parser.add_argument(
        "--i-confirm-rights",
        action="store_true",
        default=os.environ.get("I_CONFIRM_RIGHTS", "").lower() == "true",
        help="Required: confirms you can legally copy and host the images.",
    )

    args = parser.parse_args(argv)

    if args.from_chapter < 1:
        parser.error("--from-chapter must be >= 1")
    if args.to_chapter < args.from_chapter:
        parser.error("--to-chapter cannot be lower than --from-chapter")
    if args.max_pages < 1:
        parser.error("--max-pages must be >= 1")
    if args.min_pages < 1:
        parser.error("--min-pages must be >= 1")
    if not (1 <= args.webp_quality <= 100):
        parser.error("--webp-quality must be 1-100")

    return args


def read_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    content_dir = Path(args.content_dir)
    checkpoint_path = Path(args.checkpoint)

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

        start_chapter = args.from_chapter
        if args.resume_from_checkpoint:
            checkpoint = read_checkpoint(checkpoint_path)
            last_attempted = int(checkpoint.get("lastAttemptedChapter", 0) or 0)
            if last_attempted >= start_chapter:
                start_chapter = min(last_attempted + 1, args.to_chapter)
                print(f"Resuming from checkpoint: last attempted {last_attempted}; next {start_chapter}")

        chapters = list(range(start_chapter, args.to_chapter + 1))
        if not chapters:
            print("Nothing to import: range is empty after checkpoint resume.")
            return 0

        print("Mass historical import plan")
        print(f"  chapters: {chapters[0]}-{chapters[-1]} ({len(chapters)} chapter(s))")
        print(f"  source base URL: {args.source_base_url}")
        print(f"  R2 bucket: {bucket}")
        print(f"  public base URL: {public_base_url}")
        print(f"  image strategy: {args.image_strategy}")
        print(f"  WebP quality: {args.webp_quality}")
        print(f"  dry run: {args.dry_run}")
        print(f"  checkpoint: {checkpoint_path}")
        print("\nVolume mapping reminder:")
        print("  volumes 1-116 use the historical range table in scripts/op_importer_common.py")
        print("  volume 117 = chapters 1186-1195")
        print("  volume 118 = chapters 1196-1205")
        print("  each following volume adds +10 chapters indefinitely")

        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
        source_template = args.source_template or None
        extensions = parse_extensions(args.extensions)

        imported = 0
        skipped = 0
        failed = 0
        results: list[dict[str, Any]] = []
        started_at = time.time()

        for offset, chapter in enumerate(chapters, start=1):
            volume = find_volume_for_chapter(chapter)
            print(f"\n=== [{offset}/{len(chapters)}] Volume {volume} / Chapter {chapter} ===")

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

            item = {
                "chapter": result.chapter,
                "volume": result.volume,
                "imported": result.imported,
                "skipped": result.skipped,
                "pages": len(result.pages),
                "reason": result.reason,
            }
            results.append(item)
            print(
                "Result: "
                f"imported={result.imported}, skipped={result.skipped}, "
                f"pages={len(result.pages)}, reason={result.reason or '-'}"
            )

            checkpoint_payload = {
                "lastAttemptedChapter": chapter,
                "targetFromChapter": args.from_chapter,
                "targetToChapter": args.to_chapter,
                "imported": imported,
                "skipped": skipped,
                "failed": failed,
                "elapsedSeconds": round(time.time() - started_at, 2),
                "lastResult": item,
            }
            write_checkpoint(checkpoint_path, checkpoint_payload)

            if result.reason and not result.skipped and args.stop_on_error:
                print("Stopping because --stop-on-error is enabled.")
                break

            if args.pause_every > 0 and offset % args.pause_every == 0 and offset < len(chapters):
                print(f"Pausing {args.pause_seconds} seconds after {offset} attempted chapters.")
                time.sleep(max(0, args.pause_seconds))

        Path("reports").mkdir(exist_ok=True)
        report_payload = {
            "range": {"fromChapter": args.from_chapter, "toChapter": args.to_chapter},
            "attemptedFromChapter": chapters[0],
            "attemptedToChapter": chapters[-1],
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "elapsedSeconds": round(time.time() - started_at, 2),
            "results": results,
        }
        Path("reports/import-all-summary.json").write_text(
            json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        print("\nMass import summary")
        print(f"  Imported chapters: {imported}")
        print(f"  Skipped chapters: {skipped}")
        print(f"  Failed/incomplete chapters: {failed}")
        print("  Report: reports/import-all-summary.json")
        print(f"  Checkpoint: {checkpoint_path}")

        # For a mass archive, missing historical chapters should be reviewed, not hidden.
        return 1 if failed and args.stop_on_error else 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
