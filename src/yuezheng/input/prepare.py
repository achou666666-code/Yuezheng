"""Input inspection and conservative preprocessing for OMR."""
from pathlib import Path
import hashlib
import json
import re
import shutil

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
RASTER = SUPPORTED - {".pdf"}


def _natural_key(path: Path):
    """Sort page-1/page-2/page-10 in human order."""
    return [int(piece) if piece.isdigit() else piece.lower()
            for piece in re.split(r"(\d+)", path.name)]


def _page_sources(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        pages = sorted((p for p in input_path.iterdir()
                        if p.is_file() and p.suffix.lower() in RASTER), key=_natural_key)
        if not pages:
            raise ValueError(f"No supported raster pages found in {input_path}")
        return pages
    if input_path.suffix.lower() in RASTER:
        return [input_path]
    raise ValueError("Expected a PDF, raster image, or directory of raster pages")

def inspect_input(path: str) -> dict:
    source = Path(path)
    if not source.exists():
        return {"status": "error", "error": f"Input does not exist: {source}"}
    suffix = source.suffix.lower()
    result = {"status": "pass" if suffix in SUPPORTED else "error", "path": str(source.resolve()),
              "format": suffix.lstrip("."), "bytes": source.stat().st_size,
              "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    if suffix not in SUPPORTED:
        result["error"] = f"Unsupported input format: {suffix or '<none>'}"
        return result
    if suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(source)
            result["pages"] = len(doc)
            result["page_sizes"] = [{"width": p.rect.width, "height": p.rect.height} for p in doc]
        except ImportError:
            result["warning"] = "Install the image extra to inspect PDF pages: pip install -e '.[image]'"
    else:
        try:
            from PIL import Image
            with Image.open(source) as image:
                result["width"], result["height"] = image.size
                result["mode"] = image.mode
                result["dpi"] = image.info.get("dpi")
        except ImportError:
            result["warning"] = "Install the image extra to inspect raster dimensions."
    return result

def prepare_image(input_path: str, output_path: str, scale: int = 2) -> dict:
    """Create a clean grayscale image while preserving the source file."""
    source, destination = Path(input_path), Path(output_path)
    if source.suffix.lower() not in RASTER:
        raise ValueError("prepare_image requires a raster image input")
    from PIL import Image, ImageEnhance, ImageOps
    with Image.open(source) as image:
        gray = ImageOps.grayscale(image)
        if scale > 1:
            gray = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
        gray = ImageEnhance.Contrast(gray).enhance(1.35)
        destination.parent.mkdir(parents=True, exist_ok=True)
        gray.save(destination)
    return {"status": "pass", "input_path": str(source.resolve()), "output_path": str(destination.resolve()), "scale": scale}


def prepare_input(input_path: str, output_dir: str, dpi: int = 450, enhance: bool = True) -> dict:
    """Normalize PDF/image input into a source-linked, page-oriented evidence package."""
    source = Path(input_path).expanduser()
    destination = Path(output_dir).expanduser()
    if not source.exists():
        return {"status": "error", "stage": "inspect", "error": f"Input does not exist: {source}"}
    if source.is_file() and source.suffix.lower() not in SUPPORTED:
        return {"status": "error", "stage": "inspect", "error": f"Unsupported input format: {source.suffix or '<none>'}"}
    if source.is_dir() and not any(p.suffix.lower() in RASTER for p in source.iterdir()):
        return {"status": "error", "stage": "inspect", "error": f"No supported raster pages found in {source}"}
    destination.mkdir(parents=True, exist_ok=True)
    originals = destination / "original"
    rendered = destination / "pages"
    enhanced = destination / "enhanced"
    originals.mkdir(exist_ok=True); rendered.mkdir(exist_ok=True)
    if enhance: enhanced.mkdir(exist_ok=True)
    entries = []
    try:
        if source.is_file() and source.suffix.lower() == ".pdf":
            import fitz
            doc = fitz.open(source)
            for index, page in enumerate(doc, 1):
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                page_path = rendered / f"page-{index:04d}.png"
                pix.save(str(page_path))
                item = {"page": index, "source": str(source.resolve()), "source_page": index,
                        "original": str(source.resolve()), "rendered": str(page_path.resolve()),
                        "dpi": dpi, "width": pix.width, "height": pix.height}
                if enhance:
                    enhanced_path = enhanced / page_path.name
                    prepare_image(str(page_path), str(enhanced_path), scale=1)
                    item["enhanced"] = str(enhanced_path.resolve())
                entries.append(item)
            doc.close()
        else:
            pages = _page_sources(source)
            from PIL import Image
            pil_pages = []
            for index, page_source in enumerate(pages, 1):
                ext = page_source.suffix.lower()
                original_path = originals / f"page-{index:04d}{ext}"
                shutil.copy2(page_source, original_path)
                with Image.open(page_source) as image:
                    image = image.convert("RGB")
                    rendered_path = rendered / f"page-{index:04d}.png"
                    image.save(rendered_path, dpi=(dpi, dpi))
                    pil_pages.append(image.copy())
                    item = {"page": index, "source": str(page_source.resolve()), "source_page": None,
                            "original": str(original_path.resolve()), "rendered": str(rendered_path.resolve()),
                            "dpi": dpi, "width": image.width, "height": image.height}
                if enhance:
                    enhanced_path = enhanced / rendered_path.name
                    prepare_image(str(rendered_path), str(enhanced_path), scale=1)
                    item["enhanced"] = str(enhanced_path.resolve())
                entries.append(item)
            if len(pil_pages) == 1:
                internal_pdf = destination / "input.pdf"
                pil_pages[0].save(internal_pdf, "PDF", resolution=dpi)
            else:
                internal_pdf = destination / "input.pdf"
                pil_pages[0].save(internal_pdf, "PDF", resolution=dpi,
                                  save_all=True, append_images=pil_pages[1:])
        manifest = {"status": "pass", "input": str(source.resolve()),
                    "input_type": "pdf" if source.is_file() and source.suffix.lower() == ".pdf" else "images",
                    "page_count": len(entries), "dpi": dpi, "pages": entries,
                    "internal_pdf": str((destination / "input.pdf").resolve()) if not (source.is_file() and source.suffix.lower() == ".pdf") else str(source.resolve())}
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path.resolve())
        return manifest
    except (ImportError, OSError, ValueError) as exc:
        return {"status": "error", "stage": "prepare", "error": str(exc)}
