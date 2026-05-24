"""
TAG Grading DIG Report Scraper.

Scrapes TAG grading reports to build a training dataset for defect detection models.

Usage:
    # Scrape a single card
    python scripts/scrape_tag.py --cert R4937803

    # Scrape from pop report (discover + scrape)
    python scripts/scrape_tag.py --category Pokemon --limit 100

    # Scrape from a file of cert numbers
    python scripts/scrape_tag.py --certs-file data/tag_certs.txt --limit 50

    # Download images only (metadata already scraped)
    python scripts/scrape_tag.py --download-only --limit 50

    # Convert to YOLO annotations
    python scripts/scrape_tag.py --convert-only

    # Show dataset stats
    python scripts/scrape_tag.py --stats
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://my.taggrading.com"
# TAG migrated images from S3 to CloudFront ~Apr 2026; keep both for legacy URLs.
S3_BASE = "https://d39lwrz0lm7c9r.cloudfront.net/card-images"
LEGACY_S3_BASE = "https://devblock-tag.s3.us-west-2.amazonaws.com/card-images"
DATA_DIR = Path("data/tag_raw")
DATASET_DIR = Path("data/tag_dataset")
DB_PATH = DATA_DIR / "scraper.db"

# Polite scraping
REQUEST_DELAY = 1.0  # seconds between page loads
CONCURRENT_DOWNLOADS = 5  # parallel HTTP requests per card (img download)
CARD_DOWNLOAD_CONCURRENCY = 12  # cards processed in parallel during Phase 3
HTTP_CONNECTOR_LIMIT = 40  # total in-flight HTTP connections to CDN
PAGE_TIMEOUT = 45_000  # ms — TAG SPA is slow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tag_scraper")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SurfaceDefect:
    id: int
    side: str           # "front" / "back"
    defect_type: str    # "Pit", "Scratch(es)", "Print Line(s)", etc.
    x: int              # pixel x on 4463×6161 image
    y: int              # pixel y
    region: int         # card region number


@dataclass
class CornerDetail:
    position: str   # "top_left", "top_right", "bottom_left", "bottom_right"
    side: str       # "front" / "back"
    total: int = 0
    fray: int = 0
    fill: int = 0
    csw: int = 0
    angle: Optional[int] = None


@dataclass
class EdgeDetail:
    position: str   # "top", "bottom", "left", "right"
    side: str       # "front" / "back"
    total: int = 0
    fray: int = 0
    fill: int = 0
    esw: int = 0


@dataclass
class TagReport:
    cert: str = ""
    card_name: str = ""
    card_set: str = ""

    # Overall scores
    tag_score: int = 0
    grade: float = 0.0
    grade_label: str = ""
    front_score: int = 0
    back_score: int = 0

    # Sub-grades (1000-point)
    centering_front: int = 0
    centering_back: int = 0
    corners_front: int = 0
    corners_back: int = 0
    edges_front: int = 0
    edges_back: int = 0
    surface_front: int = 0
    surface_back: int = 0

    # Centering ratios
    centering_front_lr: str = ""  # "51.83/48.17"
    centering_front_tb: str = ""  # "48.77/51.23"
    centering_back_lr: str = ""
    centering_back_tb: str = ""

    # Dimensions
    height_inches: str = ""
    width_inches: str = ""

    # DINGS counts
    dings_corners_front: int = 0
    dings_corners_back: int = 0
    dings_edges_front: int = 0
    dings_edges_back: int = 0
    dings_surface_front: int = 0
    dings_surface_back: int = 0

    # Detailed measurements
    corners: list[CornerDetail] = field(default_factory=list)
    edges: list[EdgeDetail] = field(default_factory=list)
    surface_defects: list[SurfaceDefect] = field(default_factory=list)

    # Image URLs
    image_uuid: str = ""
    s3_image_urls: list[str] = field(default_factory=list)

    # Population
    pop_gem_mint: int = 0
    pop_total: int = 0

    # Metadata
    has_dig_plus: bool = False  # True if full Surface Details available
    scrape_timestamp: str = ""


# ---------------------------------------------------------------------------
# Database for tracking progress
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            cert TEXT PRIMARY KEY,
            status TEXT DEFAULT 'pending',
            has_dig_plus INTEGER DEFAULT 0,
            tag_score INTEGER DEFAULT 0,
            grade REAL DEFAULT 0,
            num_defects INTEGER DEFAULT 0,
            num_images_downloaded INTEGER DEFAULT 0,
            metadata_json TEXT,
            error TEXT,
            scraped_at TEXT,
            downloaded_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cert_discovery (
            category TEXT,
            year TEXT,
            set_name TEXT,
            cert TEXT,
            grade REAL DEFAULT 0,
            tag_score INTEGER DEFAULT 0,
            grade_label TEXT DEFAULT '',
            card_name TEXT DEFAULT '',
            discovered_at TEXT,
            PRIMARY KEY (category, cert)
        )
    """)
    # Add grade columns if missing (migration for existing DBs)
    try:
        conn.execute("ALTER TABLE cert_discovery ADD COLUMN grade REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE cert_discovery ADD COLUMN tag_score INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE cert_discovery ADD COLUMN grade_label TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE cert_discovery ADD COLUMN card_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # Track which sets have been fully processed (for resume)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discovery_progress (
            category TEXT,
            year TEXT,
            set_name TEXT,
            card_name TEXT,
            completed_at TEXT,
            PRIMARY KEY (category, year, set_name, card_name)
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Phase 1: Cert Number Discovery
# ---------------------------------------------------------------------------

async def discover_certs_from_pop_report(
    category: str = "Pokémon",
    limit: int = 100,
    db: Optional[sqlite3.Connection] = None,
) -> list[str]:
    """Navigate TAG SPA pop report to discover cert numbers.

    The site is a React SPA — there are no static <a href="/pop-report/...">
    links.  Instead we must:
      1. Open /pop-report
      2. Click the POKÉMON category tile
      3. Read year rows from the table
      4. For each year, click the row, scrape set links, visit each set,
         then visit each card page and extract cert numbers via regex.
    """
    from playwright.async_api import async_playwright

    certs: list[str] = []
    seen: set[str] = set()
    log.info(f"Discovering certs from pop report: {category} (limit={limit})")

    # Pre-load already-discovered certs so we can skip fully-processed sets
    already_discovered: dict[str, set[str]] = {}  # "year/set_name" -> {certs}
    if db:
        rows = db.execute(
            "SELECT year, set_name, cert FROM cert_discovery WHERE category = ?",
            (category,),
        ).fetchall()
        for yr, sn, c in rows:
            key = f"{yr}/{sn}"
            already_discovered.setdefault(key, set()).add(c)
            seen.add(c)
        if seen:
            log.info(f"Resuming — {len(seen)} certs already in cert_discovery")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Step 1: Go to pop-report landing page
        await page.goto(f"{BASE_URL}/pop-report", timeout=PAGE_TIMEOUT)
        await asyncio.sleep(3)

        # Step 2: Click the POKÉMON category tile
        await page.click('div.MuiGrid-item >> text=/POK/')
        await asyncio.sleep(3)

        # Step 3: Extract available years from the table
        years = await page.evaluate('''() => {
            const years = [];
            document.querySelectorAll('tr').forEach(tr => {
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 2) {
                    const text = cells[0].textContent.trim();
                    if (/^\\d{4}$/.test(text)) years.push(text);
                }
            });
            return years;
        }''')
        # Oldest first: old cards have more wear = more defects for training
        years = sorted(years)
        log.info(f"Found {len(years)} years (oldest first): {years}")

        for year in years:
            if len(certs) >= limit:
                break

            # Navigate back to category page and click the year row
            await page.goto(f"{BASE_URL}/pop-report", timeout=PAGE_TIMEOUT)
            await asyncio.sleep(3)
            await page.click('div.MuiGrid-item >> text=/POK/')
            await asyncio.sleep(3)
            await page.click(f'td >> text="{year}"')
            await asyncio.sleep(3)

            # Get set links: <a> tags whose href contains /pop-report/Pok AND the year
            set_links = await page.evaluate('''(year) => {
                const links = [];
                document.querySelectorAll('a').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const text = a.textContent.trim();
                    if (href.includes('/pop-report/Pok') && href.includes(year)) {
                        // Filter out breadcrumb-style links (short text or navigation)
                        const isBreadcrumb = a.closest('nav') !== null
                            || a.closest('[class*="breadcrumb" i]') !== null
                            || text.length < 2;
                        if (!isBreadcrumb) {
                            links.push({text: text, href: href});
                        }
                    }
                });
                return links;
            }''', year)
            log.info(f"  Year {year}: found {len(set_links)} sets")

            for set_link in set_links:
                if len(certs) >= limit:
                    break

                set_name = set_link["text"]
                set_href = set_link["href"]

                # Skip non-TCG sets (Topps photo cards/stickers, Burger King promos, Roll-Ups)
                lname = set_name.lower()
                if any(s in lname for s in ["topps", "burger king", "roll-ups"]):
                    continue
                if lname.endswith("stickers"):
                    continue

                # Build full URL if relative
                set_url = set_href if set_href.startswith("http") else f"{BASE_URL}{set_href}"

                # Navigate to the set page
                await page.goto(set_url, timeout=PAGE_TIMEOUT)
                await asyncio.sleep(3)

                # Get card links: <a> tags with deeper paths (more segments)
                card_links = await page.evaluate('''() => {
                    const links = [];
                    document.querySelectorAll('a').forEach(a => {
                        const href = a.getAttribute('href') || '';
                        if (href.includes('/pop-report/Pok') && href.split('/').length > 6) {
                            const text = a.textContent.trim();
                            const isBreadcrumb = a.closest('nav') !== null
                                || a.closest('[class*="breadcrumb" i]') !== null
                                || text.length < 2;
                            if (!isBreadcrumb) {
                                links.push({text: text, href: href});
                            }
                        }
                    });
                    return links;
                }''')

                set_cert_count = 0
                for card_link in card_links:
                    if len(certs) >= limit:
                        break

                    card_name = card_link["text"]
                    card_href = card_link["href"]
                    card_url = card_href if card_href.startswith("http") else f"{BASE_URL}{card_href}"

                    # Resume: skip already-processed cards
                    if db:
                        already = db.execute(
                            "SELECT 1 FROM discovery_progress WHERE category=? AND year=? AND set_name=? AND card_name=?",
                            (category, year, set_name, card_name),
                        ).fetchone()
                        if already:
                            continue

                    try:
                        await page.goto(card_url, timeout=PAGE_TIMEOUT)
                        await asyncio.sleep(3)
                    except Exception as e:
                        log.warning(f"    Failed to load {card_name}: {str(e)[:60]}")
                        continue

                    # Extract cert numbers WITH grade info from table
                    page_entries = await _extract_certs_with_grades(page)

                    # Handle pagination
                    while True:
                        has_next = await page.evaluate('''() => {
                            const selected = document.querySelector(
                                'button.Mui-selected, [aria-current="true"]'
                            );
                            if (selected) {
                                const next = selected.closest('li')?.nextElementSibling
                                    ?.querySelector('button:not([disabled])');
                                if (next) return true;
                            }
                            for (const el of document.querySelectorAll('button, a')) {
                                const t = el.textContent.trim();
                                if ((t === '>' || t === '›') && !el.disabled) return true;
                            }
                            return false;
                        }''')

                        if not has_next:
                            break

                        clicked = await page.evaluate('''() => {
                            const selected = document.querySelector(
                                'button.Mui-selected, [aria-current="true"]'
                            );
                            if (selected) {
                                const next = selected.closest('li')?.nextElementSibling
                                    ?.querySelector('button:not([disabled])');
                                if (next) { next.click(); return true; }
                            }
                            for (const el of document.querySelectorAll('button, a')) {
                                const t = el.textContent.trim();
                                if ((t === '>' || t === '›') && !el.disabled) {
                                    el.click(); return true;
                                }
                            }
                            return false;
                        }''')

                        if not clicked:
                            break

                        await asyncio.sleep(3)
                        new_entries = await _extract_certs_with_grades(page)
                        existing_certs = {e["cert"] for e in page_entries}
                        for entry in new_entries:
                            if entry["cert"] not in existing_certs:
                                page_entries.append(entry)
                                existing_certs.add(entry["cert"])

                    # Save all discovered certs with grade info
                    for entry in page_entries:
                        cert_num = entry["cert"]
                        if len(certs) >= limit:
                            break
                        if cert_num not in seen:
                            seen.add(cert_num)
                            certs.append(cert_num)
                            set_cert_count += 1
                            if db:
                                db.execute(
                                    """INSERT OR IGNORE INTO cert_discovery
                                       (category, year, set_name, cert, grade, tag_score, grade_label, card_name, discovered_at)
                                       VALUES (?,?,?,?,?,?,?,?,datetime('now'))""",
                                    (category, year, set_name, cert_num,
                                     entry.get("grade", 0), entry.get("tagScore", 0),
                                     entry.get("gradeLabel", ""), card_name),
                                )

                    # Mark card as processed for resume
                    if db:
                        db.execute(
                            "INSERT OR IGNORE INTO discovery_progress VALUES (?,?,?,?,datetime('now'))",
                            (category, year, set_name, card_name),
                        )
                        db.commit()

                log.info(
                    f"  {year}/{set_name}: "
                    f"+{set_cert_count} certs (total: {len(certs)})"
                )

        await browser.close()

    log.info(f"Discovered {len(certs)} cert numbers")
    return certs


async def _extract_certs_from_page(page) -> set[str]:
    """Extract cert numbers matching [A-Z]\\d{7} from page text content."""
    raw = await page.evaluate(
        "() => (document.body.textContent.match(/[A-Z]\\d{7}/g) || [])"
    )
    return set(raw)


async def _extract_certs_with_grades(page) -> list[dict]:
    """Extract cert numbers WITH grade info from pop report card table.

    The card page table looks like:
    Rank | TAG Grade           | View | ... | Cert
    1    | 9 MINT (935)        | View | ... | H7460255
    2    | 5 EX (532)          | View | ... | D2359792

    Returns list of dicts: [{cert, grade, tag_score, grade_label}, ...]
    """
    return await page.evaluate('''() => {
        const results = [];
        const rows = document.querySelectorAll('tr');
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length < 3) continue;

            // Find cert number in any cell
            let cert = null;
            for (const cell of cells) {
                const m = cell.textContent.trim().match(/^([A-Z]\\d{7})$/);
                if (m) { cert = m[1]; break; }
            }
            if (!cert) continue;

            // Find grade info - typically in 2nd column
            // Format: "9 MINT (935)" or "5 EX (532)" or "7.5 NM+ (787)" or "10 GEM MINT"
            let grade = 0;
            let tagScore = 0;
            let gradeLabel = '';

            for (const cell of cells) {
                const text = cell.textContent.trim();
                // Match patterns like "9 MINT (935)" or "5.5 EX+ (600)" or "10 GEM MINT"
                const gradeMatch = text.match(/^(\\d+\\.?\\d*)\\s+([A-Z][A-Z\\s+\\-]*?)(?:\\s*\\((\\d+)\\))?$/);
                if (gradeMatch) {
                    grade = parseFloat(gradeMatch[1]);
                    gradeLabel = gradeMatch[2].trim();
                    tagScore = gradeMatch[3] ? parseInt(gradeMatch[3]) : 0;
                    break;
                }
            }

            results.push({cert, grade, tagScore, gradeLabel});
        }
        return results;
    }''')


# ---------------------------------------------------------------------------
# Phase 2: Report Parsing
# ---------------------------------------------------------------------------

async def scrape_card_report(cert: str, page) -> TagReport:
    """Scrape a single TAG DIG report page."""
    report = TagReport(cert=cert)
    url = f"{BASE_URL}/card/{cert}"

    await page.goto(url, timeout=PAGE_TIMEOUT)
    # networkidle never settles on TAG (background polling), so wait on
    # actual report content instead — drops per-card load from ~20s to ~4s.
    await page.wait_for_load_state("domcontentloaded", timeout=PAGE_TIMEOUT)
    await page.wait_for_function(
        "document.body.textContent.includes('cert #')",
        timeout=PAGE_TIMEOUT,
    )

    # Get full page text for parsing
    text = await page.evaluate("document.body.textContent")

    # Check if report exists
    if "not found" in text.lower() or "error" in text.lower()[:200]:
        log.warning(f"  {cert}: report not found")
        return report

    # --- Card identity ---
    title_el = await page.query_selector("h1, h2, [class*='card-name'], [class*='title']")
    if title_el:
        report.card_name = (await title_el.text_content()).strip()

    # --- Extract TAG Score and Grade ---
    # Text format: "987TAG Score" or "987 TAG Score" (no space between number and TAG)
    tag_score_match = re.search(r'(\d{3,4})\s*TAG\s*Score', text)
    if tag_score_match:
        # The text often concatenates like "987TAG Score10" — extract just the score
        raw = tag_score_match.group(1)
        # If raw is 4 digits and > 1000, it's likely "9" from grade + "987" score → take last 3
        score_val = int(raw)
        if score_val > 1000 and len(raw) == 4:
            score_val = int(raw[1:])  # "9987" → "987"
        if 100 <= score_val <= 1000:
            report.tag_score = score_val
            report.has_dig_plus = True

    grade_match = re.search(r'(?<!\d)(\d+(?:\.\d)?)\s*(GEM MINT|MINT|NEAR MINT|NM-MT|EX-MT|EXCELLENT|VG|GOOD|FAIR|POOR)', text, re.IGNORECASE)
    if grade_match:
        report.grade = float(grade_match.group(1))
        report.grade_label = grade_match.group(2).strip()

    # --- Extract card image URLs ---
    # TAG serves card photos from CloudFront (d39lwrz0lm7c9r.cloudfront.net)
    # and historically from S3 (s3.us-west-2.amazonaws.com). Match either via the
    # shared "/card-images/" path so we keep working through CDN migrations.
    s3_urls = await page.evaluate("""
        () => [...document.querySelectorAll('img')]
            .map(i => i.src)
            .filter(s => s.includes('/card-images/'))
    """)
    report.s3_image_urls = s3_urls

    # Extract UUID from first image URL
    if s3_urls:
        uuid_match = re.search(r'/([a-f0-9-]{36})_', s3_urls[0])
        if uuid_match:
            report.image_uuid = uuid_match.group(1)

    # --- Parse sub-grades via JavaScript (more reliable than regex on raw text) ---
    sub_grades = await page.evaluate("""
        () => {
            const text = document.body.textContent;
            const result = {};

            // TAG Grading Summary section: "front 983 back 982"
            // and per-pillar: "centering Front: 990 Back: 995"
            const sections = ['centering', 'corners', 'surface', 'edges'];
            for (const s of sections) {
                const re = new RegExp(s + '[\\\\s\\\\S]*?Front[:\\\\s]*(\\\\d{3,4})[\\\\s\\\\S]*?Back[:\\\\s]*(\\\\d{3,4})', 'i');
                // Search only in the TAG grading summary area
                const summaryStart = text.indexOf('TAG grading summary') || text.indexOf('TAG GRADING SUMMARY');
                const chunk = summaryStart > 0 ? text.substring(summaryStart, summaryStart + 2000) : text;
                const m = chunk.match(re);
                if (m) {
                    result[s + '_front'] = parseInt(m[1]);
                    result[s + '_back'] = parseInt(m[2]);
                }
            }

            // Overall front/back scores: "front 983 back 982" right after overall score
            const fbMatch = text.match(/front\\s*(\\d{3})\\s*back\\s*(\\d{3})/i);
            if (fbMatch) {
                result['front_score'] = parseInt(fbMatch[1]);
                result['back_score'] = parseInt(fbMatch[2]);
            }

            return result;
        }
    """)

    report.centering_front = sub_grades.get("centering_front", 0)
    report.centering_back = sub_grades.get("centering_back", 0)
    report.corners_front = sub_grades.get("corners_front", 0)
    report.corners_back = sub_grades.get("corners_back", 0)
    report.surface_front = sub_grades.get("surface_front", 0)
    report.surface_back = sub_grades.get("surface_back", 0)
    report.edges_front = sub_grades.get("edges_front", 0)
    report.edges_back = sub_grades.get("edges_back", 0)
    report.front_score = sub_grades.get("front_score", 0)
    report.back_score = sub_grades.get("back_score", 0)

    # --- Centering ratios ---
    centering_raw = re.search(
        r'F:\s*([\d.]+L/[\d.]+R)\s*([\d.]+T/[\d.]+B)',
        text
    )
    if centering_raw:
        report.centering_front_lr = centering_raw.group(1)
        report.centering_front_tb = centering_raw.group(2)

    centering_back_raw = re.search(
        r'B:\s*([\d.]+L/[\d.]+R)\s*([\d.]+T/[\d.]+B)',
        text
    )
    if centering_back_raw:
        report.centering_back_lr = centering_back_raw.group(1)
        report.centering_back_tb = centering_back_raw.group(2)

    # Precise centering from diagram (C:51.83 format)
    precise_centering = re.findall(r'C[:\s]*([\d.]+)', text)
    if len(precise_centering) >= 4:
        report.centering_front_lr = f"{precise_centering[0]}/{precise_centering[1]}"
        report.centering_front_tb = f"{precise_centering[2]}/{precise_centering[3]}"

    # --- DINGS counts ---
    dings_pattern = r'corners\s*F:\s*(\d+)\s*DINGS?\s*B:\s*(\d+)\s*DINGS?'
    m = re.search(dings_pattern, text, re.IGNORECASE)
    if m:
        report.dings_corners_front = int(m.group(1))
        report.dings_corners_back = int(m.group(2))

    dings_pattern = r'edges\s*F:\s*(\d+)\s*DINGS?\s*B:\s*(\d+)\s*DINGS?'
    m = re.search(dings_pattern, text, re.IGNORECASE)
    if m:
        report.dings_edges_front = int(m.group(1))
        report.dings_edges_back = int(m.group(2))

    dings_pattern = r'surface\s*F:\s*(\d+)\s*DINGS?\s*B:\s*(\d+)\s*DINGS?'
    m = re.search(dings_pattern, text, re.IGNORECASE)
    if m:
        report.dings_surface_front = int(m.group(1))
        report.dings_surface_back = int(m.group(2))

    # --- Dimensions ---
    dim_match = re.search(r'H:\s*([\d.]+)".*?W:\s*([\d.]+)"', text)
    if dim_match:
        report.height_inches = dim_match.group(1)
        report.width_inches = dim_match.group(2)

    # --- Population ---
    pop_match = re.search(r'(\d+)\s*GEM MINT\s*graded\s*(\d+)\s*total\s*graded', text, re.IGNORECASE)
    if pop_match:
        report.pop_gem_mint = int(pop_match.group(1))
        report.pop_total = int(pop_match.group(2))

    # --- Surface Details table (PIXEL COORDINATES!) ---
    # Parse the table rows: ID | Side | Type | Location | Region
    surface_rows = await page.evaluate("""
        () => {
            const rows = [];
            const tds = [...document.querySelectorAll('td')];
            // Find the surface details table by looking for "ID" header
            // Then parse each row: ID(VIEW), Side, Type, Location, Region
            for (let i = 0; i < tds.length - 4; i++) {
                const cell = tds[i].textContent.trim();
                const viewMatch = cell.match(/^(\\d+)\\s*\\(VIEW\\)$/i);
                if (!viewMatch) continue;

                const id = parseInt(viewMatch[1]);
                const side = tds[i+1]?.textContent.trim().toLowerCase() || '';
                const type = tds[i+2]?.textContent.trim().replace(/\\/$/, '') || '';
                const location = tds[i+3]?.textContent.trim() || '';
                const region = tds[i+4]?.textContent.trim() || '';

                if (side && (side === 'front' || side === 'back')) {
                    const locMatch = location.match(/(\\d+)[,\\s]+(\\d+)/);
                    rows.push({
                        id: id,
                        side: side,
                        type: type,
                        x: locMatch ? parseInt(locMatch[1]) : 0,
                        y: locMatch ? parseInt(locMatch[2]) : 0,
                        region: parseInt(region) || 0
                    });
                }
            }
            return rows;
        }
    """)

    for row in surface_rows:
        report.surface_defects.append(SurfaceDefect(
            id=row["id"],
            side=row["side"],
            defect_type=row["type"],
            x=row["x"],
            y=row["y"],
            region=row["region"],
        ))

    # --- Corner details ---
    corner_positions = [
        ("top_left", "Top Left", "top L corner"),
        ("top_right", "Top Right", "top r corner"),
        ("bottom_left", "Bottom Left", "bottom L corner"),
        ("bottom_right", "Bottom Right", "bottom R corner"),
    ]
    for pos_key, label1, label2 in corner_positions:
        for side in ["front", "back"]:
            pattern = rf'{side}\s*Total:\s*(\d+)\s*Fray:\s*(\d+)\s*Fill:\s*(\d+)\s*CSW:\s*(\d+)(?:\s*Angle:\s*(\d+))?'
            # Search near the corner label
            search_start = text.lower().find(label2.lower())
            if search_start < 0:
                search_start = text.lower().find(label1.lower())
            if search_start < 0:
                continue

            chunk = text[max(0, search_start - 50):search_start + 500]
            m = re.search(pattern, chunk, re.IGNORECASE)
            if m:
                report.corners.append(CornerDetail(
                    position=pos_key,
                    side=side,
                    total=int(m.group(1)),
                    fray=int(m.group(2)),
                    fill=int(m.group(3)),
                    csw=int(m.group(4)),
                    angle=int(m.group(5)) if m.group(5) else None,
                ))

    # --- Edge details ---
    edge_positions = ["top", "bottom", "left", "right"]
    for pos in edge_positions:
        for side in ["front", "back"]:
            pattern = rf'{side}\s*Total:\s*(\d+)\s*Fray:\s*(\d+)\s*Fill:\s*(\d+)\s*ESW:\s*(\d+)'
            search_term = f"{pos} edge"
            search_start = text.lower().find(search_term)
            if search_start < 0:
                continue

            chunk = text[max(0, search_start - 50):search_start + 500]
            m = re.search(pattern, chunk, re.IGNORECASE)
            if m:
                report.edges.append(EdgeDetail(
                    position=pos,
                    side=side,
                    total=int(m.group(1)),
                    fray=int(m.group(2)),
                    fill=int(m.group(3)),
                    esw=int(m.group(4)),
                ))

    report.scrape_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    return report


async def scrape_cards(
    certs: list[str],
    db: sqlite3.Connection,
    concurrency: int = 5,
) -> list[TagReport]:
    """Scrape multiple card reports with parallel tabs."""
    from playwright.async_api import async_playwright
    import threading

    reports = []
    db_lock = threading.Lock()
    semaphore = asyncio.Semaphore(concurrency)
    done_count = 0
    total = len(certs)

    async def _scrape_one(cert: str, context) -> Optional[TagReport]:
        nonlocal done_count

        # Check if already scraped
        with db_lock:
            row = db.execute(
                "SELECT status FROM cards WHERE cert=?", (cert,)
            ).fetchone()
        if row and row[0] in ("done", "scraped"):
            done_count += 1
            return None

        async with semaphore:
            page = await context.new_page()
            try:
                report = await scrape_card_report(cert, page)

                # Save metadata JSON
                card_dir = DATA_DIR / cert
                card_dir.mkdir(parents=True, exist_ok=True)
                meta_path = card_dir / "metadata.json"

                report_dict = asdict(report)
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(report_dict, f, indent=2, ensure_ascii=False)

                # Update DB (thread-safe)
                with db_lock:
                    db.execute("""
                        INSERT OR REPLACE INTO cards
                        (cert, status, has_dig_plus, tag_score, grade, num_defects, metadata_json, scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """, (
                        cert,
                        "scraped",
                        1 if report.has_dig_plus else 0,
                        report.tag_score,
                        report.grade,
                        len(report.surface_defects),
                        str(meta_path),
                    ))
                    db.commit()

                done_count += 1
                log.info(
                    f"  [{done_count}/{total}] {cert}: "
                    f"TAG={report.tag_score} Grade={report.grade} "
                    f"Defects={len(report.surface_defects)} "
                    f"Images={len(report.s3_image_urls)} "
                    f"DIG+={'YES' if report.has_dig_plus else 'NO'}"
                )
                return report

            except Exception as e:
                done_count += 1
                log.error(f"  [{done_count}/{total}] {cert}: ERROR - {e}")
                with db_lock:
                    db.execute(
                        "INSERT OR REPLACE INTO cards (cert, status, error) VALUES (?,?,?)",
                        (cert, "error", str(e)),
                    )
                    db.commit()
                return None
            finally:
                await page.close()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # Block analytics to speed up page loads
        await context.route("**/google-analytics.com/**", lambda route: route.abort())
        await context.route("**/intercom.io/**", lambda route: route.abort())
        await context.route("**/googletagmanager.com/**", lambda route: route.abort())

        # Process in batches to avoid too many pending tasks
        batch_size = concurrency * 2
        for batch_start in range(0, len(certs), batch_size):
            batch = certs[batch_start:batch_start + batch_size]
            results = await asyncio.gather(
                *[_scrape_one(c, context) for c in batch]
            )
            reports.extend([r for r in results if r is not None])
            # Small delay between batches to avoid rate limiting
            await asyncio.sleep(2)

        await browser.close()

    return reports


# ---------------------------------------------------------------------------
# Phase 3: Image Download
# ---------------------------------------------------------------------------

async def download_images(
    certs: list[str],
    db: sqlite3.Connection,
) -> None:
    """Download card images for scraped certs (parallel cards)."""
    import aiohttp

    # Download card photos + photometric stereo surface maps (for defect masks)
    # All other URLs (corner crops, defect crops, slab photos) saved in metadata only
    IMAGE_SUFFIXES = [
        "_FRONT_MAIN.jpg",
        "_BACK_MAIN.jpg",
        "_FRONT_SFX.jpg",
        "_BACK_SFX.jpg",
        "_FRONT_SFX_Annotated.jpg",
        "_BACK_SFX_Annotated.jpg",
    ]
    essential_keywords = ["FRONT_MAIN", "BACK_MAIN", "FRONT_SFX", "BACK_SFX", "SFX_Annotated"]

    card_sem = asyncio.Semaphore(CARD_DOWNLOAD_CONCURRENCY)
    db_lock = asyncio.Lock()
    total = len(certs)
    done_count = 0

    async def download_one(session: aiohttp.ClientSession, url: str, dest: Path) -> bool:
        if dest.exists():
            return True
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(await resp.read())
                    return True
                return False
        except Exception as e:
            log.warning(f"    Download failed: {dest.name} - {e}")
            return False

    async def process_card(session: aiohttp.ClientSession, cert: str) -> None:
        nonlocal done_count
        async with card_sem:
            card_dir = DATA_DIR / cert
            meta_path = card_dir / "metadata.json"
            if not meta_path.exists():
                return
            with open(meta_path, "r") as f:
                meta = json.load(f)

            uuid = meta.get("image_uuid", "")
            s3_urls = meta.get("s3_image_urls", [])
            if not uuid and not s3_urls:
                log.warning(f"  {cert}: no image UUID or URLs, skipping")
                return

            img_dir = card_dir / "images"
            img_dir.mkdir(exist_ok=True)

            tasks = []
            for url in s3_urls:
                filename = url.split("/")[-1]
                if any(kw in filename for kw in essential_keywords):
                    clean_name = re.sub(r'^[a-f0-9-]{36}_', '', filename)
                    tasks.append(download_one(session, url, img_dir / clean_name))

            # Fallback: try known suffixes if UUID available and no URLs matched
            if not tasks and uuid:
                for suffix in IMAGE_SUFFIXES:
                    url = f"{S3_BASE}/{uuid}{suffix}"
                    tasks.append(download_one(session, url, img_dir / suffix.lstrip("_")))

            results = await asyncio.gather(*tasks)
            downloaded = sum(1 for r in results if r)

            async with db_lock:
                db.execute(
                    "UPDATE cards SET num_images_downloaded=?, downloaded_at=datetime('now'), status='done' WHERE cert=?",
                    (downloaded, cert),
                )
                db.commit()
                done_count += 1
                if done_count % 50 == 0 or done_count == total:
                    log.info(f"  [{done_count}/{total}] downloaded {downloaded}/{len(tasks)} for {cert}")

    connector = aiohttp.TCPConnector(limit=HTTP_CONNECTOR_LIMIT)
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        await asyncio.gather(*(process_card(session, c) for c in certs))


# ---------------------------------------------------------------------------
# Phase 4: Annotation Conversion
# ---------------------------------------------------------------------------

# Fallback image dimensions (used only if PIL can't read actual size)
TAG_IMG_WIDTH_FALLBACK = 4463
TAG_IMG_HEIGHT_FALLBACK = 6161

# 7-class merged taxonomy for better training with limited data
# Merged from original 12 classes based on semantic similarity and data volume
DEFECT_CLASSES = {
    # Class 0: corner_wear (~1634 annotations)
    "corner wear": 0,
    # Class 1: edge_wear (~679 annotations)
    "edge wear": 1,
    # Class 2: surface_damage — merged play_wear, ink_defect, print_defect, roller_mark, print_line (~800)
    "play wear defect": 2,
    "play wear": 2,
    "surface / play wear": 2,
    "ink/surface defect": 2,
    "ink defect": 2,
    "surface defect": 2,
    "surface / ink defect": 2,
    "surface / ink/surface defect": 2,
    "surface / print defect": 2,
    "print defect": 2,
    "print line(s)": 2,
    "print line": 2,
    "surface / print line(s)": 2,
    "surface / print line": 2,
    "surface / roller mark": 2,
    "roller mark": 2,
    "surface / other damage": 2,
    "other damage": 2,
    # Class 3: scratch (~160 annotations)
    "scratch(es)": 3,
    "scratch": 3,
    "surface / scratch": 3,
    "surface / scratch(es)": 3,
    "surface / scratches": 3,
    "scratches": 3,
    "surface / scuffing": 3,
    "scuffing": 3,
    # Class 4: crease (~155 annotations)
    "crease": 4,
    "surface / crease": 4,
    "wrinkle/crease": 4,
    "surface / wrinkle/crease": 4,
    "edge/corner / bend": 4,
    "bend": 4,
    # Class 5: dent — merged with pit (~190 annotations)
    "dent": 5,
    "surface / dent": 5,
    "pit": 5,
    "surface / pit": 5,
    "surface / pits": 5,
    "pits": 5,
    # Class 6: stain (~21 annotations)
    "stain": 6,
    "surface / stain": 6,
    "water/stain": 6,
    "surface / whitening": 6,
    "whitening": 6,
}

CLASS_NAMES = {
    0: "corner_wear",
    1: "edge_wear",
    2: "surface_damage",
    3: "scratch",
    4: "crease",
    5: "dent",
    6: "stain",
}

# Bbox size ranges per class (pixels on TAG's ~4463x6161 images)
# Using (min, max) ranges instead of fixed sizes to add natural variation
# The actual size is sampled uniformly from [min, max] during conversion
CLASS_BBOX_RANGES = {
    0: {"w": (200, 450), "h": (200, 450)},    # corner_wear — localized at corners
    1: {"w": (300, 600), "h": (150, 350)},     # edge_wear — elongated along edge
    2: {"w": (350, 800), "h": (350, 800)},     # surface_damage — variable size
    3: {"w": (300, 700), "h": (100, 250)},     # scratch — elongated linear
    4: {"w": (400, 800), "h": (150, 350)},     # crease — elongated
    5: {"w": (150, 350), "h": (150, 350)},     # dent/pit — compact
    6: {"w": (250, 550), "h": (250, 550)},     # stain — medium spread
}

# Coordinates to filter out (placeholders/defaults from TAG)
PLACEHOLDER_COORDS = {(50, 50), (0, 0)}


def convert_to_yolo(report: TagReport, img_sizes: dict[str, tuple[int, int]] | None = None) -> dict[str, list[str]]:
    """Convert TAG surface defects to YOLO annotation format.

    Args:
        report: TAG report with surface defects
        img_sizes: dict of {"front": (width, height), "back": (width, height)} from actual images

    Returns dict: {"front": [lines], "back": [lines]}
    Each line: "class x_center y_center width height" (normalized 0-1)
    """
    annotations = {"front": [], "back": []}

    # Use deterministic seed per card for reproducible jitter
    import hashlib
    seed = int(hashlib.md5(report.cert.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    for defect in report.surface_defects:
        # Filter placeholder coordinates
        if (defect.x, defect.y) in PLACEHOLDER_COORDS:
            continue

        defect_type = defect.defect_type.lower().strip()
        class_id = DEFECT_CLASSES.get(defect_type)

        if class_id is None:
            # Try partial match
            for key, cid in DEFECT_CLASSES.items():
                if key in defect_type:
                    class_id = cid
                    break

        if class_id is None:
            log.warning(f"  Unknown defect type: '{defect.defect_type}' in {report.cert}")
            class_id = 2  # default to surface_damage

        # Get actual image dimensions or use fallback
        side = defect.side
        if img_sizes and side in img_sizes:
            img_w, img_h = img_sizes[side]
        else:
            img_w, img_h = TAG_IMG_WIDTH_FALLBACK, TAG_IMG_HEIGHT_FALLBACK

        # Sample bbox size from range (deterministic per cert+defect)
        bbox_range = CLASS_BBOX_RANGES.get(class_id, {"w": (300, 500), "h": (300, 500)})
        bbox_w_px = rng.randint(*bbox_range["w"])
        bbox_h_px = rng.randint(*bbox_range["h"])

        # Normalize coordinates
        x_center = defect.x / img_w
        y_center = defect.y / img_h
        w = bbox_w_px / img_w
        h = bbox_h_px / img_h

        # Clamp to valid range
        x_center = max(w / 2, min(1.0 - w / 2, x_center))
        y_center = max(h / 2, min(1.0 - h / 2, y_center))

        line = f"{class_id} {x_center:.6f} {y_center:.6f} {w:.6f} {h:.6f}"
        annotations[side].append(line)

    return annotations


def _get_image_size(img_path: Path) -> tuple[int, int] | None:
    """Get image (width, height) using PIL. Returns None if image can't be read."""
    try:
        from PIL import Image
        with Image.open(img_path) as img:
            return img.size  # (width, height)
    except Exception:
        return None


def convert_all_to_yolo(db: sqlite3.Connection) -> None:
    """Convert all scraped cards to YOLO dataset format.

    Improvements over original:
    - Processes ALL cards with surface_defects (not just DIG+)
    - Reads actual image dimensions per card
    - Uses adaptive bbox sizes per defect class
    - Filters placeholder coordinates
    - Includes negative examples (clean cards)
    - Uses 7-class merged taxonomy
    """
    import shutil
    import random

    # Clean old dataset
    if DATASET_DIR.exists():
        shutil.rmtree(DATASET_DIR)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    for split in ["train", "val", "test"]:
        (DATASET_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (DATASET_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)

    # Load ALL cards with downloaded images (not just DIG+)
    rows = db.execute(
        "SELECT cert FROM cards WHERE status='done'"
    ).fetchall()

    cards_with_defects = []
    cards_clean = []

    for (cert,) in rows:
        meta_path = DATA_DIR / cert / "metadata.json"
        if not meta_path.exists():
            continue
        with open(meta_path) as f:
            card = json.load(f)

        defects = card.get("surface_defects", [])
        # Filter out placeholder coords
        real_defects = [
            d for d in defects
            if (d.get("x", 0), d.get("y", 0)) not in PLACEHOLDER_COORDS
        ]

        if real_defects:
            card["_filtered_defects"] = real_defects
            cards_with_defects.append(card)
        else:
            cards_clean.append(card)

    # Add ~200 negative examples (clean cards with empty labels)
    random.seed(42)
    random.shuffle(cards_clean)
    neg_count = min(200, len(cards_clean), len(cards_with_defects) // 4)
    negative_examples = cards_clean[:neg_count]

    all_cards = cards_with_defects + negative_examples
    random.shuffle(all_cards)

    log.info(
        f"Converting {len(cards_with_defects)} cards with defects + "
        f"{neg_count} negative examples = {len(all_cards)} total"
    )

    # Split: 70% train, 15% val, 15% test
    n = len(all_cards)
    train_end = int(n * 0.7)
    val_end = int(n * 0.85)

    splits = {
        "train": all_cards[:train_end],
        "val": all_cards[train_end:val_end],
        "test": all_cards[val_end:],
    }

    total_annotations = 0
    total_images = 0
    class_counts = {}

    for split_name, split_cards in splits.items():
        for card in split_cards:
            cert = card["cert"]
            filtered_defects = card.get("_filtered_defects", [])

            # Build report for conversion
            report = TagReport.__new__(TagReport)
            report.cert = cert
            report.surface_defects = [
                SurfaceDefect(**d) for d in filtered_defects
            ]

            # Read actual image dimensions
            img_sizes = {}
            for side in ["front", "back"]:
                img_path = DATA_DIR / cert / "images" / f"{side.upper()}_MAIN.jpg"
                if img_path.exists():
                    size = _get_image_size(img_path)
                    if size:
                        img_sizes[side] = size

            annotations = convert_to_yolo(report, img_sizes)

            for side in ["front", "back"]:
                img_src = DATA_DIR / cert / "images" / f"{side.upper()}_MAIN.jpg"
                if not img_src.exists():
                    continue

                has_annotations = bool(annotations[side])
                is_negative = not filtered_defects

                # Include image if it has annotations OR is a negative example
                if not has_annotations and not is_negative:
                    continue

                img_dest = DATASET_DIR / "images" / split_name / f"{cert}_{side}.jpg"
                if not img_dest.exists():
                    shutil.copy2(img_src, img_dest)

                # Write label file (empty for negatives)
                label_dest = DATASET_DIR / "labels" / split_name / f"{cert}_{side}.txt"
                with open(label_dest, "w") as f:
                    if has_annotations:
                        f.write("\n".join(annotations[side]) + "\n")
                    # Empty file for negatives — YOLO expects label file to exist

                total_images += 1
                total_annotations += len(annotations[side])

                # Track class distribution
                for line in annotations[side]:
                    cls_id = int(line.split()[0])
                    class_counts[cls_id] = class_counts.get(cls_id, 0) + 1

    # Write dataset YAML
    yaml_content = f"""# TAG Defect Detection Dataset (7 classes)
# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
# Images: {total_images} | Annotations: {total_annotations}
# Includes {neg_count} negative examples (clean cards)

path: {DATASET_DIR.resolve()}
train: images/train
val: images/val
test: images/test

nc: {len(CLASS_NAMES)}
names: {json.dumps(CLASS_NAMES)}
"""
    with open(DATASET_DIR / "dataset.yaml", "w") as f:
        f.write(yaml_content)

    # Log results
    log.info(
        f"Dataset created: {total_annotations} annotations across "
        f"{total_images} images "
        f"(train={len(splits['train'])}, val={len(splits['val'])}, test={len(splits['test'])})"
    )
    log.info("Class distribution:")
    for cls_id in sorted(class_counts):
        name = CLASS_NAMES.get(cls_id, f"unknown_{cls_id}")
        log.info(f"  {name:20s} {class_counts[cls_id]:5d}")
    log.info(f"Negative examples: {neg_count}")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def show_stats(db: sqlite3.Connection) -> None:
    """Show dataset statistics."""
    total = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    scraped = db.execute("SELECT COUNT(*) FROM cards WHERE status IN ('scraped','done')").fetchone()[0]
    downloaded = db.execute("SELECT COUNT(*) FROM cards WHERE status='done'").fetchone()[0]
    dig_plus = db.execute("SELECT COUNT(*) FROM cards WHERE has_dig_plus=1").fetchone()[0]
    errors = db.execute("SELECT COUNT(*) FROM cards WHERE status='error'").fetchone()[0]

    total_defects = db.execute("SELECT SUM(num_defects) FROM cards").fetchone()[0] or 0
    total_images = db.execute("SELECT SUM(num_images_downloaded) FROM cards").fetchone()[0] or 0

    avg_score = db.execute("SELECT AVG(tag_score) FROM cards WHERE tag_score > 0").fetchone()[0] or 0
    avg_grade = db.execute("SELECT AVG(grade) FROM cards WHERE grade > 0").fetchone()[0] or 0

    # Grade distribution
    grade_dist = db.execute("""
        SELECT CAST(grade AS INTEGER) as g, COUNT(*) as c
        FROM cards WHERE grade > 0
        GROUP BY g ORDER BY g DESC
    """).fetchall()

    print("\n" + "=" * 50)
    print("TAG SCRAPER DATASET STATS")
    print("=" * 50)
    print(f"Total certs:        {total}")
    print(f"Scraped:            {scraped}")
    print(f"Downloaded:         {downloaded}")
    print(f"DIG Plus:           {dig_plus}")
    print(f"Errors:             {errors}")
    print(f"Total defects:      {total_defects}")
    print(f"Total images:       {total_images}")
    print(f"Avg TAG Score:      {avg_score:.0f}")
    print(f"Avg Grade:          {avg_grade:.1f}")
    print()

    if grade_dist:
        print("Grade Distribution:")
        for grade, count in grade_dist:
            bar = "#" * min(count, 50)
            print(f"  Grade {grade:2d}: {count:5d} {bar}")

    # Storage estimate
    data_size = sum(
        f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file()
    ) if DATA_DIR.exists() else 0
    print(f"\nStorage used:       {data_size / (1024**3):.2f} GB")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="TAG Grading DIG Report Scraper")

    # Mode
    parser.add_argument("--cert", help="Scrape a single cert number")
    parser.add_argument("--certs-file", help="File with cert numbers (one per line)")
    parser.add_argument("--category", default="Pokémon", help="Pop report category")
    parser.add_argument("--limit", type=int, default=10, help="Max cards to process")
    parser.add_argument("--concurrency", type=int, default=5, help="Parallel browser tabs for scraping")

    # Phases
    parser.add_argument("--discover-only", action="store_true", help="Only discover cert numbers")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape pending certs from DB (skip discovery)")
    parser.add_argument("--download-only", action="store_true", help="Only download images")
    parser.add_argument("--convert-only", action="store_true", help="Only convert annotations")
    parser.add_argument("--stats", action="store_true", help="Show dataset stats")

    args = parser.parse_args()

    # Init database
    db = init_db(DB_PATH)

    if args.stats:
        show_stats(db)
        return

    if args.convert_only:
        convert_all_to_yolo(db)
        return

    # Determine cert list
    certs = []

    if args.cert:
        certs = [args.cert]
    elif args.certs_file:
        with open(args.certs_file) as f:
            certs = [line.strip() for line in f if line.strip()]
        certs = certs[:args.limit]
    elif args.scrape_only:
        # Take pending certs from DB (skip discovery)
        rows = db.execute(
            "SELECT cert FROM cards WHERE status='pending' LIMIT ?",
            (args.limit,)
        ).fetchall()
        certs = [r[0] for r in rows]
        log.info(f"Found {len(certs)} pending certs in DB")
    elif not args.download_only:
        # Discover from pop report
        certs = await discover_certs_from_pop_report(
            category=args.category,
            limit=args.limit,
            db=db,
        )

    if not args.download_only and certs:
        # Phase 2: Scrape reports
        log.info(f"Phase 2: Scraping {len(certs)} card reports ({args.concurrency} parallel tabs)...")
        await scrape_cards(certs, db, concurrency=args.concurrency)

    # Phase 3: Download images
    if args.download_only:
        # Newest scraped first — legacy CDN-bug rows (empty URLs) get fast-skipped at the tail
        rows = db.execute(
            "SELECT cert FROM cards WHERE status='scraped' ORDER BY scraped_at DESC LIMIT ?",
            (args.limit,)
        ).fetchall()
        certs = [r[0] for r in rows]

    if certs:
        log.info(f"Phase 3: Downloading images for {len(certs)} cards...")
        await download_images(certs, db)

    # Show stats
    show_stats(db)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
