#!/usr/bin/env python3
"""
Import finished manga archives into the GitHub repository, not R2.

This is intended for series that do not need hourly polling. Images are written
under public/manga-local/<series>/..., manifests are updated under public/content,
and the existing reader can serve them through Cloudflare static assets after deploy.

Use only with content you are allowed to copy and publish.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import requests
from PIL import UnidentifiedImageError

# Allow running from repo root without installing as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from op_importer_common import (  # noqa: E402
    DEFAULT_CONTENT_DIR,
    UploadedPage,
    encode_page_asset,
    fetch_image_bytes,
    load_volume_manifest,
    make_session,
    now_iso,
    pad_chapter,
    pad_volume,
    parse_extensions,
    rebuild_index_from_volumes,
    read_json,
    slugify,
    today_iso,
    validate_confirmation,
    volume_manifest_path,
    volume_manifests_glob,
    write_json_if_changed,
    write_legacy_combined_manifest,
)


@dataclass(frozen=True)
class FinishedSeriesConfig:
    id: str
    title: str
    description: str
    base_url: str
    total_chapters: int
    max_source_volumes: int
    start_source_chapter: int
    default_max_pages: int
    extra_source_chapters: tuple[str, ...] = ()


SERIES_CONFIGS: dict[str, FinishedSeriesConfig] = {
    "naruto": FinishedSeriesConfig(
        id="naruto",
        title="Naruto",
        description="Archivio completo ordinato per volume, capitolo e pagina.",
        base_url="https://onepiecepower.com/manga8/naruto-a",
        total_chapters=700,
        max_source_volumes=72,
        start_source_chapter=1,
        default_max_pages=80,
    ),
    "solo-leveling": FinishedSeriesConfig(
        id="solo-leveling",
        title="Solo Leveling",
        description="Archivio completo ordinato per volume, capitolo e pagina.",
        base_url="https://onepiecepower.com/manga8/solo-leveling-a",
        total_chapters=200,
        max_source_volumes=3,
        start_source_chapter=0,
        default_max_pages=90,
    ),
    "aot": FinishedSeriesConfig(
        id="aot",
        title="Attack on Titan",
        description="Archivio completo ordinato per volume, capitolo e pagina.",
        base_url="https://onepiecepower.com/manga8/attack-on-titan-d",
        total_chapters=139,
        max_source_volumes=34,
        start_source_chapter=1,
        default_max_pages=90,
        extra_source_chapters=("139-1", "139-2", "139-3", "139-4", "139-5", "139-6"),
    ),
}


@dataclass
class LocalImportResult:
    imported: bool
    skipped: bool
    missing: bool
    chapter: int | None
    source_volume: int
    source_chapter: int | str
    pages_count: int
    reason: str = ""


def pad_source_chapter_token(value: int | str) -> str:
    if isinstance(value, int):
        return f"{value:02d}"
    return str(value)


def source_url(config: FinishedSeriesConfig, source_volume: int, source_chapter: int | str, page: int, extension: str) -> str:
    return (
        f"{config.base_url.rstrip('/')}/"
        f"volume{source_volume:02d}/"
        f"capitolo{pad_source_chapter_token(source_chapter)}/"
        f"{page:02d}.{extension.lstrip('.')}"
    )


def local_key_for_page(series_id: str, volume: int, chapter: int, page: int, extension: str) -> str:
    clean_extension = extension.lower().lstrip(".") or "webp"
    if clean_extension == "jpeg":
        clean_extension = "jpg"
    return f"manga-local/{slugify(series_id)}/vol-{pad_volume(volume)}/chapter-{pad_chapter(chapter)}/page-{page:03d}.{clean_extension}"


def public_src_for_key(key: str) -> str:
    return "/" + key.lstrip("/")


def series_chapters(content_dir: Path, series_id: str) -> list[dict]:
    chapters: list[dict] = []
    for path in volume_manifests_glob(content_dir, series_id):
        data = read_json(path, {})
        if data.get("seriesId") != slugify(series_id):
            continue
        chapters.extend(data.get("chapters", []))
    chapters.sort(key=lambda item: int(item.get("number", 0)))
    return chapters


def get_chapter_by_number(content_dir: Path, series_id: str, number: int) -> dict | None:
    return next((item for item in series_chapters(content_dir, series_id) if int(item.get("number", -1)) == number), None)


def local_files_exist(chapter: dict, repo_public_dir: Path) -> bool:
    pages = chapter.get("pages") or []
    if not pages:
        return False
    for page in pages:
        key = page.get("key") or ""
        # key is stored relative to public/, for example manga-local/naruto/...
        if not key or not (repo_public_dir / key).exists():
            return False
    return True


def chapter_payload(
    *,
    config: FinishedSeriesConfig,
    chapter: int,
    volume: int,
    source_chapter: int | str,
    pages: Sequence[UploadedPage],
    display_number: str | None = None,
) -> dict:
    label = display_number or str(chapter)
    return {
        "id": f"chapter-{chapter}",
        "number": chapter,
        "displayNumber": label,
        "volume": volume,
        "title": f"{config.title} · Capitolo {label}",
        "publishedAt": today_iso(),
        "sourceVolume": volume,
        "sourceChapter": source_chapter,
        "pages": [
            {
                "src": page.src,
                "key": page.key,
                "width": page.width,
                "height": page.height,
                "bytes": page.bytes,
            }
            for page in sorted(pages, key=lambda item: item.page)
        ],
    }


def upsert_local_chapter(
    *,
    content_dir: Path,
    config: FinishedSeriesConfig,
    chapter: int,
    source_volume: int,
    source_chapter: int | str,
    pages: Sequence[UploadedPage],
    display_number: str | None = None,
) -> None:
    manifest = load_volume_manifest(content_dir, config.id, source_volume)
    manifest["schemaVersion"] = 2
    manifest["generatedAt"] = now_iso()
    manifest["seriesId"] = slugify(config.id)
    manifest["volume"] = source_volume
    manifest.setdefault("chapters", [])

    numbers = [int(item.get("number", 0)) for item in manifest["chapters"] if item.get("number") is not None]
    numbers.append(chapter)
    manifest["fromChapter"] = min(numbers)
    manifest["toChapter"] = max(numbers)

    payload = chapter_payload(
        config=config,
        chapter=chapter,
        volume=source_volume,
        source_chapter=source_chapter,
        pages=pages,
        display_number=display_number,
    )
    idx = next((i for i, item in enumerate(manifest["chapters"]) if int(item.get("number", -1)) == chapter), None)
    if idx is None:
        manifest["chapters"].append(payload)
    else:
        manifest["chapters"][idx] = payload
    manifest["chapters"].sort(key=lambda item: int(item.get("number", 0)))
    write_json_if_changed(volume_manifest_path(content_dir, config.id, source_volume), manifest)

    index = rebuild_index_from_volumes(content_dir, config.id, config.title, config.description)
    write_legacy_combined_manifest(content_dir, index)


def import_candidate(
    *,
    config: FinishedSeriesConfig,
    session: requests.Session,
    repo_public_dir: Path,
    content_dir: Path,
    source_volume: int,
    source_chapter: int | str,
    global_chapter: int,
    display_number: str | None,
    source_extensions: Sequence[str],
    max_pages: int,
    min_pages: int,
    stop_after_missing_pages: int,
    timeout: float,
    delay: float,
    webp_quality: int,
    image_strategy: str,
    overwrite: bool,
    dry_run: bool,
) -> LocalImportResult:
    existing = get_chapter_by_number(content_dir, config.id, global_chapter)
    if existing and not overwrite and local_files_exist(existing, repo_public_dir):
        return LocalImportResult(
            imported=False,
            skipped=True,
            missing=False,
            chapter=global_chapter,
            source_volume=source_volume,
            source_chapter=source_chapter,
            pages_count=len(existing.get("pages") or []),
            reason="already present",
        )

    found_pages: list[UploadedPage] = []
    consecutive_missing_pages = 0

    print(f"Trying {config.title}: source volume {source_volume:02d}, source chapter {source_chapter}, reader chapter {global_chapter}")

    for page in range(1, max_pages + 1):
        image_bytes = None
        used_content_type = ""
        used_extension = ""
        used_url = ""
        statuses: list[str] = []

        for extension in source_extensions:
            candidate = source_url(config, source_volume, source_chapter, page, extension)
            data, content_type, http_status, status = fetch_image_bytes(session, candidate, timeout)
            statuses.append(f"{extension}:{status}:{http_status or '-'}")
            if status == "ok" and data:
                image_bytes = data
                used_content_type = content_type
                used_extension = extension
                used_url = candidate
                break

        if not image_bytes:
            consecutive_missing_pages += 1
            print(f"  page {page:03d}: not found ({', '.join(statuses)})")
            if stop_after_missing_pages > 0 and consecutive_missing_pages >= stop_after_missing_pages:
                break
            if delay > 0:
                time.sleep(delay)
            continue

        consecutive_missing_pages = 0
        try:
            encoded = encode_page_asset(
                image_bytes,
                quality=webp_quality,
                strategy=image_strategy,
                source_extension=used_extension,
                content_type=used_content_type,
            )
        except UnidentifiedImageError:
            print(f"  page {page:03d}: downloaded but unreadable ({used_url})")
            continue

        key = local_key_for_page(config.id, source_volume, global_chapter, page, encoded.extension)
        output_path = repo_public_dir / key
        src = public_src_for_key(key)

        if not dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if overwrite or not output_path.exists():
                output_path.write_bytes(encoded.body)
                action = "saved"
            else:
                action = "already saved"
        else:
            action = "dry-run"

        print(
            f"  page {page:03d}: {action} {key} "
            f"({encoded.width}x{encoded.height}, {encoded.encoded_bytes} bytes, strategy={encoded.strategy})"
        )
        found_pages.append(UploadedPage(page=page, key=key, src=src, width=encoded.width, height=encoded.height, bytes=encoded.encoded_bytes))

        if delay > 0:
            time.sleep(delay)

    if len(found_pages) < min_pages:
        return LocalImportResult(
            imported=False,
            skipped=False,
            missing=True,
            chapter=global_chapter,
            source_volume=source_volume,
            source_chapter=source_chapter,
            pages_count=len(found_pages),
            reason=f"only {len(found_pages)} page(s), minimum is {min_pages}",
        )

    if not dry_run:
        upsert_local_chapter(
            content_dir=content_dir,
            config=config,
            chapter=global_chapter,
            source_volume=source_volume,
            source_chapter=source_chapter,
            pages=found_pages,
            display_number=display_number,
        )

    return LocalImportResult(
        imported=True,
        skipped=False,
        missing=False,
        chapter=global_chapter,
        source_volume=source_volume,
        source_chapter=source_chapter,
        pages_count=len(found_pages),
        reason="imported",
    )


def last_main_chapter_state(content_dir: Path, config: FinishedSeriesConfig) -> tuple[int, int, int] | None:
    chapters = [item for item in series_chapters(content_dir, config.id) if int(item.get("number", 0)) <= config.total_chapters]
    if not chapters:
        return None
    last = max(chapters, key=lambda item: int(item.get("number", 0)))
    source_volume = int(last.get("sourceVolume") or last.get("volume") or 1)
    source_chapter = int(last.get("sourceChapter") or config.start_source_chapter)
    return int(last.get("number")), source_volume, source_chapter


def import_main_archive(
    *,
    config: FinishedSeriesConfig,
    session: requests.Session,
    repo_public_dir: Path,
    content_dir: Path,
    source_extensions: Sequence[str],
    max_new_chapters: int,
    max_pages: int,
    min_pages: int,
    missing_chapters_to_next_volume: int,
    stop_after_missing_pages: int,
    timeout: float,
    delay: float,
    webp_quality: int,
    image_strategy: str,
    overwrite: bool,
    dry_run: bool,
) -> int:
    state = last_main_chapter_state(content_dir, config)
    if state is None:
        global_chapter = 1
        source_volume = 1
        source_chapter = config.start_source_chapter
        last_valid_source_chapter = config.start_source_chapter
    else:
        last_global, source_volume, last_source_chapter = state
        global_chapter = last_global + 1
        source_chapter = last_source_chapter + 1
        last_valid_source_chapter = last_source_chapter

    imported_count = 0
    missing_candidate_count = 0

    while global_chapter <= config.total_chapters and source_volume <= config.max_source_volumes:
        if max_new_chapters > 0 and imported_count >= max_new_chapters:
            break

        result = import_candidate(
            config=config,
            session=session,
            repo_public_dir=repo_public_dir,
            content_dir=content_dir,
            source_volume=source_volume,
            source_chapter=source_chapter,
            global_chapter=global_chapter,
            display_number=str(global_chapter),
            source_extensions=source_extensions,
            max_pages=max_pages,
            min_pages=min_pages,
            stop_after_missing_pages=stop_after_missing_pages,
            timeout=timeout,
            delay=delay,
            webp_quality=webp_quality,
            image_strategy=image_strategy,
            overwrite=overwrite,
            dry_run=dry_run,
        )

        if result.imported or result.skipped:
            missing_candidate_count = 0
            imported_count += 1 if result.imported else 0
            if isinstance(source_chapter, int):
                last_valid_source_chapter = source_chapter
                source_chapter += 1
            global_chapter += 1
            continue

        missing_candidate_count += 1
        if isinstance(source_chapter, int):
            source_chapter += 1

        if missing_candidate_count >= missing_chapters_to_next_volume:
            source_volume += 1
            # Requested behavior: when the next volume begins, do not restart from capitolo01.
            # Continue from the last valid source chapter found in the previous volume.
            source_chapter = last_valid_source_chapter
            missing_candidate_count = 0
            print(f"  moving to source volume {source_volume:02d}, restarting at source chapter {source_chapter}")

    return imported_count


def import_aot_extras(
    *,
    config: FinishedSeriesConfig,
    session: requests.Session,
    repo_public_dir: Path,
    content_dir: Path,
    source_extensions: Sequence[str],
    max_new_chapters: int,
    already_imported: int,
    max_pages: int,
    min_pages: int,
    stop_after_missing_pages: int,
    timeout: float,
    delay: float,
    webp_quality: int,
    image_strategy: str,
    overwrite: bool,
    dry_run: bool,
) -> int:
    if not config.extra_source_chapters:
        return 0

    # Only start extras after the 139 main chapters are present.
    if not get_chapter_by_number(content_dir, config.id, config.total_chapters):
        return 0

    imported_count = 0
    for idx, source_chapter in enumerate(config.extra_source_chapters, start=1):
        if max_new_chapters > 0 and already_imported + imported_count >= max_new_chapters:
            break
        global_chapter = config.total_chapters + idx
        if get_chapter_by_number(content_dir, config.id, global_chapter) and not overwrite:
            continue
        source_volume = config.max_source_volumes + idx
        display_number = source_chapter
        result = import_candidate(
            config=config,
            session=session,
            repo_public_dir=repo_public_dir,
            content_dir=content_dir,
            source_volume=source_volume,
            source_chapter=source_chapter,
            global_chapter=global_chapter,
            display_number=display_number,
            source_extensions=source_extensions,
            max_pages=max_pages,
            min_pages=min_pages,
            stop_after_missing_pages=stop_after_missing_pages,
            timeout=timeout,
            delay=delay,
            webp_quality=webp_quality,
            image_strategy=image_strategy,
            overwrite=overwrite,
            dry_run=dry_run,
        )
        if result.imported:
            imported_count += 1
    return imported_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import finished manga images into the GitHub repo under public/manga-local.")
    parser.add_argument("--series", choices=[*SERIES_CONFIGS.keys(), "all"], required=True)
    parser.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR))
    parser.add_argument("--public-dir", default="public")
    parser.add_argument("--extensions", default="jpg,jpeg")
    parser.add_argument("--max-new-chapters", type=int, default=20, help="0 means no per-run limit.")
    parser.add_argument("--max-pages", type=int, default=0, help="0 uses the per-series default.")
    parser.add_argument("--min-pages", type=int, default=3)
    parser.add_argument("--missing-chapters-to-next-volume", type=int, default=3)
    parser.add_argument("--stop-after-missing-pages", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--webp-quality", type=int, default=82)
    parser.add_argument("--image-strategy", choices=["best-size", "webp", "original"], default="best-size")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--i-confirm-rights", action="store_true", default=os.environ.get("I_CONFIRM_RIGHTS", "").lower() == "true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_confirmation(args.i_confirm_rights)

    content_dir = Path(args.content_dir)
    repo_public_dir = Path(args.public_dir)
    source_extensions = parse_extensions(args.extensions)
    session = make_session("OPReaderLocalArchiveImporter/1.0 (+authorized-import)")

    selected = list(SERIES_CONFIGS.values()) if args.series == "all" else [SERIES_CONFIGS[args.series]]
    total_imported = 0
    report = {"series": {}, "generatedAt": now_iso()}

    for config in selected:
        max_pages = args.max_pages or config.default_max_pages
        print(f"\n=== Importing {config.title} ({config.id}) ===")
        imported = import_main_archive(
            config=config,
            session=session,
            repo_public_dir=repo_public_dir,
            content_dir=content_dir,
            source_extensions=source_extensions,
            max_new_chapters=max(0, args.max_new_chapters - total_imported) if args.series == "all" else args.max_new_chapters,
            max_pages=max_pages,
            min_pages=args.min_pages,
            missing_chapters_to_next_volume=args.missing_chapters_to_next_volume,
            stop_after_missing_pages=args.stop_after_missing_pages,
            timeout=args.timeout,
            delay=args.delay,
            webp_quality=args.webp_quality,
            image_strategy=args.image_strategy,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        extras = import_aot_extras(
            config=config,
            session=session,
            repo_public_dir=repo_public_dir,
            content_dir=content_dir,
            source_extensions=source_extensions,
            max_new_chapters=args.max_new_chapters,
            already_imported=imported,
            max_pages=max_pages,
            min_pages=args.min_pages,
            stop_after_missing_pages=args.stop_after_missing_pages,
            timeout=args.timeout,
            delay=args.delay,
            webp_quality=args.webp_quality,
            image_strategy=args.image_strategy,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        series_imported = imported + extras
        total_imported += series_imported
        report["series"][config.id] = {"imported": series_imported}
        print(f"Imported {series_imported} new chapter(s) for {config.title}")

        if args.series == "all" and args.max_new_chapters > 0 and total_imported >= args.max_new_chapters:
            break

    Path(".tmp").mkdir(exist_ok=True)
    Path(".tmp/local-finished-manga-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nTotal imported in this run: {total_imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
