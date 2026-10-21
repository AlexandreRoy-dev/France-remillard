#!/usr/bin/env python3
"""Fetch France Rémillard listings from Royal LePage and rebuild static pages."""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape, unescape
from io import BytesIO
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
PHOTO_CACHE = "q82"
THUMB_SUFFIXES = ("_med.jpg", "_lg.jpg", "_sml.jpg", "_sm.jpg")
MIN_PHOTO_BYTES = 80_000
JPEG_QUALITY = 82
JPEG_MAX_EDGE = 1920
# A second pass at the same quality saves well under 3%. Skip it so the
# scheduled sync does not rewrite photos that are already compressed.
JPEG_MIN_RATIO = 0.97
SITE = "https://franceremillard.com"
AGENT_NODE_ID = f"{SITE}/#agent"
DEFAULT_OG_IMAGE = f"{SITE}/assets/images/maison-banlieue.webp"

CTX = ssl.create_default_context()


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


def compress_listing_jpeg(path: Path) -> None:
    """Shrink a listing photo in place. Skip files that are already small."""
    if not path.is_file() or path.stat().st_size < MIN_PHOTO_BYTES:
        return
    try:
        from PIL import Image
    except ImportError:
        print("pillow missing, listing photo left unchanged", file=sys.stderr)
        return
    original = path.read_bytes()
    with Image.open(BytesIO(original)) as image:
        rgb = image.convert("RGB")
        if max(rgb.size) > JPEG_MAX_EDGE:
            rgb.thumbnail((JPEG_MAX_EDGE, JPEG_MAX_EDGE), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        rgb.save(
            buffer,
            "JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
            subsampling=2,
        )
    data = buffer.getvalue()
    if len(data) >= MIN_PHOTO_BYTES and len(data) < len(original) * JPEG_MIN_RATIO:
        path.write_bytes(data)


def compress_listing_photos() -> None:
    if not PHOTO_DIR.is_dir():
        return
    for path in PHOTO_DIR.glob("*.jpg"):
        compress_listing_jpeg(path)


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
                item["photo_remote"] = candidate
                saved = True
                break
            except urllib.error.URLError as exc:
                last_error = exc
        if saved:
            compress_listing_jpeg(dest)
        else:
            print(f"photo failed {item['id']}: {last_error}", file=sys.stderr)
    for stale in PHOTO_DIR.glob("*.jpg"):
        if stale.name not in keep:
            stale.unlink()


def abs_url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    cleaned = path.strip()
    while cleaned.startswith("../"):
        cleaned = cleaned[3:]
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned in ("", "/"):
        return f"{SITE}/"
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return f"{SITE}{cleaned}"


def json_ld_script(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    return f'    <script type="application/ld+json">\n{payload}\n    </script>'


def agent_node() -> dict:
    return {
        "@type": "RealEstateAgent",
        "@id": AGENT_NODE_ID,
        "name": "France Rémillard",
        "url": f"{SITE}/",
        "image": f"{SITE}/assets/images/france-remillard.webp",
        "jobTitle": "Courtière immobilière",
        "telephone": "+1-514-347-3786",
        "email": "franceremillard@gmail.com",
        "knowsLanguage": ["fr-CA", "en"],
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
        "worksFor": {"@type": "Organization", "name": "Royal LePage Humania"},
        "contactPoint": [
            {
                "@type": "ContactPoint",
                "telephone": "+1-514-347-3786",
                "contactType": "Téléphone",
                "availableLanguage": ["fr-CA", "en"],
            },
            {
                "@type": "ContactPoint",
                "telephone": "+1-450-438-6868",
                "contactType": "Bureau",
                "availableLanguage": ["fr-CA", "en"],
            },
        ],
        "sameAs": [
            "https://www.royallepage.ca/fr/agent/quebec/saint-jerome/france-remillard/53785/",
            "https://www.centris.ca/fr/courtier-immobilier~france-remillard~royal-lepage-humania/d4337",
        ],
        "hasCredential": [
            {
                "@type": "EducationalOccupationalCredential",
                "name": "REIS, Real Estate Investment Specialist",
            },
            {"@type": "EducationalOccupationalCredential", "name": "Permis de l'OACIQ"},
        ],
        "award": [
            "2025, Attestation d'excellence, nouveau membre à vie",
            "2024, Attestation platine de directeur",
            "2023-2024, Membre Cercle Sélect",
            "2022-2024, Top 10 % national",
            "2020-2023, Palme d'or du président",
        ],
    }


def website_node() -> dict:
    return {
        "@type": "WebSite",
        "@id": f"{SITE}/#website",
        "url": f"{SITE}/",
        "name": "France Rémillard",
        "inLanguage": "fr-CA",
        "publisher": {"@id": AGENT_NODE_ID},
    }


def graph_script(*nodes: dict) -> str:
    return json_ld_script({"@context": "https://schema.org", "@graph": list(nodes)})


def social_meta(title: str, description: str, canonical: str, image: str) -> str:
    return f"""    <link rel="canonical" href="{escape(canonical)}" />
    <link rel="alternate" hreflang="fr-CA" href="{escape(canonical)}" />
    <link rel="alternate" hreflang="x-default" href="{escape(canonical)}" />
    <meta property="og:locale" content="fr_CA" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="France Rémillard" />
    <meta property="og:title" content="{escape(title)}" />
    <meta property="og:description" content="{escape(description)}" />
    <meta property="og:url" content="{escape(canonical)}" />
    <meta property="og:image" content="{escape(image)}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{escape(title)}" />
    <meta name="twitter:description" content="{escape(description)}" />
    <meta name="twitter:image" content="{escape(image)}" />"""


def listing_alt(item: dict) -> str:
    parts = [item.get("address") or "", item.get("city") or "", item.get("postal") or ""]
    text = ", ".join(part for part in parts if part)
    return text or item.get("alt") or "Propriété"


def listing_copy(item: dict) -> tuple[str, str]:
    address = item.get("address") or "Inscription"
    city = item.get("city") or ""
    place = f"{address}, {city}" if city else address
    title = f"{place} | France Rémillard"
    kind = item.get("type") or "Propriété"
    price = display_price(item)
    if item.get("sold") or price == "Vendue":
        lead = f"{kind} vendue, {place}."
    elif price and price != "Sur demande":
        lead = f"{kind} à {price}, {place}."
    else:
        lead = f"{kind}, {place}."
    description = f"{lead} France Rémillard, Royal LePage Humania."
    if len(description) > 160:
        description = f"{lead} France Rémillard."
    if len(description) > 160:
        description = lead
    return title, description


def postal_address(item: dict) -> dict:
    address = {
        "@type": "PostalAddress",
        "streetAddress": item.get("address") or "",
        "addressLocality": item.get("city") or "",
        "addressRegion": "QC",
        "addressCountry": "CA",
    }
    if item.get("postal"):
        address["postalCode"] = item["postal"]
    return address


def offer_node(item: dict) -> dict | None:
    seller = {"@id": AGENT_NODE_ID}
    if item.get("sold"):
        return {
            "@type": "Offer",
            "availability": "https://schema.org/SoldOut",
            "priceCurrency": "CAD",
            "seller": seller,
        }
    label = display_price(item)
    rent = re.match(r"^(\d+(?:[.,]\d+)?)\s*\$\s*/\s*mois", label, re.I)
    if rent:
        price = rent.group(1).replace(",", ".")
        return {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "CAD",
            "availability": "https://schema.org/InStock",
            "seller": seller,
            "priceSpecification": {
                "@type": "UnitPriceSpecification",
                "price": price,
                "priceCurrency": "CAD",
                "unitText": "mois",
            },
        }
    sale = re.match(r"^(\d[\d\s]*)\s*\$", label)
    if sale:
        digits = re.sub(r"\s+", "", sale.group(1))
        if digits:
            return {
                "@type": "Offer",
                "price": int(digits),
                "priceCurrency": "CAD",
                "availability": "https://schema.org/InStock",
                "seller": seller,
            }
    return None


def about_node(item: dict) -> dict:
    kind = item.get("type") or ""
    schema_type = {"Maison": "House", "Copropriété": "Apartment", "Fermette": "Residence"}.get(kind, "Place")
    about = {"@type": schema_type, "name": item.get("address") or "", "address": postal_address(item)}
    bedrooms = item.get("bedrooms") or ""
    if bedrooms.isdigit() and schema_type in {"House", "Apartment", "Residence"}:
        about["numberOfBedrooms"] = int(bedrooms)
    baths = clean_baths(item.get("bathrooms") or "")
    if baths.isdigit() and schema_type in {"House", "Apartment", "Residence"}:
        about["numberOfBathroomsTotal"] = int(baths)
    return about


def listing_graph(item: dict, canonical: str, description: str, image: str | None) -> str:
    node = {
        "@type": "RealEstateListing",
        "name": item.get("address") or "Inscription",
        "url": canonical,
        "description": description,
        "inLanguage": "fr-CA",
        "address": postal_address(item),
        "about": about_node(item),
        "seller": {
            "@type": "RealEstateAgent",
            "@id": AGENT_NODE_ID,
            "name": "France Rémillard",
            "url": f"{SITE}/",
            "telephone": "+1-514-347-3786",
        },
    }
    if image:
        node["image"] = image
    if item.get("url"):
        node["sameAs"] = item["url"]
    if item.get("mls"):
        node["identifier"] = {"@type": "PropertyValue", "name": "MLS", "value": item["mls"]}
    offer = offer_node(item)
    if offer:
        node["offers"] = offer
    crumbs = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Accueil", "item": f"{SITE}/"},
            {"@type": "ListItem", "position": 2, "name": "Inscriptions", "item": f"{SITE}/inscriptions/"},
            {"@type": "ListItem", "position": 3, "name": item.get("address") or "Inscription", "item": canonical},
        ],
    }
    return graph_script(node, crumbs)


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
          <img class="brand__logo" src="{base}assets/images/logo-royal-lepage.png" alt="Royal LePage" width="600" height="221" />
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
          <img class="brand__logo footer-logo" src="{base}assets/images/logo-royal-lepage.png" alt="Royal LePage" width="180" height="66" />
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
    alt = escape(listing_alt(item))
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


