#!/usr/bin/env python3
"""
Generic reader-page importer for a second manga series.

It is designed for sources where a chapter is exposed as a reader page, for example:
  https://onepiecepower.com/manga8/one-punch-man/reader/001

The script reads the reader HTML, extracts image candidates, filters out small UI/logo images,
converts JPG/JPEG/PNG/WebP with the existing best-size strategy, uploads to Cloudflare R2,
and writes only JSON manifests under public/content.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from PIL import UnidentifiedImageError

from op_importer_common import (
    DEFAULT_CONTENT_DIR,
    ONE_MAN_PUNCH_DESCRIPTION,
    ONE_MAN_PUNCH_SERIES_ID,
    ONE_MAN_PUNCH_SERIES_TITLE,
    UploadedPage,
    build_r2_client,
    encode_page_asset,
    generic_volume_for_chapter,
    latest_chapter_from_index,
    make_session,
    public_url_for_key,
    r2_key_for_page,
    r2_object_exists,
    rebuild_index_from_volumes,
    require_env,
    slugify,
    upload_asset_to_r2,
    upsert_chapter_in_volume,
    validate_confirmation,
    write_legacy_combined_manifest,
)

IMAGE_URL_RE = re.compile(
    r"(?P<url>(?:https?:)?//[^\"'<>\s]+?\.(?:jpe?g|png|webp)(?:\?[^\"'<>\s]*)?|(?:/|\.\.?/)[^\"'<>\s]+?\.(?:jpe?g|png|webp)(?:\?[^\"'<>\s]*)?)",
    re.IGNORECASE,
)

IMAGE_ATTRS = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-full",
    "data-url",
    "data-image",
    "data-large",
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import reader-page manga chapters to Cloudflare R2.")

    source = parser.add_argument_group("source")
    source.add_argument(
        "--source-base-url",
        default=os.environ.get("OPM_AUTHORIZED_MANGA_BASE_URL", os.environ.get("AUTHORIZED_OPM_BASE_URL", "https://onepiecepower.com/manga8/one-punch-man")),
        help="Authorized reader base URL. Default: env OPM_AUTHORIZED_MANGA_BASE_URL or One Punch Man reader base.",
    )
    source.add_argument(
        "--source-template",
        default=os.environ.get("OPM_AUTHORIZED_MANGA_SOURCE_TEMPLATE", os.environ.get("AUTHORIZED_OPM_SOURCE_TEMPLATE", "")),
        help="Optional chapter reader URL template. Placeholders: {base_url}, {chapter}, {chapter_padded}, {chapter_4}.",
    )
    source.add_argument("--reader-pad", type=int, default=int(os.environ.get("OPM_READER_PAD", "3")))

    scope = parser.add_mutually_exclusive_group(required=False)
    scope.add_argument("--chapter", type=int, help="Import/check one chapter.")
    scope.add_argument("--from-chapter", type=int, help="First chapter for a mass/manual range import.")
    parser.add_argument("--to-chapter", type=int, help="Last chapter for a mass/manual range import.")
    parser.add_argument("--scan-ahead", type=int, default=int(os.environ.get("SCAN_AHEAD", "3")))

    pages = parser.add_argument_group("page filtering")
    pages.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "80")))
    pages.add_argument("--min-pages", type=int, default=int(os.environ.get("MIN_PAGES", "3")))
    pages.add_argument("--min-image-width", type=int, default=int(os.environ.get("MIN_IMAGE_WIDTH", "400")))
    pages.add_argument("--min-image-height", type=int, default=int(os.environ.get("MIN_IMAGE_HEIGHT", "550")))
    pages.add_argument("--timeout", type=float, default=float(os.environ.get("IMPORT_TIMEOUT", "15")))
    pages.add_argument("--delay", type=float, default=float(os.environ.get("IMPORT_DELAY", "0.25")))

    images = parser.add_argument_group("image handling")
    images.add_argument("--webp-quality", type=int, default=int(os.environ.get("WEBP_QUALITY", "82")))
    images.add_argument("--image-strategy", choices=["best-size", "webp", "original"], default=os.environ.get("IMAGE_STRATEGY", "best-size"))
    images.add_argument("--overwrite", action="store_true")

    r2 = parser.add_argument_group("cloudflare r2")
    r2.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    r2.add_argument("--bucket", default=os.environ.get("R2_BUCKET_NAME", ""))
    r2.add_argument("--access-key-id", default=os.environ.get("R2_ACCESS_KEY_ID", ""))
    r2.add_argument("--secret-access-key", default=os.environ.get("R2_SECRET_ACCESS_KEY", ""))
    r2.add_argument("--public-base-url", default=os.environ.get("R2_PUBLIC_BASE_URL", "https://static.lucahome.uk"))

    manifest = parser.add_argument_group("manifest")
    manifest.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR))
    manifest.add_argument("--series-id", default=os.environ.get("OPM_SERIES_ID", ONE_MAN_PUNCH_SERIES_ID))
    manifest.add_argument("--series-title", default=os.environ.get("OPM_SERIES_TITLE", ONE_MAN_PUNCH_SERIES_TITLE))
    manifest.add_argument("--series-description", default=os.environ.get("OPM_SERIES_DESCRIPTION", ONE_MAN_PUNCH_DESCRIPTION))
    manifest.add_argument("--report", default=os.environ.get("IMPORT_REPORT", "reports/opm-new-chapter-result.json"))

    parser.add_argument("--i-confirm-rights", action="store_true", default=os.environ.get("I_CONFIRM_RIGHTS", "").lower() == "true")

    args = parser.parse_args(argv)
    if args.from_chapter is not None and args.to_chapter is None:
        parser.error("--to-chapter is required with --from-chapter")
    if args.to_chapter is not None and args.from_chapter is None:
        parser.error("--from-chapter is required with --to-chapter")
    if args.from_chapter is not None and args.from_chapter > args.to_chapter:
        parser.error("--from-chapter cannot be greater than --to-chapter")
    return args


def write_report(path: str, payload: dict) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def chapter_reader_url(base_url: str, chapter: int, pad: int, template: str | None = None) -> str:
    base = base_url.rstrip("/")
    values = {
        "base_url": base,
        "chapter": chapter,
        "chapter_padded": str(chapter).zfill(pad),
        "chapter_4": str(chapter).zfill(4),
    }
    if template:
        return template.format(**values)
    return f"{base}/reader/{values['chapter_padded']}"


def add_candidate(candidates: list[str], seen: set[str], page_url: str, value: str | None) -> None:
    if not value:
        return
    value = value.strip()
    if not value or value.startswith("data:") or value.startswith("blob:"):
        return
    if value.startswith("//"):
        value = "https:" + value
    absolute = urljoin(page_url, value)
    clean = absolute.split("#", 1)[0]
    if clean not in seen:
        seen.add(clean)
        candidates.append(clean)


def extract_reader_image_candidates(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all(["img", "source"]):
        for attr in IMAGE_ATTRS:
            add_candidate(candidates, seen, page_url, tag.get(attr))
        srcset = tag.get("srcset")
        if srcset:
            for part in srcset.split(","):
                add_candidate(candidates, seen, page_url, part.strip().split(" ")[0])

    for match in IMAGE_URL_RE.finditer(html):
        add_candidate(candidates, seen, page_url, match.group("url"))

    # Keep likely reader assets first without making the parser brittle.
    def score(url: str) -> tuple[int, int, str]:
        lower = url.lower()
        bad = any(token in lower for token in ("logo", "avatar", "icon", "banner", "amazon", "ads", "social"))
        good = any(token in lower for token in ("one-punch", "onepunch", "manga", "reader", "scan", "chapter"))
        return (0 if good else 1, 1 if bad else 0, url)

    return sorted(candidates, key=score)


def download_reader_html(session, url: str, timeout: float) -> str:
    response = session.get(url, timeout=timeout, headers={"Accept": "text/html,application/xhtml+xml"})
    response.raise_for_status()
    return response.text


def fetch_image(session, url: str, timeout: float) -> tuple[bytes | None, str, str]:
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
        content_type = response.headers.get("Content-Type", "")
        if response.status_code == 404:
            return None, content_type, "missing"
        if response.status_code in (401, 403, 429):
            return None, content_type, f"blocked:{response.status_code}"
        if not (200 <= response.status_code < 300):
            return None, content_type, f"http:{response.status_code}"
        if content_type and not content_type.lower().split(";", 1)[0].startswith("image/") and "octet-stream" not in content_type.lower():
            return None, content_type, "not-image"
        return response.content, content_type, "ok"
    except Exception as exc:
        return None, "", exc.__class__.__name__


def import_reader_chapter_to_r2(*, args, chapter: int, session, r2_client, bucket: str, public_base_url: str, content_dir: Path) -> dict:
    series_id = slugify(args.series_id)
    volume = generic_volume_for_chapter(chapter)
    reader_url = chapter_reader_url(args.source_base_url, chapter, args.reader_pad, args.source_template or None)
    print(f"\n=== {args.series_title} / Volume {volume} / Chapter {chapter} ===")
    print(f"Reader URL: {reader_url}")

    # Skip if manifest and objects already exist.
    from op_importer_common import get_manifest_chapter
    existing = get_manifest_chapter(content_dir, series_id, chapter)
    if existing and not args.overwrite:
        keys = [page.get("key") for page in existing.get("pages", []) if page.get("key")]
        if keys and all(r2_object_exists(r2_client, bucket, key) for key in keys):
            print("  chapter already present in manifest and R2")
            return {"chapter": chapter, "volume": volume, "imported": False, "skipped": True, "pages": len(keys), "reason": "already-present"}

    html = download_reader_html(session, reader_url, args.timeout)
    candidates = extract_reader_image_candidates(html, reader_url)
    print(f"  candidates extracted: {len(candidates)}")

    found_pages: list[UploadedPage] = []
    for candidate in candidates:
        if len(found_pages) >= args.max_pages:
            break
        image_bytes, content_type, status = fetch_image(session, candidate, args.timeout)
        if not image_bytes:
            print(f"  skip candidate: {status} {candidate}")
            continue

        source_extension = candidate.split("?", 1)[0].rsplit(".", 1)[-1].lower() if "." in candidate else "jpg"
        try:
            encoded = encode_page_asset(
                image_bytes,
                quality=args.webp_quality,
                strategy=args.image_strategy,
                source_extension=source_extension,
                content_type=content_type,
            )
        except UnidentifiedImageError:
            print(f"  skip unreadable image: {candidate}")
            continue

        if encoded.width < args.min_image_width or encoded.height < args.min_image_height:
            print(f"  skip small image: {encoded.width}x{encoded.height} {candidate}")
            continue

        page_number = len(found_pages) + 1
        key = r2_key_for_page(series_id, volume, chapter, page_number, encoded.extension)
        src = public_url_for_key(public_base_url, key)
        if args.overwrite or not r2_object_exists(r2_client, bucket, key):
            upload_asset_to_r2(r2_client, bucket, key, encoded.body, encoded.content_type)
            action = "uploaded"
        else:
            action = "already on R2"
        found_pages.append(UploadedPage(page=page_number, key=key, src=src, width=encoded.width, height=encoded.height, bytes=encoded.encoded_bytes))
        print(f"  page {page_number:03d}: {action} {key} ({encoded.width}x{encoded.height}, {encoded.encoded_bytes} bytes, strategy={encoded.strategy})")
        if args.delay > 0:
            time.sleep(args.delay)

    if len(found_pages) < args.min_pages:
        reason = f"only {len(found_pages)} page(s), minimum is {args.min_pages}"
        print(f"  rejected: {reason}")
        return {"chapter": chapter, "volume": volume, "imported": False, "skipped": False, "pages": len(found_pages), "reason": reason}

    upsert_chapter_in_volume(content_dir, series_id, args.series_title, chapter, volume, found_pages)
    index = rebuild_index_from_volumes(content_dir, series_id, args.series_title, args.series_description)
    write_legacy_combined_manifest(content_dir, index)
    return {"chapter": chapter, "volume": volume, "imported": True, "skipped": False, "pages": len(found_pages), "reason": ""}


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    content_dir = Path(args.content_dir)

    try:
        validate_confirmation(bool(args.i_confirm_rights))
        if not args.source_base_url:
            raise RuntimeError("Missing OPM_AUTHORIZED_MANGA_BASE_URL / --source-base-url")
        account_id = args.account_id or require_env("CLOUDFLARE_ACCOUNT_ID")
        bucket = args.bucket or require_env("R2_BUCKET_NAME")
        access_key_id = args.access_key_id or require_env("R2_ACCESS_KEY_ID")
        secret_access_key = args.secret_access_key or require_env("R2_SECRET_ACCESS_KEY")
        public_base_url = args.public_base_url.rstrip("/")

        if args.chapter:
            chapters = [args.chapter]
        elif args.from_chapter is not None:
            chapters = list(range(args.from_chapter, args.to_chapter + 1))
        else:
            latest = latest_chapter_from_index(content_dir, args.series_id)
            start = latest + 1 if latest > 0 else 1
            chapters = list(range(start, start + max(1, args.scan_ahead)))
            print(f"Latest chapter in manifest for {args.series_id}: {latest}. Probing {chapters}.")

        session = make_session()
        r2_client = build_r2_client(account_id, access_key_id, secret_access_key)

        attempts = []
        imported_any = False
        for chapter in chapters:
            result = import_reader_chapter_to_r2(
                args=args,
                chapter=chapter,
                session=session,
                r2_client=r2_client,
                bucket=bucket,
                public_base_url=public_base_url,
                content_dir=content_dir,
            )
            attempts.append(result)
            if result.get("imported"):
                imported_any = True
                if args.from_chapter is None:
                    break

        if imported_any:
            first = next(item for item in attempts if item.get("imported"))
            write_report(args.report, {"imported": True, **first, "attempts": attempts})
        else:
            write_report(args.report, {"imported": False, "attempts": attempts})
        return 0
    except Exception as exc:
        write_report(args.report, {"imported": False, "error": str(exc)})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
