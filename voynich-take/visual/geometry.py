"""Per-folio page geometry: Voynichese word boxes aligned to the TTLI tokens
and registered onto the actual scan, plus pigment masks from the scan.

Voynichese XML (Apache 2.0, voynichese.com/1/data/folio/voynichese_data.zip):
<folio name="f1r" width="1090" height="1500"><word index x y width height>eva</word>...
Its coordinate space is a crop of the folio; register() recovers the
similarity transform (scale, offset) onto the scan by correlating the
rasterized word boxes with the scan's ink."""
import difflib
import glob
import json
import os
import re
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


# --------------------------------------------------------------------------
def find_xml(voynichese_dir, folio):
    for p in glob.glob(os.path.join(voynichese_dir, '**', '*.xml'), recursive=True):
        base = os.path.splitext(os.path.basename(p))[0].lower()
        if base == folio.lower():
            return p
    for p in glob.glob(os.path.join(voynichese_dir, '**', '*.xml'), recursive=True):
        try:
            root = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        if root.tag == 'folio' and root.get('name', '').lower() == folio.lower():
            return p
    return None


def parse_xml(path):
    root = ET.parse(path).getroot()
    words = []
    for w in root.findall('word'):
        words.append((w.text or '', int(w.get('x')), int(w.get('y')), int(w.get('width')), int(w.get('height'))))
    return {'name': root.get('name'), 'width': int(root.get('width')), 'height': int(root.get('height')), 'words': words}


def folio_tokens(fol):
    """All TTLI tokens of a folio in transcription order: (lineno, wi, word, kind)."""
    out = []
    for l in fol.lines:
        for i, w in enumerate(l.words):
            out.append((l.lineno, i, w, l.kind))
    return out


def align(tokens, xml_words):
    """Map each TTLI token to a Voynichese word index by sequence matching on
    the word strings; unmatched tokens borrow an interpolated box."""
    a = [t[2] for t in tokens]
    b = [w[0] for w in xml_words]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    idx = [None] * len(a)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                idx[i1 + k] = j1 + k
        elif tag == 'replace':
            n = i2 - i1
            m = j2 - j1
            for k in range(n):
                idx[i1 + k] = j1 + min(m - 1, int(k * m / n)) if m else None
    # fill gaps by nearest matched neighbour
    last = None
    for i in range(len(idx)):
        if idx[i] is None and last is not None:
            idx[i] = last
        elif idx[i] is not None:
            last = idx[i]
    nxt = None
    for i in range(len(idx) - 1, -1, -1):
        if idx[i] is None and nxt is not None:
            idx[i] = nxt
        elif idx[i] is not None:
            nxt = idx[i]
    matched = sum(1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == 'equal' for _ in range(i2 - i1))
    return idx, (matched / len(a) if a else 0.0)


# --------------------------------------------------------------------------
def load_scan_small(path, max_w=700):
    im = Image.open(path).convert('RGB')
    W, H = im.size
    d = max(1.0, W / max_w)
    small = im.resize((int(W / d), int(H / d)), Image.BILINEAR)
    return im.size, np.asarray(small).astype(np.float32) / 255.0, d


def _boxsum(a, r):
    k = 2 * r + 1
    p = np.pad(a, r, mode='constant')
    cs = np.pad(np.cumsum(np.cumsum(p, axis=0), axis=1), ((1, 0), (1, 0)), mode='constant')
    return cs[k:, k:] - cs[:-k, k:] - cs[k:, :-k] + cs[:-k, :-k]


