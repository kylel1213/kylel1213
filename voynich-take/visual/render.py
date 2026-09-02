"""Frame renderer: the manuscript page, read aloud.

Screen space: W x H (1920x1080). Page space: scan pixels. A camera
(cx, cy, zoom = screen px per page px) is eased toward a target chosen by
the reading state. Layers, back to front:
  table (dark) -> page crop -> pigment washes -> word light / trails /
  dropped-word veils -> hits, blooms, ring lights -> entrainment pulses ->
  HUD (folio, movement, annotation strip, year-clock inset)."""
import bisect
import json
import math
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

Image.MAX_IMAGE_PIXELS = None

TABLE = np.array([0.055, 0.047, 0.040], dtype=np.float32)
GOLD = np.array([1.00, 0.84, 0.50], dtype=np.float32)        # Language A reading light
COOL = np.array([0.62, 0.86, 1.00], dtype=np.float32)        # Language B reading light
LABEL_COL = (255, 120, 70)
BLUE_COL = (110, 170, 255)
PAD_COL = np.array([0.35, 0.75, 0.35], dtype=np.float32)
RING_HUES = [(200, 60, 40), (220, 100, 40), (230, 150, 50), (230, 200, 70), (200, 220, 90),
             (120, 210, 150), (80, 190, 210), (100, 150, 240), (160, 120, 240)]   # by pool shift, low -> high
PC_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def lerp(a, b, t):
    return a + (b - a) * t


def ease(cur, target, dt, tau):
    k = 1 - math.exp(-dt / tau)
    return cur + (target - cur) * k


class Lane:
    def __init__(self, pts, default=0.0):
        self.t = np.array([p[0] for p in pts], dtype=np.float64) if pts else np.array([0.0])
        self.v = np.array([p[1] for p in pts], dtype=np.float64) if pts else np.array([default])

    def at(self, t):
        return float(np.interp(t, self.t, self.v))


class Events:
    def __init__(self, items, key='t'):
        self.items = sorted(items, key=lambda e: e[key])
        self.times = [e[key] for e in self.items]

    def window(self, t0, t1):
        i = bisect.bisect_left(self.times, t0)
        j = bisect.bisect_right(self.times, t1)
        return self.items[i:j]


