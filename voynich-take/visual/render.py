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
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageEnhance

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
    """Scan pyramid + geometry for one folio. sat_lift bakes the painting
    lane (CC1) into the page once instead of per frame."""

    def __init__(self, path, geom=None, sat_lift=0.0):
        im = Image.open(path).convert('RGB')
        if sat_lift > 0:
            im = ImageEnhance.Color(im).enhance(1 + sat_lift)
        self.size = im.size
        self.levels = [im]
        while self.levels[-1].size[0] > 900:
            l = self.levels[-1]
            self.levels.append(l.resize((l.size[0] // 2, l.size[1] // 2), Image.BILINEAR))
        self.geom = geom

    def crop(self, cam, W, H):
        """Return an RGB PIL image (W, H) of the page under the camera, black outside."""
        cx, cy, zoom = cam
        lvl = 0
        for i, l in enumerate(self.levels):
            if l.size[0] / self.size[0] >= zoom:
                lvl = i
        l = self.levels[lvl]
        f = l.size[0] / self.size[0]
        z = zoom / f
        x0 = cx * f - W / 2 / z
        y0 = cy * f - H / 2 / z
        return l.transform((W, H), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BILINEAR, fillcolor=(0, 0, 0))

    def screen_rect(self, cam, W, H):
        """The page's rectangle on screen (x0, y0, x1, y1), clipped."""
        cx, cy, zoom = cam
        x0 = W / 2 - cx * zoom; y0 = H / 2 - cy * zoom
        x1 = x0 + self.size[0] * zoom; y1 = y0 + self.size[1] * zoom
        return (int(max(0, x0)), int(max(0, y0)), int(min(W, x1)), int(min(H, y1)))

    def mask_crop(self, name, cam, W, H, q=4):
        """Pigment mask under the camera at 1/q resolution, float32 (H/q, W/q)."""
        if not self.geom or name not in self.geom.masks:
            return None
        m = self.geom.masks[name]
        if not hasattr(self, '_mask_im'):
            self._mask_im = {}
        if name not in self._mask_im:
            self._mask_im[name] = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8))
        d = self.geom.d
        cx, cy, zoom = cam
        z = zoom * d / q
        w, h = W // q, H // q
        x0 = cx / d - w / 2 / z
        y0 = cy / d - h / 2 / z
        out = self._mask_im[name].transform((w, h), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BILINEAR, fillcolor=0)
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
            cc1 = 0.0
            for sp in self.spans:
                if sp['folio'] == folio:
                    cc1 = self.lanes['cc1'].at(sp['start'] + 2.0) / 127.0
                    break
            self.pages[folio] = Page(path, self.geoms.get(folio), sat_lift=0.18 * cc1)
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
        table = tuple(int(x * 255) for x in TABLE)
        r = self.riffle_at(t)
        if r is not None:
            img = Image.new('RGB', (W, H), table)
            self.draw_riffle(img, t, r)
            return self.finish(img, t, None)
        span = self.current_span(t)
        if span is None:
            return self.finish(Image.new('RGB', (W, H), table), t, None)
        page = self.page(span['folio'])
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
        img = page.crop(cam, W, H)
        x0, y0, x1, y1 = page.screen_rect(cam, W, H)
        if x0 > 0 or y0 > 0 or x1 < W or y1 < H:
            bg = Image.new('RGB', (W, H), table)
            if x1 > x0 and y1 > y0:
                bg.paste(img.crop((x0, y0, x1, y1)), (x0, y0))
            img = bg
        # additive quarter-res layer: pigment washes and pulses
        q = 4
        add_q = np.zeros((H // q, W // q, 3), dtype=np.float32)
        self.pigment_layers(add_q, page, cam, t, span, q)
        self.entrainment_pulse(add_q, t, q)
        if add_q.any():
            add = Image.fromarray((np.clip(add_q, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
            img = ImageChops.add(img, add)
        # glow / veil overlay at half resolution
        ov = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))      # veils (alpha)
        lum = Image.new('RGB', (W // 2, H // 2), (0, 0, 0))          # light (additive)
        dr, dl = ImageDraw.Draw(ov), ImageDraw.Draw(lum)
        self.draw_words(dr, dl, page, cam, t, recent, active, span)
        self.draw_hits(dl, page, cam, t, span)
        if span['folio'] == 'f85v_86r':
            self.draw_rings(dl, page, cam, t)
        if ov.getbbox():
            ov = ov.resize((W, H), Image.BILINEAR)
            img.paste(ov, (0, 0), ov)
        if lum.getbbox():
            img = ImageChops.add(img, lum.resize((W, H), Image.BILINEAR))
        img = self.iso_breath(img, t)
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
    def pigment_layers(self, add, page, cam, t, span, q):
        W, H = self.W, self.H
        cc11 = self.lanes['cc11'].at(t) / 127.0
        pads = self.pad.window(t - 8, t)
        bloom = math.exp(-(t - pads[-1]['t']) / 2.5) if pads else 0.0
        breath = 0.5 + 0.5 * math.sin(2 * math.pi * t / 6.0)
        amt = cc11 * (0.35 + 0.25 * breath + 0.6 * bloom) * 0.55
        if amt > 0.01:
            g = page.mask_crop('green', cam, W, H, q)
            if g is not None:
                add += g[..., None] * (PAD_COL * amt)[None, None, :]
        bs = self.bass.window(t - 6, t)
        if bs:
            pulse = math.exp(-(t - bs[-1]['t']) / 1.8)
            if pulse > 0.03:
                rb = page.mask_crop('redbrown', cam, W, H, q)
                if rb is not None:
                    add += rb[..., None] * (np.array([0.9, 0.35, 0.15], dtype=np.float32) * pulse * 0.5)[None, None, :]
        bl = self.blue.window(t - 3, t)
        if bl:
            flare = math.exp(-(t - bl[-1]['t']) / 1.2)
            b = page.mask_crop('blue', cam, W, H, q)
            if b is not None:
                add += b[..., None] * (np.array([0.3, 0.55, 1.0], dtype=np.float32) * flare * 0.9)[None, None, :]

    def light_color(self, t):
        d = (self.lanes['cc74'].at(t) - 40) / 50.0
        return np.clip(lerp(GOLD, COOL, max(0.0, min(1.0, d))), 0, 1)

    def draw_words(self, dr, dl, page, cam, t, recent, active, span):
        geom = page.geom
        if not geom:
            return
        col = self.light_color(t)

        def c(k):
            return tuple(int(x * 255 * max(0.0, min(1.0, k))) for x in col)
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
                                     fill=(222, 203, 166, int(150 * a)))
                continue
            gl = [g for g in w['glyphs'] if g[0] <= t]
            if not gl:
                continue
            age = t - gl[-1][0]
            if age > 4:
                continue
            trail = math.exp(-age / 1.6)
            # outer halo, inner light: additive so it reads as light on vellum
            pad = 6 + 6 * trail
            dl.rounded_rectangle([sx - pad, sy - pad, sx + sw + pad, sy + sh + pad], radius=8, fill=c(0.22 * trail))
            dl.rounded_rectangle([sx - 2, sy - 2, sx + sw + 2, sy + sh + 2], radius=4, fill=c(0.38 * trail))
            if w is active:
                n = max(1, len(w['glyphs']))
                for g in gl[-3:]:
                    ga = t - g[0]
                    k = math.exp(-ga / 0.22)
                    gi = g[4]
                    gx = sx + (gi + 0.5) / n * sw
                    vel = g[2] / 127.0
                    rad = (4 + 5 * vel + (g[1] - 38) / 36 * 3) * (0.6 + 0.4 * k)
                    v = int(255 * k)
                    dl.ellipse([gx - rad, sy + sh / 2 - rad, gx + rad, sy + sh / 2 + rad], fill=(v, v, int(v * 0.92)))
                    if g[5]:                       # the m/g mute: a small falling tick
                        dl.line([gx, sy + sh / 2, gx + 4, sy + sh + 8], fill=c(k), width=2)

    def draw_hits(self, dl, page, cam, t, span):
        geom = page.geom

        def scale(col, k):
            return tuple(int(v * max(0.0, min(1.0, k))) for v in col)
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
            dl.rounded_rectangle([sx - 4, sy - 4, sx + sw + 4, sy + sh + 4], radius=5, fill=scale(LABEL_COL, 0.8 * k))
            dl.ellipse([sx + sw / 2 - r, sy + sh / 2 - r, sx + sw / 2 + r, sy + sh / 2 + r], outline=scale(LABEL_COL, 0.7 * k), width=2)
        for b in self.blue.window(t - 2.5, t):
            if b.get('folio') != span['folio']:
                continue
            k = math.exp(-(t - b['t']) / 1.0)
            ws = [w for w in self.words.window(b['t'] - 0.2, b['t'] + 0.6) if not w.get('dropped')]
            if ws and geom:
                box = geom.boxes.get((ws[0]['lineno'], ws[0]['wi']))
                if box:
                    sx, sy = to_screen(cam, self.W, self.H, box[0], box[1] + box[3] / 2); sx /= 2; sy /= 2
                    r = 10 + 60 * (1 - k)
                    dl.ellipse([sx - r, sy - r, sx + r, sy + r], outline=scale(BLUE_COL, 0.9 * k), width=3)
                    dl.ellipse([sx - 8, sy - 8, sx + 8, sy + 8], fill=scale(BLUE_COL, k))

    def draw_rings(self, dl, page, cam, t):
        geom = page.geom
        if not geom or not geom.ring_points:
            return
        ring_ids = sorted(geom.ring_points)

        def scale(col, k):
            return tuple(int(v * max(0.0, min(1.0, k))) for v in col)
        for ev in self.rings.window(t - 1.5, t):
            pts = geom.ring_points.get(ev['ring'])
            if not pts or ev['ti'] >= len(pts) - 1:
                continue
            x, y, a = pts[ev['ti']]
            k = math.exp(-(t - ev['t']) / 0.5)
            hue = RING_HUES[ring_ids.index(ev['ring']) % len(RING_HUES)]
            sx, sy = to_screen(cam, self.W, self.H, x, y); sx /= 2; sy /= 2
            rad = 4 + 6 * (ev['vel'] / 127) * k
            dl.ellipse([sx - rad, sy - rad, sx + rad, sy + rad], fill=scale(hue, 0.9 * k))
            if ev['ti'] > 0:
                px, py, _ = pts[ev['ti'] - 1]
                psx, psy = to_screen(cam, self.W, self.H, px, py)
                dl.line([psx / 2, psy / 2, sx, sy], fill=scale(hue, 0.45 * k), width=2)
        active = {}
        for ev in self.rings.window(t - 2.0, t):
            active[ev['ring']] = max(active.get(ev['ring'], 0), math.exp(-(t - ev['t']) / 2.0))
        for rid, k in active.items():
            cx, cy, r = geom.ring_points[rid][-1]
            sx, sy = to_screen(cam, self.W, self.H, cx, cy); sx /= 2; sy /= 2
            rr = r * cam[2] / 2
            hue = RING_HUES[ring_ids.index(rid) % len(RING_HUES)]
            dl.ellipse([sx - rr, sy - rr, sx + rr, sy + rr], outline=scale(hue, 0.35 * k), width=3)

    def entrainment_pulse(self, add, t, q):
        hz = self.lanes['beat_hz'].at(t)
        if hz > 0:
            ph = (t * hz) % 1.0
            l = 0.5 + 0.5 * math.cos(2 * math.pi * ph)
            edge = max(4, 90 // q)
            ramp = np.linspace(1, 0, edge, dtype=np.float32)
            add[:, :edge, :] += ramp[None, :, None] * (0.045 * l)
            add[:, -edge:, :] += ramp[::-1][None, :, None] * (0.045 * (1 - l))

    def iso_breath(self, img, t):
        for seg in self.iso:
            if seg['start'] <= t < seg['end']:
                ph = ((t - seg['start']) % seg['period']) / seg['period']
                g = 0.5 - 0.5 * math.cos(2 * math.pi * ph * 2) if ph < 0.5 else 0.0
                if g > 0.02:
                    return ImageEnhance.Brightness(img).enhance(1 + 0.025 * g)
                return img
        return img

    # ------------------------------------------------------------------ riffle
    def draw_riffle(self, img, t, r):
        W, H = self.W, self.H
        skipped = r['skipped']
        lead = r['lead']
        u = (t - (r['arrive'] - lead)) / lead          # 0..1
        n = len(skipped)
        if n == 0:
            prev = self.current_span(r['arrive'] - lead - 0.01)
            if prev:
                page = self.page(prev['folio'])
                cam = self.fit_cam(page)
                cam = (cam[0] + u * page.size[0] * 1.2, cam[1], cam[2])
                crop = page.crop(cam, W, H)
                x0, y0, x1, y1 = page.screen_rect(cam, W, H)
                if x1 > x0 and y1 > y0:
                    part = ImageEnhance.Brightness(crop.crop((x0, y0, x1, y1))).enhance(1 - 0.5 * u)
                    img.paste(part, (x0, y0))
            return
        pos = u * n
        i = min(n - 1, int(pos))
        frac = pos - i
        for k, off in ((i, 0.0), (i + 1, 1.0)):
            if k >= n:
                continue
            thumb = self.thumb(skipped[k])
            if thumb is None:
                continue
            tw, th = thumb.size
            scale = min(W * 0.62 / tw, H * 0.86 / th)
            tw2, th2 = int(tw * scale), int(th * scale)
            x = int(W / 2 - tw2 / 2 + (off - frac) * W * 0.55)
            y = int(H / 2 - th2 / 2)
            im = thumb.resize((tw2, th2), Image.BILINEAR)
            dim = 0.55 + 0.35 * (1 - abs(off - frac))
            im = ImageEnhance.Brightness(im).enhance(dim)
            img.paste(im, (x, y))
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
        m = self.movement_at(t)
        # bottom-left folio label
        corner = Image.new('RGBA', (420, 80), (0, 0, 0, 0))
        dr = ImageDraw.Draw(corner)
        if span is not None:
            sec = {'H': 'herbal', 'A': 'astronomical', 'Z': 'zodiac', 'C': 'cosmological', 'B': 'biological',
                   'P': 'pharmaceutical', 'S': 'recipes', 'T': 'text'}.get(span['section'], '')
            dr.text((0, 6), span['folio'].replace('_', '–'), font=self.font, fill=(235, 225, 205, 230))
            dr.text((0, 34), sec, font=self.font_small, fill=(200, 190, 170, 190))
        elif getattr(self, '_riffle_label', None):
            dr.text((0, 6), self._riffle_label, font=self.font, fill=(200, 190, 170, 150))
        img.paste(corner, (36, H - 68), corner)
        # movement title on arrival
        if m and 0 <= (t - m['start']) < 6.0:
            a = min(1, (t - m['start']) / 1.0) * min(1, (6.0 - (t - m['start'])) / 1.5)
            title = Image.new('RGBA', (1100, 60), (0, 0, 0, 0))
            ImageDraw.Draw(title).text((0, 0), m['title'], font=self.font_title, fill=(240, 230, 210, int(230 * a)))
            img.paste(title, (36, 36), title)
        # annotation strip: only where the ear needs the eye's help
        if span is not None and m['number'] in (2, 5):
            self.draw_strip(img, t, span, active, m)
        elif span is not None and active is not None and (t - span['start']) < 12.0:
            self.draw_strip(img, t, span, active, m, minimal=True)
        if m and m['number'] == 2:
            self.draw_clock_inset(img, t)
        return np.asarray(img)

    def draw_strip(self, img, t, span, active, m, minimal=False):
        W, H = self.W, self.H
        sw, sh = 724, 100
        strip = Image.new('RGBA', (sw, sh), (10, 8, 6, 120))
        dr = ImageDraw.Draw(strip)
        x = 20
        if active is not None:
            word = active['word']
            dr.text((x, 4), word, font=self.font_eva, fill=(240, 230, 205, 240))
            gl = [g for g in active['glyphs'] if g[0] <= t]
            pitch = gl[-1][1] if gl else None
            pn = f"{PC_NAMES[pitch % 12]}{pitch // 12 - 1}" if pitch is not None else ''
            dr.text((x, 70), f"{word}   {pn}", font=self.font_small, fill=(200, 190, 170, 200))
        if not minimal:
            hz = self.lanes['beat_hz'].at(t)
            band = 'delta' if hz < 4 else 'theta' if hz < 8 else 'alpha' if hz < 13 else 'beta'
            bright = self.lanes['cc74'].at(t)
            dr.text((x + 330, 14), f"binaural {hz:.2f} Hz  {band}", font=self.font_small, fill=(180, 200, 230, 210))
            dr.text((x + 330, 40), f"brightness {bright:.0f}   painting {self.lanes['cc1'].at(t):.0f}", font=self.font_small, fill=(200, 190, 170, 190))
            if m['number'] == 2:
                cl = self.clock.window(t - 1e9, t)
                if cl:
                    c = cl[-1]
                    g = c['group']
                    cnt = sum(1 for e in cl if e['group'] == g)
                    total = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31][g]
                    dr.text((x + 330, 66), f"year-clock  {c.get('folio', '')}  {cnt}/{total}   ({len(cl)}/363)",
                            font=self.font_small, fill=(240, 220, 160, 230))
            if m['number'] == 5:
                act = sorted({e['ring'] for e in self.rings.window(t - 1.0, t)})
                if act:
                    dr.text((x + 330, 66), 'rings ' + ' '.join(str(a) for a in act), font=self.font_small, fill=(200, 220, 240, 220))
        img.paste(strip, (W - 36 - sw, H - 36 - sh), strip)

    def draw_clock_inset(self, img, t):
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
        tw, th = thumb.size
        inset = Image.new('RGBA', (tw + 8, th + 40), (0, 0, 0, 0))
        inset.paste(thumb.convert('RGBA'), (4, 4))
        dr = ImageDraw.Draw(inset)
        dr.rectangle([2, 2, tw + 5, th + 5], outline=(240, 220, 160, 200), width=2)
        f = tw / page.size[0]
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
            dr.rectangle([4 + x * f, 4 + y * f, 4 + (x + w) * f, 4 + (y + h) * f],
                         fill=(240, 220, 160, int(60 + 150 * k)), outline=(255, 240, 200, int(90 + 160 * k)))
        dr.text((4, th + 10), f"{folio}  ring {g + 1}/12", font=self.font_small, fill=(240, 220, 160, 230))
        img.paste(inset, (W - 36 - tw - 8, 36), inset)