def ink_mask(rgb_small):
    """Text ink only: dark, unsaturated strokes inside the vellum. The Yale
    scans show the page on a black ground with the book edges around it, so
    the mask is confined to the eroded vellum area; green / blue / red
    pigment is excluded by hue, and thick dark regions (drawings, stains,
    shadows) are removed so the box template cannot lock onto a plant."""
    g = rgb_small @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    vellum = (g > 0.30).astype(np.float32)
    r = max(4, int(rgb_small.shape[1] * 0.012))
    inside = _boxsum(vellum, r) >= ((2 * r + 1) ** 2) * 0.995          # eroded page
    # local vellum brightness (mean over the page within ~4% of the width), so faint
    # strokes count and gradual shading near the gutter does not
    rb = max(8, int(rgb_small.shape[1] * 0.04))
    insidef = inside.astype(np.float32)
    bg = _boxsum(g * insidef, rb) / np.maximum(_boxsum(insidef, rb), 1.0)
    rel = g / np.maximum(bg, 1e-3)
    # faint pages (the versos of the zodiac foldouts) barely pass a fixed ratio:
    # the darkest 4% of the page always count as ink
    p4 = float(np.percentile(rel[inside], 4)) if inside.any() else 0.86
    dark = rel < max(0.86, min(p4, 0.97))
    mx = np.max(rgb_small, axis=2); mn = np.min(rgb_small, axis=2)
    sat = np.where(mx > 0, (mx - mn) / (mx + 1e-6), 0)
    hue = _hue(rgb_small, mx, mn)
    pigment = (sat > 0.26) & (hue > 62) & (hue < 265)                    # green, blue
    red = (sat > 0.45) & ((hue < 22) | (hue > 340))
    ink = dark & inside & ~pigment & ~red
    inkf = ink.astype(np.float32)
    thick = _boxsum(inkf, 3) >= (7 * 7) * 0.9          # survives a 7x7 erosion: a blob
    thick = _boxsum(thick.astype(np.float32), 6) > 0     # dilate back
    return (ink & ~thick).astype(np.float32)


def _hue(rgb, mx, mn):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    dm = (mx - mn) + 1e-6
    h = np.where(mx == r, ((g - b) / dm) % 6, np.where(mx == g, (b - r) / dm + 2, (r - g) / dm + 4)) * 60
    return h


def vellum_bbox(rgb_small):
    """(x0, y0, x1, y1) of the page itself (bright area) in small pixels."""
    g = rgb_small @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    rows = np.where((g > 0.30).mean(axis=1) > 0.5)[0]
    cols = np.where((g > 0.30).mean(axis=0) > 0.5)[0]
    if len(rows) == 0 or len(cols) == 0:
        return (0, 0, rgb_small.shape[1], rgb_small.shape[0])
    return (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)


