# CardChecker — Google Play Store Listing & Setup Guide

## App Details

| Field | Value |
|-------|-------|
| **App name** | CardChecker |
| **Developer name** | _(your name — as registered in Google Play Console)_ |
| **Default language** | English (en-US) |
| **App type** | Application |
| **Category** | Tools |
| **Tags** | Pokemon, Trading Cards, Price Checker, Card Scanner, TCG |
| **Pricing** | Free (with in-app purchases) |
| **Content rating** | Everyone |

---

## Store Listing Texts

### Short Description (80 chars max)

```
Scan Pokémon cards instantly — get prices from CardMarket, TCGPlayer & eBay.
```

### Full Description (4000 chars max)

```
CardChecker is the fastest way to check Pokémon card prices. Just take a photo of any card and get real-time market prices from multiple sources — all in seconds.

📸 SCAN & IDENTIFY
• Point your camera at any Pokémon card
• AI-powered recognition identifies the card instantly
• Works with English, Japanese, and Chinese (Traditional) cards
• Detects card boundaries automatically — no need to crop

💰 MULTI-SOURCE PRICING
• CardMarket (EU) — trend, low, and average prices in EUR
• TCGPlayer (US) — market prices in USD
• eBay — recent sale prices
• PriceCharting — historical price data
• Graded card prices (PSA 10, PSA 9, CGC 10)

🔍 ACCURATE RECOGNITION
• Hybrid AI engine: OCR text reading + CLIP visual matching + Gemini Vision
• 48,000+ cards in database covering all 2024–2025 sets
• Collector number detection for precise matching
• Multiple recognition methods for maximum accuracy

📊 CARD GRADING (AI Estimate)
• Get an estimated PSA-style grade (1–10) from a photo
• Centering, corners, edges, and surface analysis
• Front and back separate grading
• Defect detection with severity levels
• Note: Estimates only — not official PSA/BGS/CGC grades

🌍 SUPPORTED LANGUAGES
• English, Japanese, Chinese (Traditional) card recognition
• CardMarket links for all European locales (EN, DE, FR, IT, ES)

⚡ FEATURES
• No account required — scan immediately
• Fast processing: typically under 2 seconds
• Works offline for recently scanned cards
• Direct links to buy/sell on CardMarket, TCGPlayer, and PriceCharting
• Dark theme interface designed for card scanning

🔒 PRIVACY
• No personal data collected
• Card photos are processed and immediately deleted
• No tracking, no ads in free tier
• Servers in EU (Germany) for GDPR compliance

PREMIUM FEATURES
• Unlimited daily scans
• AI grading with detailed analysis
• Priority server processing
• Price history charts

CardChecker is an independent tool and is not affiliated with The Pokémon Company, Nintendo, CardMarket, or TCGPlayer.
```

---

## Graphic Assets Checklist

| Asset | Spec | Status |
|-------|------|--------|
| **App icon** | 512x512 PNG, 32-bit, no transparency | ⬜ Needed |
| **Feature graphic** | 1024x500 PNG or JPG | ⬜ Needed |
| **Phone screenshots** | Min 2, max 8. Min 320px, max 3840px, 16:9 or 9:16 | ⬜ Needed |
| **7-inch tablet screenshots** | Optional but recommended | ⬜ Optional |
| **10-inch tablet screenshots** | Optional but recommended | ⬜ Optional |

### Screenshot Suggestions (Phone, 9:16 portrait)

1. **Scan screen** — Camera viewfinder with a card, "Scan Card" button visible
2. **Results screen** — Identified card with name, set, prices displayed
3. **Multi-source prices** — Price boxes showing CardMarket, TCGPlayer, eBay
4. **Grading result** — AI grade with centering/corners/edges/surface scores
5. **Marketplace links** — CardMarket, TCGPlayer, PriceCharting buttons
6. **Japanese card** — Showing multi-language support

---

## Data Safety Declaration

Fill this out in Google Play Console → App content → Data safety.

### Does your app collect or share any of the required user data types?

**Yes** — the app collects data.

### Data collected:

