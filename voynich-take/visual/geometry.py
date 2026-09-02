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
    """Text ink only: dark, low-saturation, thin strokes. Thick dark regions
    (drawings, stains) and saturated pigment are removed so the box template
    cannot lock onto a plant instead of the text."""
    g = rgb_small @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    vellum = np.median(g)
    dark = (g < vellum * 0.68)
    mx = np.max(rgb_small, axis=2); mn = np.min(rgb_small, axis=2)
    sat = np.where(mx > 0, (mx - mn) / (mx + 1e-6), 0)
    ink = dark & (sat < np.median(sat) + 0.25)
    inkf = ink.astype(np.float32)
    thick = _boxsum(inkf, 3) >= (7 * 7) * 0.9          # survives a 7x7 erosion: a blob
    thick = _boxsum(thick.astype(np.float32), 6) > 0     # dilate back
    return (ink & ~thick).astype(np.float32)


def _raster_boxes(boxes, W, H, s, pad=1):
    """Fill word boxes (xml space) into an array at scale s."""
    w, h = max(1, int(W * s)), max(1, int(H * s))
    a = np.zeros((h, w), dtype=np.float32)
    for x, y, bw, bh in boxes:
        x0, y0 = int(x * s), int(y * s)
        x1, y1 = int((x + bw) * s) + pad, int((y + bh) * s) + pad
        a[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = 1.0
    return a


def _xcorr_max(template, image):
    """Cross-correlate (template may be larger than image in either dim);
    returns (score, oy, ox) of the best placement of template on image."""
    H = image.shape[0] + template.shape[0]
    W = image.shape[1] + template.shape[1]
    fi = np.fft.rfft2(image, (H, W))
    tz = template - template.mean()            # zero-mean: uniform dark areas score nothing
    ft = np.fft.rfft2(tz, (H, W))
    c = np.fft.irfft2(fi * np.conj(ft), (H, W))
    # valid offsets: template placed at (oy, ox) may be partly outside; restrict to
    # placements that keep at least 70% of the template inside the image
    k = np.unravel_index(np.argmax(c), c.shape)
    oy = k[0] if k[0] < image.shape[0] else k[0] - H
    ox = k[1] if k[1] < image.shape[1] else k[1] - W
    return float(c[k]) / float(np.abs(tz).sum() + 1e-6), oy, ox


def register(scan_small, d, xml, points=None):
    """Recover scale (scan px per xml px) and offset (scan px) that place the
    Voynichese boxes on the scan. points: optional list of (x, y) in xml
    space (rosettes tokens) used instead of boxes."""
    ink = ink_mask(scan_small)
    Hs, Ws = ink.shape
    W, H = xml['width'], xml['height']
    if points is None:
        boxes = [(x, y, w, h) for _, x, y, w, h in xml['words']]
    else:
        boxes = [(x - 6, y - 6, 12, 12) for x, y in points]
    base = Ws / W                         # if the crop spanned the whole scan width
    best = None

    def evaluate(scales):
        nonlocal best
        for s in scales:
            tmpl = _raster_boxes(boxes, W, H, s)
            if tmpl.shape[0] > Hs * 1.3 or tmpl.shape[1] > Ws * 1.3:
                continue
            score, oy, ox = _xcorr_max(tmpl, ink)
            if best is None or score > best[0]:
                best = (score, s, oy, ox)
    evaluate(np.geomspace(base * 0.62, base * 1.05, 16))
    s0 = best[1]
    evaluate(np.geomspace(s0 * 0.95, s0 * 1.05, 11))
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
    best = None
    for s in np.linspace(s_c * 0.985, s_c * 1.015, 9):
        tmpl = _raster_boxes(boxes, W, H, s)
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
    return {'scale': s * d, 'ox': ox * d, 'oy': oy * d, 'score': round(score, 4), 'refined': True}


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
    return (x * s + reg['ox'], y * s + reg['oy'], w * s, h * s)


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
        reg = manual or refine(scan_path, register(small, d, xml, points=pts), xml, points=pts)
        for r in rings:
            ring_points[r['id']] = [(_apply(reg, x, y, 0, 0)[0], _apply(reg, x, y, 0, 0)[1], a) for (x, y, a) in r['xy']]
            cx, cy, _, _ = _apply(reg, r['cx'], r['cy'], 0, 0)
            ring_points[r['id']].append((cx, cy, r['r_out'] * reg['scale']))     # last entry = centre + radius
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
