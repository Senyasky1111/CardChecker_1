# Backend plan — "Reidentify card" (manual 8-point rectify)

**Goal:** when auto card-detection is wrong, the user drags 8 points (4 corners + 4 edge
midpoints) over the **original** uploaded photo (doc-scanner style). Backend perspective-warps
the original to a perpendicular, aspect-exact (0.716) top-down crop and returns it as the new
rectified image + centering seed, so the existing green/cyan centering UI continues on a correct
crop.

Scope here = **backend only**. Frontend contract is specified so it can be built against it.

---

## 1. Current flow (upload → warp → return)

Auto path, all in `src/`:

```
CenteringStage.jsx  --(POST /centering, multipart: file=<original File>)-->  api.py:650 centering_endpoint
   api.py reads bytes -> Image.open(...).convert("RGB")               (api.py:664-665)
   rect = rectify_for_centering(image, backend="opencv")              (card_detector.py:207)
        detect_outer_quad(img)  (bg subtraction)                      (card_detector.py:143)
          -> else get_detector(backend).detect(...) / full_frame fallback
        corners = order_corners(quad)                                 (card_detector.py:71)
        warped = warp_card_to(img, corners, CENTERING_W, CENTERING_H, mx, my)  (card_detector.py:129)
   seed = seed_inner_frame(rect["warped"], rect["outer"])             (card_detector.py:243)
   save warped -> static/centering_{md5(contents[:1024])}.jpg         (api.py:673-675)
   return { warped_url, canvas{w,h}, outer, seed, seed_reliable, detect_method, detect_confidence, ... }
```

Key constants (`card_detector.py`): `CARD_ASPECT = 63/88 ≈ 0.7159`, `CENTERING_H=1760`,
`CENTERING_W=round(1760*0.7159)=1260`, `MARGIN_FRAC=0.08` → `mx=round(0.08*1260)=101`,
`my=round(0.08*1760)=141`. Canvas returned = `1462 × 2042`. Outer box (the green card-edge
lines) = `{left:101, top:141, right:1361, bottom:1901}` — i.e. the card fills the interior and
the 8% margin samples surrounding background so the outer line is draggable. **This is the exact
shape the manual endpoint must reproduce.**

`warp_card_to` (the piece we reuse): orders the 4 corners TL/TR/BR/BL via `order_corners`,
does a landscape auto-rotate (`np.roll` if top-edge > 1.1×left-edge — a no-op for a portrait
card), builds `dst` at the margin offset, and returns `cv2.warpPerspective(..., INTER_LANCZOS4)`.
So a **4-corner homography to the fixed 0.716 canvas is already implemented** — manual mode just
needs to feed it user corners instead of detected ones.

`/centering/compute` (api.py:701) is unaffected — it only takes `{outer, inner}` in canvas px and
returns the ratios. Manual mode plugs in upstream of it unchanged.

### Is the original photo retained server-side?
**No — only client-side.** `/centering` reads `contents`, warps, saves **only** the warped image
to `static/`, and discards the original bytes. Client-side the original **is** retained for the
whole pregrade flow: `Pregrade.jsx` holds `frontFile`/`backFile` in `useState`
(`Pregrade.jsx:62-63`), passes one as `file` into `CenteringStage` (`Pregrade.jsx:388`), and the
same Files are later handed to `gradeCardV2` (`Pregrade.jsx:180`). `CenteringStage.runDetect`
re-POSTs that `file` to `/centering` on every mount/reset (`CenteringStage.jsx:277`). **So the
frontend already holds the original File and can re-send it to a new endpoint** — no server-side
retention or upload-id needed.

---

## 2. NEW endpoint — `POST /centering/manual`

Same request style as `/centering` + `/grade`: multipart with the re-sent original File, plus the
8 points as a JSON `Form` field (mirrors how `/grade` takes `front_outer` as a JSON string,
api.py:1665). **Response is byte-for-byte the same shape as `/centering`**, so `CenteringStage`
reuses its existing `runDetect` render path verbatim (only the fetch call differs).

### Request (multipart/form-data)
| field | type | notes |
|-------|------|-------|
| `file` | file (required) | the **original** photo, re-sent by the client |
| `points` | Form string (required) | JSON, see below |
| `backend` | query, default `opencv` | kept for symmetry; unused in manual (no detection) |