| Data type | Collected | Shared | Purpose | Required | Encrypted in transit |
|-----------|-----------|--------|---------|----------|---------------------|
| **Photos** (camera) | Yes | No | App functionality (card scanning) | Yes (core feature) | Yes (HTTPS) |
| **App interactions** | Yes | No | Analytics | No | Yes |
| **Crash logs** | Yes | No | App diagnostics | No | Yes |
| **Device or other IDs** | No | No | — | — | — |
| **Purchase history** | Yes (via Google Play) | No | App functionality (premium) | No | Yes (Google Play) |

### Additional declarations:

| Question | Answer |
|----------|--------|
| Is data encrypted in transit? | **Yes** (all HTTPS/TLS) |
| Do you provide a way for users to request data deletion? | **Yes** — no personal data stored; contact via email |
| Does your app comply with the Families Policy? | N/A (not a children's app) |
| Does your app contain ads? | **No** (free tier has no ads) |

### Photos / Camera data — details:

- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** **Yes** — images are processed in memory and never stored
- **Is this data required or optional?** Required (core app functionality)
- **Purpose:** App functionality

---

## Content Rating Questionnaire

In Google Play Console → App content → Content rating → Start questionnaire.

### Category: **Utility / Productivity / Tools**

| Question | Answer |
|----------|--------|
| Does the app contain violence? | **No** |
| Does the app contain sexual content? | **No** |
| Does the app contain profanity or crude humor? | **No** |
| Does the app contain drug references? | **No** |
| Does the app allow users to interact or communicate? | **No** |
| Does the app share the user's location? | **No** |
| Does the app allow users to purchase digital goods? | **Yes** (in-app subscriptions) |
| Does the app contain gambling themes? | **No** |
| Does the app contain user-generated content? | **No** |
| Does the app allow unrestricted internet access? | **No** (only connects to own API + marketplace links) |

**Expected rating: Everyone (PEGI 3 / ESRB E)**

---

## App Access (for Review)

The app does **not** require login or special access. Google Play reviewers can test all free features immediately. For premium features testing, provide a test subscription promo code or note in the review instructions.

### Review instructions (paste in Play Console):

```
No login required. Open the app and use "Take Photo" or "Upload Photo" to scan
any Pokémon trading card. The app will identify the card and show prices.

Free features: Card scanning, identification, multi-source pricing.
Premium features: Unlimited scans, AI grading, price history.

Test with any Pokémon card image from Google Images if you don't have a physical card.
```

---

## Target Audience & Monetization

| Field | Value |
|-------|-------|
| **Target age group** | 13+ (trading card collectors) |
| **Does the app appeal to children?** | No (not primarily, though content is safe) |
| **Contains ads?** | No |
| **In-app purchases?** | Yes (premium subscription) |
| **Is this a news app?** | No |
| **Is this a social/dating app?** | No |

---

## Pre-Launch Checklist

- [ ] Google Play Developer Account created ($25 one-time fee)
- [ ] App icon (512x512) designed
- [ ] Feature graphic (1024x500) designed
- [ ] At least 2 phone screenshots prepared
- [ ] Privacy Policy URL live: `https://YOUR-DOMAIN/privacy-policy`
- [ ] Terms of Service URL live: `https://YOUR-DOMAIN/terms-of-service`
- [ ] AAB (Android App Bundle) signed and uploaded
- [ ] Data Safety form completed
- [ ] Content Rating questionnaire completed
- [ ] Store listing texts filled in (above)
- [ ] Target countries selected
- [ ] Pricing & distribution set to "Free" + "Contains in-app purchases"
- [ ] App categorized as "Tools"
- [ ] Contact email set: cardchecker.app@gmail.com
- [ ] Review instructions added

---

## After Submission

- Google review typically takes **1–7 days** for new apps
- If rejected, check the rejection email for specific policy violations
- Common rejection reasons for card/price apps:
  - **Intellectual property:** Make sure description says "unofficial, not affiliated with..."
  - **Misleading claims:** Don't promise "exact" prices, use "estimated"
  - **Minimum functionality:** App must work offline or show clear "needs internet" message
