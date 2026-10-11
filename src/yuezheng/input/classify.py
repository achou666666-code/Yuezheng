"""Conservative raster-page classification for score workflows."""
from pathlib import Path


def classify_page(path: str) -> dict:
    """Classify obvious score/blank pages without discarding uncertain pages.

    The detector looks for several groups of five thin, regularly spaced,
    long horizontal lines. It deliberately returns ``uncertain`` for dense
    illustrations and text pages; callers may then use OMR as a second signal.
    """
    from PIL import Image, ImageOps

    source = Path(path)
    with Image.open(source) as image:
        gray = ImageOps.grayscale(image)
        gray.thumbnail((1200, 1600))
        width, height = gray.size
        pixels = gray.load()
        # Ignore the outer margin and count dark pixels per scanline.
        left, right = width // 20, width - width // 20
        span = max(1, right - left)
        ratios = [sum(pixels[x, y] < 150 for x in range(left, right)) / span
                  for y in range(height)]

    candidates = []
    for index, ratio in enumerate(ratios):
        if 0.30 <= ratio <= 0.92:
            # Staff lines are thin. Reject rows sitting inside a solid photo or
            # banner by requiring substantially lighter neighbors.
            before = ratios[index - 2] if index >= 2 else 0.0
            after = ratios[index + 2] if index + 2 < len(ratios) else 0.0
            if ratio > before * 1.35 and ratio > after * 1.35:
                candidates.append(index)

    groups = 0
    for start in range(max(0, len(candidates) - 4)):
        five = candidates[start:start + 5]
        gaps = [five[i + 1] - five[i] for i in range(4)]
        if gaps and min(gaps) >= 2 and max(gaps) <= 18 and max(gaps) - min(gaps) <= 4:
            groups += 1

    dark_fraction = sum(ratios) / max(1, len(ratios))
    if groups >= 2:
        page_type, confidence = "score", 0.95
    elif dark_fraction < 0.004 or (groups == 0 and dark_fraction > 0.18):
        page_type, confidence = "non_score", 0.98
    else:
        page_type, confidence = "uncertain", 0.5
    return {"status": "pass", "path": str(source.resolve()), "page_type": page_type,
            "confidence": confidence, "staff_groups": groups,
            "dark_fraction": round(dark_fraction, 6)}
