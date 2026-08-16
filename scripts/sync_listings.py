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

CTX = ssl.create_default_context()


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


def download_photos(listings: list[dict]) -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    keep = set()
    for item in listings:
        dest = ROOT / item["photo"]
        keep.add(dest.name)
        if not item.get("photo_remote"):
            continue
        try:
            dest.write_bytes(fetch(item["photo_remote"]))
        except urllib.error.URLError as exc:
            print(f"photo failed {item['id']}: {exc}", file=sys.stderr)
    for stale in PHOTO_DIR.glob("*.jpg"):
        if stale.name not in keep:
            stale.unlink()


def nav_html(base: str, current: str) -> str:
    links = [
        (f"{base}index.html", "Accueil", "home"),
        (f"{base}inscriptions/", "Inscriptions", "listings"),
        (f"{base}index.html#parcours", "Parcours", "parcours"),
        (f"{base}index.html#services", "Services", "services"),
        (f"{base}index.html#contact", "Contact", "contact"),
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
        <a class="brand" href="{base}index.html">
          <img class="brand__logo" src="{base}assets/images/logo-royal-lepage.png" alt="Royal LePage" width="600" height="221" />
          <span class="brand__meta">
            <span class="brand__office">Humania</span>
            <span class="brand__name">France Rémillard</span>
          </span>
        </a>
        <nav class="site-nav" id="menu-mobile" data-nav-panel aria-label="Navigation principale">
{nav_html(base, current)}
        </nav>
        <div class="header-actions">
          <a class="btn btn--primary" href="tel:+15143473786">514 347-3786</a>
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
            France Rémillard, courtière immobilière, Royal LePage Humania. Titulaire d'un
            permis de l'OACIQ. 401, rue Laviolette, Saint-Jérôme (Québec) J7Y 2T2.
          </p>
        </div>
        <div>
          <ul class="footer-links">
            <li><a href="{base}inscriptions/">Inscriptions</a></li>
            <li><a href="https://www.royallepage.ca/fr/agent/quebec/saint-jerome/france-remillard/53785/" rel="noopener noreferrer">Profil Royal LePage</a></li>
            <li><a href="https://www.centris.ca/fr/courtier-immobilier~france-remillard~royal-lepage-humania/d4337" rel="noopener noreferrer">Inscriptions Centris</a></li>
            <li><a href="https://www.oaciq.com/" rel="noopener noreferrer">OACIQ</a></li>
            <li><a href="tel:+15143473786">514 347-3786</a></li>
          </ul>
          <p class="footer-note">
            Les inscriptions sont synchronisées depuis Royal LePage. Les renseignements du
            formulaire servent uniquement à vous répondre.
          </p>
        </div>
      </div>
    </footer>
    <script type="module" src="{base}js/main.js"></script>"""
    return header, footer


def facts(item: dict) -> str:
    bits = [item["type"]] if item.get("type") else []
    if item.get("bedrooms"):
        bits.append(f"{item['bedrooms']} ch.")
    baths = item.get("bathrooms") or ""
    if baths.endswith("+0"):
        baths = baths[:-2]
    if baths:
        bits.append(f"{baths} sdb")
    return ", ".join(bits)


def has_local_photo(item: dict) -> bool:
    path = ROOT / item["photo"]
    return path.is_file() and path.stat().st_size > 0


def card_html(item: dict, photo_prefix: str, href: str, delay: float = 0) -> str:
    price = item["price_label"] or "Sur demande"
    if item["sold"]:
        price = f"Vendue, {price}" if price not in {"Vendue", ""} else "Vendue"
    alt = escape(item.get("alt") or item["address"])
    delay_attr = f' data-animation-delay-in-seconds="{delay:g}"' if delay else ""
    if has_local_photo(item):
        media = f"""                <div class="listing-card__media">
                  <img src="{photo_prefix}{item['photo']}" alt="{alt}" width="800" height="600" loading="lazy" />
                </div>"""
    else:
        media = '                <div class="listing-card__media listing-card__media--empty" aria-hidden="true"></div>'
    return f"""            <article class="listing-card animIn"{delay_attr}>
              <a href="{href}">
{media}
                <p class="listing-card__price">{escape(price)}</p>
                <h3>{escape(item['address'])}</h3>
                <p class="listing-card__meta">{escape(item['city'])}</p>
                <p class="listing-card__meta">{escape(facts(item))}</p>
              </a>
            </article>"""


def page_shell(
    title: str,
    description: str,
    base: str,
    current: str,
    body: str,
    canonical: str = "./",
    og_image: str | None = None,
) -> str:
    header, footer = chrome(base, current)
    image = og_image or f"{base}assets/images/france-remillard.jpg"
    return f"""<!DOCTYPE html>
<html lang="fr-CA">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <meta name="description" content="{escape(description)}" />
    <link rel="canonical" href="{escape(canonical)}" />
    <link rel="icon" href="{base}assets/images/favicon.svg" type="image/svg+xml" />
    <meta property="og:title" content="{escape(title)}" />
    <meta property="og:description" content="{escape(description)}" />
    <meta property="og:image" content="{escape(image)}" />
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
          <p class="section__intro">Propriétés à vendre avec France Rémillard, Royal LePage Humania. Mis à jour automatiquement depuis Royal LePage.</p>
{active_html}
{sold_block}
        </div>
      </section>"""
    html = page_shell(
        "Inscriptions | France Rémillard",
        "Maisons, condos, terrains et immeubles à vendre dans les Laurentides et à Laval.",
        "../",
        "listings",
        body,
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
        alt = escape(item.get("alt") or item["address"])
        if has_local_photo(item):
            media = f"""          <figure class="listing-detail__media">
            <img src="../{item['photo']}" alt="{alt}" width="1200" height="900" />
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
            <p class="listing-detail__note">Les photos et le prix proviennent de Royal LePage. Vérifiez la fiche officielle avant une visite.</p>
          </div>
        </div>
      </article>"""
        html = page_shell(
            f"{item['address']} | France Rémillard",
            f"{item['address']}, {item['city']}. Inscription Royal LePage Humania.",
            "../",
            "listings",
            body,
            canonical=f"{item['id']}.html",
            og_image=f"../{item['photo']}" if has_local_photo(item) else None,
        )
        (INSCRIPTIONS_DIR / f"{item['id']}.html").write_text(html, encoding="utf-8")
    for stale in INSCRIPTIONS_DIR.glob("*.html"):
        if stale.name not in keep:
            stale.unlink()


def update_home_listings(active: list[dict]) -> None:
    featured = active[:3]
    cards = listing_block(
        featured,
        "",
        "inscriptions/",
        "Aucune inscription active pour le moment.",
    )
    block = f"""{cards}
          <p class="listings-more">
            <a class="btn btn--ghost" href="inscriptions/">Toutes les inscriptions</a>
          </p>"""
    text = INDEX_HTML.read_text(encoding="utf-8")
    if MARKER_START not in text or MARKER_END not in text:
        raise RuntimeError("index.html is missing SYNC:LISTINGS markers")
    start = text.index(MARKER_START) + len(MARKER_START)
    end = text.index(MARKER_END)
    INDEX_HTML.write_text(text[:start] + "\n" + block + "\n          " + text[end:], encoding="utf-8")


def write_sitemap(listings: list[dict]) -> None:
    urls = ["./", "./inscriptions/"]
    urls.extend(f"./inscriptions/{item['id']}.html" for item in listings)
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
    if unchanged:
        print("listing data unchanged, refreshing pages only")
    else:
        download_photos(listings)
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