`points` JSON — coordinates in **original-image natural pixels** (post-EXIF, see risks):
```json
{
  "corners": { "tl": [x,y], "tr": [x,y], "br": [x,y], "bl": [x,y] },
  "edges":   { "top": [x,y], "right": [x,y], "bottom": [x,y], "left": [x,y] },
  "img_w": 4325,
  "img_h": 5996
}
```
- `corners` **required** (the 4 draggable corner handles). Labels are advisory — the backend
  re-orders geometrically via `order_corners`, so a scrambled order still works.
- `edges` **optional** — accepted and validated, but **not used for the warp** in v1 (see §3).
  Send them so we can add curvature correction later without a contract change.
- `img_w`/`img_h` **strongly recommended** = the pixel dimensions the point coords are relative to
  (the `naturalWidth/Height` of the image the user dragged on). Lets the backend rescale if the
  client displayed/sent a downscaled preview, and cross-check EXIF orientation.

### Response (identical keys to `/centering`)
```json
{
  "warped_url": "/static/centering_manual_<fh>_<phash>.jpg",
  "canvas": { "w": 1462, "h": 2042 },
  "outer": { "left":101, "top":141, "right":1361, "bottom":1901 },
  "seed":  { "left":..., "right":..., "top":..., "bottom":... },
  "seed_reliable": true,
  "detect_method": "manual",
  "detect_confidence": 1.0,
  "processing_time_ms": 42.1
}
```

### Endpoint sketch (`src/api.py`)
```python
from PIL import ImageOps
import json as _json

@app.post("/centering/manual")
async def centering_manual_endpoint(
    file: UploadFile = File(...),
    points: str = Form(...),
    backend: str = Query(default="opencv"),  # unused; kept for symmetry
):
    """Rectify a card from USER-placed corners (manual re-detect). Returns the same shape
    as /centering so the client reuses its centering render path unchanged."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    contents = await file.read()
    if len(contents) > MAX_GRADE_IMAGE_BYTES:            # reuse the 15 MB guard
        raise HTTPException(413, "Image too large (max 15 MB)")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(contents))).convert("RGB")
    except Exception:
        raise HTTPException(400, "File is not a readable image")
    W, H = image.size
    if W * H > MAX_GRADE_IMAGE_PIXELS:                   # reuse the 40 MP bomb guard
        raise HTTPException(413, "Image resolution too high")

    try:
        p = _json.loads(points)
        c = p["corners"]
        corners = [c["tl"], c["tr"], c["br"], c["bl"]]   # 4x[x,y]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "points must be JSON with corners.{tl,tr,br,bl}")

    # rescale if the client's coords are relative to a different (downscaled) size
    iw, ih = float(p.get("img_w") or W), float(p.get("img_h") or H)
    sx, sy = (W / iw if iw else 1.0), (H / ih if ih else 1.0)
    pts = np.array([[float(x) * sx, float(y) * sy] for x, y in corners], np.float32)

    t0 = time.time()
    try:
        rect = rectify_manual(image, pts)                # new helper in card_detector.py
    except ValueError as e:                              # degenerate / out-of-bounds quad
        raise HTTPException(422, str(e))
    seed = seed_inner_frame(rect["warped"], rect["outer"])
    elapsed_ms = (time.time() - t0) * 1000

    import hashlib
    fh = hashlib.md5(contents[:1024]).hexdigest()[:8]
    phash = hashlib.md5(pts.tobytes()).hexdigest()[:6]   # distinct per point-set; idempotent re-runs
    warp_name = f"centering_manual_{fh}_{phash}.jpg"
    rect["warped"].save(f"static/{warp_name}")

    return {
        "warped_url": f"/static/{warp_name}",
        "canvas": {"w": rect["W"], "h": rect["H"]},
        "outer": rect["outer"],
        "seed": {k: seed[k] for k in ("left", "right", "top", "bottom")},
        "seed_reliable": seed["reliable"],
        "detect_method": "manual",
        "detect_confidence": 1.0,
        "processing_time_ms": round(elapsed_ms, 1),
    }
```

---

## 3. Warp math — recommendation

**Use option A now: 4-corner homography via the existing `warp_card_to`
(`cv2.getPerspectiveTransform`) to the fixed 0.716 canvas; keep the 4 edge midpoints reserved.**

