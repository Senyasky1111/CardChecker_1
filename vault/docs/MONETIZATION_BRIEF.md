# CardChecker - Monetization Strategy Brief

> Copy this entire document into Claude or ChatGPT for a detailed monetization consultation.

---

## Your Role

You are a **SaaS pricing strategist** with deep expertise in:
- Freemium-to-paid conversion optimization
- Usage-based and subscription hybrid models
- TCG (Trading Card Game) collector market dynamics
- Mobile app monetization (both web and native)
- Stripe integration best practices

You will analyze my product, cost structure, competitive landscape, and user personas, then recommend an optimal monetization strategy with specific tier definitions, pricing, and implementation priorities.

---

## 1. Product Overview

**CardChecker** is a web application (cardchecker.app) that helps Pokemon TCG collectors:

### Core Actions (2 types)

| Action | What it does | Tech stack | Cost to me | Speed |
|--------|-------------|------------|-----------|-------|
| **Scan (Price Check)** | Upload card photo, AI identifies card, shows market prices from CardMarket (EUR), TCGPlayer (USD), eBay (USD), graded prices (PSA 10, PSA 9, CGC 10) | Local OCR + SQL lookup + CLIP neural network. Falls back to Gemini Vision AI only if local pipeline fails (~5% of cases) | ~$0 per scan (local compute). Gemini fallback: ~$0.0001/call | ~100ms local, ~2s with Gemini fallback |
| **Grade (Condition Check)** | Upload front + optional back photo, AI grades card condition on PSA-style 1-10 scale across 4 pillars (Centering, Corners, Edges, Surface), lists defects with severity | Gemini 2.5 Flash Vision API | ~$0.0003 per grading (3,500 input tokens + 600 output tokens at Gemini Flash pricing) | ~3-5 seconds |

### Additional Features
- **Collection Management** - organize cards in binders, track total portfolio value
- **Watchlist** - set price alerts for cards you want to buy
- **Detailed Card Report** (coming soon) - full annotated grading report with defect heatmap, grade probability distribution, ROI calculator. Costs 1 "credit"

### Key Metrics
- **Card database**: 50,850 cards (22K English, 15K Japanese, 12K Traditional Chinese)
- **Price sources**: CardMarket, TCGPlayer, eBay, PriceCharting, with daily price snapshots
- **Graded price data**: PSA 10, PSA 9, CGC 10, CGC 9, BGS 10, PSA 8
- **Platform**: Base44 (React web app), with React Native mobile app in development
- **Auth**: Base44 built-in authentication (email + Google SSO)

---

## 2. Current Problems

### Critical: No Monetization
- **All scans are unlimited and free** - no usage tracking, no limits
- **Credits can be added without payment** - the "Buy Credits" button creates a CreditTransaction record directly in the database WITHOUT any actual Stripe charge. Anyone clicking "10 credits for $9.99" gets 10 credits instantly for free
- **No subscription enforcement** - the "Subscribe" button exists but only works in Base44 production environment, and even then there is no webhook to update user permissions after payment
- **No feature gating** - free users and "premium" users have identical access to everything

### What Exists (Can Be Reused)
- Stripe SDK installed and configured (publishable key + secret key)
- Stripe serverless function for checkout session creation (works in production)
- Stripe price ID already created: `price_1T7N2rPVtgYLRHJWfRTtocR7` (subscription)
- CreditTransaction entity for tracking credit balance
- Base44 User entity with `role` field (can store tier/plan info)
- Credit deduction logic in Detailed Report flow (deducts 1 credit per report)

---

## 3. Cost Structure

### Variable Costs (Per-Operation)

| Operation | API/Resource | Cost per call | Notes |
|-----------|-------------|---------------|-------|
| Scan (local pipeline) | OCR + SQL + CLIP (local) | **$0.00** | Runs entirely on my server, no API calls |
| Scan (Gemini fallback) | Gemini 2.5 Flash | ~$0.0001 | Only ~5% of scans trigger this |
| Condition Grading | Gemini 2.5 Flash | ~$0.0003 | 3,500 input + 600 output tokens |
| Detailed Report | Gemini Flash x2 (identify + grade) | ~$0.0004 | Two Gemini calls |
| Price data fetch | Local SQLite lookup | $0.00 | Pre-fetched daily |

### Fixed Costs (Monthly)

| Resource | Cost/month | Notes |
|----------|-----------|-------|
| Hetzner Cloud server | ~EUR 40 (~$44) | Runs FastAPI + models + SQLite |
| PokeTrace API | Unknown (subscription) | 9,500 calls/day for price updates |
| RapidAPI (Pokemon-API) | ~$5-50 | 3,000 calls/day for price updates |
| Domain + DNS | ~$15/year | cardchecker.app |
| Base44 platform | Free tier | Hosting + auth + entities |

### Marginal Cost Analysis
- **1,000 scans cost me**: ~$0.01 (practically free, local compute)
- **1,000 gradings cost me**: ~$0.30 (Gemini API)
- **1,000 detailed reports cost me**: ~$0.40 (Gemini API x2)
- **Server can handle**: ~10,000 requests/day comfortably

**Key insight**: Scans are essentially free to deliver. Grading has marginal cost but is very low. The main costs are fixed (server + price data APIs).

---

## 4. Competitive Landscape