def page_shell(
    title: str,
    description: str,
    base: str,
    current: str,
    body: str,
    canonical: str = "/inscriptions/",
    og_image: str | None = None,
    json_ld: str = "",
) -> str:
    header, footer = chrome(base, current)
    image = abs_url(og_image) if og_image else DEFAULT_OG_IMAGE
    canon = abs_url(canonical)
    ld = f"\n{json_ld}" if json_ld else ""
    return f"""<!DOCTYPE html>
<html lang="fr-CA">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <meta name="description" content="{escape(description)}" />
{social_meta(title, description, canon, image)}
    <link rel="icon" href="{base}assets/images/favicon.svg" type="image/svg+xml" />
    <link rel="stylesheet" href="{base}theme/vendor/fontawesome-5.14.0.min.css" />
    <link rel="stylesheet" href="{base}css/styles.css" />
  </head>
  <body>
{header}
    <main id="contenu">
{body}
    </main>
{footer}{ld}
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
    title = "Inscriptions à vendre, Laurentides et Laval | France Rémillard"
    description = "Maisons, condos, terrains et immeubles à vendre dans les Laurentides et à Laval, avec France Rémillard."
    elements = []
    position = 1
    for item in active + sold:
        elements.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": item.get("address") or "Inscription",
                "url": f"{SITE}/inscriptions/{item['id']}.html",
            }
        )
        position += 1
    item_list = {
        "@type": "ItemList",
        "name": "Inscriptions",
        "url": f"{SITE}/inscriptions/",
        "numberOfItems": len(elements),
        "itemListElement": elements,
    }
    html = page_shell(
        title,
        description,
        "../",
        "listings",
        body,
        canonical="/inscriptions/",
        json_ld=graph_script(agent_node(), website_node(), item_list),
    )
    (INSCRIPTIONS_DIR / "index.html").write_text(html, encoding="utf-8")


def write_detail_pages(listings: list[dict]) -> None:
    keep = {f"{item['id']}.html" for item in listings}
    keep.add("index.html")
    for item in listings:
        status = "Vendue" if item["sold"] else item["price_label"] or "Sur demande"
        mls = f", MLS {escape(item['mls'])}" if item.get("mls") else ""
        city_line = escape(item["city"])
        if item.get("postal"):
            city_line = f"{city_line}, {escape(item['postal'])}"
        alt = escape(listing_alt(item))
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
        title, description = listing_copy(item)
        canonical = f"/inscriptions/{item['id']}.html"
        image = abs_url(item["photo"]) if has_local_photo(item) else None
        html = page_shell(
            title,
            description,
            "../",
            "listings",
            body,
            canonical=canonical,
            og_image=image,
            json_ld=listing_graph(item, abs_url(canonical), description, image),
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
        f"{SITE}/",
        f"{SITE}/inscriptions/",
        f"{SITE}/secteurs/",
        f"{SITE}/secteurs/laurentides.html",
        f"{SITE}/secteurs/laval.html",
        f"{SITE}/secteurs/couronne-nord.html",
    ]
    urls.extend(f"{SITE}/inscriptions/{item['id']}.html" for item in listings)
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
    compress_listing_photos()
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
