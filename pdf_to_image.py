#!/usr/bin/env python3
"""
pdf_to_image.py

Convert PDF documents into images (PNG or JPEG), one image per page.

Uses pypdfium2 (a binding for Chromium's PDFium engine) for fast, high-fidelity
rendering with no external system dependencies (e.g. no Poppler install needed).

Examples
--------
Convert every page of a PDF to PNG at default quality:
    python pdf_to_image.py report.pdf

Convert to JPEG at higher resolution (300 DPI equivalent):
    python pdf_to_image.py report.pdf --format jpeg --dpi 300

Convert only pages 1-3 and 5, into a specific output folder:
    python pdf_to_image.py report.pdf --pages 1-3,5 --output-dir ./pages

Convert every PDF in a folder:
    python pdf_to_image.py ./my_pdfs --output-dir ./converted
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    sys.exit(
        "Missing dependency 'pypdfium2'.\n"
        "Install it with:  pip install pypdfium2 pillow"
    )

logger = logging.getLogger("pdf_to_image")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """
    Parse a page-selection string like "1-3,5,8-10" into a sorted list of
    0-indexed page numbers, clamped to the document's actual page count.

    Raises ValueError on malformed input.
    """
    selected: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_str, end_str = chunk.split("-", 1)
            start, end = int(start_str), int(end_str)
            if start < 1 or end < start:
                raise ValueError(f"Invalid page range: '{chunk}'")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(chunk))

    out_of_range = [p for p in selected if p < 1 or p > page_count]
    if out_of_range:
        raise ValueError(
            f"Page(s) {sorted(out_of_range)} are out of range "
            f"(document has {page_count} page(s))."
        )

    return sorted(p - 1 for p in selected)  # convert to 0-indexed


def dpi_to_scale(dpi: int) -> float:
    """PDFium renders at a 'scale' where 1.0 == 72 DPI (the PDF default)."""
    return dpi / 72.0


def convert_pdf(
    pdf_path: Path,
    output_dir: Path,
    image_format: str = "png",
    dpi: int = 200,
    pages_spec: str | None = None,
    prefix: str | None = None,
    jpeg_quality: int = 92,
) -> list[Path]:
    """
    Convert a single PDF's pages to image files.

    Returns the list of image file paths that were written.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    image_format = image_format.lower()
    if image_format not in ("png", "jpeg", "jpg"):
        raise ValueError(f"Unsupported format: {image_format!r} (use 'png' or 'jpeg')")
    ext = "jpg" if image_format in ("jpeg", "jpg") else "png"
    pil_format = "JPEG" if ext == "jpg" else "PNG"

    output_dir.mkdir(parents=True, exist_ok=True)
    file_prefix = prefix or pdf_path.stem

    logger.info("Opening %s", pdf_path)
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except pdfium.PdfiumError as exc:
        raise RuntimeError(f"Could not open PDF '{pdf_path}': {exc}") from exc

    try:
        page_count = len(pdf)
        if page_count == 0:
            logger.warning("'%s' has no pages, skipping.", pdf_path.name)
            return []

        page_indices = (
            parse_page_ranges(pages_spec, page_count)
            if pages_spec
            else range(page_count)
        )

        scale = dpi_to_scale(dpi)
        pad_width = len(str(page_count))
        written: list[Path] = []

        for idx in page_indices:
            page = pdf[idx]
            try:
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()

                # JPEG doesn't support an alpha channel; flatten onto white.
                if pil_format == "JPEG" and pil_image.mode in ("RGBA", "LA"):
                    background = pil_image.convert("RGB")
                    pil_image = background

                out_path = output_dir / f"{file_prefix}_page_{idx + 1:0{pad_width}d}.{ext}"
                save_kwargs = {"quality": jpeg_quality, "optimize": True} if pil_format == "JPEG" else {}
                pil_image.save(out_path, pil_format, **save_kwargs)
                written.append(out_path)
                logger.info("  wrote %s", out_path.name)
            finally:
                page.close()

        return written
    finally:
        pdf.close()


def iter_input_pdfs(input_path: Path) -> list[Path]:
    """Resolve the input argument into a list of PDF file paths."""
    if input_path.is_dir():
        pdfs = sorted(input_path.glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(f"No .pdf files found in directory: {input_path}")
        return pdfs
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {input_path}")
        return [input_path]
    raise FileNotFoundError(f"Input path does not exist: {input_path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert PDF document(s) into images, one image per page.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples\n--------\n", 1)[-1],
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a PDF file, or a directory containing PDF files.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("output_images"),
        help="Directory to save images into (default: ./output_images).",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["png", "jpeg", "jpg"],
        default="png",
        help="Output image format (default: png).",
    )
    parser.add_argument(
        "-d", "--dpi",
        type=int,
        default=200,
        help="Rendering resolution in DPI. Higher = sharper but larger files "
             "(default: 200; try 300 for print quality).",
    )
    parser.add_argument(
        "-p", "--pages",
        type=str,
        default=None,
        help="Specific pages to convert, e.g. '1-3,5,8-10'. "
             "Default: convert all pages.",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=92,
        help="JPEG quality, 1-100 (default: 92). Ignored for PNG.",
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

    if not (1 <= args.jpeg_quality <= 100):
        logger.error("--jpeg-quality must be between 1 and 100.")
        return 2

    if args.dpi <= 0:
        logger.error("--dpi must be a positive integer.")
        return 2

    try:
        pdf_paths = iter_input_pdfs(args.input)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    total_written = 0
    had_errors = False

    for pdf_path in pdf_paths:
        try:
            written = convert_pdf(
                pdf_path=pdf_path,
                output_dir=args.output_dir,
                image_format=args.format,
                dpi=args.dpi,
                pages_spec=args.pages,
                jpeg_quality=args.jpeg_quality,
            )
            total_written += len(written)
        except Exception as exc:  # noqa: BLE001 - surface any conversion failure clearly
            logger.error("Failed to convert '%s': %s", pdf_path, exc)
            had_errors = True

    logger.info(
        "\nDone. %d image(s) written to '%s'.",
        total_written,
        args.output_dir.resolve(),
    )
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
