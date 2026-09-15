# doc-image-toolkit

Two small, dependency-light command-line tools for converting between PDFs and images:

| Script                               | Converts                                     |
|--------------------------------------|----------------------------------------------|
| [pdf_to_image.py](#1-pdf_to_imagepy) | PDF → images (PNG / JPEG, one file per page) |
| [image_to_pdf.py](#2-image_to_pdfpy) | Images (any common format) → a single PDF    |

Both are self-contained, single-file Python scripts with no system-level dependencies (no Poppler, no ImageMagick); just two pure-Python packages. They're built as proper CLIs: argument parsing, structured logging, meaningful exit codes, and defensive error handling, so they're safe to drop into a larger pipeline or CI job as well as run by hand.

***

## Table of contents

-   [Why these tools](#why-these-tools)
-   [Installation](#installation)
-   [1. pdf_to_image.py](#1-pdf_to_imagepy)
    -   [Usage](#usage)
    -   [Options](#options)
    -   [Examples](#examples)
-   [2. image_to_pdf.py](#2-image_to_pdfpy)
    -   [Usage](#usage-1)
    -   [Options](#options-1)
    -   [Examples](#examples-1)
    -   [Multi-image pages (--per-page)](#multi-image-pages---per-page)
-   [Design notes](#design-notes)
-   [Exit codes](#exit-codes)
-   [Limitations](#limitations)
-   [License](#license)

***

## Why these tools

Most quick "PDF to image" or "image to PDF" scripts either shell out to Poppler/ImageMagick (an install headache on Windows, and a common source of "works on my machine" bugs) or silently mishandle the edge cases that actually show up in real documents:

-   transparent PNGs turning into black or checkerboard pages when written into a PDF,
-   EXIF-rotated phone photos coming out sideways,
-   palette-mode GIFs/indexed PNGs crashing a naive `Image.open().save()` call,
-   no sensible behavior when you want to select just a few pages, or combine several images into one page.

Both scripts here handle those cases explicitly (see [Design notes](#design-notes)), and were built and verified incrementally; each feature was tested against generated sample files and the resulting PDFs/images were re-opened and visually inspected before being considered done, not just assumed to work from reading the library docs.

***

## Installation

```bash
git clone https://github.com/Engr-Brandon/image-pdf-converter.git
cd image-pdf-converter
pip install -r requirements.txt
```

**Requirements:**

-   Python 3.10+ (uses `X | Y` union type hints)
-   [pypdfium2](https://pypi.org/project/pypdfium2/); a binding for Chromium's PDFium engine, used for PDF rendering
-   [Pillow](https://pypi.org/project/Pillow/); used for image I/O and for writing PDFs

No Poppler, no ImageMagick, no other system packages. Both libraries ship prebuilt wheels for Windows, macOS, and Linux, so `pip install` is the entire setup.

Optional: install [pillow-heif](https://pypi.org/project/pillow-heif/) to let `image_to_pdf.py` also accept HEIC/HEIF input (iPhone photos). It's auto-detected at runtime; if it's not installed, everything else works normally and HEIC input just isn't available.

***

## 1. `pdf_to_image.py`

Converts every page of a PDF (or every PDF in a folder) into a separate image file. Rendering is done with PDFium at a resolution you control, so output stays sharp even when zoomed in; this isn't a screenshot-quality rasterizer.

### Usage

```
usage: pdf_to_image.py [-h] [-o OUTPUT_DIR] [-f {png,jpeg,jpg}] [-d DPI]
                        [-p PAGES] [--jpeg-quality JPEG_QUALITY] [-v]
                        input
```

### Options

| Flag                 | Default           | Description                                                                                              |
|----------------------|-------------------|----------------------------------------------------------------------------------------------------------|
| `input`              | -                 | Path to a single PDF, or a directory containing PDFs (all `*.pdf` files inside are processed).           |
| `-o`, `--output-dir` | `./output_images` | Directory the images are written into (created if missing).                                              |
| `-f`, `--format`     | `png`             | `png` or `jpeg`.                                                                                         |
| `-d`, `--dpi`        | `200`             | Render resolution. 150–200 is fine for on-screen use; use 300 for print quality.                         |
| `-p`, `--pages`      | all pages         | Page selection, e.g. `1-3,5,8-10`. Out-of-range pages raise a clear error rather than silently clamping. |
| `--jpeg-quality`     | `92`              | JPEG compression quality, 1–100. Ignored for PNG.                                                        |
| `-v`, `--verbose`    | off               | Debug-level logging (per-page progress).                                                                 |

Output files are named `<pdf_stem>_page_<N>.<ext>`, zero-padded to the document's page count so they always sort correctly (`page_01`, `page_02`, ... `page_12`, not `page_1`, `page_10`, `page_11`, `page_2`).

### Examples

Convert every page to PNG at default quality:

```bash
python pdf_to_image.py report.pdf
```

Higher resolution, JPEG output:

```bash
python pdf_to_image.py report.pdf --format jpeg --dpi 300
```

Only specific pages, into a chosen folder:

```bash
python pdf_to_image.py report.pdf --pages 1-3,5 --output-dir ./pages
```

Batch-convert every PDF in a directory:

```bash
python pdf_to_image.py ./my_pdfs --output-dir ./converted
```

***

## 2. `image_to_pdf.py`

Converts one or more images; any common format; into a single, properly formed multi-page PDF. Handles mixed input formats and mixed orientations in the same run, with no manual pre-processing needed.

**Supported input formats:** JPEG, PNG, BMP, GIF, TIFF, WEBP, PPM/PGM/PBM, ICO, and HEIC/HEIF (with the optional `pillow-heif` package).

### Usage

```
usage: image_to_pdf.py [-h] [-o OUTPUT] [--page-size {a4,letter,legal}]
                        [-q QUALITY] [--per-page N]
                        [--layout {grid,horizontal,vertical}] [--margin PT]
                        [--gap PT] [-v]
                        input [input ...]
```

### Options

| Flag              | Default                  | Description                                                                                                                                                 |
|-------------------|--------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `input`           | -                        | One or more image files and/or directories. Multiple images are combined into one PDF in the order given (directories are expanded and sorted by filename). |
| `-o`, `--output`  | `<first_input_name>.pdf` | Output PDF path.                                                                                                                                            |
| `--page-size`     | none (native size)       | `a4`, `letter`, or `legal`. If omitted, each page matches its source image's own pixel dimensions; nothing is cropped or padded.                            |
| `-q`, `--quality` | `95`                     | Internal JPEG compression quality used for the PDF's image streams, 1–100.                                                                                  |
| `--per-page`      | `1`                      | How many images to place on each PDF page. See [Multi-image pages](#multi-image-pages---per-page) below.                                                    |
| `--layout`        | `grid`                   | Arrangement when `--per-page > 1`: `grid` (auto rows/columns), `horizontal` (single row), or `vertical` (single column, stacked).                           |
| `--margin`        | `18` (pt)                | Page margin when `--per-page > 1`. 18pt ≈ 0.25in.                                                                                                           |
| `--gap`           | `10` (pt)                | Spacing between images when `--per-page > 1`.                                                                                                               |
| `-v`, `--verbose` | off                      | Debug-level logging (per-image progress).                                                                                                                   |

### Examples

Single image to PDF:

```bash
python image_to_pdf.py photo.jpg
```

Combine several images into one PDF, in the order given:

```bash
python image_to_pdf.py page1.png page2.png page3.png -o booklet.pdf
```

Every image in a folder, sorted by filename, into one PDF:

```bash
python image_to_pdf.py ./scans -o scans.pdf
```

Fit every image onto uniform A4 pages instead of native size:

```bash
python image_to_pdf.py ./scans -o scans.pdf --page-size a4
```

### Multi-image pages (`--per-page`)

By default each image gets its own page. `--per-page` places several images on the same page instead, arranged in a grid; useful for contact sheets, side-by-side comparisons, or fitting a set of small images without wasting a page per item.

```bash
# 2 images side by side on one page
python image_to_pdf.py photo1.jpg photo2.jpg --per-page 2 -o combined.pdf

# 4 images in an automatic 2x2 grid, on Letter-sized pages
python image_to_pdf.py ./photos --per-page 4 --page-size letter -o grid.pdf

# 2 images stacked vertically instead of side by side
python image_to_pdf.py top.jpg bottom.jpg --per-page 2 --layout vertical -o stacked.pdf
```

Notes on how this works:

-   `--per-page > 1` needs a fixed page to lay images out on, so `--page-size` defaults to `a4` automatically if you don't set one.
-   Each image is scaled to fit inside its own cell **without distortion** (aspect ratio preserved) and centered there.
-   `grid` layout picks a near-square arrangement automatically (2 → 1×2, 4 → 2×2, 5 → 2×3, etc.).
-   If you provide more images than fit on one page, the tool just continues onto additional pages; e.g. 5 images at `--per-page 2` produces 3 pages, with the last page holding a single image rather than erroring or leaving an awkward gap.

***

## Design notes

A few deliberate decisions, documented here so they don't look accidental:

-   **PDFium over Poppler** (`pdf_to_image.py`): `pypdfium2` ships as a self-contained wheel with the PDFium engine bundled in, so there's nothing to install at the OS level; a common pain point with `pdf2image`, which shells out to a Poppler binary that has to be separately installed and put on `PATH`.
-   **Pillow's native PDF writer over reportlab/img2pdf** (`image_to_pdf.py`): Pillow can already read every format this tool needs to accept and write valid multi-page PDFs directly, so no extra dependency was pulled in just for PDF assembly.
-   **Transparency is always flattened onto white before saving**: PDF has no alpha channel. Rather than let an RGBA or palette image degrade unpredictably when Pillow is forced to save it as a PDF (this is what produces the "black background" or "checkerboard" artifacts people run into with naive scripts), every image is explicitly composited onto a white RGB canvas first.
-   **EXIF orientation is corrected on load**: photos taken on phones are frequently stored "sideways" with a rotation flag in their EXIF metadata. Both scripts normalize this via `ImageOps.exif_transpose` so output isn't rotated 90°.
-   **Page-fit vs. native size is explicit, not implied**: `image_to_pdf.py` defaults to giving each page the image's own pixel dimensions (no distortion, no padding) unless `--page-size` is set, rather than silently forcing everything onto a fixed page and letting the user discover unwanted cropping/letterboxing later.
-   **Zero-padded, deterministic output filenames**: page numbers in `pdf_to_image.py` output are padded to the document's page count so filenames sort correctly in any file browser or shell glob, at any page count.
-   **Fail loud, per item, without aborting a whole batch**: when converting a directory of PDFs or images, one corrupt/unreadable file is reported and skipped rather than stopping the entire run; the tool still exits non-zero so the failure isn't silently swallowed in scripts/CI.

## Exit codes

Both scripts follow the same convention:

| Code | Meaning                                                                                       |
|------|-----------------------------------------------------------------------------------------------|
| `0`  | Success.                                                                                      |
| `1`  | Input/output error at run time; missing file, unreadable image, invalid page range, etc.      |
| `2`  | Invalid arguments (e.g. `--dpi 0`, `--quality 150`); caught before any file I/O is attempted. |

## Limitations

-   `--page-size` is limited to A4 / Letter / Legal (portrait/landscape auto-selected per image). Custom dimensions aren't currently exposed as a flag.
-   `pdf_to_image.py` does not extract embedded text, form fields, or annotations; it's a rasterizer, purely visual output.
-   Very large batch jobs (hundreds of high-DPI pages) are processed sequentially, not in parallel.

## License

MIT; see <LICENSE>.
