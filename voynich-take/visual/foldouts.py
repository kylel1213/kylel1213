"""Cut the foldout panels out of the Yale openings.

The transcription and the Voynichese boxes name foldout panels (f70r1,
f72v3, ...); Yale photographs each foldout as a whole opening ("69v and
70r"). The Voynichese frame of a panel is one page tall (1500 px), so on
a parent of height Hp the panel is Hp/1500 scan px per frame px, and the
panels of one opening tile it side by side. For every feasible assignment
of a group's panels to its parent images (width must fit) and every
left-to-right order, each panel is correlated with the parent's ink in a
window around its tiled position; the best-scoring layout wins and the
panels are cropped at full resolution.

  python -m visual.foldouts --data data            # download parents, locate, crop -> data/foldouts/crops
  python -m visual.foldouts --data data --install  # copy the crops into data/scans/<panel>.jpg

QA: data/foldouts/qa/<parent>.jpg shows each parent with its crops."""
import argparse
import itertools
import json
import os
import shutil
import sys
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from visual.geometry import find_xml, parse_xml, load_scan_small, ink_mask, _raster_boxes, _xcorr_max  # noqa: E402
from visual.fetch import get  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
IIIF = 'https://collections.library.yale.edu/iiif/2/{id}/full/full/0/default.jpg'

# groups: candidate parent ids (manifest order) and the panels they hold between them
GROUPS = [
    ([1006194], ['f67r1', 'f67r2']),
    ([1006195], ['f67v1', 'f67v2']),
    ([1006196], ['f68r1', 'f68r2', 'f68r3']),
    ([1006197], ['f68v1', 'f68v2', 'f68v3']),
    ([1006199], ['f69v', 'f70r1', 'f70r2']),
    ([1006200, 1006201], ['f70v1', 'f70v2']),
    ([1006203], ['f71v', 'f72r1', 'f72r2', 'f72r3']),
    ([1006204, 1006205], ['f72v1', 'f72v2', 'f72v3']),
    ([1006228, 1006229, 1006230], ['f85r1', 'f85r2', 'f86v3', 'f86v4', 'f86v5', 'f86v6']),
    ([1006233], ['f88v', 'f89r1', 'f89r2']),
    ([1006234, 1006235, 1006236, 1006237], ['f89v1', 'f89v2', 'f90r1', 'f90r2', 'f90v1', 'f90v2']),
    ([1006241], ['f94v', 'f95r1', 'f95r2']),
    ([1006242, 1006243], ['f95v1', 'f95v2']),
    ([1006249], ['f100v', 'f101r1']),
    ([1006250, 1006251], ['f101v2', 'f102r1', 'f102r2']),
    ([1006252, 1006253], ['f102v1', 'f102v2']),
]
# panels with no Voynichese boxes (riffle only): the whole parent image
WHOLE = {'f101r': 1006249, 'f101r2': 1006249, 'f101v': 1006250, 'f101v1': 1006250}
MAX_LAYOUTS = 60
# hand-measured crops (parent px) where the correlation could not lock (faint versos)
CROP_OVERRIDES = {'f72v3': (1006204, (700, 0, 3600, 3794))}


class Parent:
    def __init__(self, pid, path):
        self.id, self.path = pid, path
        # keep ~0.36 small px per scan px so the text strokes survive the downscale
        with Image.open(path) as im:
            W0 = im.size[0]
        self.size, self.small, self.d = load_scan_small(path, max_w=int(min(3600, max(1400, 0.36 * W0))))
        self.ink = ink_mask(self.small)
        self.Hs, self.Ws = self.ink.shape
        self.s_small = self.Hs / 1500.0         # frame px -> small px
        self.cache = {}

    def fit(self, panel_xml, scale_factor=1.0, x_center=None):
        """Best placement of the panel's boxes at scales around the prior;
        x window around x_center (small px) if given, else free."""
        W, H = panel_xml['width'], panel_xml['height']
        boxes = [(x, y, w, h) for _, x, y, w, h in panel_xml['words']]
        best = None
        for s in np.geomspace(self.s_small * scale_factor * 0.965, self.s_small * scale_factor * 1.035, 9):
            tmpl = _raster_boxes(boxes, W, H, s)
            if tmpl.shape[0] > self.Hs * 1.3 or tmpl.shape[1] > self.Ws * 1.3:
                continue
            H2, W2 = self.Hs + tmpl.shape[0], self.Ws + tmpl.shape[1]
            fi = self._fft(H2, W2)
            tz = tmpl - tmpl.mean()
            c = np.fft.irfft2(fi * np.conj(np.fft.rfft2(tz, (H2, W2))), (H2, W2))
            wy = int(0.07 * self.Hs + max(0.0, H * s - self.Hs))
            m = np.full(c.shape, -np.inf, dtype=c.dtype)
            m[:wy + 1] = c[:wy + 1]
            m[-wy:] = c[-wy:]
            if x_center is not None:
                wx = int(0.045 * self.Ws)
                xs = np.arange(W2)
                xs = np.where(xs < self.Ws, xs, xs - W2)
                keep = np.abs(xs - x_center) <= wx
                m[:, ~keep] = -np.inf
            k = np.unravel_index(np.argmax(m), m.shape)
            oy = k[0] if k[0] < self.Hs else k[0] - H2
            ox = k[1] if k[1] < self.Ws else k[1] - W2
            score = float(m[k]) / float(np.abs(tz).sum() + 1e-6)
            if best is None or score > best[0]:
                best = (score, s, oy, ox)
        if best is None:                      # the frame does not fit this parent at any scale
            return None
        score, s, oy, ox = best
        return {'scale': s * self.d, 'ox': ox * self.d, 'oy': oy * self.d, 'score': round(score, 4)}

    def _fft(self, H2, W2):
        key = (H2, W2)
        if key not in self.cache:
            self.cache[key] = np.fft.rfft2(self.ink, (H2, W2))
        return self.cache[key]


