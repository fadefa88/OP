#!/usr/bin/env python3
"""
image_audit_dryrun.py

Dry-run/audit script:
- Builds image URLs using volume/chapter/page logic.
- Checks whether images appear to exist.
- Does NOT download or save images.
- Copyright/licensing must be verified manually by the user before any real use.

Example URL generated:
https://onepiecepower.com/manga8/onepiece/volumi/volume116/1176/01.jpg
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import requests


# Current volume -> chapter ranges.
# Extend this list when future official volume/chapter mappings are known.
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
    status: str  # found | missing | blocked | error | not_image
    http_status: Optional[int]
    content_type: str
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

        # Some static servers misconfigure Content-Type.
        # Treat it as found only if the server did not obviously return HTML/text.
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

            # HEAD can lie or omit Content-Type. If it says found without type, confirm lightly.
            if status != "found" or looks_like_image(content_type):
                return status, head.status_code, content_type, "HEAD"

        # Fallback: ask for a single byte and close the stream immediately.
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


def audit_chapter(
    session: requests.Session,
    base_url: str,
    chapter: int,
    max_pages: int,
    extension: str,
    timeout: float,
    delay: float,
    stop_after_missing: int,
) -> list[CheckResult]:
    volume = find_volume_for_chapter(chapter)
    results: list[CheckResult] = []
    consecutive_missing = 0

    for page in range(1, max_pages + 1):
        url = build_image_url(base_url, volume, chapter, page, extension)
        status, http_status, content_type, note = check_image_exists(session, url, timeout)

        result = CheckResult(
            chapter=chapter,
            volume=volume,
            page=page,
            url=url,
            status=status,
            http_status=http_status,
            content_type=content_type,
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
    missing = sum(1 for r in results if r.status == "missing")
    blocked = sum(1 for r in results if r.status == "blocked")
    errors = sum(1 for r in results if r.status == "error")
    not_image = sum(1 for r in results if r.status == "not_image")

    print(
        f"Volume {volume} / Chapter {chapter}: "
        f"{found} image(s) would be downloadable, "
        f"{missing} missing, "
        f"{blocked} blocked, "
        f"{errors} error(s), "
        f"{not_image} non-image response(s)."
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
                    "note": result.note,
                }
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit image URLs by volume/chapter/page. "
            "Dry-run only: it does not download or save images."
        )
    )

    parser.add_argument(
        "--base-url",
        required=True,
        help="Base domain, e.g. https://onepiecepower.com/manga8/onepiece",
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--chapter", type=int, help="Single chapter to audit, e.g. 1176")
    target.add_argument("--volume", type=int, help="Whole volume to audit, e.g. 116")
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

    parser.add_argument(
        "--max-pages",
        type=int,
        default=40,
        help="Maximum pages/images to check per chapter. Default: 40",
    )
    parser.add_argument(
        "--extension",
        default="jpg",
        help="Image extension. Default: jpg",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="HTTP timeout in seconds. Default: 8",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay between requests in seconds. Default: 0.25",
    )
    parser.add_argument(
        "--stop-after-missing",
        type=int,
        default=3,
        help=(
            "Stop a chapter after this many consecutive missing pages. "
            "Use 0 to always check all pages up to --max-pages. Default: 3"
        ),
    )
    parser.add_argument(
        "--csv",
        default="reports/audit.csv",
        help="CSV report path. Default: reports/audit.csv",
    )
    parser.add_argument(
        "--show-urls",
        action="store_true",
        help="Print every checked URL and status.",
    )

    args = parser.parse_args(argv)

    if args.from_chapter is not None and args.to_chapter is None:
        parser.error("--from-chapter requires --to-chapter")

    if args.to_chapter is not None and args.from_chapter is None:
        parser.error("--to-chapter requires --from-chapter")

    if args.max_pages < 1:
        parser.error("--max-pages must be >= 1")

    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "ImageAuditDryRun/1.0 "
                "(dry-run; no downloads; licensing must be verified manually)"
            )
        }
    )

    all_results: list[CheckResult] = []

    try:
        chapters = list(iter_chapters(args))

        for chapter in chapters:
            results = audit_chapter(
                session=session,
                base_url=args.base_url,
                chapter=chapter,
                max_pages=args.max_pages,
                extension=args.extension,
                timeout=args.timeout,
                delay=args.delay,
                stop_after_missing=args.stop_after_missing,
            )
            all_results.extend(results)
            print_chapter_summary(chapter, results)

            if args.show_urls:
                for result in results:
                    http = result.http_status if result.http_status is not None else "-"
                    print(f"  {result.status:9} HTTP {http:>3} page {result.page:02d} {result.url}")

        output_path = Path(args.csv)
        write_csv(output_path, all_results)
        print(f"\nCSV report written to: {output_path}")

        total_found = sum(1 for r in all_results if r.status == "found")
        print(f"Total image(s) that would be downloadable: {total_found}")
        print("No image file was downloaded or saved.")

        return 0

    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
