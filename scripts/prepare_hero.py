#!/usr/bin/env python3
"""Download a suburban house photo and cut France out of the studio background."""

from io import BytesIO
from pathlib import Path

import ssl
import urllib.request

from PIL import Image
from rembg import remove

ROOT = Path(__file__).resolve().parents[1] / "assets" / "images"
CTX = ssl.create_default_context()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FranceRemillardSite/1.0)",
}

# Typical two-storey suburban house with lawn (Unsplash).
HOUSE_URL = (
    "https://images.unsplash.com/photo-1570129477492-45c003edd2be"
    "?auto=format&fit=crop&w=1920&q=80"
)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, context=CTX, timeout=60) as response:
        return response.read()


def save_jpeg_webp(image: Image.Image, stem: str) -> None:
    rgb = image.convert("RGB")
    rgb.save(ROOT / f"{stem}.jpg", "JPEG", quality=86, optimize=True)
    rgb.save(ROOT / f"{stem}.webp", "WEBP", quality=82, method=6)


def cutout() -> None:
    source = Image.open(ROOT / "france-remillard.jpg").convert("RGBA")
    result = remove(
        source,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=4,
    )
    if not isinstance(result, Image.Image):
        result = Image.open(BytesIO(result)).convert("RGBA")
    else:
        result = result.convert("RGBA")

    alpha = result.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        left, top, right, bottom = bbox
        pad = 4
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(result.width, right + pad)
        result = result.crop((left, top, right, bottom))

    result.save(ROOT / "france-remillard-cutout.png", "PNG", optimize=True)
    result.save(ROOT / "france-remillard-cutout.webp", "WEBP", quality=90, method=6)
    print("cutout", result.size, result.mode)


def house() -> None:
    raw = fetch(HOUSE_URL)
    image = Image.open(BytesIO(raw))
    image = image.convert("RGB")
    image.thumbnail((1920, 1280), Image.Resampling.LANCZOS)
    save_jpeg_webp(image, "maison-banlieue")
    print("house", image.size)


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    house()
    cutout()
