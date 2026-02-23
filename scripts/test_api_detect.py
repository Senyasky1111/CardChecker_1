"""Test /detect-card and /identify-v2 endpoints with synthetic scenes."""
import sys
import json
import io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)


def create_scene(card_path: str, rotation: float = 15, scale: float = 0.5) -> bytes:
    """Create a synthetic scene with a card on dark background."""
    card = cv2.imread(card_path)
    if card is None:
        raise ValueError(f"Cannot read {card_path}")
    ch, cw = card.shape[:2]

    new_w = int(cw * scale)
    new_h = int(ch * scale)
    card = cv2.resize(card, (new_w, new_h))

    canvas_w, canvas_h = 1200, 900
    canvas = np.full((canvas_h, canvas_w, 3), (40, 40, 60), dtype=np.uint8)
    noise = np.random.randint(0, 15, canvas.shape, dtype=np.uint8)
    canvas = cv2.add(canvas, noise)

    src_pts = np.array([[0, 0], [new_w, 0], [new_w, new_h], [0, new_h]], dtype=np.float32)

    cx, cy = canvas_w / 2, canvas_h / 2
    rad = np.radians(rotation)
    dst_pts = []
    for sx, sy in src_pts:
        x, y = sx - new_w / 2, sy - new_h / 2
        rx = x * np.cos(rad) - y * np.sin(rad) + cx
        ry = x * np.sin(rad) + y * np.cos(rad) + cy
        dst_pts.append([rx, ry])
    dst_pts = np.array(dst_pts, dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    cv2.warpPerspective(card, M, (canvas_w, canvas_h), dst=canvas, borderMode=cv2.BORDER_TRANSPARENT)

    _, buf = cv2.imencode(".jpg", canvas)
    return buf.tobytes()


# Test 1: Direct card image
print("=" * 60)
print("Test 1: Direct card image (no background)")
with open("data/cardmarket/images/sv06.5/en_sv06.5-051.jpg", "rb") as f:
    resp = client.post("/detect-card", files={"file": ("test.jpg", f, "image/jpeg")})
data = resp.json()
print(f"  Detection: method={data['method']}, found={data['card_found']}, "
      f"conf={data['confidence']:.3f}, {data['processing_time_ms']:.0f}ms")

# Test 2: Synthetic scene — rotated card on background
print("\nTest 2: Synthetic scene (15deg rotation)")
scene_bytes = create_scene("data/cardmarket/images/sv06.5/en_sv06.5-051.jpg", rotation=15, scale=0.5)
resp = client.post("/detect-card", files={"file": ("scene.jpg", io.BytesIO(scene_bytes), "image/jpeg")})
data = resp.json()
print(f"  Detection: method={data['method']}, found={data['card_found']}, "
      f"conf={data['confidence']:.3f}, {data['processing_time_ms']:.0f}ms")

# Test 3: Full pipeline — identify-v2 with synthetic scene
print("\nTest 3: Full identify-v2 pipeline on synthetic scene")
scene_bytes = create_scene("data/cardmarket/images/sv06.5/en_sv06.5-051.jpg", rotation=10, scale=0.6)
resp = client.post("/identify-v2", files={"file": ("scene.jpg", io.BytesIO(scene_bytes), "image/jpeg")})
data = resp.json()
if resp.status_code != 200:
    print(f"  Skipped (DB not loaded in test mode): {data.get('detail', '')}")
else:
    print(f"  Success: {data['success']}")
    print(f"  Method: {data['method']}")
    print(f"  OCR name: {data.get('ocr_name')}")
    print(f"  OCR number: {data.get('ocr_number')}")
    if data.get('top_match'):
        m = data['top_match']
        print(f"  Top match: {m['name']} ({m['set_name']})")
        print(f"  Price: {m['price_trend']}")
    print(f"  Time: {data['processing_time_ms']:.0f}ms")

# Test 4: Japanese card
print("\nTest 4: Japanese card — synthetic scene")
jp_cards = list(Path("data/cardmarket/images").rglob("ja_*.jpg"))
if jp_cards:
    scene_bytes = create_scene(str(jp_cards[0]), rotation=5, scale=0.55)
    resp = client.post("/detect-card", files={"file": ("jp.jpg", io.BytesIO(scene_bytes), "image/jpeg")})
    data = resp.json()
    print(f"  Detection: method={data['method']}, found={data['card_found']}, "
          f"conf={data['confidence']:.3f}, {data['processing_time_ms']:.0f}ms")

print("\n" + "=" * 60)
print("All tests completed!")