def _raster_boxes(boxes, W, H, s, pad=1, sy=None):
    """Fill word boxes (xml space) into an array at scale s (sy vertically)."""
    sy = s if sy is None else sy
    w, h = max(1, int(W * s)), max(1, int(H * sy))
    a = np.zeros((h, w), dtype=np.float32)
    for x, y, bw, bh in boxes:
        x0, y0 = int(x * s), int(y * sy)
        x1, y1 = int((x + bw) * s) + pad, int((y + bh) * sy) + pad
        a[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = 1.0
    return a


def _xcorr_max(template, image, window=None):
    """Cross-correlate (template may be larger than image in either dim);
    returns (score, oy, ox) of the best placement of template on image.
    window = (wy, wx): only placements with |oy| <= wy and |ox| <= wx."""
    H = image.shape[0] + template.shape[0]
    W = image.shape[1] + template.shape[1]
    fi = np.fft.rfft2(image, (H, W))
    tz = template - template.mean()            # zero-mean: uniform dark areas score nothing
    ft = np.fft.rfft2(tz, (H, W))
    c = np.fft.irfft2(fi * np.conj(ft), (H, W))
    if window is not None:
        wy, wx = int(window[0]), int(window[1])
        m = np.full(c.shape, -np.inf, dtype=c.dtype)
        m[:wy + 1, :wx + 1] = c[:wy + 1, :wx + 1]
        if wy:
            m[-wy:, :wx + 1] = c[-wy:, :wx + 1]
        if wx:
            m[:wy + 1, -wx:] = c[:wy + 1, -wx:]
        if wy and wx:
            m[-wy:, -wx:] = c[-wy:, -wx:]
        c = m
    k = np.unravel_index(np.argmax(c), c.shape)
    oy = k[0] if k[0] < image.shape[0] else k[0] - H
    ox = k[1] if k[1] < image.shape[1] else k[1] - W
    return float(c[k]) / float(np.abs(tz).sum() + 1e-6), oy, ox


def register(scan_small, d, xml, points=None):
    """Recover scale (scan px per xml px) and offset (scan px) that place the
    Voynichese boxes on the scan. The Voynichese frame is the Yale image
    scaled to 1500 px tall (verified: widths agree within 1%), so the scale
    prior is scan_height / frame_height and the offset stays near the
    origin on a single page; on a foldout opening (image much wider than
    the frame) the panel may sit anywhere. points: optional list of (x, y)
    in xml space (rosettes tokens) used instead of boxes, with a free
    search."""
    ink = ink_mask(scan_small)
    Hs, Ws = ink.shape
    W, H = xml['width'], xml['height']
    if points is None:
        boxes = [(x, y, w, h) for _, x, y, w, h in xml['words']]
    else:
        boxes = [(x - 6, y - 6, 12, 12) for x, y in points]
    best = None

    def evaluate(scales, windowed=False):
        nonlocal best
        for s in scales:
            tmpl = _raster_boxes(boxes, W, H, s)
            if tmpl.shape[0] > Hs * 1.3 or tmpl.shape[1] > Ws * 1.3:
                continue
            window = None
            if windowed:      # near the origin, plus whatever the frame overhangs the image by
                window = (0.07 * Hs + max(0.0, H * s - Hs), 0.07 * Ws + max(0.0, W * s - Ws))
            score, oy, ox = _xcorr_max(tmpl, ink, window)
            if best is None or score > best[0]:
                best = (score, s, oy, ox)
    if points is None:
        base = Hs / H
        single = W * base > 0.8 * Ws              # the frame is (about) the whole image
        evaluate(np.geomspace(base * 0.965, base * 1.035, 11), single)   # measured: within 2.5%
        s0 = best[1]
        evaluate(np.geomspace(s0 * 0.985, s0 * 1.015, 7), single)
    else:
        # the spatial frame's aspect differs from the photo's: independent x / y scales
        bx, by = Ws / W, Hs / H
        for sx in np.geomspace(bx * 0.6, bx * 1.05, 14):
            for sy in np.geomspace(by * 0.6, by * 1.05, 14):
                tmpl = _raster_boxes(boxes, W, H, sx, sy=sy)
                if tmpl.shape[0] > Hs * 1.3 or tmpl.shape[1] > Ws * 1.3:
                    continue
                score, oy, ox = _xcorr_max(tmpl, ink)
                if best is None or score > best[0]:
                    best = (score, sx, oy, ox, sy)
        _, sx0, _, _, sy0 = best
        for sx in np.geomspace(sx0 * 0.96, sx0 * 1.04, 9):
            for sy in np.geomspace(sy0 * 0.96, sy0 * 1.04, 9):
                tmpl = _raster_boxes(boxes, W, H, sx, sy=sy)
                score, oy, ox = _xcorr_max(tmpl, ink)
                if score > best[0]:
                    best = (score, sx, oy, ox, sy)
        score, sx, oy, ox, sy = best
        return {'scale': sx * d, 'sy': sy * d, 'ox': ox * d, 'oy': oy * d, 'score': round(score, 4)}
    score, s, oy, ox = best
    return {'scale': s * d, 'ox': ox * d, 'oy': oy * d, 'score': round(score, 4)}


def refine(scan_path, reg, xml, points=None, max_w=1500):
    """Second pass at ~2x the resolution in a +-1.5% scale window around the
    coarse solution."""
    size, small, d = load_scan_small(scan_path, max_w=max_w)
    ink = ink_mask(small)
    Hs, Ws = ink.shape
    W, H = xml['width'], xml['height']
    boxes = ([(x, y, w, h) for _, x, y, w, h in xml['words']] if points is None
             else [(x - 5, y - 5, 10, 10) for x, y in points])
    s_c = reg['scale'] / d
    sy_c = reg['sy'] / d if 'sy' in reg else None
    best = None
    for s in np.linspace(s_c * 0.985, s_c * 1.015, 9):
        tmpl = _raster_boxes(boxes, W, H, s, sy=(None if sy_c is None else sy_c * s / s_c))
        if tmpl.shape[0] > Hs * 1.3 or tmpl.shape[1] > Ws * 1.3:
            continue
        score, oy, ox = _xcorr_max(tmpl, ink)
        # stay near the coarse offset (within 3% of the page) to avoid a new false lock
        if abs(ox * d - reg['ox']) > 0.03 * size[0] or abs(oy * d - reg['oy']) > 0.03 * size[1]:
            continue
        if best is None or score > best[0]:
            best = (score, s, oy, ox)
    if best is None:
        return reg
    score, s, oy, ox = best
    out = {'scale': s * d, 'ox': ox * d, 'oy': oy * d, 'score': round(score, 4), 'refined': True}
    if sy_c is not None:
        out['sy'] = sy_c * s / s_c * d
    return out


def ring_fits(scan_path, reg, rings, max_w=1500, window=0.06):
    """The foldout is creased differently in the two photographs, so after the
    global fit each rosette is fitted on its own as a rigid unit: its ring of
    tokens is an annulus of radius r_out, searched over a radius factor and a
    position window on the darkness map. Returns {ring id: (dx, dy, f)} in
    scan px / a factor on the global scale; (0, 0, 1) when nothing locks."""
    size, small, d = load_scan_small(scan_path, max_w=max_w)
    dk = _blur(darkness(small), 2)
    Hs, Ws = dk.shape
    s, sy = reg['scale'] / d, reg.get('sy', reg['scale']) / d
    out = {}
    for r in rings:
        cx, cy = reg['ox'] / d + r['cx'] * s, reg['oy'] / d + r['cy'] * sy
        R0 = r['r_out'] * (s + sy) / 2
        best = None
        for f in np.geomspace(0.85, 1.35, 15):
            R = R0 * f
            half = int(R * 1.3)
            yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
            rr = np.sqrt(yy * yy + xx * xx)
            ring = ((rr >= R * 0.88) & (rr <= R * 1.03)).astype(np.float32)     # the ring of tokens ...
            outside = ((rr > R * 1.06) & (rr <= R * 1.28)).astype(np.float32)   # ... with bare vellum beyond it
            annulus = ring - outside * (ring.sum() / max(outside.sum(), 1.0))    # (an inner ring would fail this)
            score, oy, ox = _xcorr_near(annulus, dk, cy - half, cx - half, window * Hs, window * Ws)
            dx, dy = (ox + half - cx), (oy + half - cy)
            if best is None or score > best[0]:
                best = (score, dx, dy, f)
        score, dx, dy, f = best
        if abs(dx) >= 0.95 * window * Ws or abs(dy) >= 0.95 * window * Hs or f < 0.87 or f > 1.33:
            dx, dy, f = 0.0, 0.0, 1.0                                          # ran to an edge: no lock
        out[r['id']] = (dx * d, dy * d, float(f))
    return out


def darkness(rgb_small):
    """How much darker than the local vellum each pixel is (0..1), page only."""
    g = rgb_small @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    vellum = (g > 0.30).astype(np.float32)
    r = max(4, int(rgb_small.shape[1] * 0.012))
    inside = (_boxsum(vellum, r) >= ((2 * r + 1) ** 2) * 0.995).astype(np.float32)
    rb = max(8, int(rgb_small.shape[1] * 0.08))
    bg = _boxsum(g * inside, rb) / np.maximum(_boxsum(inside, rb), 1.0)
    bg = np.maximum(bg, np.percentile(g[inside > 0], 60) * 0.8) if inside.any() else bg
    return np.clip((bg - g) / np.maximum(bg, 1e-3), 0, 1) * inside


def _xcorr_near(template, image, cy, cx, wy, wx):
    """Best placement of template on image within a window around (cy, cx)."""
    H = image.shape[0] + template.shape[0]
    W = image.shape[1] + template.shape[1]
    fi = np.fft.rfft2(image, (H, W))
    tz = template - template.mean()
    c = np.fft.irfft2(fi * np.conj(np.fft.rfft2(tz, (H, W))), (H, W))
    ys = np.arange(H); ys = np.where(ys < image.shape[0], ys, ys - H)
    xs = np.arange(W); xs = np.where(xs < image.shape[1], xs, xs - W)
    keep = (np.abs(ys - cy) <= wy)[:, None] & (np.abs(xs - cx) <= wx)[None, :]
    c = np.where(keep, c, -np.inf)
    k = np.unravel_index(np.argmax(c), c.shape)
    return float(c[k]) / float(np.abs(tz).sum() + 1e-6), float(ys[k[0]]), float(xs[k[1]])


def paint_masks(rgb_small):
    """Pigment masks (0..1) from hue/saturation/value of the scan."""
    r, g, b = rgb_small[..., 0], rgb_small[..., 1], rgb_small[..., 2]
    mx = np.max(rgb_small, axis=2)
    mn = np.min(rgb_small, axis=2)
    v = mx
    sat = np.where(mx > 0, (mx - mn) / (mx + 1e-6), 0)
    hue = np.zeros_like(mx)
    dm = (mx - mn) + 1e-6
    hue = np.where(mx == r, ((g - b) / dm) % 6, np.where(mx == g, (b - r) / dm + 2, (r - g) / dm + 4)) * 60
    # vellum itself is a warm yellow-brown with modest saturation; pigments are more saturated
    vs = np.median(sat)
    def band(lo, hi, smin):
        h = ((hue >= lo) & (hue <= hi)) if lo <= hi else ((hue >= lo) | (hue <= hi))
        m = h & (sat > max(smin, vs + 0.15)) & (v > 0.15)
        return m.astype(np.float32)
    masks = {'green': band(62, 170, 0.22), 'redbrown': band(345, 22, 0.35), 'yellow': band(35, 60, 0.42),
             'blue': band(185, 255, 0.18)}
    # soften
    for k in masks:
        masks[k] = _blur(masks[k], 2)
    return masks


def _blur(a, r):
    if r <= 0:
        return a
    k = 2 * r + 1
    cs = np.cumsum(np.pad(a, ((r, r + 1), (0, 0)), mode='edge'), axis=0)
    a = (cs[k:] - cs[:-k]) / k
    cs = np.cumsum(np.pad(a, ((0, 0), (r, r + 1)), mode='edge'), axis=1)
    return (cs[:, k:] - cs[:, :-k]) / k


# --------------------------------------------------------------------------
class FolioGeometry:
    """boxes: {(lineno, wi): (x, y, w, h)} in scan pixels; lines: {lineno: (x,y,w,h)};
    masks at small scale with factor d; scan size (W, H)."""

    def __init__(self, folio, size, boxes, lines, masks, d, reg, match_rate, ring_points=None):
        self.folio, self.size, self.boxes, self.lines = folio, size, boxes, lines
        self.masks, self.d, self.reg, self.match_rate = masks, d, reg, match_rate
        self.ring_points = ring_points or {}

    def content_bbox(self):
        if not self.boxes:
            return (0, 0, self.size[0], self.size[1])
        xs = [b[0] for b in self.boxes.values()] + [b[0] + b[2] for b in self.boxes.values()]
        ys = [b[1] for b in self.boxes.values()] + [b[1] + b[3] for b in self.boxes.values()]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _apply(reg, x, y, w, h):
    s = reg['scale']
    sy = reg.get('sy', s)
    return (x * s + reg['ox'], y * sy + reg['oy'], w * s, h * sy)


def build_geometry(folio, fol, scan_path, voynichese_dir, cache_dir, manual=None, rings=None, qa_dir=None):
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, folio + '.json')
    npz = os.path.join(cache_dir, folio + '.npz')
    if os.path.exists(cache) and os.path.exists(npz) and manual is None:
        j = json.load(open(cache))
        m = np.load(npz)
        masks = {k: m[k] for k in m.files}
        boxes = {tuple(json.loads(k)): tuple(v) for k, v in j['boxes'].items()}
        lines = {k: tuple(v) for k, v in j['lines'].items()}
        rp = {int(k): v for k, v in j.get('ring_points', {}).items()}
        return FolioGeometry(folio, tuple(j['size']), boxes, lines, masks, j['d'], j['reg'], j['match_rate'], rp)
    size, small, d = load_scan_small(scan_path)
    masks = paint_masks(small)
    boxes, lines, reg, match_rate = {}, {}, None, 0.0
    ring_points = {}
    if rings is not None:                       # the rosettes foldout: spatial points
        pts = [(x, y) for r in rings for (x, y, _) in r['xy']]
        xml = {'width': 2412, 'height': 2375, 'words': []}
        manual = manual or {}
        reg = ({k: v for k, v in manual.items() if k != 'ring_fits'} if 'scale' in manual
               else refine(scan_path, register(small, d, xml, points=pts), xml, points=pts))
        fits = ring_fits(scan_path, reg, rings)
        for k, v in manual.get('ring_fits', {}).items():         # hand corrections: {ring id: [dx, dy, f]}
            fits[int(k)] = (float(v[0]), float(v[1]), float(v[2]))
        for r in rings:
            dx, dy, f = fits.get(r['id'], (0.0, 0.0, 1.0))
            cx, cy, _, _ = _apply(reg, r['cx'], r['cy'], 0, 0)
            cx, cy = cx + dx, cy + dy
            cx0, cy0 = cx - dx, cy - dy
            pts = []
            for (x, y, a) in r['xy']:
                px, py, _, _ = _apply(reg, x, y, 0, 0)
                pts.append((cx + (px - cx0) * f, cy + (py - cy0) * f, a))    # rigid: scaled about the centre
            ring_points[r['id']] = pts
            ring_points[r['id']].append((cx, cy, r['r_out'] * f * (reg['scale'] + reg.get('sy', reg['scale'])) / 2))     # last entry = centre + radius
        reg = dict(reg, ring_fits={str(k): [round(float(v[0]), 1), round(float(v[1]), 1), round(float(v[2]), 3)] for k, v in fits.items()})
    else:
        xp = find_xml(voynichese_dir, folio) if voynichese_dir else None
        if xp:
            xml = parse_xml(xp)
            tokens = folio_tokens(fol)
            idx, match_rate = align(tokens, xml['words'])
            reg = manual or refine(scan_path, register(small, d, xml), xml)
            for (ln, wi, w, kind), j in zip(tokens, idx):
                if j is None:
                    continue
                _, x, y, bw, bh = xml['words'][j]
                boxes[(ln, wi)] = _apply(reg, x, y, bw, bh)
            for ln in {k[0] for k in boxes}:
                bs = [b for k, b in boxes.items() if k[0] == ln]
                x0 = min(b[0] for b in bs); y0 = min(b[1] for b in bs)
                x1 = max(b[0] + b[2] for b in bs); y1 = max(b[1] + b[3] for b in bs)
                lines[ln] = (x0, y0, x1 - x0, y1 - y0)
    g = FolioGeometry(folio, size, boxes, lines, masks, d, reg, match_rate, ring_points)
    with open(cache, 'w') as fh:
        json.dump({'size': size, 'd': d, 'reg': reg, 'match_rate': match_rate,
                   'boxes': {json.dumps(list(k)): list(v) for k, v in boxes.items()},
                   'lines': {k: list(v) for k, v in lines.items()},
                   'ring_points': {str(k): v for k, v in ring_points.items()}}, fh)
    np.savez_compressed(npz, **masks)
    if qa_dir:
        write_qa(g, scan_path, qa_dir)
    return g


