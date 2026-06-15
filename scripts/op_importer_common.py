#!/usr/bin/env python3
"""
Shared utilities for legal OP Reader imports.

The importer is intentionally generic: it can fetch from a source you are
allowed to copy from, convert JPG/JPEG pages only when WebP is smaller, upload to Cloudflare R2,
and update JSON manifests. It does not require storing images in Git.
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urljoin

import boto3
import requests
from botocore.client import Config
from PIL import Image, ImageOps, UnidentifiedImageError


VOLUME_CHAPTER_RANGES: list[tuple[int, int, int]] = [
    (1, 1, 8),
    (2, 9, 17),
    (3, 18, 26),
    (4, 27, 35),
    (5, 36, 44),
    (6, 45, 53),
    (7, 54, 62),
    (8, 63, 71),
    (9, 72, 81),
    (10, 82, 90),
    (11, 91, 99),
    (12, 100, 108),
    (13, 109, 117),
    (14, 118, 126),
    (15, 127, 136),
    (16, 137, 145),
    (17, 146, 155),
    (18, 156, 166),
    (19, 167, 176),
    (20, 177, 186),
    (21, 187, 195),
    (22, 196, 205),
    (23, 206, 216),
    (24, 217, 226),
    (25, 227, 236),
    (26, 237, 246),
    (27, 247, 255),
    (28, 256, 264),
    (29, 265, 275),
    (30, 276, 285),
    (31, 286, 295),
    (32, 296, 305),
    (33, 306, 316),
    (34, 317, 327),
    (35, 328, 336),
    (36, 337, 346),
    (37, 347, 357),
    (38, 358, 367),
    (39, 368, 377),
    (40, 378, 388),
    (41, 389, 399),
    (42, 400, 409),
    (43, 410, 419),
    (44, 420, 430),
    (45, 431, 440),
    (46, 441, 449),
    (47, 450, 459),
    (48, 460, 470),
    (49, 471, 481),
    (50, 482, 491),
    (51, 492, 502),
    (52, 503, 512),
    (53, 513, 522),
    (54, 523, 532),
    (55, 533, 541),
    (56, 542, 551),
    (57, 552, 562),
    (58, 563, 573),
    (59, 574, 584),
    (60, 585, 594),
    (61, 595, 603),
    (62, 604, 614),
    (63, 615, 626),
    (64, 627, 636),
    (65, 637, 646),
    (66, 647, 656),
    (67, 657, 667),
    (68, 668, 678),
    (69, 679, 690),
    (70, 691, 700),
    (71, 701, 711),
    (72, 712, 721),
    (73, 722, 731),
    (74, 732, 742),
    (75, 743, 752),
    (76, 753, 763),
    (77, 764, 775),
    (78, 776, 785),
    (79, 786, 795),
    (80, 796, 806),
    (81, 807, 816),
    (82, 817, 827),
    (83, 828, 838),
    (84, 839, 848),
    (85, 849, 858),
    (86, 859, 869),
    (87, 870, 879),
    (88, 880, 889),
    (89, 890, 900),
    (90, 901, 910),
    (91, 911, 921),
    (92, 922, 931),
    (93, 932, 942),
    (94, 943, 953),
    (95, 954, 964),
    (96, 965, 974),
    (97, 975, 984),
    (98, 985, 994),
    (99, 995, 1004),
    (100, 1005, 1015),
    (101, 1016, 1025),
    (102, 1026, 1035),
    (103, 1036, 1046),
    (104, 1047, 1055),
    (105, 1056, 1065),
    (106, 1066, 1076),
    (107, 1077, 1088),
    (108, 1089, 1100),
    (109, 1101, 1110),
    (110, 1111, 1121),
    (111, 1122, 1133),
    (112, 1134, 1144),
    (113, 1145, 1155),
    (114, 1156, 1165),
    (115, 1166, 1175),
    (116, 1176, 1185),
    (117, 1186, 1195),
]

# Future dynamic rule requested by Luca:
# volume 117 = chapters 1186-1195
# volume 118 = chapters 1196-1205
# volume 119 = chapters 1206-1215
# ...and so on, indefinitely.
FUTURE_VOLUME_BASE = 117
FUTURE_CHAPTER_BASE = 1186
FUTURE_CHAPTERS_PER_VOLUME = 10

DEFAULT_SERIES_ID = "op"
DEFAULT_SERIES_TITLE = "OP Reader"
DEFAULT_SERIES_DESCRIPTION = "Archivio ordinato per volume, capitolo e pagina."
DEFAULT_CONTENT_DIR = Path("public/content")

ONE_MAN_PUNCH_SERIES_ID = "opm"
ONE_MAN_PUNCH_SERIES_TITLE = "One Man Punch"
ONE_MAN_PUNCH_DESCRIPTION = "Archivio ordinato per volume, capitolo e pagina."
GENERIC_CHAPTERS_PER_VOLUME = 10


@dataclass(frozen=True)
class PageCandidate:
    url: str
    extension: str


@dataclass(frozen=True)
class UploadedPage:
    page: int
    key: str
    src: str
    width: int
    height: int
    bytes: int


@dataclass(frozen=True)
class EncodedPage:
    body: bytes
    width: int
    height: int
    extension: str
    content_type: str
    strategy: str
    original_bytes: int
    encoded_bytes: int


@dataclass(frozen=True)
class ChapterImportResult:
    chapter: int
    volume: int
    imported: bool
    skipped: bool
    pages: list[UploadedPage]
    reason: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "reader"


def pad_volume(volume: int) -> str:
    return f"{volume:03d}" if volume < 100 else str(volume)


def pad_chapter(chapter: int) -> str:
    return f"{chapter:04d}"


def pad_source_chapter(chapter: int) -> str:
    return f"{chapter:03d}" if chapter < 100 else str(chapter)


def pad_page(page: int) -> str:
    return f"{page:02d}"


def future_volume_for_chapter(chapter: int) -> int:
    if chapter < FUTURE_CHAPTER_BASE:
        raise ValueError(f"Chapter {chapter} is before the future mapping base")
    return FUTURE_VOLUME_BASE + ((chapter - FUTURE_CHAPTER_BASE) // FUTURE_CHAPTERS_PER_VOLUME)


def future_chapter_range_for_volume(volume: int) -> tuple[int, int]:
    if volume < FUTURE_VOLUME_BASE:
        raise ValueError(f"Volume {volume} is before the future mapping base")
    start = FUTURE_CHAPTER_BASE + ((volume - FUTURE_VOLUME_BASE) * FUTURE_CHAPTERS_PER_VOLUME)
    return start, start + FUTURE_CHAPTERS_PER_VOLUME - 1


def generic_volume_for_chapter(chapter: int, chapters_per_volume: int = GENERIC_CHAPTERS_PER_VOLUME) -> int:
    if chapter < 1:
        raise ValueError(f"Chapter must be >= 1, got {chapter}")
    return ((chapter - 1) // chapters_per_volume) + 1


def generic_chapter_range_for_volume(volume: int, chapters_per_volume: int = GENERIC_CHAPTERS_PER_VOLUME) -> tuple[int, int]:
    if volume < 1:
        raise ValueError(f"Volume must be >= 1, got {volume}")
    start = ((volume - 1) * chapters_per_volume) + 1
    return start, start + chapters_per_volume - 1


def uses_generic_volume_mapping(series_id: str) -> bool:
    return slugify(series_id) not in {DEFAULT_SERIES_ID}


def find_volume_for_chapter(chapter: int, series_id: str = DEFAULT_SERIES_ID) -> int:
    if uses_generic_volume_mapping(series_id):
        return generic_volume_for_chapter(chapter)
    for volume, start, end in VOLUME_CHAPTER_RANGES:
        if start <= chapter <= end:
            return volume
    if chapter >= FUTURE_CHAPTER_BASE:
        return future_volume_for_chapter(chapter)
    raise ValueError(f"No volume mapping for chapter {chapter}")


def chapter_range_for_volume(volume: int, series_id: str = DEFAULT_SERIES_ID) -> tuple[int, int]:
    if uses_generic_volume_mapping(series_id):
        return generic_chapter_range_for_volume(volume)
    for current_volume, start, end in VOLUME_CHAPTER_RANGES:
        if current_volume == volume:
            return start, end
    if volume >= FUTURE_VOLUME_BASE:
        return future_chapter_range_for_volume(volume)
    raise ValueError(f"No chapter mapping for volume {volume}")


def iter_chapters_from_args(
    chapter: int | None,
    volume: int | None,
    from_chapter: int | None,
    to_chapter: int | None,
    series_id: str = DEFAULT_SERIES_ID,
) -> list[int]:
    if chapter is not None:
        return [chapter]
    if volume is not None:
        start, end = chapter_range_for_volume(volume, series_id)
        return list(range(start, end + 1))
    if from_chapter is not None and to_chapter is not None:
        if from_chapter > to_chapter:
            raise ValueError("from_chapter cannot be greater than to_chapter")
        return list(range(from_chapter, to_chapter + 1))
    raise ValueError("Specify chapter, volume, or from/to chapter range")


def build_source_url(base_url: str, volume: int, chapter: int, page: int, extension: str, template: str | None = None) -> str:
    base = base_url.rstrip("/") + "/"
    values = {
        "base_url": base.rstrip("/"),
        "volume": volume,
        "volume_padded": pad_volume(volume),
        "chapter": chapter,
        "chapter_padded": pad_source_chapter(chapter),
        "chapter_4": pad_chapter(chapter),
        "page": page,
        "page_padded": pad_page(page),
        "page_3": f"{page:03d}",
        "extension": extension.lstrip("."),
    }
    if template:
        return template.format(**values)
    return urljoin(base, f"volumi/volume{pad_volume(volume)}/{pad_source_chapter(chapter)}/{pad_page(page)}.{extension.lstrip('.')}")


def r2_key_for_page(series_id: str, volume: int, chapter: int, page: int, extension: str = "webp") -> str:
    clean_extension = extension.lower().lstrip(".") or "webp"
    if clean_extension == "jpeg":
        clean_extension = "jpg"
    return f"{slugify(series_id)}/vol-{pad_volume(volume)}/chapter-{pad_chapter(chapter)}/page-{page:03d}.{clean_extension}"


def public_url_for_key(public_base_url: str, key: str) -> str:
    return public_base_url.rstrip("/") + "/" + key.lstrip("/")


def looks_like_image(content_type: str) -> bool:
    return content_type.lower().split(";")[0].strip().startswith("image/")


def guess_extension_from_content_type(content_type: str, fallback: str) -> str:
    clean = content_type.lower().split(";")[0].strip()
    guessed = mimetypes.guess_extension(clean) if clean else None
    if guessed == ".jpe":
        guessed = ".jpg"
    return (guessed or f".{fallback.lstrip('.')}").lstrip(".")


def make_session(user_agent: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent or "OPReaderLegalImporter/2.0 (+authorized-import)",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    })
    return session


def fetch_image_bytes(session: requests.Session, url: str, timeout: float) -> tuple[bytes | None, str, int | None, str]:
    try:
        with session.get(url, timeout=timeout, allow_redirects=True, stream=True) as response:
            content_type = response.headers.get("Content-Type", "")
            status_code = response.status_code
            if status_code == 404:
                return None, content_type, status_code, "missing"
            if status_code in (401, 403, 429):
                return None, content_type, status_code, "blocked"
            if not (200 <= status_code < 300):
                return None, content_type, status_code, "error"
            if content_type and not looks_like_image(content_type) and "octet-stream" not in content_type.lower():
                return None, content_type, status_code, "not_image"
            data = response.content
            if not data:
                return None, content_type, status_code, "empty"
            return data, content_type, status_code, "ok"
    except requests.RequestException as exc:
        return None, "", None, exc.__class__.__name__


def _normalized_source_extension(content_type: str, fallback: str) -> str:
    extension = guess_extension_from_content_type(content_type, fallback).lower().lstrip(".")
    if extension in {"jpe", "jpeg"}:
        return "jpg"
    if extension not in {"jpg", "png", "gif", "webp", "avif"}:
        # The importer is expected to ingest jpg/jpeg sources, but keep this conservative.
        return fallback.lower().lstrip(".") or "jpg"
    return extension


def encode_page_asset(
    image_bytes: bytes,
    *,
    quality: int = 82,
    strategy: str = "best-size",
    source_extension: str = "jpg",
    content_type: str = "",
) -> EncodedPage:
    """Return the asset to upload.

    strategy=best-size converts to WebP, compares the final byte size, and keeps
    the original JPG/JPEG when it is smaller than the WebP version. This avoids
    making already-compressed scans heavier.
    """
    strategy = (strategy or "best-size").lower().strip()
    if strategy not in {"best-size", "webp", "original"}:
        raise ValueError("image strategy must be one of: best-size, webp, original")

    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image)
        width, height = image.size

        if strategy == "original":
            extension = _normalized_source_extension(content_type, source_extension)
            return EncodedPage(
                body=image_bytes,
                width=width,
                height=height,
                extension=extension,
                content_type=mimetypes.types_map.get(f".{extension}", content_type or "application/octet-stream"),
                strategy="original",
                original_bytes=len(image_bytes),
                encoded_bytes=len(image_bytes),
            )

        output_image = image
        if output_image.mode not in ("RGB", "RGBA"):
            output_image = output_image.convert("RGB")
        output = io.BytesIO()
        output_image.save(output, format="WEBP", quality=quality, method=6)
        webp_bytes = output.getvalue()

    if strategy == "webp" or len(webp_bytes) < len(image_bytes):
        return EncodedPage(
            body=webp_bytes,
            width=width,
            height=height,
            extension="webp",
            content_type="image/webp",
            strategy="webp",
            original_bytes=len(image_bytes),
            encoded_bytes=len(webp_bytes),
        )

    extension = _normalized_source_extension(content_type, source_extension)
    return EncodedPage(
        body=image_bytes,
        width=width,
        height=height,
        extension=extension,
        content_type=mimetypes.types_map.get(f".{extension}", content_type or "application/octet-stream"),
        strategy="original-smaller",
        original_bytes=len(image_bytes),
        encoded_bytes=len(image_bytes),
    )


def build_r2_client(account_id: str, access_key_id: str, secret_access_key: str):
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def r2_object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def upload_asset_to_r2(
    client,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    cache_control: str = "public, max-age=31536000, immutable",
) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl=cache_control,
    )


def read_json(path: Path, fallback: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return fallback


def write_json_if_changed(path: Path, data: dict) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == payload:
        return False
    path.write_text(payload, encoding="utf-8")
    return True


def volume_manifest_path(content_dir: Path, series_id: str, volume: int) -> Path:
    normalized_id = slugify(series_id)
    legacy_path = content_dir / "volumes" / f"{pad_volume(volume)}.json"
    if normalized_id == DEFAULT_SERIES_ID:
        return legacy_path
    return content_dir / "series" / normalized_id / "volumes" / f"{pad_volume(volume)}.json"


def volume_manifests_glob(content_dir: Path, series_id: str) -> list[Path]:
    normalized_id = slugify(series_id)
    if normalized_id == DEFAULT_SERIES_ID:
        return sorted((content_dir / "volumes").glob("*.json"))
    return sorted((content_dir / "series" / normalized_id / "volumes").glob("*.json"))


def index_manifest_path(content_dir: Path) -> Path:
    return content_dir / "index.json"


def legacy_manifest_path(content_dir: Path) -> Path:
    return content_dir / "manifest.json"


def load_index(content_dir: Path, series_id: str, series_title: str, series_description: str) -> dict:
    path = index_manifest_path(content_dir)
    data = read_json(path, {
        "schemaVersion": 2,
        "generatedAt": None,
        "series": [],
    })
    data.setdefault("schemaVersion", 2)
    data.setdefault("series", [])
    normalized_id = slugify(series_id)
    series = next((item for item in data["series"] if item.get("id") == normalized_id), None)
    if not series:
        series = {
            "id": normalized_id,
            "title": series_title,
            "description": series_description,
            "cover": "",
            "latestChapter": 0,
            "chaptersCount": 0,
            "volumes": [],
        }
        data["series"].append(series)
    else:
        series["title"] = series_title or series.get("title", normalized_id)
        series["description"] = series_description or series.get("description", "")
        series.setdefault("volumes", [])
        series.setdefault("latestChapter", 0)
        series.setdefault("chaptersCount", 0)
    return data


def load_volume_manifest(content_dir: Path, series_id: str, volume: int) -> dict:
    start, end = chapter_range_for_volume(volume, series_id)
    return read_json(volume_manifest_path(content_dir, series_id, volume), {
        "schemaVersion": 2,
        "generatedAt": None,
        "seriesId": slugify(series_id),
        "volume": volume,
        "fromChapter": start,
        "toChapter": end,
        "chapters": [],
    })


def chapter_payload(series_title: str, chapter: int, volume: int, pages: Sequence[UploadedPage]) -> dict:
    return {
        "id": f"chapter-{chapter}",
        "number": chapter,
        "volume": volume,
        "title": f"Volume {volume} · Capitolo {chapter}",
        "publishedAt": today_iso(),
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


def upsert_chapter_in_volume(
    content_dir: Path,
    series_id: str,
    series_title: str,
    chapter: int,
    volume: int,
    pages: Sequence[UploadedPage],
) -> None:
    manifest = load_volume_manifest(content_dir, series_id, volume)
    manifest["schemaVersion"] = 2
    manifest["generatedAt"] = now_iso()
    manifest["seriesId"] = slugify(series_id)
    manifest["volume"] = volume
    manifest["fromChapter"], manifest["toChapter"] = chapter_range_for_volume(volume, series_id)
    manifest.setdefault("chapters", [])

    payload = chapter_payload(series_title, chapter, volume, pages)
    idx = next((i for i, item in enumerate(manifest["chapters"]) if int(item.get("number", -1)) == chapter), None)
    if idx is None:
        manifest["chapters"].append(payload)
    else:
        manifest["chapters"][idx] = payload

    manifest["chapters"].sort(key=lambda item: int(item.get("number", 0)))
    write_json_if_changed(volume_manifest_path(content_dir, series_id, volume), manifest)


def rebuild_index_from_volumes(
    content_dir: Path,
    series_id: str = DEFAULT_SERIES_ID,
    series_title: str = DEFAULT_SERIES_TITLE,
    series_description: str = DEFAULT_SERIES_DESCRIPTION,
) -> dict:
    index = load_index(content_dir, series_id, series_title, series_description)
    normalized_id = slugify(series_id)
    series = next(item for item in index["series"] if item.get("id") == normalized_id)

    volume_entries = []
    all_chapters = []
    for path in volume_manifests_glob(content_dir, series_id):
        data = read_json(path, {})
        if data.get("seriesId") != normalized_id:
            continue
        chapters = sorted(data.get("chapters", []), key=lambda item: int(item.get("number", 0)))
        if not chapters:
            continue
        volume = int(data.get("volume"))
        start, end = chapter_range_for_volume(volume, series_id)
        volume_entries.append({
            "volume": volume,
            "fromChapter": start,
            "toChapter": end,
            "chaptersCount": len(chapters),
            "manifest": (f"/content/volumes/{pad_volume(volume)}.json" if normalized_id == DEFAULT_SERIES_ID else f"/content/series/{normalized_id}/volumes/{pad_volume(volume)}.json"),
        })
        all_chapters.extend(chapters)

    all_chapters.sort(key=lambda item: int(item.get("number", 0)))
    volume_entries.sort(key=lambda item: int(item["volume"]))

    series["title"] = series_title
    series["description"] = series_description
    series["volumes"] = volume_entries
    series["chaptersCount"] = len(all_chapters)
    series["latestChapter"] = int(all_chapters[-1]["number"]) if all_chapters else 0
    if all_chapters and all_chapters[0].get("pages"):
        series["cover"] = all_chapters[0]["pages"][0].get("src", "")
    series.pop("chapters", None)
    index["generatedAt"] = now_iso()
    write_json_if_changed(index_manifest_path(content_dir), index)
    return index


def write_legacy_combined_manifest(content_dir: Path, index: dict) -> None:
    """Optional compatibility file for older code/tools. It contains no local images."""
    combined = json.loads(json.dumps(index))
    for series in combined.get("series", []):
        chapters = []
        for volume_entry in series.get("volumes", []):
            manifest_file = content_dir / volume_entry["manifest"].lstrip("/").replace("content/", "", 1)
            if not manifest_file.exists():
                continue
            data = read_json(manifest_file, {})
            chapters.extend(data.get("chapters", []))
        chapters.sort(key=lambda item: int(item.get("number", 0)))
        series["chapters"] = chapters
    write_json_if_changed(legacy_manifest_path(content_dir), combined)


def latest_chapter_from_index(content_dir: Path, series_id: str = DEFAULT_SERIES_ID) -> int:
    data = read_json(index_manifest_path(content_dir), {"series": []})
    normalized_id = slugify(series_id)
    series = next((item for item in data.get("series", []) if item.get("id") == normalized_id), None)
    if not series:
        return 0
    return int(series.get("latestChapter") or 0)


def get_manifest_chapter(content_dir: Path, series_id: str, chapter: int) -> dict | None:
    try:
        volume = find_volume_for_chapter(chapter, series_id)
    except ValueError:
        return None
    data = load_volume_manifest(content_dir, series_id, volume)
    normalized_id = slugify(series_id)
    if data.get("seriesId") != normalized_id:
        return None
    return next((item for item in data.get("chapters", []) if int(item.get("number", -1)) == chapter), None)


def manifest_has_chapter(content_dir: Path, series_id: str, chapter: int) -> bool:
    return get_manifest_chapter(content_dir, series_id, chapter) is not None


def import_single_chapter_to_r2(
    *,
    session: requests.Session,
    r2_client,
    bucket: str,
    public_base_url: str,
    source_base_url: str,
    source_template: str | None,
    source_extensions: Sequence[str],
    content_dir: Path,
    series_id: str,
    series_title: str,
    series_description: str,
    chapter: int,
    volume_override: int | None,
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
    volume = volume_override if volume_override is not None else find_volume_for_chapter(chapter, series_id)
    existing_chapter = get_manifest_chapter(content_dir, series_id, chapter)
    if not overwrite and existing_chapter:
        existing_pages = existing_chapter.get("pages", [])
        existing_keys = [page.get("key") for page in existing_pages if page.get("key")]
        if existing_keys and all(r2_object_exists(r2_client, bucket, key) for key in existing_keys):
            return ChapterImportResult(chapter, volume, imported=False, skipped=True, pages=[], reason="chapter already present in manifest and R2")
        print("  manifest entry exists, but one or more R2 objects are missing. Re-importing chapter.")

    found_pages: list[UploadedPage] = []
    consecutive_missing = 0

    for page in range(1, max_pages + 1):
        page_statuses = []
        image_bytes = None
        used_url = ""
        used_content_type = ""
        used_extension = ""

        for extension in source_extensions:
            candidate_url = build_source_url(source_base_url, volume, chapter, page, extension, source_template)
            data, content_type, http_status, status = fetch_image_bytes(session, candidate_url, timeout)
            page_statuses.append(f"{extension}:{status}:{http_status or '-'}")
            if status == "ok" and data:
                image_bytes = data
                used_url = candidate_url
                used_content_type = content_type
                used_extension = extension
                break

        if not image_bytes:
            if any(":missing:" in status or status.endswith(":missing:-") for status in page_statuses):
                consecutive_missing += 1
            else:
                # Treat blocked/errors as non-missing so a transient issue does not prematurely stop after one page.
                consecutive_missing = 0
            print(f"  page {page:03d}: not found ({', '.join(page_statuses)})")
            if stop_after_missing > 0 and consecutive_missing >= stop_after_missing:
                break
            if delay > 0:
                time.sleep(delay)
            continue

        consecutive_missing = 0
        try:
            encoded = encode_page_asset(
                image_bytes,
                quality=webp_quality,
                strategy=image_strategy,
                source_extension=used_extension,
                content_type=used_content_type,
            )
        except UnidentifiedImageError:
            print(f"  page {page:03d}: downloaded but not a readable image ({used_url})")
            if delay > 0:
                time.sleep(delay)
            continue

        key = r2_key_for_page(series_id, volume, chapter, page, encoded.extension)
        src = public_url_for_key(public_base_url, key)

        if not dry_run:
            if overwrite or not r2_object_exists(r2_client, bucket, key):
                upload_asset_to_r2(r2_client, bucket, key, encoded.body, encoded.content_type)
                action = "uploaded"
            else:
                action = "already on R2"
        else:
            action = "dry-run"

        size_note = f"{encoded.encoded_bytes} bytes"
        if encoded.strategy in {"webp", "original-smaller"}:
            size_note += f", original={encoded.original_bytes} bytes, strategy={encoded.strategy}"
        else:
            size_note += f", strategy={encoded.strategy}"
        print(f"  page {page:03d}: {action} {key} ({encoded.width}x{encoded.height}, {size_note}, source={used_extension}/{used_content_type or 'unknown'})")
        found_pages.append(UploadedPage(page=page, key=key, src=src, width=encoded.width, height=encoded.height, bytes=encoded.encoded_bytes))

        if delay > 0:
            time.sleep(delay)

    if len(found_pages) < min_pages:
        return ChapterImportResult(
            chapter=chapter,
            volume=volume,
            imported=False,
            skipped=False,
            pages=found_pages,
            reason=f"only {len(found_pages)} page(s), minimum is {min_pages}",
        )

    if not dry_run:
        upsert_chapter_in_volume(content_dir, series_id, series_title, chapter, volume, found_pages)
        index = rebuild_index_from_volumes(content_dir, series_id, series_title, series_description)
        write_legacy_combined_manifest(content_dir, index)

    return ChapterImportResult(chapter=chapter, volume=volume, imported=True, skipped=False, pages=found_pages)


def parse_extensions(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        items = [item.strip().lstrip(".") for item in value.split(",")]
    else:
        items = [str(item).strip().lstrip(".") for item in value]
    return [item for item in items if item]


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def validate_confirmation(confirm: bool) -> None:
    if not confirm:
        raise RuntimeError("Import requires --i-confirm-rights / I_CONFIRM_RIGHTS=true")
