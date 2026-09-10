#!/usr/bin/env python3
"""Prepare the 2026 portrait set: hero cutout plus the two in-page portraits."""

from io import BytesIO
from pathlib import Path
import sys

from PIL import Image, ImageFilter
from rembg import remove

ROOT = Path(__file__).resolve().parents[1] / "assets" / "images"
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else None

FILES = {
    "studio": "_O2A8299",
    "assise": "_O2A8359",
    "fenetre": "_O2A8317",
}


def find(stem_marker: str) -> Path:
    matches = [p for p in SOURCE.glob("*.jpg") if stem_marker in p.name]
    if not matches:
        raise FileNotFoundError(stem_marker)
    return matches[0]


def save_pair(image: Image.Image, stem: str, quality: int = 88) -> None:
    rgb = image.convert("RGB")
    rgb.save(ROOT / f"{stem}.jpg", "JPEG", quality=quality, optimize=True, progressive=True)
    rgb.save(ROOT / f"{stem}.webp", "WEBP", quality=82, method=6)
    print(stem, rgb.size)


def crop_ratio(image: Image.Image, ratio: float, anchor_y: float = 0.5) -> Image.Image:
    """Center-crop horizontally, anchor vertically, to width/height == ratio."""
    w, h = image.size
    target_h = min(h, int(round(w / ratio)))
    target_w = min(w, int(round(target_h * ratio)))
    left = (w - target_w) // 2
    top = int(round((h - target_h) * anchor_y))
    return image.crop((left, top, left + target_w, top + target_h))


def hero_cutout() -> None:
    source = Image.open(find(FILES["studio"])).convert("RGBA")
    result = remove(
        source,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=12,
        alpha_matting_erode_size=4,
    )
    if not isinstance(result, Image.Image):
        result = Image.open(BytesIO(result))
    result = result.convert("RGBA")

    alpha = result.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        left, top, right, bottom = bbox
        result = result.crop((max(0, left - 2), max(0, top - 2),
                              min(result.width, right + 2), min(result.height, bottom + 2)))

    # Soften the mask edge so the unframed portrait melts into the page.
    alpha = result.getchannel("A").filter(ImageFilter.GaussianBlur(0.8))
    result.putalpha(alpha)

    result.save(ROOT / "france-remillard-cutout.webp", "WEBP", quality=90, method=6)

    # PNG is only the no-WebP fallback, so it ships at half the pixels.
    fallback = result.resize(
        (512, round(512 * result.height / result.width)), Image.Resampling.LANCZOS
    )
    fallback.save(ROOT / "france-remillard-cutout.png", "PNG", optimize=True, compress_level=9)
    print("cutout", result.size, "fallback", fallback.size)


def flat_portraits() -> None:
    studio = Image.open(find(FILES["studio"])).convert("RGB")
    save_pair(crop_ratio(studio, 3 / 4, anchor_y=0.0), "france-remillard")

    assise = Image.open(find(FILES["assise"])).convert("RGB")
    save_pair(crop_ratio(assise, 4 / 5, anchor_y=0.0), "france-remillard-assise")

    fenetre = Image.open(find(FILES["fenetre"])).convert("RGB")
    save_pair(crop_ratio(fenetre, 4 / 5, anchor_y=0.0), "france-remillard-fenetre")


if __name__ == "__main__":
    if SOURCE is None:
        raise SystemExit("usage: prepare_portraits.py <dossier-des-photos-sources>")
    ROOT.mkdir(parents=True, exist_ok=True)
    flat_portraits()
    hero_cutout()
