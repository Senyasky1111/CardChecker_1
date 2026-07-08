# 🟢 START HERE — "Re-trace the card" feature (new session kickoff)

Read this first, then the 3 detail files:
- [_reidentify_decisions.md](_reidentify_decisions.md) — locked decisions + phases
- [_reidentify_plan_backend.md](_reidentify_plan_backend.md) — full backend analysis + design
- [_reidentify_plan_frontend.md](_reidentify_plan_frontend.md) — full frontend/UX analysis + design

## Goal
In the pre-grading **Centering** step, when auto card-detection is wrong, let the user **manually re-trace the card outline with 8 draggable points (4 corners + 4 edge-midpoints) + a magnifier loupe on the ORIGINAL photo** (document-scanner style). Then perspective-warp to a perpendicular, aspect-exact (0.716) top-down crop and continue the normal green/cyan centering on that corrected crop. Also: "Reset view" should return to the original photo.

## Locked decisions (user-confirmed 2026-07-07)
1. **Warp = 4-corner homography** (`cv2.getPerspectiveTransform`, reuse `warp_card_to`). The 4 edge-midpoints are **UX-only** (8 handles) + an "edge bowed" flag; they do NOT drive the transform. Mesh/TPS deferred.
2. **Entry button always visible** in Centering, **highlighted when auto-seed is "rough"** (`seed_reliable` false / `detect_method === 'full_frame'`).
3. **User-facing name: "Re-trace the card"** (internal component/prop may be ManualOutline/Reidentify).
4. **A mode inside the Centering step** (not a separate wizard step): toggle between green/cyan line view and the 8-point outline editor.

## Already DONE (Phase 0) — NOT committed, NOT deployed
- **Rotation bug fix** (backend, this repo): `src/card_detector.py`
  - l.~192: require the 2nd-most-departed corner (`np.sort(...)[-2]`) to exceed 3% before using a perspective quad.
  - l.~197: `quad = box if (tilt >= 5.0 and fill < 0.85) else bbox` (only rotate on unambiguous tilt; else axis-aligned crop). **Verified upright** by running `rectify_for_centering` on the Mew photo.
- **Reset-view logic fix** (webapp): `src/components/pregrade/CenteringStage.jsx` — cache `s.outer0/s.seed0` in `runDetect`; added `resetView` useCallback (restore seed + `fit()` + `updateReadout()`); button `onClick={resetView}`. NOTE: Phase 2's `applyDetect` refactor will extend this to also **reload the original corrected image** (the user's "return to original photo" ask).

