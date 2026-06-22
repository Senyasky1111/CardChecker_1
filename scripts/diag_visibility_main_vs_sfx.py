"""
Visibility experiment: flat MAIN vs specular SFX, per defect class.

Tests the user's single-view thesis:
  - WHITENING (CORNER/EDGE WEAR = white where color worn to cardstock) -> a flat
    brightness signal, should be VISIBLE in MAIN (high local white contrast).
  - EDGE/CORNER physical relief/dents -> should need specular SFX (high texture/relief
    energy in SFX, low in MAIN).

For each sampled defect point we crop a window in MAIN and SFX and measure:
  - white_contrast = (local max whiteness) - (local median whiteness)
       whiteness = V*(1-S) in HSV (0..255). High => a bright desaturated speck.
  - texture_energy = std of Sobel gradient magnitude (relief/specular highlights)

We report a per-class, per-image-type visibility RATE: fraction of points whose
signal exceeds a threshold calibrated against random control crops on the same card.
"""
import json, glob, os, sys, random, collections
import numpy as np
import cv2

random.seed(0); np.random.seed(0)

ROOT = 'data/tag_raw'
OUT  = 'data/_vis_demo'
os.makedirs(OUT, exist_ok=True)

WIN = 120  # half-size of crop window in pixels (window = 240x240)

def load_meta(p):
    try: return json.load(open(p))
    except: return None

def is_placeholder(x, y):
    # placeholder per spec: normalized space near (50,50) or near (0,0)
    if x <= 100 and y <= 100:
        if abs(x-50) <= 25 and abs(y-50) <= 25: return True
        if x <= 3 and y <= 3: return True
        return True  # ALL <=100 are normalized junk-prone center cluster; treat as ambiguous
    return False

def to_pixel(x, y, W, H):
    # mixed space: <=100 -> normalized 0..100; else already pixel
    if x <= 100 and y <= 100:
        return int(x/100.0*W), int(y/100.0*H)
    return int(x), int(y)

