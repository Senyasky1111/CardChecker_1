"""Integration tests for POST /centering/manual (manual card re-trace).

Calls the async endpoint function directly with in-memory UploadFiles (no app lifespan,
no model load). Covers: happy path returns the /centering shape with detect_method:"manual",
the `points` object and bare `corners` field both work, scrambled corner order is re-ordered,
downscaled-preview coords are rescaled via img_w/img_h, EXIF orientation is applied, and the
degenerate / out-of-bounds / non-convex / missing-points / bad-image failures map to 4xx.
"""
import asyncio
import io
import json

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import Headers, UploadFile

import src.api as api


# A card-like source: 1000x1400 with a lighter rectangle so the warp has real content.
def _card_png(w: int = 1000, h: int = 1400) -> bytes:
    img = Image.new("RGB", (w, h), (30, 30, 30))
    inner = Image.new("RGB", (int(w * 0.8), int(h * 0.8)), (200, 200, 200))
    img.paste(inner, (int(w * 0.1), int(h * 0.1)))
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _upload(data: bytes, name: str = "card.png", ctype: str = "image/png") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data),
                      headers=Headers({"content-type": ctype}))


# A convex, in-bounds quad (TL, TR, BR, BL) for a 1000x1400 image.
GOOD_CORNERS = [[100, 140], [900, 140], [900, 1260], [100, 1260]]


def _call(upload, *, points=None, corners=None, side=None):
    return asyncio.run(api.centering_manual_endpoint(
        file=upload,
        points=json.dumps(points) if points is not None else None,
        corners=json.dumps(corners) if corners is not None else None,
        side=side, backend="opencv",
    ))


@pytest.fixture(autouse=True)
def _static_dir(tmp_path, monkeypatch):
    """Run in a temp CWD with a static/ dir so warps don't pollute the repo."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "static").mkdir()
    yield tmp_path


def test_happy_path_points_returns_centering_shape(_static_dir):
    r = _call(_upload(_card_png()),
              points={"corners": GOOD_CORNERS, "img_w": 1000, "img_h": 1400})
    # identical shape/keys to /centering
    assert set(r) == {"warped_url", "canvas", "outer", "seed", "seed_reliable",
                      "detect_method", "detect_confidence", "processing_time_ms"}
    assert r["detect_method"] == "manual"
    assert r["detect_confidence"] == 1.0
    assert r["canvas"] == {"w": 1462, "h": 2042}
    assert r["outer"] == {"left": 101, "top": 141, "right": 1361, "bottom": 1901}
    assert set(r["seed"]) == {"left", "right", "top", "bottom"}
    # the warp file was actually written under static/
    assert (_static_dir / "static" / r["warped_url"].split("/")[-1]).exists()
    assert r["warped_url"].startswith("/static/centering_manual_")


def test_bare_corners_field_is_accepted(_static_dir):
    r = _call(_upload(_card_png()), corners=GOOD_CORNERS)
    assert r["detect_method"] == "manual"
    assert r["canvas"] == {"w": 1462, "h": 2042}


def test_corners_dict_form_is_accepted(_static_dir):
    d = {"tl": [100, 140], "tr": [900, 140], "br": [900, 1260], "bl": [100, 1260]}
    r = _call(_upload(_card_png()), points={"corners": d})
    assert r["detect_method"] == "manual"


def test_scrambled_corner_order_still_works(_static_dir):
    scrambled = [GOOD_CORNERS[2], GOOD_CORNERS[0], GOOD_CORNERS[3], GOOD_CORNERS[1]]
    r = _call(_upload(_card_png()), corners=scrambled)
    assert r["outer"] == {"left": 101, "top": 141, "right": 1361, "bottom": 1901}


def test_edges_are_accepted_and_ignored(_static_dir):
    r = _call(_upload(_card_png()),
              points={"corners": GOOD_CORNERS, "edges": {"top": [500, 140]},
                      "img_w": 1000, "img_h": 1400})
    assert r["detect_method"] == "manual"


def test_downscaled_preview_coords_are_rescaled(_static_dir):
    # Client dragged on a half-size preview (500x700) but re-sent the full 1000x1400 file.
    half = [[c[0] / 2, c[1] / 2] for c in GOOD_CORNERS]
    r = _call(_upload(_card_png()),
              points={"corners": half, "img_w": 500, "img_h": 700})
    # rescaled back to full res -> same outer box as the full-res call
    assert r["outer"] == {"left": 101, "top": 141, "right": 1361, "bottom": 1901}


def test_exif_orientation_is_applied(_static_dir):
    # Landscape 1400x1000 JPEG tagged orientation=6 (rotate 90 CW on display) -> becomes 1000x1400.
    img = Image.new("RGB", (1400, 1000), (200, 200, 200))
    exif = img.getexif()
    exif[0x0112] = 6
    b = io.BytesIO()
    img.save(b, "JPEG", exif=exif)
    # corners are in the DISPLAY (post-EXIF, 1000x1400) space the user dragged on
    r = _call(_upload(b.getvalue(), name="c.jpg", ctype="image/jpeg"),
              points={"corners": GOOD_CORNERS, "img_w": 1000, "img_h": 1400})
    assert r["detect_method"] == "manual"


def test_degenerate_quad_returns_422(_static_dir):
    tiny = [[10, 10], [30, 10], [30, 30], [10, 30]]
    with pytest.raises(HTTPException) as ei:
        _call(_upload(_card_png()), corners=tiny)
    assert ei.value.status_code == 422


def test_out_of_bounds_returns_422(_static_dir):
    oob = [[-500, -500], [5000, 140], [5000, 5000], [100, 5000]]
    with pytest.raises(HTTPException) as ei:
        _call(_upload(_card_png()), corners=oob)
    assert ei.value.status_code == 422


def test_non_convex_returns_422(_static_dir):
    concave = [[50, 50], [950, 50], [500, 400], [500, 1350]]
    with pytest.raises(HTTPException) as ei:
        _call(_upload(_card_png()), corners=concave)
    assert ei.value.status_code == 422


def test_missing_points_returns_400(_static_dir):
    with pytest.raises(HTTPException) as ei:
        _call(_upload(_card_png()))
    assert ei.value.status_code == 400


def test_wrong_number_of_points_returns_400(_static_dir):
    with pytest.raises(HTTPException) as ei:
        _call(_upload(_card_png()), corners=[[1, 2], [3, 4]])
    assert ei.value.status_code == 400


def test_non_image_content_type_returns_400(_static_dir):
    bad = UploadFile(filename="x.txt", file=io.BytesIO(b"nope"),
                     headers=Headers({"content-type": "text/plain"}))
    with pytest.raises(HTTPException) as ei:
        _call(bad, corners=GOOD_CORNERS)
    assert ei.value.status_code == 400


def test_unreadable_image_returns_400(_static_dir):
    bad = UploadFile(filename="x.png", file=io.BytesIO(b"not a real image"),
                     headers=Headers({"content-type": "image/png"}))
    with pytest.raises(HTTPException) as ei:
        _call(bad, corners=GOOD_CORNERS)
    assert ei.value.status_code == 400


def test_idempotent_filename_for_same_points(_static_dir):
    png = _card_png()
    r1 = _call(_upload(png), corners=GOOD_CORNERS)
    r2 = _call(_upload(png), corners=GOOD_CORNERS)
    assert r1["warped_url"] == r2["warped_url"]  # same file hash + point hash