def write_qa(g, scan_path, qa_dir):
    """A contact sheet: the scan with every registered word box drawn on it."""
    from PIL import ImageDraw
    os.makedirs(qa_dir, exist_ok=True)
    im = Image.open(scan_path).convert('RGB')
    W, H = im.size
    d = max(1.0, W / 1400)
    im = im.resize((int(W / d), int(H / d)), Image.BILINEAR)
    dr = ImageDraw.Draw(im, 'RGBA')
    for (ln, wi), (x, y, w, h) in g.boxes.items():
        dr.rectangle([x / d, y / d, (x + w) / d, (y + h) / d], outline=(0, 120, 255, 200), width=2)
    for rid, pts in g.ring_points.items():
        for (x, y, a) in pts[:-1]:
            dr.ellipse([x / d - 4, y / d - 4, x / d + 4, y / d + 4], outline=(255, 60, 0, 220), width=2)
        cx, cy, r = pts[-1]
        dr.ellipse([(cx - r) / d, (cy - r) / d, (cx + r) / d, (cy + r) / d], outline=(255, 60, 0, 120), width=2)
    dr.text((10, 10), f"{g.folio}  match {g.match_rate:.0%}  reg {g.reg}", fill=(255, 255, 255, 255))
    im.save(os.path.join(qa_dir, g.folio + '.jpg'), quality=80)