def whiteness_map(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    H, S, V = hsv[...,0], hsv[...,1], hsv[...,2]
    return V * (1.0 - S/255.0)  # 0..255

def texture_energy(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx*gx + gy*gy)
    return float(mag.std())

def white_contrast(bgr):
    wm = whiteness_map(bgr)
    # kill halftone with median blur, then top vs median
    wm_s = cv2.medianBlur(wm.astype(np.uint8), 5).astype(np.float32)
    return float(np.percentile(wm_s, 99) - np.median(wm_s))

def crop(img, px, py, win=WIN):
    H, W = img.shape[:2]
    x0 = max(0, px-win); x1 = min(W, px+win)
    y0 = max(0, py-win); y1 = min(H, py+win)
    if x1-x0 < 40 or y1-y0 < 40: return None
    return img[y0:y1, x0:x1]

def img_paths(cert_dir, side):
    pre = 'FRONT' if side == 'front' else 'BACK'
    return (os.path.join(cert_dir,'images',f'{pre}_MAIN.jpg'),
            os.path.join(cert_dir,'images',f'{pre}_SFX.jpg'))

# ---- build defect pools ----
WHITEN_TYPES = {'CORNER WEAR','EDGE WEAR'}  # user-framed whitening (white at border/corner)
# Distinguish: corner-wear vs edge-wear separately for class-level reporting.
pools = collections.defaultdict(list)   # class -> list of (cert_dir, side, x, y)

dirs = glob.glob(os.path.join(ROOT,'*','metadata.json'))
random.shuffle(dirs)
TARGET = 30
need = {'CORNER WEAR':TARGET, 'EDGE WEAR':TARGET}
scanned = 0
for p in dirs:
    if all(len(pools[k])>=need[k] for k in need): break
    scanned += 1
    m = load_meta(p)
    if not m: continue
    cert_dir = os.path.dirname(p)
    # require both image variants exist (front or back per defect)
    for d in m.get('surface_defects', []):
        t = d.get('defect_type'); side = d.get('side','front')
        x = d.get('x'); y = d.get('y')
        if t not in need or len(pools[t])>=need[t]: continue
        if not isinstance(x,(int,float)) or not isinstance(y,(int,float)): continue
        if is_placeholder(x,y): continue
        mp, sp = img_paths(cert_dir, side)
        if not (os.path.exists(mp) and os.path.exists(sp)): continue
        pools[t].append((cert_dir, side, x, y))

print('scanned cards:', scanned)
for k in need: print(f'  pool[{k}] = {len(pools[k])}')

# ---- measure ----
results = collections.defaultdict(lambda: collections.defaultdict(list))
montage_rows = []
def measure_point(cert_dir, side, x, y):
    mp, sp = img_paths(cert_dir, side)
    main = cv2.imread(mp); sfx = cv2.imread(sp)
    if main is None or sfx is None: return None
    H, W = main.shape[:2]
    px, py = to_pixel(x, y, W, H)
    cm = crop(main, px, py); cs = crop(sfx, px, py)
    if cm is None or cs is None: return None
    # control crops: 4 random locations on same image (interior band) for baseline
    def controls(img):
        wcs=[]; tes=[]
        for _ in range(6):
            rx = random.randint(WIN, W-WIN-1); ry = random.randint(WIN, H-WIN-1)
            c = crop(img, rx, ry)
            if c is None: continue
            wcs.append(white_contrast(c)); tes.append(texture_energy(c))
        return (np.median(wcs) if wcs else 0, np.median(tes) if tes else 0)
    cw_main = white_contrast(cm); cw_sfx = white_contrast(cs)
    te_main = texture_energy(cm); te_sfx = texture_energy(cs)
    base_w_m, base_t_m = controls(main)
    base_w_s, base_t_s = controls(sfx)
    return dict(cm=cm, cs=cs,
                cw_main=cw_main, cw_sfx=cw_sfx, te_main=te_main, te_sfx=te_sfx,
                base_w_m=base_w_m, base_t_m=base_t_m, base_w_s=base_w_s, base_t_s=base_t_s,
                cert=os.path.basename(cert_dir), side=side)

saved = 0
for cls in need:
    for (cert_dir, side, x, y) in pools[cls]:
        r = measure_point(cert_dir, side, x, y)
        if r is None: continue
        results[cls]['cw_main'].append(r['cw_main'])
        results[cls]['cw_sfx'].append(r['cw_sfx'])
        results[cls]['te_main'].append(r['te_main'])
        results[cls]['te_sfx'].append(r['te_sfx'])
        # visibility flags: signal exceeds 1.5x same-image random-control baseline
        results[cls]['wvis_main'].append(1 if r['cw_main'] > 1.5*max(r['base_w_m'],1) else 0)
        results[cls]['wvis_sfx'].append(1 if r['cw_sfx'] > 1.5*max(r['base_w_s'],1) else 0)
        results[cls]['tvis_main'].append(1 if r['te_main'] > 1.5*max(r['base_t_m'],1) else 0)
        results[cls]['tvis_sfx'].append(1 if r['te_sfx'] > 1.5*max(r['base_t_s'],1) else 0)
        # save a few montages
        if saved < 12:
            h = min(r['cm'].shape[0], r['cs'].shape[0]); w = min(r['cm'].shape[1], r['cs'].shape[1])
            cmr = cv2.resize(r['cm'], (w,h)); csr = cv2.resize(r['cs'], (w,h))
            sep = np.full((h,6,3),255,np.uint8)
            row = np.hstack([cmr, sep, csr])
            cv2.putText(row, f"{cls} {r['side']} MAIN|SFX cwM={r['cw_main']:.0f} cwS={r['cw_sfx']:.0f} teM={r['te_main']:.0f} teS={r['te_sfx']:.0f}",
                        (4,18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
            fn = os.path.join(OUT, f"{cls.replace(' ','_').replace('/','-')}_{r['cert']}_{saved}.jpg")
            cv2.imwrite(fn, row); saved += 1

def med(a): return float(np.median(a)) if a else float('nan')
def rate(a): return float(np.mean(a))*100 if a else float('nan')

print('\n================ RESULTS (medians; rates in %) ================')
for cls in need:
    R = results[cls]
    n = len(R['cw_main'])
    cwm=med(R['cw_main']); cws=med(R['cw_sfx'])
    tem=med(R['te_main']); tes=med(R['te_sfx'])
    wvm=rate(R['wvis_main']); wvs=rate(R['wvis_sfx'])
    tvm=rate(R['tvis_main']); tvs=rate(R['tvis_sfx'])
    print('\n[%s]  n=%d' % (cls, n))
    print('  white_contrast   MAIN median=%6.1f   SFX median=%6.1f' % (cwm, cws))
    print('  texture_energy   MAIN median=%6.1f   SFX median=%6.1f' % (tem, tes))
    print('  WHITE visible rate   MAIN=%5.1f%%   SFX=%5.1f%%' % (wvm, wvs))
    print('  TEXTURE visible rate MAIN=%5.1f%%   SFX=%5.1f%%' % (tvm, tvs))
    if R['te_main'] and R['te_sfx']:
        lift = (tes - tem) / max(tem,1) * 100
        print('  SFX texture lift over MAIN: %+.1f%%' % lift)

print('\nmontages saved to', OUT)