Why:
- A homography (8 DoF) is **fully determined by the 4 corner correspondences**. Adding the 4 edge
  midpoints over-constrains it and can only be honored by a *non-projective* model (mesh/TPS),
  which changes the transform class.
- A trading card is **planar and rigid**; the only reason a straight-line homography would be
  "wrong" is real physical bow/warp or lens barrel distortion, which for a graded-condition photo
  are sub-pixel-to-tiny. Modeling them (option B barrel-fit, option C thin-plate-spline / mesh
  warp) is **premature** — extra params, harder to validate, and it can *inject* curvature that
  moves the border band and corrupts the very centering measurement we're protecting.
- The midpoints still earn their place: (a) they let the UI show 8 handles for precise edge
  placement (the corner is inferred from where the user pulls the edges), and (b) the backend can
  use them as a **sanity signal** — if a midpoint deviates from the straight line between its two
  corners by more than a few percent of the edge length, the physical edge is bowed; we can flag
  it (`"edge_bow": true`) and revisit option C later. No warp change in v1.

New helper reuses `order_corners` + `warp_card_to` (`src/card_detector.py`):
```python
def rectify_manual(image: Image.Image, corners_px: np.ndarray) -> dict:
    """Rectify from 4 USER-placed corners (original-image px) to the SAME hi-res, aspect-exact
    (0.716) canvas as rectify_for_centering. corners_px: 4x2 float32 (any order)."""
    img = np.array(image.convert("RGB"))
    H, W = img.shape[:2]
    ordered = order_corners(corners_px.astype(np.float32))

    # --- degenerate / out-of-bounds guards ---
    pad = 0.02 * max(W, H)
    if (ordered[:, 0] < -pad).any() or (ordered[:, 0] > W + pad).any() or \
       (ordered[:, 1] < -pad).any() or (ordered[:, 1] > H + pad).any():
        raise ValueError("corner points fall outside the image")
    quad = ordered.reshape(-1, 1, 2).astype(np.int32)
    area = abs(cv2.contourArea(quad))
    if area < 0.01 * W * H:
        raise ValueError("selected quad is too small / degenerate")
    if not cv2.isContourConvex(quad):
        raise ValueError("selected points are not a convex quad")

    mx, my = round(MARGIN_FRAC * CENTERING_W), round(MARGIN_FRAC * CENTERING_H)
    warped = warp_card_to(img, ordered, CENTERING_W, CENTERING_H, mx, my)  # REUSE
    cw, ch = CENTERING_W + 2 * mx, CENTERING_H + 2 * my
    outer = {"left": mx, "top": my, "right": mx + CENTERING_W, "bottom": my + CENTERING_H}
    return {"warped": warped, "W": cw, "H": ch, "outer": outer,
            "corners": ordered, "confidence": 1.0, "method": "manual", "card_found": True}
```
Note: `warp_card_to` internally calls `order_corners` again (idempotent) and applies a landscape
auto-rotate that is a no-op for a portrait quad. Leave it; if a ~90°-rotated card ever needs
respecting the user's exact TL, add a `rotate=False` param to `warp_card_to` (one-line refactor).

---

## 4. How the result seeds the existing centering step

The manual warp lands the user's card edges exactly on the margin box, so:
- **Outer lines (green)** = the returned `outer` = `{101,141,1361,1901}` — already sitting on the
  card edge (same as auto). The user usually won't touch them.
- **Inner seed (cyan)** = `seed_inner_frame(warped, outer)` scanned inward from those outer edges —
  identical mechanism to auto. It's a rough guess (`seed_reliable` reflects gradient strength);
  the user drags the 4 inner lines, then `/centering/compute` returns the ratio. **Zero new
  centering logic** — the manual endpoint just produces a better `warped`+`outer`+`seed` triple
  for the same downstream flow. The `warped_url` is also what `/grade` later reads for its crops
  (api.py:1627 `_load_grade_geo`), so a manual rectify improves grading crops for free.

---

## 5. "Reset view" clean re-fetch

Two facts:
- The warped image is a plain static asset. It's served both by the `/static` mount
  (api.py:1793) **and** the path-traversal-safe `FileResponse` route (api.py:1640-1642), and the
  client already loads it with a cache-buster (`img.src = ${API_BASE}${warped_url}?t=${Date.now()}`,
  CenteringStage.jsx:301). **So a clean re-fetch is fully supported today** — no backend change
  needed for reload.
