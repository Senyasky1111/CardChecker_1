# "Reidentify card" — Frontend/UX plan (Pregrade → Centering)

**TL;DR** — In the Centering step, when auto-detection warped the wrong region, the user taps **"Fix the outline"** and gets the **original** uploaded photo with 8 draggable handles (4 corners + 4 edge-mids), a magnifier loupe, and arrow-key nudge — a document-scanner corner-adjust screen. On **"Use this outline"** we POST the original image + 4 corner points to a new `manualRectify` endpoint, receive the same payload shape as `/centering`, and re-seed the existing green/cyan centering canvas on the corrected crop. No change to the Upload/Condition/Decision steps or to `gradeCardV2` — the corrected `warped_url`/`outer` flow through the normal confirm path.

This is a **new component `ManualOutline.jsx`** (points editor) mounted from `CenteringStage.jsx` behind a `mode` toggle, reusing CenteringStage's loupe, `fit`, drag-gain, and gray-900 canvas panel styling. One new API function. One small backend endpoint (dependency, spec in appendix).

---

## 0. Grounding — what the code already gives us

Verified against the webapp at `D:\amotrychenko\Desktop\CardChecker_MVP\`:

- **`src/pages/Pregrade.jsx`** — wizard `STEPS = ['Upload','Centering','Condition','Decision']`. Holds `frontFile`/`backFile` (PNG `File`, produced by `convertImageToPNG`) and `frontUrl`/`backUrl` (`URL.createObjectURL` blob URLs). Renders `<CenteringStage file={centeringSide==='front'?frontFile:backFile} side=… onConfirm={handleCenteringConfirm}/>` (front, then back). `handleCenteringConfirm` stores `${side}_warped_url` + `${side}_outer` and later hands them to `gradeCardV2`.
- **`src/components/pregrade/CenteringStage.jsx`** — for ONE side: `runDetect()` POSTs to `/centering`, seeds `stateRef.current` (`canvas`, `outer` green, `inner` cyan from `seed`), caches `outer0`/`seed0` for **Reset view**, loads `warped_url` into `imgRef`, then `fit()`+`draw()`. Has the reusable `showLoupe(cx,cy)` / `loupeRef` magnifier, `fit()` (scale = min(maxW/canvas.w, maxH/canvas.h)), `DRAG_GAIN=0.4` fine-drag, arrow-key nudge (`onKeyDown`), and the `bg-gray-900 rounded-2xl p-3` canvas panel + fixed-position circular loupe canvas.
- **`src/api/cardcheckApi.js`** — `detectCentering(file,{signal})` → `/centering`; `confirmCentering(payload)` → `/centering/compute`. `API_BASE`, `NGROK_HEADERS`, `linkSignal`, `CENTERING_TIMEOUT_MS=20000` all reusable. Add `manualRectify` next to these.
- **Backend (`D:\CardChecker\src`)** — `/centering` (api.py:650) calls `rectify_for_centering` → `warp_card_to(img, corners, W, H, mx, my)` (card_detector.py:129) which is exactly `getPerspectiveTransform(orderedCorners → dst rect)`. The manual endpoint reuses this with the **user's** corners. Canvas is aspect-exact 0.716, `CENTERING_W×H = 1260×1760` + 8% margin, saved to `static/`.

**Key consequence:** the original photo is already in `CenteringStage` as the `file` prop — no plumbing needed to display it. And a manual endpoint that returns the `/centering` shape lets us reuse the entire existing seed/draw/confirm path unchanged.

---

## 1. Where the original image is, client-side

| Need | Source |
|---|---|
| Original `File` (front) | `Pregrade.frontFile` → passed as `CenteringStage` `file` prop |
| Original `File` (back) | `Pregrade.backFile` → same prop when `centeringSide==='back'` |
| Blob preview URL | `Pregrade.frontUrl`/`backUrl` (not needed here; we decode `file` directly) |
| Natural pixel dims (for px mapping) | `Image.naturalWidth/Height` after `img.src = URL.createObjectURL(file)` |

So **`ManualOutline` only needs the `file` prop**, which `CenteringStage` already owns. It decodes it to an in-memory `Image` (for both canvas draw and the loupe source), and reads `naturalWidth/Height` as the original-pixel coordinate space. Revoke the object URL on unmount.

The `file` is post-`convertImageToPNG`, i.e. already normalized (EXIF-rotation baked in by the canvas re-encode), so `naturalWidth/Height` is the true display orientation — no EXIF handling needed.

---

## 2. UX flow

### Entry point
Two placements, both landing in the same action (`enterOutline()`):

1. **Always-available, low-emphasis** — a text/outline button in the CenteringStage right-hand info panel, under the readout and the seed-quality pill:
   ```jsx
   <button
     onClick={enterOutline}
     className="mt-4 w-full text-sm font-medium text-blue-600 hover:text-blue-700
                inline-flex items-center justify-center gap-1.5">
     <Crop className="w-4 h-4" /> Wrong outline? Re-trace the card
   </button>
   ```
2. **Emphasized when detection failed** — inside the existing red `detect_method === 'full_frame'` box (CenteringStage.jsx:421), swap the "retake the photo" dead-end for an actionable CTA:
   ```jsx
   <Button onClick={enterOutline}
     className="mt-2 w-full bg-gradient-to-r from-blue-600 to-purple-600 …">
     <Crop className="w-4 h-4 mr-2" /> Trace the card yourself
   </Button>
   ```
   (Keep the "or retake flat on contrasting background" text as the secondary path.)

Copy note: user-facing label is **"Re-trace the card" / "Fix the outline"** — clearer than the internal name "Reidentify". The task's "Reidentify card" name is fine for the code/props; the button copy should describe the action.

### The 8-point editor screen (`ManualOutline`)
Replaces the CenteringStage body while `mode==='outline'` (same card panel, so the stepper/header stay). Layout mirrors CenteringStage: gray-900 canvas panel + a right info/instructions column.

- **Canvas** shows the **original** photo scaled to fit (`fit()` identical to CenteringStage). Over it: a filled translucent quad (`fillStyle rgba(37,99,235,0.12)`, `stroke #2563eb` — blue-600, the brand accent) connecting the 4 corners, with:
  - **4 corner handles** (TL/TR/BR/BL) — larger dots (r≈9), free 2D drag.
  - **4 edge-mid handles** (TOP/RIGHT/BOTTOM/LEFT) — smaller dots (r≈7) at each edge midpoint; dragging one translates **both** adjacent corners by the (gained) delta, so an edge slides as a unit (standard scanner behavior).