## Build phases (next)
### Phase 1 — Backend `POST /centering/manual` (~2-3h) [DO FIRST]
File: `src/api.py` (new endpoint) + `src/card_detector.py` (new `rectify_manual` helper).
- Request: multipart `file` (frontend re-sends the ORIGINAL File) + Form field `points` (JSON: `{corners:[TL,TR,BR,BL], edges:{top,bottom,left,right}, img_w, img_h}` in original-image px) — edges optional/ignored for warp.
- `rectify_manual(image, corners)`: `ImageOps.exif_transpose` → `order_corners` → `warp_card_to` (same fixed 0.716 canvas + 8% draggable margin as auto path) → `seed_inner_frame`.
- Response: **identical shape to `/centering`** (`warped_url, canvas, outer, seed, seed_reliable:true, detect_method:"manual", detect_confidence:1.0`) so the frontend render path is reused unchanged.
- Guards: reuse existing 15MB/40MP limits; `contourArea`+`isContourConvex` on the quad → 422 on degenerate/non-convex; distinct filename `centering_manual_<file_hash>_<phash>.jpg` (don't overwrite auto warp; idempotent re-runs).
- Optionally return `src_corners` (the auto-detected quad in original px) so the editor can pre-seed handles.

### Phase 2 — Frontend `ManualOutline.jsx` + wiring (~1.5 day)
Webapp `D:\amotrychenko\Desktop\CardChecker_MVP\`:
- New `src/components/pregrade/ManualOutline.jsx`: 8-point 2D editor over the ORIGINAL photo. **Reuse** from `CenteringStage.jsx`: loupe (`showLoupe`/`loupeRef`), `fit()`, `DRAG_GAIN=0.4`, arrow-key nudge, gray-900 canvas panel styling. Map original-image px ↔ canvas px. Initial handles from `src_corners` if present, else an inset rectangle. Handles: TL/TR/BL/BR + TOP/BOTTOM/LEFT/RIGHT. Buttons: "Use this outline" / "Cancel".
- `CenteringStage.jsx`: add a **mode toggle** ("Re-trace the card" button, always shown, highlighted when seed rough). Refactor the detect-apply path into `applyDetect(reply)` used by both `/centering` (mount) and `/centering/manual`. Fold **"Reset view → reload original corrected image"** into `applyDetect` (refresh `outer0/seed0`, re-fetch warped with `?t=` cache-buster).
- `src/api/cardcheckApi.js`: add `manualRectify(file, points, { signal })` → POST `/centering/manual`.
- `src/pages/Pregrade.jsx`: expected **unchanged** (front/back Files already held there; `file` passed to CenteringStage).

### Phase 3 — Polish
Edge-bow flag from the 4 midpoints; touch drag + loupe on mobile; microcopy; self-intersection/tiny-drag guards.

## Repos, env & run notes
- **This repo** `d:\CardChecker` — backend (FastAPI `src/`). Python: `./venv/Scripts/python.exe` (3.11).
- **Webapp** `D:\amotrychenko\Desktop\CardChecker_MVP\` (React/Vite/Base44, ~10 real users). `permissions.additionalDirectories` already includes it; if a subagent hits permission errors, restart or inline file contents.
- **Backend prod:** Hetzner 89.167.31.124, Docker `/opt/cardcheck/`. ⚠️ Do NOT deploy untested; follow vault deploy-procedure. Phase-0 rotation fix needs a backend redeploy; webapp fixes need rebuild/redeploy to hit `bees.cardchecker.app`.
- **Verify centering warp locally:** `rectify_for_centering(PIL.Image)` from `src/card_detector.py` returns `{warped, W, H, outer, corners, confidence, method, card_found}` — save `warped` and eyeball it (used to confirm the rotation fix on Mew).

## Handy assets already produced
- Mew "Bubble Mew" card (TAG cert F2928859), full slab: `landing/public/pregrade/mew-front.jpg`, `mew-back.jpg` (4325×5996).
- TAG image download recipe: puppeteer-load `https://my.taggrading.com/card/<cert>`, grab `<img>` srcs containing `/card-images/`, pick `<uuid>_FRONT_MAIN.jpg` / `_BACK_MAIN.jpg` (CDN `d39lwrz0lm7c9r.cloudfront.net`). Script pattern was `landing/tag-imgs.mjs`.

## Side context (landing — separate from this feature)
Landing pre-grading section was rebuilt into ONE composition (`landing/app/components/PregradeMocks.tsx` + `Sections.tsx PreGrading()`), currently using a **Butterfree** card + generated crops (`landing/public/pregrade/card-front.png`, `crop-*.png`). Possible follow-up: swap in the **Mew** card. Guesswork + Aggregation landing scenes are DONE & wired. None committed. Prod landing server used port 3100 (`cd /d/CardChecker/landing && npm start -- -p 3100`); screenshot via `landing/shot-sec.mjs <url> "<h2 substring>" <out>`.

## First move for the new session
1. Read this + the 3 detail files.
2. Start **Phase 1**: implement `rectify_manual` in `src/card_detector.py` and `POST /centering/manual` in `src/api.py` per the backend plan; verify locally by warping the Mew photo with hand-picked corner points and eyeballing the output.
3. Then Phase 2 frontend.
