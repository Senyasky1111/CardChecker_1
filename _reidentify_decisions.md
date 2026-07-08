# Re-trace the card — LOCKED DECISIONS (2026-07-07)

Feature: manual card-outline correction in the pre-grading Centering step, when auto-detection is wrong. Full plans: `_reidentify_plan_backend.md`, `_reidentify_plan_frontend.md`.

## Decisions (user-confirmed)
1. **Warp math = 4-corner homography** (`cv2.getPerspectiveTransform` → fixed 0.716 aspect, reuse `warp_card_to`). The 4 edge-midpoints are UX-only (8 draggable handles) + an "edge bowed" sanity flag; they do NOT drive the transform. Mesh / thin-plate-spline deferred. [CONFIRMED by user 2026-07-07]
2. **Entry button: ALWAYS visible** in the Centering step, **highlighted when auto-seed is "rough"** (`seed_reliable` false / detect_method full_frame).
3. **Naming (user-facing): "Re-trace the card"** (internal prop/component can be Reidentify/ManualOutline).
4. **Placement: a MODE inside the Centering step** (not a separate wizard step). Toggles between the green/cyan line view and the 8-point outline editor on the ORIGINAL photo.

## Build phases
- Phase 0 (done): rotation fix in `src/card_detector.py` (l.192,197) ✓ verified upright on Mew; Reset-view logic fix in `CenteringStage.jsx` ✓ (local reset of seed+fit).
- Phase 1: backend `POST /centering/manual` (orig file + 8 pts + img_w/img_h → same shape as `/centering`, detect_method:"manual"; `exif_transpose`; convexity guards; distinct filename). ~2-3h.
- Phase 2: frontend `ManualOutline.jsx` (8-pt editor on original photo, reuse loupe/fit/drag from CenteringStage), entry button in Centering, wire `manualRectify(file, points)` → refactored `applyDetect()` → back to green/cyan on corrected crop. Fold "Reset view → reload original corrected image" into `applyDetect` (refresh outer0/seed0 + cache-buster). ~1.5 day.
- Phase 3: polish — edge-bow flag, touch drag + loupe, microcopy, self-intersection/degenerate-quad guards.

## Repos / key files
- Backend (this repo): `src/api.py` (add `/centering/manual`), `src/card_detector.py` (`rectify_manual` helper reusing `order_corners`/`warp_card_to`).
- Webapp: `D:\amotrychenko\Desktop\CardChecker_MVP\` — `src/components/pregrade/ManualOutline.jsx` (new), `CenteringStage.jsx` (mode toggle + applyDetect refactor), `src/api/cardcheckApi.js` (add `manualRectify`), `src/pages/Pregrade.jsx` (unchanged expected).

## NOT done / notes
- Nothing committed. Backend fix needs Hetzner redeploy; webapp fixes need rebuild/redeploy to hit prod (bees.cardchecker.app).
- Original photo already client-side (`frontFile`/`backFile` in Pregrade → `file` prop) — no server storage needed for re-trace or reset-to-original.
