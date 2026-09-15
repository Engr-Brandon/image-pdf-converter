#!/usr/bin/env python3
"""
image_to_pdf.py

Convert image file(s) — any common format (JPEG, PNG, BMP, GIF, TIFF, WEBP,
HEIC*, etc.) — into a single PDF document.

Uses Pillow, which writes PDFs natively, so no external system dependencies
are required.

*HEIC support requires the optional 'pillow-heif' package to be installed
and registered; see the --help text for details.

Examples
--------
Convert a single image to a PDF:
    python image_to_pdf.py photo.jpg

Combine several images into one multi-page PDF, in the order given:
    python image_to_pdf.py page1.png page2.png page3.png -o booklet.pdf

Convert every image in a folder (sorted by filename) into one PDF:
    python image_to_pdf.py ./scans -o scans.pdf

Fit each image to A4 pages instead of using each image's native size:
    python image_to_pdf.py ./scans -o scans.pdf --page-size a4

Put 2 images side by side on each page:
    python image_to_pdf.py *.jpg --per-page 2 -o combined.pdf

Put 4 images per page, 2x2 grid, on Letter-sized pages:
    python image_to_pdf.py ./photos --per-page 4 --page-size letter -o grid.pdf

Stack 2 images vertically (one above the other) instead of side by side:
    python image_to_pdf.py top.jpg bottom.jpg --per-page 2 --layout vertical -o stacked.pdf
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit(
        "Missing dependency 'Pillow'.\n"
        "Install it with:  pip install pillow"
    )

logger = logging.getLogger("image_to_pdf")

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff",
    ".webp", ".ppm", ".pgm", ".pbm", ".ico", ".heic", ".heif",
}

# Page sizes in points (1 point = 1/72 inch), portrait orientation.
PAGE_SIZES_PT = {
    "a4": (595, 842),
    "letter": (612, 792),
    "legal": (612, 1008),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def try_register_heif() -> None:
    """Best-effort registration of HEIC/HEIF support, if the package exists."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        logger.debug("HEIC/HEIF support registered via pillow-heif.")
    except ImportError:
        pass  # HEIC input will simply fail later with a clear error if attempted.


def iter_input_images(paths: list[Path]) -> list[Path]:
    """
    Resolve the input arguments (files and/or directories) into an ordered,
    de-duplicated list of image file paths.
    """
    resolved: list[Path] = []
    seen: set[Path] = set()

    for raw_path in paths:
        if not raw_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {raw_path}")

        if raw_path.is_dir():
            found = sorted(
                p for p in raw_path.iterdir()
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )
            if not found:
                raise FileNotFoundError(f"No supported images found in directory: {raw_path}")
            candidates = found
        else:
            if raw_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"Unsupported image format: {raw_path}")
            candidates = [raw_path]

        for p in candidates:
            resolved_p = p.resolve()
            if resolved_p not in seen:
                seen.add(resolved_p)
                resolved.append(p)

    return resolved


def load_and_flatten(image_path: Path) -> Image.Image:
    """
    Open an image, fix orientation via EXIF, and flatten any transparency
    onto a white background (PDF has no alpha channel). Does NOT resize.
    """
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)  # respect camera/scan rotation metadata

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    return img


def fit_into_box(img: Image.Image, box_w_px: int, box_h_px: int) -> Image.Image:
    """Resize an image to fit within a pixel box, preserving aspect ratio."""
    scale = min(box_w_px / img.width, box_h_px / img.height)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(new_size, Image.LANCZOS)


def pt_to_px(value_pt: float, dpi: int) -> int:
    return round(value_pt / 72 * dpi)


def fit_to_page(img: Image.Image, page_size_pt: tuple[int, int], dpi: int = 150) -> Image.Image:
    """
    Center a single image on a fixed page size, preserving aspect ratio,
    matching the page's orientation (portrait/landscape) to the image's own.
    """
    page_w_pt, page_h_pt = page_size_pt
    if img.width > img.height:  # landscape image -> landscape page
        page_w_pt, page_h_pt = page_h_pt, page_w_pt

    page_w_px, page_h_px = pt_to_px(page_w_pt, dpi), pt_to_px(page_h_pt, dpi)
    resized = fit_into_box(img, page_w_px, page_h_px)

    canvas = Image.new("RGB", (page_w_px, page_h_px), (255, 255, 255))
    offset = ((page_w_px - resized.width) // 2, (page_h_px - resized.height) // 2)
    canvas.paste(resized, offset)
    return canvas


def build_grid_page(
    images: list[Image.Image],
    page_size_pt: tuple[int, int],
    layout: str = "grid",
    dpi: int = 150,
    margin_pt: float = 18,
    gap_pt: float = 10,
) -> Image.Image:
    """
    Arrange multiple images as a grid of cells on one fixed-size page, each
    image centered and fit within its own cell (preserving aspect ratio).

    layout: "grid" (auto rows/cols, near-square), "horizontal" (one row),
    or "vertical" (one column).
    """
    n = len(images)
    if layout == "horizontal":
        cols, rows = n, 1
    elif layout == "vertical":
        cols, rows = 1, n
    else:  # "grid"
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)

    page_w_px, page_h_px = pt_to_px(page_size_pt[0], dpi), pt_to_px(page_size_pt[1], dpi)
    margin_px, gap_px = pt_to_px(margin_pt, dpi), pt_to_px(gap_pt, dpi)

    cell_w = (page_w_px - 2 * margin_px - (cols - 1) * gap_px) // cols
    cell_h = (page_h_px - 2 * margin_px - (rows - 1) * gap_px) // rows
    if cell_w < 1 or cell_h < 1:
        raise ValueError(
            f"Page size too small to fit {n} image(s) in a {cols}x{rows} "
            f"layout with the current margins."
        )

    canvas = Image.new("RGB", (page_w_px, page_h_px), (255, 255, 255))
    for idx, img in enumerate(images):
        row, col = divmod(idx, cols)
        resized = fit_into_box(img, cell_w, cell_h)
        cell_x = margin_px + col * (cell_w + gap_px)
        cell_y = margin_px + row * (cell_h + gap_px)
        offset_x = cell_x + (cell_w - resized.width) // 2
        offset_y = cell_y + (cell_h - resized.height) // 2
        canvas.paste(resized, (offset_x, offset_y))

    return canvas


