#!/usr/bin/env python3
"""Fetch France Rémillard listings from Royal LePage and rebuild static pages."""

from __future__ import annotations

import io
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "53785"
FEED_URL = "https://www.royallepage.ca/fr/search/get-list/property/{agent}/{page}/"
USER_AGENT = (
    "Mozilla/5.0 (compatible; FranceRemillardSite/1.0; +https://github.com/AlexandreRoy-dev/France-remillard)"
)
LISTINGS_JSON = ROOT / "data" / "listings.json"
PHOTO_DIR = ROOT / "assets" / "images" / "listings"
INSCRIPTIONS_DIR = ROOT / "inscriptions"
INDEX_HTML = ROOT / "index.html"
SITEMAP = ROOT / "sitemap.xml"
MARKER_START = "<!-- SYNC:LISTINGS -->"
MARKER_END = "<!-- /SYNC:LISTINGS -->"
PHOTO_CACHE = "hd"
THUMB_SUFFIXES = ("_med.jpg", "_lg.jpg", "_sml.jpg", "_sm.jpg")
MIN_PHOTO_BYTES = 80_000
MAX_PHOTO_EDGE = 1600
JPEG_QUALITY = 82
SITE = "https://franceremillard.com"
AGENT_NODE = f"{SITE}/#agent"
PORTRAIT = "assets/images/france-remillard.webp"
HERO = "assets/images/maison-banlieue.jpg"
SALE_PRICE = re.compile(r"^\d{1,3}(?: \d{3})* \$$")

CTX = ssl.create_default_context()


def site_url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{SITE}{path}"


def compress_jpeg(path: Path, max_edge: int = MAX_PHOTO_EDGE, quality: int = JPEG_QUALITY) -> None:
    """Re-encode a downloaded listing photo. Keep the original if Pillow is missing or the file would grow."""
    try:
        from PIL import Image
    except ImportError:
        print(f"pillow missing, left {path.name} uncompressed", file=sys.stderr)
        return
    original = path.read_bytes()
    try:
        with Image.open(io.BytesIO(original)) as im:
            im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            im.save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    except Exception as exc:
        path.write_bytes(original)
        print(f"compress failed {path.name}: {exc}", file=sys.stderr)
        return
    if not path.is_file() or path.stat().st_size >= len(original):
        path.write_bytes(original)


def listing_title(item: dict) -> str:
    address = item.get("address") or "Inscription"
    city = item.get("city") or ""
    if city:
        return f"{address}, {city} | France Rémillard"
    return f"{address} | France Rémillard"


def listing_description(item: dict) -> str:
    address = item.get("address") or "Cette inscription"
    city = item.get("city") or "Québec"
    kind = item.get("type") or "Propriété"
    if item.get("sold"):
        lead = f"{kind} vendue à {city}"
    else:
        lead = f"{kind} à {city}"
    text = f"{lead}. {address}. France Rémillard, courtière immobilière, Royal LePage Humania."
    if len(text) > 165:
        text = f"{lead}. {address}. Inscription Royal LePage Humania."
    return text


def sale_price(item: dict) -> int | None:
    """Plain sale price only. Skip monthly rents, tax notes, and sold listings."""
    if item.get("sold"):
        return None
    label = (item.get("price_label") or "").strip()
    if not SALE_PRICE.fullmatch(label):
        return None
    digits = re.sub(r"\D", "", label)
    return int(digits) if digits else None