- `resetView` (CenteringStage.jsx:312) is already **local** — it restores cached `outer0`/`seed0`
  and re-fits; it does not refetch. For manual mode the frontend just caches the *manual*
  response's `outer`/`seed` into `outer0`/`seed0` (exactly as it caches the auto ones at
  CenteringStage.jsx:283-284). Reset then restores the manual lines, and the already-loaded manual
  warp stays on the canvas. If we ever want a true image reload, the `?t=` cache-buster already
  guarantees it's clean.

**Backend action:** ensure the manual warp filename is **distinct** from the auto one
(`centering_manual_<fh>_<phash>.jpg` vs `centering_<fh>.jpg`) so a manual rectify does not
overwrite the auto warp — both remain independently re-fetchable if the user flips between them.
Including `phash` also makes identical re-submissions idempotent (same URL, no static churn).

---

## 6. File-by-file changes, effort, risks

### Changes
| File | Change | ~LOC |
|------|--------|------|
| `src/card_detector.py` | add `rectify_manual(image, corners_px)` (reuses `order_corners` + `warp_card_to` + `MARGIN_FRAC`/`CENTERING_W/H`); degenerate/OOB guards | ~30 |
| `src/api.py` | add `POST /centering/manual` (exif_transpose, bytes/pixel guards reusing `MAX_GRADE_IMAGE_BYTES/PIXELS`, points parse + rescale, call `rectify_manual`, `seed_inner_frame`, save static, return `/centering`-shaped dict); import `ImageOps`, `rectify_manual` | ~55 |
| *(frontend, out of scope)* | `cardcheckApi.js`: `reidentifyCentering(file, points)`; `CenteringStage.jsx`: 8-handle drag over the original, POST points, swap in the response via the existing render path | — |

No DB, no auth, no schema changes. `/centering/compute` and `/grade` unchanged (they already
consume `outer`/`warped_url`).

**Effort:** backend ~2-3h incl. a `pytest` covering: happy path (points → 1462×2042 canvas +
`method:"manual"`), scrambled corner order, degenerate quad → 422, out-of-bounds → 422, EXIF-rotated
input, and downscaled-preview rescale (`img_w/img_h` ≠ decoded size).

### Risks / edge cases
- **EXIF orientation (highest risk).** Neither `/centering` nor `/grade` currently apply
  `exif_transpose`; the auto path is internally consistent because it never mixes in
  browser-space coords. Manual mode **does** (points come from the browser-oriented image, which
  browsers auto-rotate). **Mitigation:** `ImageOps.exif_transpose` in the manual endpoint so PIL's
  array matches what the user dragged on. Consider (separately, with a test) adding the same to
  `/centering` for whole-pipeline consistency — low risk, not required for this feature.
- **Downscaled preview.** Clients often display a shrunk copy but re-send the full-res File; the
  dragged coords are then in preview space. **Mitigation:** `img_w/img_h` in the payload +
  rescale by `W/img_w, H/img_h`. If absent, assume coords are full-res.
- **Points out of order.** Handled — `order_corners` assigns TL/TR/BR/BL geometrically, so the
  label keys are advisory. Fails only for a card rotated ~>45° in-frame (rare for a re-detect fix);
  note as a known limitation.
- **Degenerate / non-convex quad** (coincident/collinear points, self-intersection, tiny area):
  explicit guards (`contourArea` floor, `isContourConvex`) → HTTP 422 with a clear message rather
  than a garbage homography.
- **Huge SAR photos (4325×5996 = 25.9 MP).** Under the 40 MP cap; decode ≈78 MB RGB, and
  `warpPerspective` samples the source into a ~1462×2042 dst — fast and bounded. The existing
  `MAX_GRADE_IMAGE_BYTES` (15 MB) / `MAX_GRADE_IMAGE_PIXELS` (40 MP) guards are reused.
- **Static churn.** Manual warps accumulate in `static/` like the auto ones do today (no cleanup
  job). Pre-existing debt; the `phash` keeps re-runs idempotent. A TTL sweep of `static/centering_*`
  is a separate cleanup task, not a blocker.
```