def convert_images_to_pdf(
    image_paths: list[Path],
    output_path: Path,
    page_size: str | None = None,
    quality: int = 95,
    per_page: int = 1,
    layout: str = "grid",
    margin_pt: float = 18,
    gap_pt: float = 10,
) -> Path:
    """Convert an ordered list of image files into a single multi-page PDF."""
    if not image_paths:
        raise ValueError("No images to convert.")
    if per_page < 1:
        raise ValueError("per_page must be at least 1.")

    if per_page > 1 and page_size is None:
        page_size = "a4"
        logger.info("No --page-size given; defaulting to 'a4' (required for --per-page > 1).")

    page_size_pt = PAGE_SIZES_PT.get(page_size) if page_size else None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    loaded: list[Image.Image] = []
    pages: list[Image.Image] = []
    try:
        for path in image_paths:
            logger.info("Loading %s", path.name)
            try:
                loaded.append(load_and_flatten(path))
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Could not read image '{path}': {exc}") from exc

        if per_page == 1:
            pages = [
                fit_to_page(img, page_size_pt) if page_size_pt else img
                for img in loaded
            ]
        else:
            for i in range(0, len(loaded), per_page):
                chunk = loaded[i : i + per_page]
                pages.append(
                    build_grid_page(
                        chunk, page_size_pt, layout=layout,
                        margin_pt=margin_pt, gap_pt=gap_pt,
                    )
                )

        first, rest = pages[0], pages[1:]
        logger.info("Writing %d page(s) to %s", len(pages), output_path)
        first.save(
            output_path,
            "PDF",
            save_all=True,
            append_images=rest,
            resolution=150.0,
            quality=quality,
        )
    finally:
        for img in loaded:
            img.close()
        for img in pages:
            img.close()

    return output_path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert image file(s) into a single PDF document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples\n--------\n", 1)[-1],
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="+",
        help="One or more image files and/or directories of images. "
             "When multiple images are given, they are combined into one "
             "PDF in the order listed (directories are sorted by filename).",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: <first_input_name>.pdf in the "
             "current directory).",
    )
    parser.add_argument(
        "--page-size",
        choices=["a4", "letter", "legal"],
        default=None,
        help="Fit each image onto a fixed page size, centered with margins "
             "preserved for aspect ratio. Default: each page matches its "
             "source image's own pixel dimensions (no fitting/cropping).",
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=95,
        help="JPEG compression quality used internally for the PDF's image "
             "streams, 1-100 (default: 95).",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=1,
        metavar="N",
        help="Number of images to place on each PDF page (default: 1, "
             "i.e. one image per page). Requires a fixed --page-size; "
             "defaults to 'a4' if not given.",
    )
    parser.add_argument(
        "--layout",
        choices=["grid", "horizontal", "vertical"],
        default="grid",
        help="How to arrange images when --per-page > 1: 'grid' (auto "
             "rows/columns, near-square), 'horizontal' (one row), or "
             "'vertical' (one column, stacked). Default: grid.",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=18,
        metavar="PT",
        help="Page margin in points when --per-page > 1 (default: 18, "
             "i.e. 0.25in).",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=10,
        metavar="PT",
        help="Gap between images in points when --per-page > 1 (default: 10).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if not (1 <= args.quality <= 100):
        logger.error("--quality must be between 1 and 100.")
        return 2

    if args.per_page < 1:
        logger.error("--per-page must be at least 1.")
        return 2

    try_register_heif()

    try:
        image_paths = iter_input_images(args.input)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    output_path = args.output
    if output_path is None:
        base_name = args.input[0].stem if args.input[0].is_file() else args.input[0].name
        output_path = Path(f"{base_name}.pdf")

    try:
        convert_images_to_pdf(
            image_paths=image_paths,
            output_path=output_path,
            page_size=args.page_size,
            quality=args.quality,
            per_page=args.per_page,
            layout=args.layout,
            margin_pt=args.margin,
            gap_pt=args.gap,
        )
    except (RuntimeError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    logger.info(
        "\nDone. %d image(s) combined into '%s'.",
        len(image_paths),
        output_path.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