AGENT_LD = {
    "@context": "https://schema.org",
    "@type": "RealEstateAgent",
    "@id": AGENT_NODE,
    "name": "France Rémillard",
    "url": f"{SITE}/",
    "image": site_url("/" + PORTRAIT),
    "description": (
        "Courtière immobilière à Saint-Jérôme. Achat et vente de maisons, chalets "
        "et immeubles dans les Laurentides, à Laval et sur la couronne nord."
    ),
    "telephone": "+1-514-347-3786",
    "email": "franceremillard@gmail.com",
    "address": {
        "@type": "PostalAddress",
        "streetAddress": "401, rue Laviolette",
        "addressLocality": "Saint-Jérôme",
        "addressRegion": "QC",
        "postalCode": "J7Y 2T2",
        "addressCountry": "CA",
    },
    "areaServed": [
        "Laurentides",
        "Saint-Jérôme",
        "Saint-Sauveur",
        "Sainte-Adèle",
        "Prévost",
        "Piedmont",
        "Morin-Heights",
        "Saint-Hippolyte",
        "Sainte-Anne-des-Lacs",
        "Sainte-Agathe-des-Monts",
        "Val-David",
        "Val-Morin",
        "Mont-Tremblant",
        "Saint-Colomban",
        "Sainte-Sophie",
        "Estérel",
        "Mille-Isles",
        "Laval",
        "Chomedey",
        "Saint-Vincent-de-Paul",
        "Laval-des-Rapides",
        "Duvernay",
        "Vimont",
        "Saint-François",
        "Blainville",
        "Boisbriand",
        "Mirabel",
        "Terrebonne",
        "Lachute",
    ],
    "worksFor": {
        "@type": "Organization",
        "name": "Royal LePage Humania",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "401, rue Laviolette",
            "addressLocality": "Saint-Jérôme",
            "addressRegion": "QC",
            "postalCode": "J7Y 2T2",
            "addressCountry": "CA",
        },
    },
    "contactPoint": [
        {
            "@type": "ContactPoint",
            "telephone": "+1-514-347-3786",
            "contactType": "customer service",
            "availableLanguage": ["French", "English"],
        },
        {
            "@type": "ContactPoint",
            "telephone": "+1-450-438-6868",
            "contactType": "customer service",
        },
    ],
    "knowsLanguage": ["fr-CA", "en"],
    "sameAs": [
        "https://www.royallepage.ca/fr/agent/quebec/saint-jerome/france-remillard/53785/",
        "https://www.centris.ca/fr/courtier-immobilier~france-remillard~royal-lepage-humania/d4337",
    ],
}


def upgrade_photo_url(url: str) -> str:
    """Card feed serves _med thumbs (~250px). The unsuffixed file is the 1920px original."""
    if not url:
        return url
    for suffix in THUMB_SUFFIXES:
        if url.endswith(suffix):
            return url[: -len(suffix)] + ".jpg"
    return url


def photo_candidates(url: str) -> list[str]:
    candidates = []
    original = upgrade_photo_url(url)
    if original:
        candidates.append(original)
    if url.endswith("_med.jpg"):
        large = url[: -len("_med.jpg")] + "_lg.jpg"
        if large not in candidates:
            candidates.append(large)
    if url and url not in candidates:
        candidates.append(url)
    return candidates


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "fr-CA,fr;q=0.9",
            "Referer": "https://www.royallepage.ca/",
        },
    )
    with urllib.request.urlopen(req, context=CTX, timeout=45) as response:
        return response.read()


def fetch_text(url: str) -> str:
    return fetch(url).decode("utf-8", errors="replace")