class Page:
    """Scan pyramid + geometry for one folio."""

    def __init__(self, path, geom=None):
        im = Image.open(path).convert('RGB')
        self.size = im.size
        self.levels = [im]
        while self.levels[-1].size[0] > 900:
            l = self.levels[-1]
            self.levels.append(l.resize((l.size[0] // 2, l.size[1] // 2), Image.BILINEAR))
        self.geom = geom

    def crop(self, cam, W, H):
        """Return RGB float32 (H, W, 3) and coverage alpha (H, W)."""
        cx, cy, zoom = cam
        # choose the pyramid level whose scale is closest above the zoom
        lvl = 0
        for i, l in enumerate(self.levels):
            if l.size[0] / self.size[0] >= zoom:
                lvl = i
        l = self.levels[lvl]
        f = l.size[0] / self.size[0]
        z = zoom / f
        x0 = cx * f - W / 2 / z
        y0 = cy * f - H / 2 / z
        im = l.transform((W, H), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BILINEAR, fillcolor=(0, 0, 0))
        a = Image.new('L', l.size, 255).transform((W, H), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BILINEAR, fillcolor=0)
        return np.asarray(im).astype(np.float32) / 255.0, np.asarray(a).astype(np.float32) / 255.0

    def mask_crop(self, name, cam, W, H):
        if not self.geom or name not in self.geom.masks:
            return None
        m = self.geom.masks[name]
        d = self.geom.d
        cx, cy, zoom = cam
        z = zoom * d
        x0 = cx / d - W / 2 / z
        y0 = cy / d - H / 2 / z
        im = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8))
        out = im.transform((W, H), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BILINEAR, fillcolor=0)
        return np.asarray(out).astype(np.float32) / 255.0


def to_screen(cam, W, H, x, y):
    cx, cy, zoom = cam
    return (x - cx) * zoom + W / 2, (y - cy) * zoom + H / 2


class Renderer:
    def __init__(self, cues, scans_dir, geoms, W=1920, H=1080, fps=30, fonts=None, thumbs=None):
        self.cues, self.scans, self.geoms = cues, scans_dir, geoms
        self.W, self.H, self.fps = W, H, fps
        self.words = Events(cues['words'], 'start')
        self.labels = Events(cues['labels'])
        self.bass = Events(cues['bass'])
        self.pad = Events(cues['pad'])
        self.blue = Events(cues['blue'])
        self.clock = Events(cues['clock'])
        self.rings = Events(cues['rings'])
        self.spans = cues['folio_spans']
        self.span_starts = [s['start'] for s in self.spans]
        self.riffles = cues['riffles']
        self.lanes = {k: Lane(v, {'cc1': 60, 'cc11': 60, 'cc74': 40, 'beat_hz': 0}[k]) for k, v in cues['lanes'].items()}
        self.iso = cues['iso']
        self.movs = cues['movements']
        self.pages = {}
        self.thumbs = thumbs or {}
        fonts = fonts or {}
        self.font = ImageFont.truetype(fonts.get('sans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), 26)
        self.font_small = ImageFont.truetype(fonts.get('sans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), 19)
        self.font_title = ImageFont.truetype(fonts.get('serif', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'), 40)
        self.font_eva = ImageFont.truetype(fonts['eva'], 44) if fonts.get('eva') else self.font
        self.cam = None
        self.last_t = None
        self.cam_mode = 'FULL'
        self.ring_cache = {}

    # ------------------------------------------------------------------ state
    def page(self, folio):
        if folio not in self.pages:
            if len(self.pages) > 6:
                self.pages.pop(next(iter(self.pages)))
            path = os.path.join(self.scans, folio + '.jpg')
            self.pages[folio] = Page(path, self.geoms.get(folio))
        return self.pages[folio]

    def current_span(self, t):
        i = bisect.bisect_right(self.span_starts, t) - 1
        if i < 0:
            return None
        s = self.spans[i]
        return s if t < s['end'] + 0.01 else s

    def movement_at(self, t):
        for m in self.movs:
            if m['start'] <= t < m['end']:
                return m
        return self.movs[-1] if t >= self.movs[-1]['start'] else self.movs[0]

    def riffle_at(self, t):
        for r in self.riffles:
            if r['arrive'] - r['lead'] <= t < r['arrive']:
                return r
        return None

    # ------------------------------------------------------------------ camera
    def fit_cam(self, page, pad=0.94, rect=None):
        W, H = self.W, self.H
        if rect is None:
            pw, ph = page.size
            cx, cy = pw / 2, ph / 2
        else:
            x, y, w, h = rect
            cx, cy = x + w / 2, y + h / 2
            pw, ph = w, h
        zoom = min(W * pad / pw, H * pad / ph)
        return (cx, cy, zoom)

    def choose_camera(self, t, span, page, active_word, para_rect, style_hint):
        """FULL / PARA / LINE by section and moment; returns (target cam, mode)."""
        since = t - span['start']
        sec = span['section']
        folio = span['folio']
        geom = page.geom
        if style_hint == 'FULL' or since < 4.0 or sec in ('A', 'Z', 'C', 'P') or folio == 'f85v_86r' or not geom or not geom.boxes:
            return self.fit_cam(page), 'FULL'
        if active_word is None:
            return self.cam if self.cam else self.fit_cam(page), self.cam_mode
        key = (active_word['lineno'], active_word['wi'])
        box = geom.boxes.get(key)
        line = geom.lines.get(active_word['lineno'])
        if box is None or line is None:
            return self.fit_cam(page), 'FULL'
        if para_rect is not None and (t - para_rect[4]) < 3.0:
            x, y, w, h = para_rect[:4]
            m = h * 0.25
            return self.fit_cam(page, 0.9, (x - m, y - m, w + 2 * m, h + 2 * m)), 'PARA'
        lx, ly, lw, lh = line
        zoom = self.H * 0.62 / max(lh * 3.2, 1)
        zoom = min(zoom, 1.6)                             # never beyond 1.6 screen px per scan px
        # keep the whole line in view if it fits; else follow the word
        if lw * zoom <= self.W * 0.9:
            cx = lx + lw / 2
        else:
            cx = box[0] + box[2] / 2
        cy = ly + lh / 2
        return (cx, cy, zoom), 'LINE'

    def step_camera(self, target, mode, dt, snap=False):
        if self.cam is None or snap:
            self.cam = target
            self.cam_mode = mode
            return
        tau = 0.9 if mode == 'LINE' else 1.4
        cx, cy, z = self.cam
        tx, ty, tz = target
        self.cam = (ease(cx, tx, dt, tau), ease(cy, ty, dt, tau), math.exp(ease(math.log(z), math.log(tz), dt, tau)))
        self.cam_mode = mode

    # ------------------------------------------------------------------ frame
    def frame(self, t):
        W, H = self.W, self.H
        dt = (t - self.last_t) if self.last_t is not None else 1 / self.fps
        self.last_t = t
        img = np.empty((H, W, 3), dtype=np.float32)
        img[:] = TABLE
        r = self.riffle_at(t)
        if r is not None:
            self.draw_riffle(img, t, r)
            return self.finish(img, t, None)
        span = self.current_span(t)
        if span is None:
            return self.finish(img, t, None)
        page = self.page(span['folio'])
        # reading state
        recent = self.words.window(t - 4.0, t + 0.001)
        active = None
        for w in recent:
            if not w.get('dropped') and w['start'] <= t <= w['end'] + 0.05:
                active = w
        if active is None:
            cand = [w for w in recent if not w.get('dropped')]
            active = cand[-1] if cand else None
        para_rect = self.paragraph_rect(page, active, t)
        style = self.style_hint(t, span)
        target, mode = self.choose_camera(t, span, page, active, para_rect, style)
        self.step_camera(target, mode, dt, snap=(t - span['start']) < dt * 1.5)
        cam = self.cam
        base, alpha = page.crop(cam, W, H)
        img = img * (1 - alpha[..., None]) + base * alpha[..., None]
        # page shadow/edge
        self.pigment_layers(img, page, cam, t, span)
        ov = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
        dr = ImageDraw.Draw(ov)
        self.draw_words(dr, page, cam, t, recent, active, span)
        self.draw_hits(dr, page, cam, t, span)
        if span['folio'] == 'f85v_86r':
            self.draw_rings(dr, page, cam, t)
        ovf = np.asarray(ov.resize((W, H), Image.BILINEAR)).astype(np.float32) / 255.0
        img = img * (1 - ovf[..., 3:4] * 0.35) + ovf[..., :3] * ovf[..., 3:4] * 1.15
        self.entrainment_pulse(img, t)
        return self.finish(img, t, span, active)

    def style_hint(self, t, span):
        # the blue-bell window and every zodiac/rosette page are seen whole
        for b in self.blue.window(t - 6, t + 10):
            if b.get('folio') == span['folio']:
                return 'FULL'
        return None

    def paragraph_rect(self, page, active, t):
        """(x, y, w, h, t_start) of the paragraph the active word opens, if it just began."""
        if active is None or not page.geom:
            return None
        if active.get('wi') != 0 or (t - active['start']) > 3.0:
            return None
        # a paragraph start is a word with wi 0 whose line begins a paragraph: approximate by
        # the previous line's last word ending far enough in the past (a bar of padding)
        prev = [w for w in self.words.window(active['start'] - 6, active['start'] - 0.01) if not w.get('dropped')]
        if prev and active['start'] - prev[-1]['end'] < 1.2:
            return None
        ln = active['lineno']
        lines = page.geom.lines
        keys = sorted(lines, key=lambda k: int(k) if k.isdigit() else 0)
        if ln not in keys:
            return None
        i = keys.index(ln)
        sel = keys[i:i + 4]
        xs = [lines[k][0] for k in sel]; ys = [lines[k][1] for k in sel]
        xe = [lines[k][0] + lines[k][2] for k in sel]; ye = [lines[k][1] + lines[k][3] for k in sel]
        return (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys), active['start'])

    # ------------------------------------------------------------------ layers
    def pigment_layers(self, img, page, cam, t, span):
        W, H = self.W, self.H
        cc11 = self.lanes['cc11'].at(t) / 127.0
        cc1 = self.lanes['cc1'].at(t) / 127.0
        # pad: the green wash breathes with the chord; bloom at a chord change
        pads = self.pad.window(t - 8, t)
        bloom = 0.0
        if pads:
            bloom = math.exp(-(t - pads[-1]['t']) / 2.5)
        breath = 0.5 + 0.5 * math.sin(2 * math.pi * t / 6.0)
        g = page.mask_crop('green', cam, W, H)
        if g is not None:
            amt = cc11 * (0.35 + 0.25 * breath + 0.6 * bloom)
            img += g[..., None] * PAD_COL[None, None, :] * amt * 0.55
        # bass: red-brown pigment pulses at each paragraph root
        bs = self.bass.window(t - 6, t)
        if bs:
            pulse = math.exp(-(t - bs[-1]['t']) / 1.8)
            rb = page.mask_crop('redbrown', cam, W, H)
            if rb is not None and pulse > 0.02:
                img += rb[..., None] * np.array([0.9, 0.35, 0.15], dtype=np.float32) * pulse * 0.5
        # blue: the rare pigment flares on the bell
        bl = self.blue.window(t - 3, t)
        if bl:
            flare = math.exp(-(t - bl[-1]['t']) / 1.2)
            b = page.mask_crop('blue', cam, W, H)
            if b is not None:
                img += b[..., None] * np.array([0.3, 0.55, 1.0], dtype=np.float32) * flare * 0.9
        # painting lane: overall pigment saturation lift
        if cc1 > 0:
            gray = img.mean(axis=2, keepdims=True)
            img += (img - gray) * (0.12 * cc1)

    def light_color(self, t):
        d = (self.lanes['cc74'].at(t) - 40) / 50.0
        return np.clip(lerp(GOLD, COOL, max(0.0, min(1.0, d))), 0, 1)

    def draw_words(self, dr, page, cam, t, recent, active, span):
        geom = page.geom
        if not geom:
            return
        col = self.light_color(t)
        c255 = tuple(int(x * 255) for x in col)
        for w in recent:
            if w['folio'] != span['folio']:
                continue
            box = geom.boxes.get((w['lineno'], w['wi']))
            if box is None:
                continue
            x, y, bw, bh = box
            sx, sy = to_screen(cam, self.W, self.H, x, y)
            sx, sy = sx / 2, sy / 2
            sw, sh = bw * cam[2] / 2, bh * cam[2] / 2
            if w.get('dropped'):
                # art displacing text: the word is veiled as its time passes
                a = min(1.0, max(0.0, (t - w['start']) / max(0.3, w['end'] - w['start'])))
                dr.rounded_rectangle([sx - 2, sy - 2, sx + sw + 2, sy + sh + 2], radius=4,
                                     fill=(222, 203, 166, int(140 * a)))
                continue
            gl = [g for g in w['glyphs'] if g[0] <= t]
            if not gl:
                continue
            last = gl[-1]
            age = t - last[0]
            trail = math.exp(-age / 1.6)
            if age > 4:
                continue
            pad = 3 + 3 * trail
            dr.rounded_rectangle([sx - pad, sy - pad, sx + sw + pad, sy + sh + pad], radius=6,
                                 fill=c255 + (int(70 * trail),), outline=c255 + (int(160 * trail),), width=1)
            if w is active:
                n = max(1, len(w['glyphs']))
                for g in gl[-3:]:
                    ga = t - g[0]
                    k = math.exp(-ga / 0.22)
                    gi = g[4]
                    gx = sx + (gi + 0.5) / n * sw
                    vel = g[2] / 127.0
                    rad = (3 + 5 * vel + (g[1] - 38) / 36 * 3) * (0.6 + 0.4 * k)
                    a = int(230 * k)
                    dr.ellipse([gx - rad, sy + sh / 2 - rad, gx + rad, sy + sh / 2 + rad],
                               fill=(255, 250, 235, a))
                    if g[5]:                       # the m/g mute: a small falling tick
                        dr.line([gx, sy + sh / 2, gx + 4, sy + sh + 8], fill=c255 + (a,), width=2)

    def draw_hits(self, dr, page, cam, t, span):
        geom = page.geom
        for l in self.labels.window(t - 1.2, t):
            if l['folio'] != span['folio'] or not geom:
                continue
            box = geom.boxes.get((l['lineno'], l['wi']))
            if box is None:
                continue
            k = math.exp(-(t - l['t']) / 0.45)
            x, y, bw, bh = box
            sx, sy = to_screen(cam, self.W, self.H, x, y); sx /= 2; sy /= 2
            sw, sh = bw * cam[2] / 2, bh * cam[2] / 2
            r = 6 + 18 * (1 - k)
            dr.rounded_rectangle([sx - 4, sy - 4, sx + sw + 4, sy + sh + 4], radius=5, fill=LABEL_COL + (int(200 * k),))
            dr.ellipse([sx + sw / 2 - r, sy + sh / 2 - r, sx + sw / 2 + r, sy + sh / 2 + r], outline=LABEL_COL + (int(180 * k),), width=2)
        for b in self.blue.window(t - 2.5, t):
            if b.get('folio') != span['folio']:
                continue
            k = math.exp(-(t - b['t']) / 1.0)
            # bloom at the line start of the word sounding then
            ws = [w for w in self.words.window(b['t'] - 0.2, b['t'] + 0.6) if not w.get('dropped')]
            if ws and geom:
                box = geom.boxes.get((ws[0]['lineno'], ws[0]['wi']))
                if box:
                    sx, sy = to_screen(cam, self.W, self.H, box[0], box[1] + box[3] / 2); sx /= 2; sy /= 2
                    r = 10 + 60 * (1 - k)
                    dr.ellipse([sx - r, sy - r, sx + r, sy + r], outline=BLUE_COL + (int(220 * k),), width=3)
                    dr.ellipse([sx - 8, sy - 8, sx + 8, sy + 8], fill=BLUE_COL + (int(240 * k),))

    def draw_rings(self, dr, page, cam, t):
        geom = page.geom
        if not geom or not geom.ring_points:
            return
        ring_ids = sorted(geom.ring_points)
        for ev in self.rings.window(t - 1.5, t):
            pts = geom.ring_points.get(ev['ring'])
            if not pts or ev['ti'] >= len(pts) - 1:
                continue
            x, y, a = pts[ev['ti']]
            k = math.exp(-(t - ev['t']) / 0.5)
            hue = RING_HUES[ring_ids.index(ev['ring']) % len(RING_HUES)]
            sx, sy = to_screen(cam, self.W, self.H, x, y); sx /= 2; sy /= 2
            rad = 4 + 6 * (ev['vel'] / 127) * k
            dr.ellipse([sx - rad, sy - rad, sx + rad, sy + rad], fill=hue + (int(230 * k),))
            if ev['ti'] > 0:
                px, py, _ = pts[ev['ti'] - 1]
                psx, psy = to_screen(cam, self.W, self.H, px, py)
                dr.line([psx / 2, psy / 2, sx, sy], fill=hue + (int(120 * k),), width=2)
        # a slow glow on the centre of every ring that played in the last 2 s
        active = {}
        for ev in self.rings.window(t - 2.0, t):
            active[ev['ring']] = max(active.get(ev['ring'], 0), math.exp(-(t - ev['t']) / 2.0))
        for rid, k in active.items():
            cx, cy, r = geom.ring_points[rid][-1]
            sx, sy = to_screen(cam, self.W, self.H, cx, cy); sx /= 2; sy /= 2
            rr = r * cam[2] / 2
            hue = RING_HUES[ring_ids.index(rid) % len(RING_HUES)]
            dr.ellipse([sx - rr, sy - rr, sx + rr, sy + rr], outline=hue + (int(90 * k),), width=3)

    def entrainment_pulse(self, img, t):
        # isochronic: the frame breathes at the gate rate; binaural: the page edges alternate at the beat
        for seg in self.iso:
            if seg['start'] <= t < seg['end']:
                ph = ((t - seg['start']) % seg['period']) / seg['period']
                g = 0.5 - 0.5 * math.cos(2 * math.pi * ph * 2) if ph < 0.5 else 0.0
                img *= (1 + 0.025 * g)
                break
        hz = self.lanes['beat_hz'].at(t)
        if hz > 0:
            ph = (t * hz) % 1.0
            l = 0.5 + 0.5 * math.cos(2 * math.pi * ph)
            edge = 90
            ramp = np.linspace(1, 0, edge, dtype=np.float32)
            img[:, :edge, :] += (ramp[None, :, None] * 0.045 * l)
            img[:, -edge:, :] += (ramp[::-1][None, :, None] * 0.045 * (1 - l))

    # ------------------------------------------------------------------ riffle
    def draw_riffle(self, img, t, r):
        W, H = self.W, self.H
        skipped = r['skipped']
        lead = r['lead']
        u = (t - (r['arrive'] - lead)) / lead          # 0..1
        n = len(skipped)
        if n == 0:
            # a plain page turn: the previous page slides out
            prev = self.current_span(r['arrive'] - lead - 0.01)
            if prev:
                page = self.page(prev['folio'])
                cam = self.fit_cam(page)
                base, alpha = page.crop((cam[0] + u * page.size[0] * 1.2, cam[1], cam[2]), W, H)
                img *= 1
                img[:] = img * (1 - alpha[..., None]) + base * alpha[..., None] * (1 - 0.5 * u)
            return
        pos = u * n
        i = min(n - 1, int(pos))
        frac = pos - i
        for k, off in ((i, 0.0), (i + 1, 1.0)):
            if k >= n:
                continue
            folio = skipped[k]
            thumb = self.thumb(folio)
            if thumb is None:
                continue
            tw, th = thumb.size
            scale = min(W * 0.62 / tw, H * 0.86 / th)
            tw2, th2 = int(tw * scale), int(th * scale)
            x = int(W / 2 - tw2 / 2 + (off - frac) * W * 0.55)
            y = int(H / 2 - th2 / 2)
            im = thumb.resize((tw2, th2), Image.BILINEAR)
            arr = np.asarray(im).astype(np.float32) / 255.0
            x0, x1 = max(0, x), min(W, x + tw2)
            y0, y1 = max(0, y), min(H, y + th2)
            if x1 <= x0 or y1 <= y0:
                continue
            dim = 0.55 + 0.35 * (1 - abs(off - frac))
            img[y0:y1, x0:x1] = arr[y0 - y:y1 - y, x0 - x:x1 - x] * dim
        self._riffle_label = skipped[i]

    def thumb(self, folio):
        if folio in self.thumbs:
            return self.thumbs[folio]
        path = os.path.join(self.scans, folio + '.jpg')
        if not os.path.exists(path):
            self.thumbs[folio] = None
            return None
        im = Image.open(path).convert('RGB')
        im.thumbnail((1100, 1100), Image.BILINEAR)
        if len(self.thumbs) > 40:
            self.thumbs.pop(next(iter(self.thumbs)))
        self.thumbs[folio] = im
        return im

    # ------------------------------------------------------------------ HUD
    def finish(self, img, t, span, active=None):
        W, H = self.W, self.H
        hud = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(hud)
        m = self.movement_at(t)
        # folio label
        label = None
        if span is not None:
            label = span['folio'].replace('_', '–')
            sec = {'H': 'herbal', 'A': 'astronomical', 'Z': 'zodiac', 'C': 'cosmological', 'B': 'biological',
                   'P': 'pharmaceutical', 'S': 'recipes', 'T': 'text'}.get(span['section'], '')
            dr.text((36, H - 62), f"{label}", font=self.font, fill=(235, 225, 205, 230))
            dr.text((36, H - 34), sec, font=self.font_small, fill=(200, 190, 170, 190))
        elif getattr(self, '_riffle_label', None):
            dr.text((36, H - 62), self._riffle_label, font=self.font, fill=(200, 190, 170, 150))
        # movement title on arrival
        if m and (t - m['start']) < 6.0 and t >= m['start']:
            a = min(1, (t - m['start']) / 1.0) * min(1, (6.0 - (t - m['start'])) / 1.5)
            dr.text((36, 36), m['title'], font=self.font_title, fill=(240, 230, 210, int(230 * a)))
        # annotation strip: only where the ear needs the eye's help
        if span is not None and m['number'] in (2, 5):
            self.draw_strip(dr, hud, t, span, active, m)
        elif span is not None and active is not None and (t - span['start']) < 12.0:
            self.draw_strip(dr, hud, t, span, active, m, minimal=True)
        if m and m['number'] == 2:
            self.draw_clock_inset(hud, t)
        arr = np.asarray(hud).astype(np.float32) / 255.0
        img = img * (1 - arr[..., 3:4]) + arr[..., :3] * arr[..., 3:4]
        return (np.clip(img, 0, 1) * 255).astype(np.uint8)

    def draw_strip(self, dr, hud, t, span, active, m, minimal=False):
        W, H = self.W, self.H
        y = H - 120
        dr.rectangle([W - 760, y, W - 36, H - 36], fill=(10, 8, 6, 150))
        x = W - 740
        if active is not None:
            word = active['word']
            dr.text((x, y + 14), word, font=self.font_eva, fill=(240, 230, 205, 240))
            gl = [g for g in active['glyphs'] if g[0] <= t]
            pitch = gl[-1][1] if gl else None
            pn = f"{PC_NAMES[pitch % 12]}{pitch // 12 - 1}" if pitch is not None else ''
            dr.text((x, y + 62), f"{word}   {pn}", font=self.font_small, fill=(200, 190, 170, 200))
        if not minimal:
            hz = self.lanes['beat_hz'].at(t)
            band = 'delta' if hz < 4 else 'theta' if hz < 8 else 'alpha' if hz < 13 else 'beta'
            bright = self.lanes['cc74'].at(t)
            dr.text((x + 330, y + 14), f"binaural {hz:.2f} Hz  {band}", font=self.font_small, fill=(180, 200, 230, 210))
            dr.text((x + 330, y + 40), f"brightness {bright:.0f}   painting {self.lanes['cc1'].at(t):.0f}", font=self.font_small, fill=(200, 190, 170, 190))
            if m['number'] == 2:
                cl = self.clock.window(t - 1e9, t)
                if cl:
                    c = cl[-1]
                    g = c['group']
                    cnt = sum(1 for e in cl if e['group'] == g)
                    total = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31][g]
                    dr.text((x + 330, y + 66), f"year-clock  {c.get('folio', '')}  {cnt}/{total}   ({len(cl)}/363)",
                            font=self.font_small, fill=(240, 220, 160, 230))
            if m['number'] == 5:
                act = sorted({e['ring'] for e in self.rings.window(t - 1.0, t)})
                if act:
                    dr.text((x + 330, y + 66), 'rings ' + ' '.join(str(a) for a in act), font=self.font_small, fill=(200, 220, 240, 220))

    def draw_clock_inset(self, hud, t):
        cl = self.clock.window(t - 1e9, t)
        if not cl:
            return
        c = cl[-1]
        folio = c.get('folio')
        if not folio or folio not in self.geoms:
            return
        if (t - cl[-1]['t']) > 6.0 and len(cl) == 363:
            return
        page = self.page(folio)
        size = 400
        key = (folio, size)
        if key not in self.ring_cache:
            im = page.levels[-1].copy()
            im.thumbnail((size, size), Image.BILINEAR)
            self.ring_cache[key] = im
        thumb = self.ring_cache[key]
        W, H = self.W, self.H
        x0, y0 = W - 36 - thumb.size[0], 36
        hud.paste(thumb.convert('RGBA'), (x0, y0))
        dr = ImageDraw.Draw(hud)
        dr.rectangle([x0 - 2, y0 - 2, x0 + thumb.size[0] + 1, y0 + thumb.size[1] + 1], outline=(240, 220, 160, 200), width=2)
        f = thumb.size[0] / page.size[0]
        geom = self.geoms[folio]
        g = c['group']
        for e in cl:
            if e['group'] != g or 'lineno' not in e:
                continue
            box = geom.boxes.get((e['lineno'], e['wi']))
            if box is None:
                continue
            k = math.exp(-(t - e['t']) / 0.6)
            x, y, w, h = box
            a = int(90 + 160 * k)
            dr.rectangle([x0 + x * f, y0 + y * f, x0 + (x + w) * f, y0 + (y + h) * f],
                         fill=(240, 220, 160, int(60 + 150 * k)), outline=(255, 240, 200, a))
        dr.text((x0, y0 + thumb.size[1] + 8), f"{folio}  ring {g + 1}/12", font=self.font_small, fill=(240, 220, 160, 230))
