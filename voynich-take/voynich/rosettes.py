"""Nine circular ostinati from the actual f85v-86r spatial data."""
import csv
import json
import math
from collections import defaultdict
from .constants import SIXTEENTH, BAR, POOL, ROSETTE_BARS, STAGGER_BARS

# pool-step transposition by radius rank (largest ring first): pentatonic pool,
# 5 steps = one octave, so these are distinct octave regions with offsets
POOL_SHIFTS = [-5, -3, -2, -1, 0, 1, 2, 3, 5]
from .events import Note
from .pitch import pool_step
from .compiler import burst_gaps, NOTE_DUR, _jitter, VEL_BASE, VEL_JITTER_SD


def load_rings(polygons_path, tokens_path, transforms_path):
    with open(polygons_path) as fh:
        polys = json.load(fh)['polygons']
    roles = {}
    with open(transforms_path) as fh:
        for r in csv.DictReader(fh):
            roles[int(r['paragraph'])] = r['role']
    tokens = defaultdict(list)
    with open(tokens_path) as fh:
        for r in csv.DictReader(fh):
            tokens[int(r['paragraph'])].append(r)
    rings = []
    for q in polys:
        if q.get('shape') != 'ring':
            continue
        if not roles.get(q['id'], '').endswith('.ring'):
            continue   # annuli / bays / bands are inner structure, not the text rings
        cx, cy = q['cx'], q['cy']
        r_out = (q['rxOuter'] + q['ryOuter']) / 2
        r_in = (q['rxInner'] + q['ryInner']) / 2
        toks = tokens.get(q['id'], [])
        ordered = sorted(toks, key=lambda t: math.atan2(float(t['y_px']) - cy, float(t['x_px']) - cx))
        words = [t['token'].lower() for t in ordered]
        words = [''.join(ch for ch in w if 'a' <= ch <= 'z') for w in words]
        words = [w for w in words if w]
        rings.append({'id': q['id'], 'role': roles[q['id']], 'cx': cx, 'cy': cy,
                      'r_out': r_out, 'r_in': r_in, 'words': words})
    rings.sort(key=lambda r: r['id'])
    assert len(rings) == 9, len(rings)
    return rings


def compile_rosette_canons(rings, rankmap, rng, start_tick, bars=ROSETTE_BARS,
                           track='ROSETTE_CANONS'):
    """Each ring = a loop (glyph=16th, word gap=16th), transposed to a pool
    region by radius rank, entering at a time given by its centre x-position
    (0..16 bars), melodically closed, with burst-gap dropout."""
    end_tick = start_tick + bars * BAR
    xs = [r['cx'] for r in rings]
    xmin, xmax = min(xs), max(xs)
    by_radius = sorted(range(len(rings)), key=lambda i: -rings[i]['r_out'])   # largest first
    rank_of = {i: k for k, i in enumerate(by_radius)}
    notes = []
    info = []
    for i, ring in enumerate(rings):
        entry = start_tick + int(round((ring['cx'] - xmin) / (xmax - xmin) * STAGGER_BARS * BAR / SIXTEENTH)) * SIXTEENTH
        shift = POOL_SHIFTS[rank_of[i]]          # pool steps: big rings low, small rings high
        # loop content
        loop = []                                # (offset, pitch, glyph, word)
        off = 0
        for w in ring['words']:
            for g in w:
                loop.append([off, pool_step(rankmap.pitch(g), shift), g, w])
                off += SIXTEENTH
            off += SIXTEENTH
        loop_len = off - SIXTEENTH if loop else 0
        if not loop:
            continue
        # tangential closure: the last pitch steps to the first pitch
        first_p, last_p = loop[0][1], loop[-1][1]
        if abs(first_p - last_p) > 3:
            loop[-1][1] = pool_step(first_p, -1 if last_p < first_p else 1)
        # burst-gap dropout: play k cycles, vanish for a shaped gap, return
        t = entry
        cycles_played = 0
        segments = []
        while t < end_tick:
            on_cycles = max(1, int(round(rng.lognormvariate(math.log(3), 0.5))))
            for _ in range(on_cycles):
                if t >= end_tick:
                    break
                for o, p, g, w in loop:
                    tt = t + o
                    if tt >= end_tick:
                        break
                    vel = int(max(20, min(120, round(VEL_BASE - 10 + rng.gauss(0, VEL_JITTER_SD)))))
                    notes.append(Note(track, max(0, tt + _jitter(rng)), NOTE_DUR, p, vel,
                                      {'kind': 'ring', 'ring': ring['id'], 'word': w, 'glyph': g}))
                t += loop_len + SIXTEENTH
                cycles_played += 1
            gap = burst_gaps(1, rng)[0] * loop_len
            gap = int(round(gap / SIXTEENTH)) * SIXTEENTH
            segments.append((t, gap))
            t += gap
        info.append({'ring': ring['id'], 'role': ring['role'], 'tokens': len(ring['words']),
                     'glyphs': sum(len(w) for w in ring['words']), 'loop_ticks': loop_len,
                     'entry_bar': round((entry - start_tick) / BAR, 2), 'pool_shift': shift,
                     'radius_px': round(ring['r_out'], 1), 'cycles': cycles_played})
    notes.sort(key=lambda n: n.tick)
    return notes, info