def fetch_feed_page(page: int) -> str:
    raw = fetch_text(FEED_URL.format(agent=AGENT_ID, page=page))
    match = re.search(r"\((\{.*\})\)\s*;?\s*$", raw, re.S)
    if not match:
        match = re.search(r"(\{.*\})", raw, re.S)
    if not match:
        raise RuntimeError(f"Unexpected feed payload on page {page}")
    payload = json.loads(match.group(1))
    return payload.get("html") or ""


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_card(chunk: str) -> dict | None:
    listing_id = re.search(r'data-id="(\d+)"', chunk)
    if not listing_id:
        return None
    url_match = re.search(r'href="(https://www\.royallepage\.ca/fr/property/[^"]+)"', chunk)
    photo_match = re.search(r'<img src="(//rlp\.jumplisting\.com/photos/[^"]+)"[^>]*alt="([^"]*)"', chunk)
    price_match = re.search(r'class="title--h3 price"[^>]*>(.*?)</span>\s*</span>', chunk, re.S)
    type_match = re.search(r'listing-meta--small">\s*<span>(.*?)</span>', chunk, re.S)
    beds_match = re.search(r"(\d+)\s*CAC", chunk, re.I)
    baths_match = re.search(r"(\d+(?:\+\d+)?)\s*SDB", chunk, re.I)
    key_match = re.search(r'data-rlp-key="([^"]+)"', chunk)
    mls_match = re.search(r"/mls(\d+)/", url_match.group(1) if url_match else "")

    url = url_match.group(1) if url_match else ""
    sold = "sold=1" in url
    alt = unescape(clean(photo_match.group(2) if photo_match else ""))
    price_html = price_match.group(1) if price_match else ""
    price_label = clean(unescape(re.sub(r"<[^>]+>", " ", price_html))).replace("\xa0", " ")
    price_label = re.sub(r"\s+", " ", price_label).strip()
    if re.fullmatch(r"\$?", price_label):
        price_label = ""
    elif price_label and not price_label.endswith("$") and any(ch.isdigit() for ch in price_label):
        price_label = f"{price_label} $"

    lat = lng = None
    if key_match:
        geo = re.match(r"^(-?\d+\.\d+)\.(-?\d+\.\d+)$", key_match.group(1))
        if geo:
            lat, lng = float(geo.group(1)), float(geo.group(2))

    addr_match = re.search(r'class="address-1"[^>]*>\s*<a[^>]*>(.*?)</a>', chunk, re.S)
    city_match = re.search(r'class="card__address-2"[^>]*>(.*?)</address>', chunk, re.S)
    address = unescape(clean(re.sub(r"<[^>]+>", " ", addr_match.group(1)))) if addr_match else ""
    city_raw = unescape(clean(re.sub(r"<[^>]+>", " ", city_match.group(1)))) if city_match else ""
    city = re.sub(r",?\s*QC$", "", city_raw).strip(" ,.")
    postal = ""
    tail = re.search(r",\s*QC\s+([A-Z]\d[A-Z]\s?\d[A-Z]\d)\s*$", alt, re.I)
    if tail:
        postal = tail.group(1).upper()
        head = alt[: tail.start()].strip()
        if address and head.lower().startswith(address.lower()):
            address = head[: len(address)]
            city = head[len(address) :].strip(" ,") or city
        elif head:
            address = address or head
            if not city:
                city = head

    photo = ""
    if photo_match:
        photo = photo_match.group(1)
        if photo.startswith("//"):
            photo = "https:" + photo
        photo = upgrade_photo_url(photo)

    return {
        "id": listing_id.group(1),
        "url": url.split("?")[0],
        "mls": mls_match.group(1) if mls_match else "",
        "sold": sold,
        "price_label": "Vendue" if sold and not price_label else price_label,
        "type": unescape(clean(type_match.group(1))) if type_match else "",
        "bedrooms": beds_match.group(1) if beds_match else "",
        "bathrooms": baths_match.group(1) if baths_match else "",
        "address": address,
        "city": city,
        "postal": postal,
        "photo_remote": photo,
        "photo": f"assets/images/listings/{listing_id.group(1)}.jpg",
        "lat": lat,
        "lng": lng,
        "alt": alt,
    }


def parse_listings(html: str) -> list[dict]:
    pieces = re.split(r'(?=<div class="card card--listing-card)', html)
    listings = []
    seen = set()
    for piece in pieces:
        if "card--listing-card" not in piece:
            continue
        item = parse_card(piece)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        listings.append(item)
    return listings


def fetch_all_listings() -> list[dict]:
    all_items = []
    seen = set()
    for page in range(1, 8):
        html = fetch_feed_page(page)
        batch = parse_listings(html)
        fresh = [item for item in batch if item["id"] not in seen]
        if not fresh:
            break
        for item in fresh:
            seen.add(item["id"])
        all_items.extend(fresh)
        if len(batch) < 8:
            break
    return all_items


def photo_is_small(path: Path) -> bool:
    return not path.is_file() or path.stat().st_size < MIN_PHOTO_BYTES


def download_photos(listings: list[dict], force: bool = False) -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    keep = set()
    for item in listings:
        dest = ROOT / item["photo"]
        keep.add(dest.name)
        remote = item.get("photo_remote") or ""
        if not remote:
            continue
        if not force and not photo_is_small(dest) and remote == upgrade_photo_url(remote):
            continue
        last_error = None
        saved = False
        for candidate in photo_candidates(remote):
            try:
                dest.write_bytes(fetch(candidate))
                compress_jpeg(dest)
                item["photo_remote"] = candidate
                saved = True
                break
            except urllib.error.URLError as exc:
                last_error = exc
        if not saved:
            print(f"photo failed {item['id']}: {last_error}", file=sys.stderr)
    for stale in PHOTO_DIR.glob("*.jpg"):
        if stale.name not in keep:
            stale.unlink()