- **Loupe** — reuse `showLoupe` verbatim, pointing `imgRef` at the original image and using the outline's `scale`. On `pointerdown`/drag over any handle it shows the magnified original pixels + cyan crosshair at the exact handle point (`sx=cx/scale, sy=cy/scale`), positioned above the finger and clamped to viewport (identical to CenteringStage lines 143–174).
- **Fine control** — `DRAG_GAIN=0.4` on drag (handle tracks slower than finger); after grabbing a handle it becomes `selected`, and **arrow keys nudge 1px (Shift=10px)** on both axes for corners, perpendicular for edge-mids. `refreshLoupe()` after each nudge.
- **Actions row** (mirrors CenteringStage's Reset/Confirm row):
  - `Cancel` (ghost, `RotateCcw`) → `exitOutline()` back to the centering canvas, discarding edits.
  - `Reset corners` (outline) → restore initial handle positions.
  - `Use this outline` (blue→purple gradient, `Check`) → `handleUseOutline()` (spinner "Straightening…" while `manualRectify` runs). Disabled while the quad is invalid (see §5).

### Return to centering
On success, `manualRectify` returns a `/centering`-shaped payload. `ManualOutline` calls `onRectified(payload)`; `CenteringStage.applyDetect(payload)` re-seeds state (green/cyan lines on the corrected crop), loads the new `warped_url` into `imgRef`, updates the `outer0`/`seed0` reset caches, sets `mode='centering'`. The user is now on the **normal green/cyan centering step on the corrected crop** and proceeds to Confirm exactly as before.

---

## 3. Component plan

**New component: `src/components/pregrade/ManualOutline.jsx`.** Rationale: CenteringStage's geometry is 1-D **lines** (each handle constrained to one axis, hit-tested by axis distance); the outline editor is 2-D **points** with corner/edge coupling and convexity constraints — different `nearest`/`move`/`draw`/keyboard logic. Cramming a second geometry mode into CenteringStage's `stateRef` would tangle two models. A sibling component keeps each cohesive. We **reuse** the loupe + `fit` + panel styling (copy the ~30-line `showLoupe`/`refreshLoupe` block; optionally lift to a `useLoupe(imgRef,loupeRef,stateRef)` hook shared by both — nice-to-have, not required for v1).

### Props
```jsx
<ManualOutline
  file={file}                 // original File for THIS side (already a CenteringStage prop)
  side={side}                 // 'front' | 'back' (passed to manualRectify for logging)
  initialQuad={srcCornersOrNull}  // [[x,y]×4] in ORIGINAL px, or null → inset default
  onRectified={applyDetect}   // (centeringShapedPayload) => void
  onCancel={exitOutline}      // () => void
/>
```

### State (`stateRef`, mirroring CenteringStage's pattern)
```js
stateRef.current = {
  natW, natH,          // original image px (naturalWidth/Height)
  scale,               // origPx → canvasPx (from fit())
  pts: {               // SOURCE OF TRUTH, in ORIGINAL px
    tl:{x,y}, tr:{x,y}, br:{x,y}, bl:{x,y},
  },
  dragging: null,      // 'tl'|'tr'|'br'|'bl'|'top'|'right'|'bottom'|'left' | null
  dragStartPt: null,   // captured corner(s) value at pointerdown (for gained relative drag)
  dragStartCanvas: {x,y},
  lastClientX, lastClientY, loupeCanvasX, loupeCanvasY,
};
const [selected, setSelected] = useState(null);
const [busy, setBusy] = useState(false);   // manualRectify in flight
const [invalid, setInvalid] = useState(false);
```
Edge-mids are **derived** (`mid(tl,tr)` etc.), not stored; dragging an edge-mid mutates its two corners.

### Coordinate mapping (original px ↔ canvas px)
- **Source of truth = original px** in `pts`. Draw at `x*scale, y*scale`. `scale` from `fit()` (identical formula to CenteringStage: `min((min(innerWidth-64,560))/natW, (innerHeight-220)/natH)`).
- **Pointer → original px:** `origX = (clientX - rect.left)/scale`, but movement is **relative + gained**: `newVal = dragStartVal + (canvasDelta*DRAG_GAIN)/scale`, clamped to `[0,natW]`/`[0,natH]` — same math as CenteringStage `move()`.
- **Loupe** samples the original image at `sx=cx/scale, sy=cy/scale` — `showLoupe` works unchanged because its `imgRef` is now the original.
- **On confirm** we send `pts` in original px directly — the backend `warp_card_to`/`getPerspectiveTransform` consumes original-image coordinates, so **no rescaling** is needed client-side.

### Initial handle positions
1. **Preferred — the auto-detected quad**, so the user only nudges what's wrong. Requires the backend `/centering` response to include the source corners in original px. Add one field `src_corners: corners.tolist()` to the `/centering` return (card_detector already computes `corners`); CenteringStage stashes it and passes as `initialQuad`. (Small, optional backend enrichment — see appendix.)
2. **Fallback — inset rectangle** when `src_corners` is absent or `detect_method==='full_frame'`: 8% inset of the original,
   `TL=(0.08·W,0.08·H) TR=(0.92·W,0.08·H) BR=(0.92·W,0.92·H) BL=(0.08·W,0.92·H)`.
   `Reset corners` restores whichever of these was the initial.

---

## 4. Wire-up

### 4a. New API function (`src/api/cardcheckApi.js`)
Mirror `detectCentering` exactly (multipart, `NGROK_HEADERS`, `linkSignal`, `CENTERING_TIMEOUT_MS`):
```js
/**
 * Manually rectify a card the user traced → POST /centering/manual.
 * Sends the ORIGINAL image + 4 corner points (original-image px, TL,TR,BR,BL).
 * Returns the SAME shape as detectCentering so the caller re-seeds identically.
 * @param {File} imageFile — the ORIGINAL uploaded photo (not the warped one)
 * @param {[number,number][]} corners — [[x,y]×4] in original px, order TL,TR,BR,BL
 */
export async function manualRectify(imageFile, corners, { side, signal } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CENTERING_TIMEOUT_MS);
  linkSignal(controller, signal);
  const form = new FormData();
  form.append('file', imageFile);
  form.append('corners', JSON.stringify(corners));
  if (side) form.append('side', side);
  let res;
  try {
    res = await fetch(`${API_BASE}/centering/manual`, {
      method: 'POST', headers: NGROK_HEADERS, body: form, signal: controller.signal,
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error('Rectify timed out — please try again.');
    throw err;
  } finally { clearTimeout(timer); }
  if (!res.ok) throw new Error(`Manual rectify failed (${res.status}): ${await res.text()}`);
  return res.json();   // { warped_url, canvas, outer, seed, seed_reliable, detect_method:'manual', … }
}
```

### 4b. CenteringStage refactor — extract `applyDetect`, add `mode`
Pull the seed-and-load body out of `runDetect` into a reusable `applyDetect(d, signal)` so both auto-detect and manual-rectify share it — and so **Reset view keeps working on the manual crop** (it updates `outer0`/`seed0`):
```js
const applyDetect = useCallback((d, signal) => {
  const s = stateRef.current;
  s.canvas = d.canvas;
  s.outer = { ...d.outer };  s.inner = { ...d.seed };
  s.outer0 = { ...d.outer };  s.seed0 = { ...d.seed };   // Reset-view cache (now the manual crop)
  setSeedReliable(!!d.seed_reliable);
  setDetectMethod(d.detect_method || null);
  setWarpedUrl(d.warped_url);
  setStatus(d.detect_method === 'full_frame'
    ? 'Card not auto-detected — place the lines'
    : 'Card found — adjust the border lines');
  const img = new Image(); img.crossOrigin = 'anonymous';
  img.onload = () => { if (signal?.aborted) return; imgRef.current = img; fit(); draw(); setReady(true); };
  img.src = `${API_BASE}${d.warped_url}?t=${Date.now()}`;
}, [fit, draw]);
```
`runDetect` now just: `const d = await detectCentering(file,{signal}); applyDetect(d, signal);` (plus its existing `src_corners` stash, `setReady(false)` and error handling).

Add state + handlers:
```js
const [mode, setMode] = useState('centering');      // 'centering' | 'outline'
const srcCornersRef = useRef(null);                 // from /centering.src_corners (or null)

const enterOutline = () => { if (loupeRef.current) loupeRef.current.style.display='none'; setMode('outline'); };
const exitOutline  = () => setMode('centering');
const onRectified  = (d) => { setReady(false); applyDetect(d); setMode('centering'); };
```
Render: when `mode==='outline'`, render `<ManualOutline file={file} side={side} initialQuad={srcCornersRef.current} onRectified={onRectified} onCancel={exitOutline} />` **instead of** the canvas+panel+Reset/Confirm block. Everything else (readout math, `handleConfirm`, `resetView`) is untouched.

### 4c. ManualOutline confirm
```js
const handleUseOutline = async () => {
  if (busy || invalid) return;
  const { pts } = stateRef.current;
  const corners = [[pts.tl.x,pts.tl.y],[pts.tr.x,pts.tr.y],[pts.br.x,pts.br.y],[pts.bl.x,pts.bl.y]];
  setBusy(true); setError(null);
  try {
    const d = await manualRectify(file, corners, { side });
    onRectified(d);            // → CenteringStage.applyDetect + mode='centering'
  } catch (e) {
    setError(e.message || 'Could not straighten the card. Try adjusting the corners.');
  } finally { setBusy(false); }
};
```
No `Pregrade.jsx` change is required: the corrected `warped_url`/`outer` reach `gradeCardV2` through the unchanged `handleCenteringConfirm` path.

### 4d. "Reset view" reloads the corrected image
Because `applyDetect` refreshes `outer0`/`seed0` and re-loads `warped_url` into `imgRef`, the existing `resetView` (CenteringStage.jsx:312) now restores the **manual** crop's auto-seed. To also force a fresh image decode (guard against a stale bitmap), have `resetView` additionally re-set `imgRef` from the current `warpedUrl` if `imgRef` is missing — a 3-line safety add. Optional but matches the task's "reload the original rectified image".

---

## 5. Accessibility, mobile, edge cases, microcopy

### Accessibility / mobile
- Pointer events unify mouse + touch; `touchAction:'none'` on the canvas (as in CenteringStage) stops page-scroll/pinch stealing the drag. Loupe canvas is `pointerEvents:'none'`, `position:fixed`, flips below the finger near the top — reused as-is, so **loupe-on-touch works identically to the existing centering step**.
- `canvas role="application"` + `aria-label`: "Card outline editor. Tap a corner or edge handle, drag to move it, then use arrow keys to nudge one pixel (hold Shift for ten)." `tabIndex={0}`, `outline:none`.
- Add `aria-live="polite"` text announcing the `selected` handle, e.g. "Top-left corner selected — arrow keys nudge."
- Handles ≥ 18px touch target (draw r≈9 but hit-test radius 16px like `nearest`). Larger corner dots than edge-mids for discoverability.
- Respect the panel's dark-mode classes (`dark:bg-gray-900`, etc.) as CenteringStage does.

### Edge cases
- **Points crossing / self-intersecting quad:** after every drag/nudge, run a convexity check (sign of the cross product at all 4 vertices must agree) **and** a min-area check (quad area ≥ ~4% of canvas). If it fails, set `invalid=true`: keep the stroke red, disable "Use this outline", show "Straighten the corners — the outline is twisted." Prevents a degenerate `getPerspectiveTransform`.
- **Corner ordering:** clamp each corner into a valid half so TL can't cross past TR/BL, etc. (soft clamp: keep ≥ 24px separation on each axis from its neighbors). Cheap and prevents most tangles before the convexity check even fires.
- **Tiny drags / accidental taps:** a pointerdown+up moving < 3px is a **select** (arm arrow-keys), not a move — `DRAG_GAIN` already suppresses jitter. Tap on empty canvas (no handle within 16px) does nothing.
- **Edge-mid vs corner overlap:** hit-test corners first, then edge-mids, so a corner near an edge-mid still wins.
- **Huge phone photos (4–6k px):** we draw a fitted canvas and the loupe samples the full-res in-memory `Image` — memory-bounded, no server round-trip. Decode once on mount.
- **Rectify failure / timeout:** inline red error under the actions (like CenteringStage), stay in outline mode so edits aren't lost.
- **Cancel mid-rectify:** disable Cancel while `busy`, or abort the fetch via the timeout controller.
- **Back button (Pregrade):** the CenteringStage `key={centeringSide}` remount already resets `mode` to `'centering'` when switching sides — no leak between front/back.

### Microcopy set
| Slot | Copy |
|---|---|
| Entry button (panel) | **Wrong outline? Re-trace the card** |
| Entry CTA (failed-detect box) | **Trace the card yourself** |
| Editor title | **Trace the card** |
| Editor subtitle | **Drag the 4 corners onto the real card corners. Drag an edge to slide it. A magnifier follows your finger.** |
| Hint line | After grabbing a handle, arrow keys nudge 1px (Shift = 10px). |
| Selected (aria-live) | *{Corner} selected — arrow keys nudge.* |
| Invalid state | **Straighten the corners — the outline is twisted.** |
| Primary action | **Use this outline** (busy: **Straightening…**) |
| Secondary | **Reset corners** · **Cancel** |
| Error | **Couldn't straighten the card. Adjust the corners and try again.** |
| Success (implicit) | returns silently to the green/cyan step on the corrected crop |

---

## 6. File-by-file changes + effort

| File | Change | LOC | Effort |
|---|---|---|---|
| `src/api/cardcheckApi.js` | Add `manualRectify(file, corners, {side,signal})` (mirror `detectCentering`) | ~30 | 0.5 h |
| `src/components/pregrade/ManualOutline.jsx` | **New** 8-point editor: fit/draw quad+handles, 2-D drag with `DRAG_GAIN`, reuse `showLoupe`/`refreshLoupe`, arrow-nudge, convexity guard, confirm→`manualRectify` | ~260 | 1 day |
| `src/components/pregrade/CenteringStage.jsx` | Extract `applyDetect`; add `mode` state + `enterOutline`/`exitOutline`/`onRectified`; stash `src_corners`; render `<ManualOutline>` in outline mode; entry buttons (panel + failed-detect box); 3-line `resetView` image-reload safety | ~55 | 3 h |
| `src/components/pregrade/Pregrade.jsx` | None required (optional: one hint line in the centering intro) | ~0–2 | — |
| *(optional)* `src/components/pregrade/loupe.js` | Lift `showLoupe`/`refreshLoupe` into a shared hook | ~40 | 1 h |

**Frontend total: ~1.5 dev-days** (editor + wiring + touch/edge polish).

### Backend dependency (not frontend, but blocks the feature) — appendix
Add `POST /centering/manual` in `D:\CardChecker\src\api.py`, ~25 lines, mirroring `/centering` (api.py:650):
- Accept `file` (original image) + `corners` (JSON `[[x,y]×4]`, original px) + optional `side`.
- `corners_np = np.array(corners, float32)`; `warped = warp_card_to(img, corners_np, CENTERING_W, CENTERING_H, mx, my)`; `seed = seed_inner_frame(warped, outer)`; save to `static/centering_<hash>.jpg`.
- Return the **identical** dict as `/centering` with `detect_method:'manual'`, `detect_confidence:1.0`, `seed_reliable:false`. That guarantees `applyDetect` re-seeds without any special-casing, and `_load_grade_geo` (api.py:1627) reads the manual warp from `static/` on `/grade` exactly like the auto one.
- *(Optional enrichment for §3 pre-seed)* add `src_corners: corners.tolist()` to the existing `/centering` response so ManualOutline starts from the detected quad instead of a blind inset rectangle. ~2 h backend incl. the enrichment.
