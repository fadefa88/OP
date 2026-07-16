#!/usr/bin/env python3
"""
Refresh an existing One Piece chapter when the source images are replaced.

The source sometimes publishes provisional scans and later replaces them with
better files at the same URLs. This script re-encodes the current source pages
using the same production settings, compares the resulting R2 objects by size
and SHA-256, uploads only changed pages, removes superseded R2 objects, and
updates the JSON manifest with cache-busting version query strings.

If the source has fewer than the configured minimum pages or is unchanged, it
exits successfully without modifying public/content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from PIL import UnidentifiedImageError

from op_importer_common import (
    DEFAULT_CONTENT_DIR,
    DEFAULT_SERIES_DESCRIPTION,
    DEFAULT_SERIES_ID,
    DEFAULT_SERIES_TITLE,
    build_r2_client,
    build_source_url,
    encode_page_asset,
    fetch_image_bytes,
    get_manifest_chapter,
    latest_chapter_from_index,
    make_session,
    now_iso,
    parse_extensions,
    public_url_for_key,
    r2_key_for_page,
    read_json,
    rebuild_index_from_volumes,
    require_env,
    upload_asset_to_r2,
    validate_confirmation,
    volume_manifest_path,
    write_json_if_changed,
    write_legacy_combined_manifest,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh existing chapter images when the source changes.")
    parser.add_argument("--source-base-url", default=os.environ.get("AUTHORIZED_MANGA_BASE_URL", ""))
    parser.add_argument("--source-template", default=os.environ.get("AUTHORIZED_MANGA_SOURCE_TEMPLATE", ""))
    parser.add_argument("--extensions", default=os.environ.get("IMAGE_EXTENSIONS", "jpg,jpeg"))
    parser.add_argument("--chapter", type=int, help="Optional chapter to refresh. Default: latest manifest chapter.")
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "45")))
    parser.add_argument("--min-pages", type=int, default=int(os.environ.get("MIN_PAGES", "3")))
    parser.add_argument("--stop-after-missing", type=int, default=int(os.environ.get("STOP_AFTER_MISSING", "3")))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("IMPORT_TIMEOUT", "15")))
    parser.add_argument("--delay", type=float, default=float(os.environ.get("IMPORT_DELAY", "0.25")))
    parser.add_argument("--webp-quality", type=int, default=int(os.environ.get("WEBP_QUALITY", "82")))
    parser.add_argument(
        "--image-strategy",
        choices=["best-size", "webp", "original"],
        default=os.environ.get("IMAGE_STRATEGY", "best-size"),
    )
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
    parser.add_argument("--report", default="reports/latest-chapter-refresh-result.json")
    return parser.parse_args(argv)


def write_report(path: str, payload: dict) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def page_number(page: dict, fallback: int) -> int:
    key = str(page.get("key") or page.get("src") or "")
    match = re.search(r"page-(\d+)", key)
    return int(match.group(1)) if match else fallback


def r2_object_digest(client, bucket: str, key: str) -> tuple[int | None, str | None]:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        size = int(head.get("ContentLength") or 0)
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return size, hashlib.sha256(body).hexdigest()
    except Exception:
        return None, None


def delete_r2_object(client, bucket: str, key: str) -> bool:
    try:
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:
        print(f"  unable to delete superseded R2 object {key}: {exc}", file=sys.stderr)
        return False


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

        chapter = args.chapter or latest_chapter_from_index(content_dir, args.series_id)
        if chapter < 1:
            raise RuntimeError("No latest chapter found in manifest")

        existing = get_manifest_chapter(content_dir, args.series_id, chapter)
        if not existing:
            write_report(args.report, {"updated": False, "chapter": chapter, "reason": "chapter not found in manifest"})
            print(f"Chapter {chapter} is not present in the manifest. Nothing to refresh.")
            return 0

        source_volume = int(existing.get("sourceVolume") or existing.get("volume") or 0)
        source_chapter = int(existing.get("sourceChapter") or chapter)
        manifest_volume = int(existing.get("volume") or source_volume)
        if source_volume < 1 or manifest_volume < 1:
            raise RuntimeError(f"Invalid source/manifest volume for chapter {chapter}")

        print(
            f"Refreshing chapter {chapter}: source volume {source_volume}, "
            f"source chapter {source_chapter}, manifest volume {manifest_volume}"
        )

        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)
        extensions = parse_extensions(args.extensions)
        source_template = args.source_template or None

        encoded_pages: list[dict] = []
        consecutive_missing = 0

        for page in range(1, args.max_pages + 1):
            image_bytes = None
            used_content_type = ""
            used_extension = ""
            statuses: list[str] = []

            for extension in extensions:
                url = build_source_url(
                    args.source_base_url,
                    source_volume,
                    chapter,
                    page,
                    extension,
                    source_template,
                    source_chapter=source_chapter,
                )
                data, content_type, http_status, status = fetch_image_bytes(session, url, args.timeout)
                statuses.append(f"{extension}:{status}:{http_status or '-'}")
                if status == "ok" and data:
                    image_bytes = data
                    used_content_type = content_type
                    used_extension = extension
                    break

            if not image_bytes:
                if any(":missing:" in status or status.endswith(":missing:-") for status in statuses):
                    consecutive_missing += 1
                else:
                    consecutive_missing = 0
                print(f"  page {page:03d}: not found ({', '.join(statuses)})")
                if args.stop_after_missing > 0 and consecutive_missing >= args.stop_after_missing:
                    break
                if args.delay > 0:
                    time.sleep(args.delay)
                continue

            consecutive_missing = 0
            try:
                encoded = encode_page_asset(
                    image_bytes,
                    quality=args.webp_quality,
                    strategy=args.image_strategy,
                    source_extension=used_extension,
                    content_type=used_content_type,
                )
            except UnidentifiedImageError:
                print(f"  page {page:03d}: source is not a readable image")
                continue

            key = r2_key_for_page(args.series_id, manifest_volume, chapter, page, encoded.extension)
            digest = hashlib.sha256(encoded.body).hexdigest()
            src = f"{public_url_for_key(public_base_url, key)}?v={digest[:16]}"

            encoded_pages.append(
                {
                    "page": page,
                    "key": key,
                    "src": src,
                    "width": encoded.width,
                    "height": encoded.height,
                    "bytes": encoded.encoded_bytes,
                    "sourceBytes": len(image_bytes),
                    "sha256": digest,
                    "body": encoded.body,
                    "contentType": encoded.content_type,
                }
            )
            if args.delay > 0:
                time.sleep(args.delay)

        existing_pages = sorted(existing.get("pages", []), key=lambda item: page_number(item, 0))

        if len(encoded_pages) < args.min_pages:
            reason = f"source currently has only {len(encoded_pages)} valid page(s)"
            write_report(args.report, {"updated": False, "chapter": chapter, "reason": reason})
            print(f"Skipping refresh: {reason}.")
            return 0

        existing_by_page = {page_number(item, index): item for index, item in enumerate(existing_pages, start=1)}
        desired_keys = {str(item["key"]) for item in encoded_pages}
        changed_pages: list[int] = []
        removed_pages: list[int] = []
        manifest_changed = len(encoded_pages) != len(existing_pages)

        for item in encoded_pages:
            current = existing_by_page.get(item["page"])
            remote_size, remote_sha = r2_object_digest(r2_client, bucket, item["key"])
            content_changed = remote_size != item["bytes"] or remote_sha != item["sha256"]

            if content_changed:
                upload_asset_to_r2(r2_client, bucket, item["key"], item["body"], item["contentType"])
                changed_pages.append(item["page"])
                print(
                    f"  page {item['page']:03d}: replaced on R2 "
                    f"(old bytes={remote_size}, new bytes={item['bytes']})"
                )
            else:
                print(f"  page {item['page']:03d}: unchanged")

            desired_manifest_page = {
                "src": item["src"],
                "key": item["key"],
                "width": item["width"],
                "height": item["height"],
                "bytes": item["bytes"],
                "sourceBytes": item["sourceBytes"],
                "sha256": item["sha256"],
            }
            if current != desired_manifest_page:
                manifest_changed = True

        for index, old_page in enumerate(existing_pages, start=1):
            old_key = str(old_page.get("key") or "")
            if not old_key or old_key in desired_keys:
                continue
            old_page_number = page_number(old_page, index)
            if delete_r2_object(r2_client, bucket, old_key):
                removed_pages.append(old_page_number)
                print(f"  page {old_page_number:03d}: removed superseded R2 object {old_key}")

        affected_pages = sorted(set(changed_pages + removed_pages))

        if not manifest_changed and not affected_pages:
            write_report(
                args.report,
                {
                    "updated": False,
                    "chapter": chapter,
                    "volume": manifest_volume,
                    "pages": len(encoded_pages),
                    "reason": "source and R2 images are unchanged",
                },
            )
            print("Chapter images are unchanged.")
            return 0

        manifest_path = volume_manifest_path(content_dir, args.series_id, manifest_volume)
        manifest = read_json(manifest_path, {})
        chapters = manifest.setdefault("chapters", [])
        chapter_index = next((index for index, item in enumerate(chapters) if int(item.get("number", -1)) == chapter), None)
        if chapter_index is None:
            raise RuntimeError(f"Chapter {chapter} disappeared from {manifest_path}")

        updated_chapter = dict(chapters[chapter_index])
        updated_chapter["pages"] = [
            {
                "src": item["src"],
                "key": item["key"],
                "width": item["width"],
                "height": item["height"],
                "bytes": item["bytes"],
                "sourceBytes": item["sourceBytes"],
                "sha256": item["sha256"],
            }
            for item in encoded_pages
        ]
        updated_chapter["sourceVolume"] = source_volume
        updated_chapter["sourceChapter"] = source_chapter
        updated_chapter["updatedAt"] = now_iso()
        chapters[chapter_index] = updated_chapter
        manifest["generatedAt"] = now_iso()

        write_json_if_changed(manifest_path, manifest)
        index = rebuild_index_from_volumes(content_dir, args.series_id, args.series_title, args.series_description)
        write_legacy_combined_manifest(content_dir, index)

        write_report(
            args.report,
            {
                "updated": True,
                "chapter": chapter,
                "volume": manifest_volume,
                "pages": len(encoded_pages),
                "changedPages": affected_pages,
                "removedPages": sorted(set(removed_pages)),
                "metadataBackfilled": manifest_changed and not affected_pages,
            },
        )
        print(
            f"Chapter {chapter} refreshed. Affected pages: "
            f"{affected_pages if affected_pages else 'none; manifest metadata/cache version updated'}"
        )
        return 0

    except Exception as exc:
        write_report(args.report, {"updated": False, "error": str(exc)})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