def nav_html(current: str) -> str:
    links = [
        ("/", "Accueil", "home"),
        ("/inscriptions/", "Inscriptions", "listings"),
        ("/#parcours", "Parcours", "parcours"),
        ("/#services", "Services", "services"),
        ("/#contact", "Contact", "contact"),
    ]
    items = []
    for href, label, key in links:
        current_class = ' class="is-current" aria-current="page"' if key == current else ""
        items.append(f'          <a href="{href}"{current_class}>{label}</a>')
    return "\n".join(items)


def chrome(base: str, current: str) -> tuple[str, str]:
    header = f"""    <a class="skip-link" href="#contenu">Aller au contenu</a>
    <header class="site-header">
      <div class="container header-inner">
        <a class="brand" href="/">
          <img class="brand__logo" src="{base}assets/images/logo-royal-lepage.png" alt="Royal LePage Humania" width="600" height="221" />
          <span class="brand__meta">
            <span class="brand__office">Humania</span>
            <span class="brand__name">France Rémillard</span>
          </span>
        </a>
        <nav class="site-nav" id="menu-mobile" data-nav-panel aria-label="Navigation principale">
{nav_html(current)}
        </nav>
        <div class="header-actions">
          <a class="btn btn--primary btn--phone" href="tel:+15143473786">514 347-3786</a>
          <button class="nav-toggle" type="button" data-nav-toggle aria-expanded="false" aria-controls="menu-mobile" aria-label="Ouvrir le menu">
            <span></span><span></span><span></span>
          </button>
        </div>
      </div>
    </header>"""
    footer = f"""    <footer class="site-footer">
      <div class="container footer-grid">
        <div>
          <img class="brand__logo footer-logo" src="{base}assets/images/logo-royal-lepage.png" alt="Royal LePage Humania" width="180" height="66" />
          <p class="footer-note">
            France Rémillard, courtière immobilière résidentielle et commerciale, Royal LePage
            Humania. Titulaire d'un permis de l'OACIQ. 401, rue Laviolette, Saint-Jérôme
            (Québec) J7Y 2T2.
          </p>
          <p class="footer-phone">
            <a href="tel:+15143473786">514&nbsp;347-3786</a>
          </p>
        </div>
        <div>
          <ul class="footer-links">
            <li><a href="{base}inscriptions/">Inscriptions</a></li>
            <li><a href="https://www.royallepage.ca/fr/agent/quebec/saint-jerome/france-remillard/53785/" rel="noopener noreferrer">Profil Royal LePage</a></li>
            <li><a href="https://www.centris.ca/fr/courtier-immobilier~france-remillard~royal-lepage-humania/d4337" rel="noopener noreferrer">Inscriptions Centris</a></li>
            <li><a href="https://www.oaciq.com/" rel="noopener noreferrer">OACIQ</a></li>
            <li><a href="mailto:franceremillard@gmail.com">franceremillard@gmail.com</a></li>
          </ul>
          <p class="footer-note">
            Les renseignements du formulaire servent uniquement à vous répondre.
          </p>
        </div>
      </div>
    </footer>
    <script type="module" src="{base}js/main.js"></script>"""
    return header, footer


SECONDARY_ADDR = re.compile(r"(?i)\d+Z\b")
RESIDENTIAL_TYPES = {"Maison", "Fermette", "Copropriété"}


def clean_baths(baths: str) -> str:
    return baths[:-2] if baths.endswith("+0") else baths


def facts(item: dict) -> str:
    bits = [item["type"]] if item.get("type") else []
    if item.get("bedrooms"):
        bits.append(f"{item['bedrooms']} ch.")
    baths = clean_baths(item.get("bathrooms") or "")
    if baths:
        bits.append(f"{baths} sdb")
    return ", ".join(bits)


