---
type: note
status: stable
area: [data-pipelines, ebay]
tags: [ebay, scraping, photos, training-data]
created: 2026-05-23
updated: 2026-05-23
---

# eBay Photo Scraping

> Real-world user-style card photos из eBay listings — основа для training data (YOLO + CLIP augmentation).

## Goal

Synthetic compositing (для YOLO card detector) использует **scraped real backgrounds** + **clean card scans**. eBay listings — отличный source: реальные user photos карт на различных backgrounds, sleeves, lighting.

Также: eBay sold listings → market pricing signal (future work).

## Script

`scripts/scrape_ebay_photos.py` (~329 строк).

## Pipeline

1. Query eBay search via Apify actor (handles anti-bot, JS rendering)
2. Parse listing pages → extract image URLs
3. Download images concurrently
4. Filter: minimum resolution, single card heuristic
5. Save to `data/ebay_photos/<card_id>/<listing_id>.jpg`

## Apify integration

Why Apify (paid service): eBay's anti-scraping в 2026 makes direct scraping painful (headers, JS challenges, rate limits, captchas). Apify wraps это в reliable actor. Cost ~$0.001 per listing.

## Outputs

- `data/ebay_photos/<card_id>/*.jpg` — images organized by card
- Used as:
  - Background source для [[../../09-ml-research/yolo-card-detection/dataset]] composite generation
  - Augmentation source для [[../../09-ml-research/clip-finetuning/pairs-generation]]

## Failure modes

- **Apify quota exhausted** — paid limit. Job pauses.
- **eBay schema change** — Apify actor may need update.
- **Image rights**: scraped photos used for **training only**, not redistributed. If business model evolves to host these, need permissions review.

## Frequency

- One-time bulk + periodic refresh для new cards
- Not part of daily pipeline

## Related

- URL construction (eBay): [[../../06-api/modules/ebay_url]]
- [[../../09-ml-research/yolo-card-detection/dataset]]
- [[../scripts-catalog]]