def layouts(parents, panels, xmls):
    """Feasible (parent -> ordered panels) assignments: each parent holds a
    contiguous run of the panel list in forward or reversed order (rectos
    unfold rightwards, versos leftwards); a run's frame widths must fit."""
    n = len(panels)
    out = []

    def fits(p, run):
        return sum(xmls[q]['width'] for q in run) * p.s_small <= p.Ws * 1.08

    def rec(i, pi, cur):
        if i == n:
            out.append(dict(cur)); return
        if pi >= len(parents):
            return
        p = parents[pi]
        # this parent may hold 0 panels (a duplicate view) or a run of 1..(n-i)
        rec(i, pi + 1, cur)
        for k in range(1, n - i + 1):
            run = panels[i:i + k]
            if not fits(p, run):
                break
            for order in ([run] if k == 1 else [run, run[::-1]]):
                cur[p.id] = list(order)
                rec(i + k, pi + 1, cur)
                del cur[p.id]
    rec(0, 0, {})
    return out


def score_layout(parents, layout, xmls):
    """Windowed fits at the tiled positions; returns (total score, placements)."""
    total, places = 0.0, {}
    byid = {p.id: p for p in parents}
    for pid, run in layout.items():
        p = byid[pid]
        widths = [xmls[q]['width'] * p.s_small for q in run]
        slack = p.Ws - sum(widths)
        x = slack / 2.0
        prev_right = None
        for q, w in zip(run, widths):
            reg = p.fit(xmls[q], x_center=x)
            if reg is None:
                return -1e9, {}
            places[q] = (pid, reg)
            total += reg['score']
            left = reg['ox'] / p.d
            if prev_right is not None and left < prev_right:        # frames carry margins: tolerate 20% overlap
                over = (prev_right - left) / min(w, widths[run.index(q) - 1])
                total -= 0.05 * max(0.0, over - 0.20)
            prev_right = left + xmls[q]['width'] * reg['scale'] / p.d
            x += w
    return total, places