def display_price(item: dict) -> str:
    if item.get("sold"):
        return "Vendue"
    price = item.get("price_label") or "Sur demande"
    return re.sub(r"\s+\+TPS/TVQ\s*\$", " + TPS/TVQ", price)


def price_value(item: dict) -> int:
    digits = re.sub(r"[^\d]", "", item.get("price_label") or "")
    return int(digits) if digits else 0


def address_stem(address: str) -> str:
    cleaned = SECONDARY_ADDR.sub(lambda match: match.group(0)[:-1], address or "")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def pick_featured(active: list[dict], limit: int = 3) -> list[dict]:
    seen: set[str] = set()
    preferred: list[dict] = []
    others: list[dict] = []
    for item in active:
        address = item.get("address") or ""
        if SECONDARY_ADDR.search(address):
            continue
        stem = address_stem(address)
        if not stem or stem in seen:
            continue
        seen.add(stem)
        if not has_local_photo(item):
            continue
        if item.get("type") in RESIDENTIAL_TYPES and item.get("bedrooms"):
            preferred.append(item)
        else:
            others.append(item)
    preferred.sort(key=price_value, reverse=True)
    return (preferred + others)[:limit]


def specs_html(item: dict) -> str:
    parts = []
    if item.get("bedrooms"):
        parts.append(
            f'<li><i class="fal fa-bed" aria-hidden="true"></i> {escape(item["bedrooms"])} ch.</li>'
        )
    baths = clean_baths(item.get("bathrooms") or "")
    if baths:
        parts.append(f'<li><i class="fal fa-bath" aria-hidden="true"></i> {escape(baths)} sdb</li>')
    if item.get("type") and not parts:
        parts.append(f"<li>{escape(item['type'])}</li>")
    if not parts:
        return ""
    return f'<ul class="listing-card__specs">{"".join(parts)}</ul>'


def has_local_photo(item: dict) -> bool:
    path = ROOT / item["photo"]
    return path.is_file() and path.stat().st_size > 0


def card_html(item: dict, photo_prefix: str, href: str, delay: float = 0) -> str:
    price = display_price(item)
    badge = "Vendue" if item.get("sold") else (item.get("type") or "Propriété")
    alt = escape(item.get("alt") or item["address"])
    wow_delay = 2 + min(round(delay / 0.3) if delay else 0, 2)
    sold_class = " listing-card--sold" if item.get("sold") else ""
    if has_local_photo(item):
        media = f"""                <div class="listing-card__media">
                  <img src="{photo_prefix}{item['photo']}?v={PHOTO_CACHE}" alt="{alt}" width="800" height="500" loading="lazy" />
                  <span class="listing-card__type">{escape(badge)}</span>
                  <p class="listing-card__price">{escape(price)}</p>
                </div>"""
    else:
        media = f"""                <div class="listing-card__media listing-card__media--empty">
                  <span class="listing-card__type">{escape(badge)}</span>
                  <p class="listing-card__price">{escape(price)}</p>
                </div>"""
    return f"""            <article class="listing-card{sold_class} wow fadeInUp delay-0-{wow_delay}s">
              <a href="{href}">
{media}
                <div class="listing-card__body">
                  <h3>{escape(item['address'])}</h3>
                  <p class="listing-card__city"><i class="fal fa-map-marker-alt" aria-hidden="true"></i> {escape(item['city'])}</p>
                  {specs_html(item)}
                </div>
              </a>
            </article>"""


def meta_tags(title: str, description: str, canonical: str, image: str) -> str:
    safe_title = escape(title)
    safe_description = escape(description)
    safe_canonical = escape(canonical)
    safe_image = escape(image)
    return f"""    <title>{safe_title}</title>
    <meta name="description" content="{safe_description}" />
    <link rel="canonical" href="{safe_canonical}" />
    <meta property="og:locale" content="fr_CA" />
    <meta property="og:site_name" content="France Rémillard" />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="{safe_title}" />
    <meta property="og:description" content="{safe_description}" />
    <meta property="og:url" content="{safe_canonical}" />
    <meta property="og:image" content="{safe_image}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{safe_title}" />
    <meta name="twitter:description" content="{safe_description}" />
    <meta name="twitter:image" content="{safe_image}" />"""


