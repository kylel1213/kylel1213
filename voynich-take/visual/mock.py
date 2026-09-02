"""Mock scans + mock Voynichese XML generated from the transcription, so the
whole visual pipeline (alignment, registration, rendering, encoding) can be
exercised without the Beinecke images. NEVER a substitute for the scans:
the real build refuses to run on mock pages unless --mock is passed."""
import json
import math
import os
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

VELLUM = (222, 203, 166)


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _vellum(w, h, rng):
    base = np.full((h, w, 3), VELLUM, dtype=np.float32)
    noise = rng.standard_normal((h // 8 + 1, w // 8 + 1, 1)).astype(np.float32) * 6
    noise = np.kron(noise, np.ones((8, 8, 1), dtype=np.float32))[:h, :w]
    yy, xx = np.mgrid[0:h, 0:w]
    edge = 1 - 0.18 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) ** 0.5)
    img = np.clip((base + noise) * edge[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(img)


def make_mock(folios, rings, out_dir, eva_font_path, detail_folios, seed=408, big=(2000, 2800)):
    """Writes out_dir/scans/<folio>.jpg for every folio and
    out_dir/voynichese/<folio>.xml for detail folios; returns truth registration."""
    rng = np.random.default_rng(seed)
    prng = random.Random(seed)
    scans = os.path.join(out_dir, 'scans'); xmls = os.path.join(out_dir, 'voynichese')
    os.makedirs(scans, exist_ok=True); os.makedirs(xmls, exist_ok=True)
    truth = {}
    font = _font(eva_font_path, 44)
    small_font = _font(eva_font_path, 30)
    for name, fol in folios.items():
        detail = name in detail_folios
        W, H = big if detail else (1000, 1400)
        im = _vellum(W, H, rng)
        dr = ImageDraw.Draw(im, 'RGBA')
        # a "drawing": pigment blobs in the lower part (herbal) or a ring (astro)
        circular = fol.section in ('A', 'Z', 'C')
        if not circular:
            for _ in range(6 if detail else 2):
                cx, cy = prng.uniform(0.2, 0.8) * W, prng.uniform(0.55, 0.9) * H
                r = prng.uniform(0.05, 0.16) * W
                col = prng.choice([(70, 120, 60, 170), (150, 70, 40, 160), (200, 170, 60, 150)])
                dr.ellipse([cx - r, cy - r * 0.7, cx + r, cy + r * 0.7], fill=col)
        boxes = []       # (word, x, y, w, h) in scan px, transcription order
        if detail:
            if circular:
                cx, cy = W / 2, H / 2
                rr = min(W, H) * 0.42
                dr.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(90, 60, 40, 200), width=6)
                dr.ellipse([cx - rr * 0.6, cy - rr * 0.6, cx + rr * 0.6, cy + rr * 0.6], outline=(90, 60, 40, 200), width=4)
                for l in fol.lines:
                    if not l.words:
                        continue
                    n = len(l.words)
                    radius = rr * 0.9 if l.kind == 'text' else rr * 0.72
                    for i, w in enumerate(l.words):
                        ang = 2 * math.pi * (i + 0.5) / n + (0.3 if l.kind == 'label' else 0)
                        f = font if l.kind == 'text' else small_font
                        tw, th = dr.textbbox((0, 0), w, font=f)[2:]
                        x, y = cx + radius * math.cos(ang) - tw / 2, cy + radius * math.sin(ang) - th / 2
                        dr.text((x, y), w, font=f, fill=(60, 40, 30, 255))
                        boxes.append((w, x, y, tw, th))
            else:
                y = 220
                for l in fol.lines:
                    if not l.words:
                        continue
                    if l.kind == 'label':
                        x = prng.uniform(0.15, 0.7) * W; yy = prng.uniform(0.6, 0.92) * H
                        for w in l.words:
                            tw, th = dr.textbbox((0, 0), w, font=small_font)[2:]
                            dr.text((x, yy), w, font=small_font, fill=(60, 40, 30, 255))
                            boxes.append((w, x, yy, tw, th)); x += tw + 30
                        continue
                    x = 190 + (60 if l.para_start else 0)
                    for w in l.words:
                        tw, th = dr.textbbox((0, 0), w, font=font)[2:]
                        if x + tw > W - 150:
                            break
                        dr.text((x, y), w, font=font, fill=(60, 40, 30, 255))
                        boxes.append((w, x, y, tw, th))
                        x += tw + 34
                    y += 66 + (18 if l.para_end else 0)
        else:
            y = 130
            for l in fol.text_lines[:18]:
                dr.line([(120, y), (120 + prng.uniform(0.5, 0.8) * W, y)], fill=(80, 60, 45, 200), width=5)
                y += 40
        im.save(os.path.join(scans, name + '.jpg'), quality=82)
        if detail:
            # a Voynichese-style crop: 1090 wide, offset & scale differ from the scan
            crop_w = 0.86 * W; crop_x0 = 0.07 * W; crop_y0 = 0.05 * H
            s = 1090 / crop_w
            crop_h = 1500
            truth[name] = {'scale': 1 / s, 'ox': crop_x0, 'oy': crop_y0}
            with open(os.path.join(xmls, name + '.xml'), 'w') as fh:
                fh.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<folio name="{name}" wordCount="{len(boxes)}" width="1090" height="{crop_h}">\n')
                for i, (w, x, y0, bw, bh) in enumerate(boxes):
                    fh.write(f'  <word index="{i}" x="{int((x - crop_x0) * s)}" y="{int((y0 - crop_y0) * s)}" '
                             f'width="{int(bw * s)}" height="{int(bh * s)}">{w}</word>\n')
                fh.write('</folio>\n')
    # the rosettes foldout: rings + tokens from the spatial data
    W, H = 2412 * 1.3, 2375 * 1.3
    W, H = int(W), int(H)
    im = _vellum(W, H, rng); dr = ImageDraw.Draw(im, 'RGBA')
    s = 1.3; ox, oy = 0, 0
    for r in rings:
        cx, cy = r['cx'] * s + ox, r['cy'] * s + oy
        for rad in (r['r_out'], r['r_in']):
            dr.ellipse([cx - rad * s, cy - rad * s, cx + rad * s, cy + rad * s], outline=(90, 60, 40, 200), width=5)
        for (x, y, a), w in zip(r['xy'], r['words']):
            dr.text((x * s + ox - 12, y * s + oy - 10), w, font=small_font, fill=(60, 40, 30, 255))
    im.save(os.path.join(scans, 'f85v_86r.jpg'), quality=82)
    truth['f85v_86r'] = {'scale': s, 'ox': ox, 'oy': oy}
    with open(os.path.join(out_dir, 'mock_truth.json'), 'w') as fh:
        json.dump(truth, fh, indent=1)
    return truth