### Professional Grading Services (Physical)
| Service | Price/card | Turnaround | What they do |
|---------|-----------|-----------|-------------|
| PSA | $20-150 | 20-120 days | Physical card grading, slab, cert number |
| BGS/Beckett | $20-250 | 10-60 days | Physical grading with sub-grades |
| CGC | $15-100 | 15-65 days | Physical grading, newer entrant |
| TAG | $8-15 | 10-30 days | Physical grading, digital-first approach |

### Digital Tools (Our Direct Competitors)
| Tool | Pricing | What they do |
|------|---------|-------------|
| TCGPlayer app | Free | Price lookup only (barcode scan) |
| Pokellector | Free | Collection tracking, no pricing |
| PriceCharting | Free (web) | Historical price charts, no grading |
| CollX | Free + Premium $5/mo | AI card identification, collection tracking |
| CardCatcher | Unknown | AI identification |
| Dex by Pokedata | $4.99/mo or $49.99/yr | Price tracking, portfolio, alerts |

### Our Unique Value Proposition
We are the **only tool that combines AI identification + AI condition grading + multi-source pricing** in one flow. Competitors either do identification OR pricing, never grading. Professional grading costs $15-150 per card and takes weeks - we give an AI estimate in 5 seconds.

---

## 5. User Personas

| Persona | Volume | Willingness to Pay | Primary Need |
|---------|--------|-------------------|-------------|
| **Casual Collector** | 5-20 cards/month | Low ($0-5/mo) | "What is my card worth?" Quick price checks |
| **Active Collector** | 50-200 cards/month | Medium ($5-15/mo) | Portfolio tracking, price alerts, grade estimates before sending to PSA |
| **Trader/Reseller** | 200-1000 cards/month | High ($15-30/mo) | Bulk scanning for arbitrage, condition checks before listing |
| **LGS Owner** (Local Game Store) | 500-5000 cards/month | High ($30-100/mo) | Inventory pricing, buy/sell decisions, grading for premium listings |

---

## 6. My Initial Thinking (Draft - Please Critique)

| | Free | Basic ($8/mo) | Premium ($15/mo) |
|---|------|-------------|-----------------|
| Scans (price checks) | 20/week | 1,000/month | 10,000/month |
| Condition grades | 2/week | 10/week | 300 total/month |
| Collection | Limited (1 binder, 50 cards) | Unlimited | Unlimited |
| Watchlist | 5 cards | 50 cards | Unlimited |
| Detailed Reports | No | 5/month | 30/month |
| Price History Charts | No | Yes | Yes |
| Graded Prices (PSA/CGC) | No | Yes | Yes |
| Priority Support | No | No | Yes |

I am not confident in these numbers and suspect they may be wrong. Please analyze and recommend.

---

## 7. Questions I Need Answered

### Pricing and Tiers
1. Are 3 tiers (Free/Basic/Premium) the right structure, or should I do Free + 1 paid tier, or Free + 3 paid tiers?
2. Is $8 and $15 in the right ballpark? What does pricing psychology suggest (e.g., $7.99 vs $9.99)?
3. Should I offer annual billing? What discount is standard (15%? 20%? 40%)?
4. Should I have a "Pro" or "Business" tier for LGS owners at $30-50/mo?

### Credits vs Subscriptions
5. Should grading be credit-based (buy packs of credits) or included in subscription? Or both?
6. If credit-based: what should 1 credit cost? ($0.25? $0.50? $1.00?)
7. Should scans be unlimited for paid users, or always metered?

### Conversion and Retention
8. What Free tier limits maximize conversion to paid? (Too generous = no conversion; too restrictive = users leave)
9. What is a realistic freemium conversion rate for this type of tool? (1%? 3%? 5%?)
10. How do I prevent churn? What features create stickiness?

### Feature Gating
11. Which features should be the "paywall triggers" - the moment a free user thinks "I need to upgrade"?
12. Should graded prices (PSA 10, PSA 9 values) be behind the paywall? They are high-value data for serious collectors
13. Should I limit the number of cards in Collection for free users?

### Launch Strategy
14. Should I launch with a beta/early-bird discount?
15. Should I grandfather existing users?
16. What is the minimum viable monetization I should ship first?

---

## 8. Requested Output Format

Please provide:

### A. Recommended Tier Structure
A table with exact tier names, prices, and limits for each feature. Include monthly AND annual pricing.

### B. Rationale
For each pricing decision, explain WHY - reference competitive positioning, cost structure, conversion psychology.

### C. Revenue Projections
Given these assumptions:
- 1,000 monthly active users in Month 1
- 10% month-over-month growth for 12 months
- Your estimated conversion rates per tier

Project monthly revenue for months 1-12.

### D. Implementation Priority
What should I build FIRST to start monetizing? Rank by impact x effort.

### E. Anti-Patterns to Avoid
Common monetization mistakes for tools like this that I should watch out for.

### F. A/B Testing Suggestions
What should I test to optimize pricing and conversion?

---

## 9. Additional Context

- **Solo developer** - I am building this alone, so implementation complexity matters
- **Target market**: Global, but primarily EU (CardMarket is EU-based) and US
- **Payment processor**: Stripe (already integrated)
- **Platform**: Web app (Base44), mobile app coming soon
- **Current users**: Early stage, under 100 users
- **No marketing budget** - growth is organic (Reddit, Discord, word of mouth)
- **Currencies**: Need to support EUR and USD pricing