def jsonld_script(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""    <script type="application/ld+json">
{body}
    </script>"""


def page_shell(
    title: str,
    description: str,
    base: str,
    current: str,
    body: str,
    canonical: str,
    og_image: str,
    structured: dict | None = None,
) -> str:
    header, footer = chrome(base, current)
    structured_html = f"\n{jsonld_script(structured)}" if structured else ""
    return f"""<!DOCTYPE html>
<html lang="fr-CA">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
{meta_tags(title, description, canonical, og_image)}
    <link rel="icon" href="{base}assets/images/favicon.svg" type="image/svg+xml" />{structured_html}
    <link rel="stylesheet" href="{base}theme/vendor/fontawesome-5.14.0.min.css" />
    <link rel="stylesheet" href="{base}css/styles.css" />
  </head>
  <body>
{header}
    <main id="contenu">
{body}
    </main>
{footer}
  </body>
</html>
"""


def render_listing_cards(items: list[dict], photo_prefix: str, link_prefix: str) -> str:
    return "\n".join(
        card_html(
            item,
            photo_prefix,
            f"{link_prefix}{item['id']}.html",
            delay=min(index, 2) * 0.3,
        )
        for index, item in enumerate(items)
    )


def listing_block(items: list[dict], photo_prefix: str, link_prefix: str, empty: str) -> str:
    if not items:
        return f'          <p class="empty-state">{empty}</p>'
    return f"""          <div class="listing-grid">
{render_listing_cards(items, photo_prefix, link_prefix)}
          </div>"""


def write_inscriptions_index(active: list[dict], sold: list[dict]) -> None:
    INSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    active_html = listing_block(
        active,
        "../",
        "",
        "Aucune inscription active pour le moment.",
    )
    sold_block = ""
    if sold:
        sold_html = listing_block(sold, "../", "", "Aucune vente récente à afficher.")
        sold_block = f"""
          <h2 class="listings-subhead">Récemment vendues</h2>
{sold_html}"""
    body = f"""      <section class="section">
        <div class="container">
          <h1>Inscriptions</h1>
          <p class="section__intro">Propriétés à vendre avec France Rémillard, Royal LePage Humania.</p>
{active_html}
{sold_block}
        </div>
      </section>"""
    html = page_shell(
        "Inscriptions immobilières | France Rémillard, Saint-Jérôme",
        "Maisons, condos, terrains et immeubles à vendre dans les Laurentides, à Laval et sur la couronne nord.",
        "../",
        "listings",
        body,
        canonical=site_url("/inscriptions/"),
        og_image=site_url("/" + HERO),
        structured=AGENT_LD,
    )
    (INSCRIPTIONS_DIR / "index.html").write_text(html, encoding="utf-8")


def listing_ld(item: dict) -> dict:
    path = f"/inscriptions/{item['id']}.html"
    data: dict = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": item.get("address") or "Inscription",
        "url": site_url(path),
        "description": listing_description(item),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": item.get("address") or "",
            "addressLocality": item.get("city") or "",
            "addressRegion": "QC",
            "addressCountry": "CA",
        },
        "broker": {"@id": AGENT_NODE},
    }
    if item.get("postal"):
        data["address"]["postalCode"] = item["postal"]
    if has_local_photo(item):
        data["image"] = site_url("/" + item["photo"])
    amount = sale_price(item)
    if amount:
        data["offers"] = {
            "@type": "Offer",
            "price": str(amount),
            "priceCurrency": "CAD",
            "url": site_url(path),
        }
    return data


def write_detail_pages(listings: list[dict]) -> None:
    keep = {f"{item['id']}.html" for item in listings}
    keep.add("index.html")
    for item in listings:
        status = "Vendue" if item["sold"] else item["price_label"] or "Sur demande"
        mls = f", MLS {escape(item['mls'])}" if item.get("mls") else ""
        city_line = escape(item["city"])
        if item.get("postal"):
            city_line = f"{city_line}, {escape(item['postal'])}"
        alt = escape(item.get("alt") or item["address"])
        if has_local_photo(item):
            media = f"""          <figure class="listing-detail__media">
            <img src="../{item['photo']}?v={PHOTO_CACHE}" alt="{alt}" width="1600" height="1200" />
          </figure>"""
        else:
            media = '          <figure class="listing-detail__media listing-card__media--empty"></figure>'
        body = f"""      <article class="section listing-detail">
        <div class="container listing-detail__grid">
{media}
          <div>
            <p class="listing-detail__price">{escape(status)}</p>
            <h1>{escape(item['address'])}</h1>
            <p class="section__intro">{city_line}</p>
            <p class="listing-detail__facts">{escape(facts(item))}{mls}</p>
            <div class="hero__actions">
              <a class="btn btn--primary" href="tel:+15143473786">Appeler</a>
              <a class="btn btn--ghost" href="{escape(item['url'])}" rel="noopener noreferrer">Fiche Royal LePage</a>
            </div>
          </div>
        </div>
      </article>"""
        image = site_url("/" + item["photo"]) if has_local_photo(item) else site_url("/" + PORTRAIT)
        html = page_shell(
            listing_title(item),
            listing_description(item),
            "../",
            "listings",
            body,
            canonical=site_url(f"/inscriptions/{item['id']}.html"),
            og_image=image,
            structured=listing_ld(item),
        )
        (INSCRIPTIONS_DIR / f"{item['id']}.html").write_text(html, encoding="utf-8")
    for stale in INSCRIPTIONS_DIR.glob("*.html"):
        if stale.name not in keep:
            stale.unlink()


def update_home_listings(active: list[dict]) -> None:
    featured = pick_featured(active)
    cards = listing_block(
        featured,
        "",
        "inscriptions/",
        "Aucune inscription active pour le moment.",
    )
    block = f"""{cards}
                <p class="text-center mt-50">
                    <a class="theme-btn" href="inscriptions/">Toutes les inscriptions</a>
                </p>"""
    text = INDEX_HTML.read_text(encoding="utf-8")
    if MARKER_START not in text or MARKER_END not in text:
        raise RuntimeError("index.html is missing SYNC:LISTINGS markers")
    start = text.index(MARKER_START) + len(MARKER_START)
    end = text.index(MARKER_END)
    INDEX_HTML.write_text(text[:start] + "\n" + block + "\n          " + text[end:], encoding="utf-8")


def write_sitemap(listings: list[dict]) -> None:
    urls = [
        site_url("/"),
        site_url("/inscriptions/"),
        site_url("/secteurs/"),
        site_url("/secteurs/laurentides.html"),
        site_url("/secteurs/laval.html"),
        site_url("/secteurs/couronne-nord.html"),
    ]
    urls.extend(site_url(f"/inscriptions/{item['id']}.html") for item in listings)
    items = "\n".join(
        f"  <url>\n    <loc>{url}</loc>\n    <changefreq>daily</changefreq>\n  </url>" for url in urls
    )
    SITEMAP.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n"
        "</urlset>\n",
        encoding="utf-8",
    )


def load_snapshot() -> dict:
    if not LISTINGS_JSON.exists():
        return {}
    try:
        payload = json.loads(LISTINGS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(listings: list[dict], synced_at: str) -> None:
    LISTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "synced_at": synced_at,
        "source": FEED_URL.format(agent=AGENT_ID, page=1),
        "count": len(listings),
        "listings": listings,
    }
    LISTINGS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    try:
        listings = fetch_all_listings()
    except Exception as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    if not listings and LISTINGS_JSON.exists():
        print("no listings parsed, keeping previous snapshot", file=sys.stderr)
        return 1
    previous = load_snapshot()
    previous_listings = previous.get("listings") or []
    unchanged = previous_listings == listings
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    synced_at = previous.get("synced_at") if unchanged and previous.get("synced_at") else now
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    INSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    needs_photos = (not unchanged) or any(photo_is_small(ROOT / item["photo"]) for item in listings)
    if needs_photos:
        download_photos(listings, force=not unchanged)
    else:
        print("listing data unchanged, refreshing pages only")
    write_json(listings, synced_at)
    active = [item for item in listings if not item["sold"]]
    sold = [item for item in listings if item["sold"]]
    write_inscriptions_index(active, sold)
    write_detail_pages(listings)
    update_home_listings(active)
    write_sitemap(listings)
    print(f"synced {len(listings)} listings ({len(active)} active, {len(sold)} sold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
