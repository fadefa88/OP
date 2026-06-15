#!/usr/bin/env python3
"""Helpers for One Punch Man imports using volumeXX/capitoloYY direct-image paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from op_importer_common import (
    DEFAULT_CONTENT_DIR,
    ChapterImportResult,
    import_single_chapter_to_r2,
    latest_chapter_from_index,
    read_json,
    slugify,
    volume_manifests_glob,
)

OPM_SERIES_ID = "opm"
OPM_SERIES_TITLE = "One Punch Man"
OPM_SERIES_DESCRIPTION = "Archivio ordinato per volume, capitolo e pagina."
OPM_DEFAULT_BASE_URL = "https://onepiecepower.com/manga8/one-punch-man"
OPM_DEFAULT_TEMPLATE = "{base_url}/volume{volume_2}/capitolo{source_chapter_2}/{page_padded}.{extension}"


def iter_series_chapters(content_dir: Path, series_id: str = OPM_SERIES_ID) -> list[dict]:
    chapters: list[dict] = []
    normalized_id = slugify(series_id)
    for path in volume_manifests_glob(content_dir, series_id):
        data = read_json(path, {})
        if data.get("seriesId") != normalized_id:
            continue
        chapters.extend(data.get("chapters", []))
    return sorted(chapters, key=lambda item: int(item.get("number", 0)))


def existing_source_pairs(content_dir: Path, series_id: str = OPM_SERIES_ID) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for chapter in iter_series_chapters(content_dir, series_id):
        try:
            source_volume = int(chapter.get("sourceVolume") or chapter.get("volume"))
            source_chapter = int(chapter.get("sourceChapter") or chapter.get("number"))
        except (TypeError, ValueError):
            continue
        pairs.add((source_volume, source_chapter))
    return pairs


def latest_opm_source_position(content_dir: Path, series_id: str = OPM_SERIES_ID) -> tuple[int, int, int] | None:
    chapters = iter_series_chapters(content_dir, series_id)
    if not chapters:
        return None
    latest = chapters[-1]
    try:
        global_chapter = int(latest.get("number"))
        source_volume = int(latest.get("sourceVolume") or latest.get("volume"))
        source_chapter = int(latest.get("sourceChapter") or latest.get("number"))
    except (TypeError, ValueError):
        return None
    return global_chapter, source_volume, source_chapter


def next_global_chapter(content_dir: Path, series_id: str = OPM_SERIES_ID) -> int:
    latest = latest_chapter_from_index(content_dir, series_id)
    if latest > 0:
        return latest + 1
    chapters = iter_series_chapters(content_dir, series_id)
    if chapters:
        return int(chapters[-1].get("number", 0)) + 1
    return 1


def import_opm_source_chapter_to_r2(
    *,
    session,
    r2_client,
    bucket: str,
    public_base_url: str,
    source_base_url: str,
    source_template: str | None,
    source_extensions,
    content_dir: Path,
    global_chapter: int,
    source_volume: int,
    source_chapter: int,
    max_pages: int,
    min_pages: int,
    stop_after_missing: int,
    timeout: float,
    delay: float,
    webp_quality: int,
    image_strategy: str,
    overwrite: bool,
    dry_run: bool = False,
) -> ChapterImportResult:
    return import_single_chapter_to_r2(
        session=session,
        r2_client=r2_client,
        bucket=bucket,
        public_base_url=public_base_url,
        source_base_url=source_base_url,
        source_template=source_template or OPM_DEFAULT_TEMPLATE,
        source_extensions=source_extensions,
        content_dir=content_dir,
        series_id=OPM_SERIES_ID,
        series_title=OPM_SERIES_TITLE,
        series_description=OPM_SERIES_DESCRIPTION,
        chapter=global_chapter,
        volume_override=source_volume,
        source_chapter_override=source_chapter,
        max_pages=max_pages,
        min_pages=min_pages,
        stop_after_missing=stop_after_missing,
        timeout=timeout,
        delay=delay,
        webp_quality=webp_quality,
        image_strategy=image_strategy,
        overwrite=overwrite,
        dry_run=dry_run,
    )