def crop_rect(size, reg, xml, margin=0.02):
    s = reg['scale']
    x0, y0 = reg['ox'], reg['oy']
    x1, y1 = x0 + xml['width'] * s, y0 + xml['height'] * s
    mw, mh = (x1 - x0) * margin, (y1 - y0) * margin
    return (int(max(0, x0 - mw)), int(max(0, y0 - mh)), int(min(size[0], x1 + mw)), int(min(size[1], y1 + mh)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--only', default='', help='comma-separated panels: only groups containing them')
    args = ap.parse_args()
    root = os.path.join(args.data, 'foldouts')
    parents_dir, crops, qa = [os.path.join(root, n) for n in ('parents', 'crops', 'qa')]
    for p in (parents_dir, crops, qa):
        os.makedirs(p, exist_ok=True)
    scans = os.path.join(args.data, 'scans')
    if args.install:
        n = 0
        for name in sorted(os.listdir(crops)):
            if name.endswith('.jpg'):
                shutil.copyfile(os.path.join(crops, name), os.path.join(scans, name))
                n += 1
        print(f'installed {n} panel images into {scans}')
        return
    only = {f for f in args.only.split(',') if f}
    voy = os.path.join(args.data, 'voynichese')
    ids = sorted({i for c, _ in GROUPS for i in c} | set(WHOLE.values()))
    for i in ids:
        dst = os.path.join(parents_dir, f'{i}.jpg')
        if not (os.path.exists(dst) and os.path.getsize(dst) > 10000):
            print('fetching parent', i, flush=True)
            with open(dst, 'wb') as fh:
                fh.write(get(IIIF.format(id=i)))
    report_path = os.path.join(root, 'report.json')
    report = json.load(open(report_path)) if os.path.exists(report_path) else {}
    for cands, panels in GROUPS:
        if only and not (only & set(panels)):
            continue
        xmls = {}
        for q in panels:
            xp = find_xml(voy, q)
            if xp:
                xmls[q] = parse_xml(xp)
        panels = [q for q in panels if q in xmls]
        parents = [Parent(i, os.path.join(parents_dir, f'{i}.jpg')) for i in cands]
        # rectos unfold rightwards, versos leftwards: the parent images may come in
        # either direction relative to the panel numbering
        lays = layouts(parents, panels, xmls)
        seen = {json.dumps(l, sort_keys=True) for l in lays}
        for l in layouts(parents[::-1], panels, xmls):
            if json.dumps(l, sort_keys=True) not in seen:
                lays.append(l)
        if not lays:                                    # nothing fits at the page-height scale: free search
            print(f'{panels}: no tiling fits {cands}; free search', flush=True)
            for q in panels:
                best = None
                for p in parents:
                    for sf in (1.0, 0.9, 0.8):
                        reg = p.fit(xmls[q], scale_factor=sf)
                        if reg is not None and (best is None or reg['score'] > best[1]['score']):
                            best = (p.id, reg)
                if best is None:
                    print(f'  {q}: fits no candidate parent', flush=True)
                    continue
                _emit(q, best[0], best[1], xmls[q], parents_dir, crops, report)
            json.dump(report, open(report_path, 'w'), indent=1)
            continue
        if len(lays) > MAX_LAYOUTS:
            print(f'{panels}: {len(lays)} layouts, keeping the first {MAX_LAYOUTS}', flush=True)
            lays = lays[:MAX_LAYOUTS]
        best = None
        for lay in lays:
            tot, places = score_layout(parents, lay, xmls)
            if best is None or tot > best[0]:
                best = (tot, lay, places)
        tot, lay, places = best
        print(f'{panels}: {len(lays)} layouts; best {tot:.4f}: ' +
              ', '.join(f'{pid}=[{",".join(run)}]' for pid, run in lay.items()), flush=True)
        for q, (pid, reg) in places.items():
            _emit(q, pid, reg, xmls[q], parents_dir, crops, report)
        # QA per parent
        for pid, run in lay.items():
            _qa(pid, run, places, xmls, parents_dir, qa)
        json.dump(report, open(report_path, 'w'), indent=1)
    for panel, i in WHOLE.items():
        if only and panel not in only:
            continue
        shutil.copyfile(os.path.join(parents_dir, f'{i}.jpg'), os.path.join(crops, panel + '.jpg'))
        report[panel] = {'parent': i, 'whole': True}
    for panel, (i, rect) in CROP_OVERRIDES.items():
        if only and panel not in only:
            continue
        Image.open(os.path.join(parents_dir, f'{i}.jpg')).convert('RGB').crop(rect).save(os.path.join(crops, panel + '.jpg'), quality=94)
        report[panel] = {'parent': i, 'rect': list(rect), 'manual': True}
    json.dump(report, open(report_path, 'w'), indent=1)
    print('done; check', qa, 'then run with --install', flush=True)


def _emit(q, pid, reg, xml, parents_dir, crops, report):
    path = os.path.join(parents_dir, f'{pid}.jpg')
    im = Image.open(path).convert('RGB')
    rect = crop_rect(im.size, reg, xml)
    im.crop(rect).save(os.path.join(crops, q + '.jpg'), quality=94)
    report[q] = {'parent': pid, 'reg': {k: (float(v) if not isinstance(v, bool) else v) for k, v in reg.items()},
                 'rect': rect, 'parent_size': im.size}
    print(f'  {q}: parent {pid}, rect {rect}, score {reg["score"]}', flush=True)


def _qa(pid, run, places, xmls, parents_dir, qa):
    path = os.path.join(parents_dir, f'{pid}.jpg')
    im = Image.open(path).convert('RGB')
    size = im.size
    d = max(1.0, size[0] / 1800)
    q = im.resize((int(size[0] / d), int(size[1] / d)), Image.BILINEAR)
    dr = ImageDraw.Draw(q, 'RGBA')
    cols = [(255, 40, 0), (0, 200, 80), (255, 200, 0), (200, 0, 255)]
    for k, name in enumerate(run):
        _, reg = places[name]
        rect = crop_rect(size, reg, xmls[name])
        col = cols[k % len(cols)]
        dr.rectangle([rect[0] / d, rect[1] / d, rect[2] / d, rect[3] / d], outline=col + (230,), width=4)
        s = reg['scale']
        for _, x, y, w, h in xmls[name]['words']:
            X, Y = (x * s + reg['ox']) / d, (y * s + reg['oy']) / d
            dr.rectangle([X, Y, X + w * s / d, Y + h * s / d], outline=(0, 120, 255, 200), width=1)
        dr.text((rect[0] / d + 8, rect[1] / d + 8), f'{name} {reg["score"]}', fill=col + (255,))
    q.save(os.path.join(qa, f'{pid}.jpg'), quality=80)


if __name__ == '__main__':
    main()
