#!/usr/bin/env python3
"""
download_manga.py

Audits or imports manga/comic page images into the Cloudflare manga reader.

Default mode is audit-only. Real downloads require both:
  1. --download
  2. --i-confirm-rights

Use the download mode only with images you own, have licensed, that are public
domain, or that you are otherwise legally allowed to copy and host.

The GitHub workflow in this repo is intentionally limited to volumes 115 and 116
for the initial production test. The full-catalog import block is left commented
inside the workflow.
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests


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
]


@dataclass(frozen=True)
class CheckResult:
    chapter: int
    volume: int
    page: int
    url: str
    status: str  # found | downloaded | missing | blocked | error | not_image | skipped
    http_status: Optional[int]
    content_type: str
    file_path: str = ""
    note: str = ""


def pad_volume(volume: int) -> str:
    """Volumes lower than 100 are formatted as 001, 002, ..., 099."""
    return f"{volume:03d}" if volume < 100 else str(volume)


def pad_chapter(chapter: int) -> str:
    """Chapters lower than 100 are formatted as 001, 002, ..., 099."""
    return f"{chapter:03d}" if chapter < 100 else str(chapter)


def pad_page(page: int) -> str:
    """Image pages are formatted as 01, 02, ..., 40."""
    return f"{page:02d}"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "manga"


def find_volume_for_chapter(chapter: int) -> int:
    for volume, start_chapter, end_chapter in VOLUME_CHAPTER_RANGES:
        if start_chapter <= chapter <= end_chapter:
            return volume
    raise ValueError(
        f"Chapter {chapter} is not present in VOLUME_CHAPTER_RANGES. "
        "Extend the mapping or pass a known chapter."
    )


def chapter_range_for_volume(volume: int) -> tuple[int, int]:
    for vol, start_chapter, end_chapter in VOLUME_CHAPTER_RANGES:
        if vol == volume:
            return start_chapter, end_chapter
    raise ValueError(
        f"Volume {volume} is not present in VOLUME_CHAPTER_RANGES. "
        "Extend the mapping first."
    )


def build_image_url(base_url: str, volume: int, chapter: int, page: int, extension: str) -> str:
    base = base_url.rstrip("/")
    return (
        f"{base}/volumi/"
        f"volume{pad_volume(volume)}/"
        f"{pad_chapter(chapter)}/"
        f"{pad_page(page)}.{extension.lstrip('.')}"
    )


def looks_like_image(content_type: str) -> bool:
    return content_type.lower().split(";")[0].strip().startswith("image/")


def extension_for_response(content_type: str, fallback: str) -> str:
    clean = content_type.lower().split(";")[0].strip()
    guessed = mimetypes.guess_extension(clean) if clean else None
    if guessed == ".jpe":
        guessed = ".jpg"
    return (guessed or f".{fallback.lstrip('.')}").lower()


def classify_response(response: requests.Response) -> tuple[str, str]:
    content_type = response.headers.get("Content-Type", "")
    status_code = response.status_code

    if status_code in (401, 403, 429):
        return "blocked", content_type

    if status_code == 404:
        return "missing", content_type

    if 200 <= status_code < 300:
        if looks_like_image(content_type):
            return "found", content_type

        lower_type = content_type.lower()
        if not lower_type or ("html" not in lower_type and "text/" not in lower_type):
            return "found", content_type

        return "not_image", content_type

    if 300 <= status_code < 400:
        return "blocked", content_type

    return "error", content_type


def check_image_exists(
    session: requests.Session,
    url: str,
    timeout: float,
) -> tuple[str, Optional[int], str, str]:
    """
    Check an image URL without saving content.

    Strategy:
    1. HEAD request.
    2. If HEAD is unsupported or inconclusive, GET with Range: bytes=0-0.
    """
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }

    try:
        head = session.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if head.status_code not in (405, 501):
            status, content_type = classify_response(head)
            if status != "found" or looks_like_image(content_type):
                return status, head.status_code, content_type, "HEAD"

        get_headers = {**headers, "Range": "bytes=0-0"}
        with session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers=get_headers,
            stream=True,
        ) as get:
            status, content_type = classify_response(get)
            return status, get.status_code, content_type, "GET Range"

    except requests.RequestException as exc:
        return "error", None, "", exc.__class__.__name__


def download_image(
    session: requests.Session,
    url: str,
    output_path_without_ext: Path,
    extension: str,
    timeout: float,
    overwrite: bool,
) -> tuple[str, Optional[int], str, str, Path | None]:
    """Download one image to a temporary file, validate response, then move atomically."""
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }

    try:
        with session.get(url, timeout=timeout, allow_redirects=True, headers=headers, stream=True) as response:
            status, content_type = classify_response(response)
            if status != "found":
                return status, response.status_code, content_type, "GET", None

            final_ext = extension_for_response(content_type, extension)
            final_path = output_path_without_ext.with_suffix(final_ext)

            if final_path.exists() and not overwrite:
                return "skipped", response.status_code, content_type, "already exists", final_path

            final_path.parent.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(delete=False, dir=str(final_path.parent), suffix=".tmp") as tmp:
                tmp_path = Path(tmp.name)
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        tmp.write(chunk)

            if tmp_path.stat().st_size == 0:
                tmp_path.unlink(missing_ok=True)
                return "error", response.status_code, content_type, "empty file", None

            os.replace(tmp_path, final_path)
            return "downloaded", response.status_code, content_type, "GET", final_path

    except requests.RequestException as exc:
        return "error", None, "", exc.__class__.__name__, None


def iter_chapters(args: argparse.Namespace) -> Iterable[int]:
    if args.chapter is not None:
        yield args.chapter
        return

    if args.volume is not None:
        start_chapter, end_chapter = chapter_range_for_volume(args.volume)
        yield from range(start_chapter, end_chapter + 1)
        return

    if args.from_chapter is not None and args.to_chapter is not None:
        if args.from_chapter > args.to_chapter:
            raise ValueError("--from-chapter cannot be greater than --to-chapter")
        yield from range(args.from_chapter, args.to_chapter + 1)
        return

    raise ValueError("Specify one of: --chapter, --volume, or --from-chapter + --to-chapter")


def target_page_base_path(output_dir: Path, series_id: str, chapter: int, page: int) -> Path:
    chapter_id = f"chapter-{pad_chapter(chapter)}"
    return output_dir / slugify(series_id) / chapter_id / f"page-{page:03d}"


def process_chapter(
    session: requests.Session,
    base_url: str,
    chapter: int,
    max_pages: int,
    extension: str,
    timeout: float,
    delay: float,
    stop_after_missing: int,
    download: bool,
    output_dir: Path,
    series_id: str,
    overwrite: bool,
) -> list[CheckResult]:
    volume = find_volume_for_chapter(chapter)
    results: list[CheckResult] = []
    consecutive_missing = 0

    for page in range(1, max_pages + 1):
        url = build_image_url(base_url, volume, chapter, page, extension)

        if download:
            path_base = target_page_base_path(output_dir, series_id, chapter, page)
            status, http_status, content_type, note, saved_path = download_image(
                session=session,
                url=url,
                output_path_without_ext=path_base,
                extension=extension,
                timeout=timeout,
                overwrite=overwrite,
            )
        else:
            status, http_status, content_type, note = check_image_exists(session, url, timeout)
            saved_path = None

        result = CheckResult(
            chapter=chapter,
            volume=volume,
            page=page,
            url=url,
            status=status,
            http_status=http_status,
            content_type=content_type,
            file_path=str(saved_path) if saved_path else "",
            note=note,
        )
        results.append(result)

        if status == "missing":
            consecutive_missing += 1
        else:
            consecutive_missing = 0

        if stop_after_missing > 0 and consecutive_missing >= stop_after_missing:
            break

        if delay > 0:
            time.sleep(delay)

    return results


def print_chapter_summary(chapter: int, results: list[CheckResult]) -> None:
    if not results:
        print(f"Chapter {chapter}: no checks performed")
        return

    volume = results[0].volume
    found = sum(1 for r in results if r.status == "found")
    downloaded = sum(1 for r in results if r.status == "downloaded")
    skipped = sum(1 for r in results if r.status == "skipped")
    missing = sum(1 for r in results if r.status == "missing")
    blocked = sum(1 for r in results if r.status == "blocked")
    errors = sum(1 for r in results if r.status == "error")
    not_image = sum(1 for r in results if r.status == "not_image")

    if downloaded or skipped:
        print(
            f"Volume {volume} / Chapter {chapter}: "
            f"{downloaded} downloaded, {skipped} already present, "
            f"{missing} missing, {blocked} blocked, {errors} errors, {not_image} non-image."
        )
    else:
        print(
            f"Volume {volume} / Chapter {chapter}: "
            f"{found} image(s) would be downloadable, "
            f"{missing} missing, {blocked} blocked, {errors} errors, {not_image} non-image."
        )


def write_csv(path: Path, all_results: list[CheckResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "chapter",
                "volume",
                "page",
                "url",
                "status",
                "http_status",
                "content_type",
                "file_path",
                "note",
            ],
        )
        writer.writeheader()

        for result in all_results:
            writer.writerow(
                {
                    "chapter": result.chapter,
                    "volume": result.volume,
                    "page": result.page,
                    "url": result.url,
                    "status": result.status,
                    "http_status": result.http_status or "",
                    "content_type": result.content_type,
                    "file_path": result.file_path,
                    "note": result.note,
                }
            )


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schemaVersion": 1, "generatedAt": None, "series": []}


def public_url_for_file(path: Path, public_dir: Path) -> str:
    relative = path.resolve().relative_to(public_dir.resolve())
    return "/" + relative.as_posix()


def update_manifest(
    manifest_path: Path,
    public_dir: Path,
    series_id: str,
    series_title: str,
    series_description: str,
    all_results: list[CheckResult],
) -> None:
    downloaded_by_chapter: dict[int, list[CheckResult]] = {}
    for result in all_results:
        if result.status in ("downloaded", "skipped") and result.file_path:
            downloaded_by_chapter.setdefault(result.chapter, []).append(result)

    if not downloaded_by_chapter:
        print("No downloaded/skipped images found, manifest unchanged.")
        return

    manifest = load_manifest(manifest_path)
    manifest.setdefault("schemaVersion", 1)
    manifest.setdefault("series", [])
    manifest["generatedAt"] = datetime.now(timezone.utc).isoformat()

    normalized_series_id = slugify(series_id)
    series = next((item for item in manifest["series"] if item.get("id") == normalized_series_id), None)
    if not series:
        series = {
            "id": normalized_series_id,
            "title": series_title,
            "description": series_description,
            "cover": "",
            "chapters": [],
        }
        manifest["series"].insert(0, series)
    else:
        series["title"] = series_title or series.get("title", normalized_series_id)
        series["description"] = series_description or series.get("description", "")
        series.setdefault("chapters", [])

    for chapter, results in sorted(downloaded_by_chapter.items()):
        chapter_id = f"chapter-{pad_chapter(chapter)}"
        volume = find_volume_for_chapter(chapter)
        pages = []
        for result in sorted(results, key=lambda item: item.page):
            file_path = Path(result.file_path)
            pages.append({"src": public_url_for_file(file_path, public_dir)})

        if not pages:
            continue

        chapter_payload = {
            "id": chapter_id,
            "number": chapter,
            "volume": volume,
            "title": f"Volume {volume} · Capitolo {chapter}",
            "publishedAt": datetime.now(timezone.utc).date().isoformat(),
            "pages": pages,
        }

        existing_idx = next((idx for idx, item in enumerate(series["chapters"]) if item.get("id") == chapter_id), None)
        if existing_idx is None:
            series["chapters"].append(chapter_payload)
        else:
            series["chapters"][existing_idx] = chapter_payload

    series["chapters"].sort(key=lambda item: item.get("number", 0))
    if series["chapters"] and series["chapters"][0].get("pages"):
        series["cover"] = series["chapters"][0]["pages"][0]["src"]

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest updated: {manifest_path}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit or legally import image URLs by volume/chapter/page."
    )

    parser.add_argument(
        "--base-url",
        required=True,
        help="Authorized source base URL, e.g. https://example.com/manga/source",
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--chapter", type=int, help="Single chapter to process, e.g. 1176")
    target.add_argument("--volume", type=int, help="Whole volume to process, e.g. 116")
    target.add_argument(
        "--from-chapter",
        type=int,
        help="First chapter of a custom chapter range. Requires --to-chapter.",
    )

    parser.add_argument(
        "--to-chapter",
        type=int,
        help="Last chapter of a custom chapter range. Requires --from-chapter.",
    )

    parser.add_argument("--max-pages", type=int, default=40, help="Maximum pages/images per chapter. Default: 40")
    parser.add_argument("--extension", default="jpg", help="Image extension to try. Default: jpg")
    parser.add_argument("--timeout", type=float, default=12.0, help="HTTP timeout in seconds. Default: 12")
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between requests in seconds. Default: 0.35")
    parser.add_argument(
        "--stop-after-missing",
        type=int,
        default=3,
        help="Stop a chapter after this many consecutive missing pages. Use 0 to check all pages. Default: 3",
    )
    parser.add_argument("--csv", default="reports/import-report.csv", help="CSV report path.")
    parser.add_argument("--show-urls", action="store_true", help="Print every checked URL and status.")

    parser.add_argument("--download", action="store_true", help="Actually download images instead of audit-only mode.")
    parser.add_argument(
        "--i-confirm-rights",
        action="store_true",
        help="Required with --download. Confirms you have the legal right to copy and host these images.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite already downloaded files.")
    parser.add_argument("--public-dir", default="public", help="Public assets root. Default: public")
    parser.add_argument("--output-dir", default="public/manga", help="Downloaded manga image root. Default: public/manga")
    parser.add_argument("--manifest", default="public/content/manifest.json", help="Manifest JSON path.")
    parser.add_argument("--series-id", default="op", help="Series id used in manifest and paths. Default: op")
    parser.add_argument("--series-title", default="OP Reader", help="Series title shown in the site.")
    parser.add_argument(
        "--series-description",
        default="Capitoli importati da una sorgente autorizzata.",
        help="Series description shown in the site.",
    )

    args = parser.parse_args(argv)

    if args.from_chapter is not None and args.to_chapter is None:
        parser.error("--from-chapter requires --to-chapter")
    if args.to_chapter is not None and args.from_chapter is None:
        parser.error("--to-chapter requires --from-chapter")
    if args.max_pages < 1:
        parser.error("--max-pages must be >= 1")
    if args.download and not args.i_confirm_rights:
        parser.error("--download requires --i-confirm-rights")

    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "CloudflareMangaReaderImporter/1.0 "
                "(+legal-import; contact=repo-owner)"
            )
        }
    )

    all_results: list[CheckResult] = []

    try:
        chapters = list(iter_chapters(args))
        mode = "download" if args.download else "audit"
        print(f"Mode: {mode}")
        print(f"Chapters: {chapters[0]}-{chapters[-1]} ({len(chapters)})")

        for chapter in chapters:
            results = process_chapter(
                session=session,
                base_url=args.base_url,
                chapter=chapter,
                max_pages=args.max_pages,
                extension=args.extension,
                timeout=args.timeout,
                delay=args.delay,
                stop_after_missing=args.stop_after_missing,
                download=args.download,
                output_dir=Path(args.output_dir),
                series_id=args.series_id,
                overwrite=args.overwrite,
            )
            all_results.extend(results)
            print_chapter_summary(chapter, results)

            if args.show_urls:
                for result in results:
                    http = result.http_status if result.http_status is not None else "-"
                    suffix = f" -> {result.file_path}" if result.file_path else ""
                    print(f"  {result.status:10} HTTP {http!s:>3} page {result.page:02d} {result.url}{suffix}")

        output_path = Path(args.csv)
        write_csv(output_path, all_results)
        print(f"\nCSV report written to: {output_path}")

        total_found = sum(1 for r in all_results if r.status == "found")
        total_downloaded = sum(1 for r in all_results if r.status == "downloaded")
        total_skipped = sum(1 for r in all_results if r.status == "skipped")
        print(f"Total image(s) found in audit mode: {total_found}")
        print(f"Total image(s) downloaded: {total_downloaded}")
        print(f"Total existing image(s) skipped: {total_skipped}")

        if args.download:
            update_manifest(
                manifest_path=Path(args.manifest),
                public_dir=Path(args.public_dir),
                series_id=args.series_id,
                series_title=args.series_title,
                series_description=args.series_description,
                all_results=all_results,
            )
        else:
            print("No image file was downloaded or saved. Use --download --i-confirm-rights for legal imports.")

        return 0

    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
