"""Entrainment layers derived from the grid and the page.

BINAURAL_L / BINAURAL_R: carrier = the sounding ROOT_BASS one octave up
(D3 when no paragraph is sounding), left ear the carrier, right ear the
carrier + beat. Beat frequency = glyph rate (a 16th at 124 BPM = 8.267 Hz)
x the section's measured note density, morphing over 2 beats at folio
boundaries exactly like the CC lanes; or, in 'drift' mode, one theta->beta
morph (4.13 -> 16.5 Hz) across the whole piece on the A->B drift lane.

ISOCHRONIC: a carrier one octave above the binaural carrier, gated at a
grid subdivision chosen by the section's density, phase-locked to bar 1,
level riding the CC1 painting lane. Raised-cosine 50% duty gate.

Nothing here is composed: tempo, density, paragraph roots and the
painting lane are the only inputs."""
import math
from .constants import (SECTION_PROFILE, BAR, PPQN, SIXTEENTH, BPM)
from .events import Note, CC

GLYPH_HZ = BPM / 60 * 4                       # 8.2667 Hz: one glyph per 16th
BAND_EDGES = [(4, 'delta'), (8, 'theta'), (13, 'alpha'), (30, 'beta'), (200, 'gamma')]
RAMP = 2 * PPQN

# section density -> isochronic gate period (ticks), all grid-locked
def iso_period_for(density):
    if density < 0.7:
        return PPQN // 2          # 8th          4.13 Hz theta
    if density < 0.78:
        return PPQN // 3          # 8th triplet  6.20 Hz theta/alpha
    if density < 0.95:
        return PPQN // 4          # 16th         8.27 Hz alpha
    return PPQN // 6              # 16th triplet 12.4 Hz low beta


def band_of(hz):
    for edge, name in BAND_EDGES:
        if hz < edge:
            return name
    return 'gamma'


def _stepped_with_ramps(folio_spans, value_of):
    """[(tick, value)] points: a step per folio with a 2-beat linear ramp."""
    pts = []
    prev = None
    for fname, sec, start, end in folio_spans:
        v = value_of(sec)
        if prev is None or prev == v:
            pts.append((start, v))
        else:
            steps = RAMP // SIXTEENTH
            for k in range(steps + 1):
                pts.append((start + k * SIXTEENTH, prev + (v - prev) * k / steps))
        prev = v
    return pts


def beat_points(mvt, mode, global_start, total_length):
    if mode == 'drift':
        pts = []
        t = 0
        while t <= mvt.length:
            frac = (global_start + t) / total_length
            pts.append((t, 4.1333 + (16.5333 - 4.1333) * frac))
            t += BAR
        return pts
    return _stepped_with_ramps(mvt.folio_spans, lambda sec: GLYPH_HZ * SECTION_PROFILE[sec][0])


def value_at(points, tick):
    v = points[0][1]
    for t, x in points:
        if t <= tick:
            v = x
        else:
            break
    return v


def carrier_segments(mvt):
    """(start, end, midi_pitch) for the binaural carrier: ROOT_BASS + 12,
    D3 (50) wherever no paragraph root is sounding."""
    bass = sorted((n for n in mvt.notes if n.track == 'ROOT_BASS'), key=lambda n: n.tick)
    segs = []
    cursor = 0
    for n in bass:
        if n.tick > cursor:
            segs.append((cursor, n.tick, 50))
        end = min(mvt.length, n.tick + n.dur + 10)
        segs.append((n.tick, end, n.pitch + 12))
        cursor = end
    if cursor < mvt.length:
        segs.append((cursor, mvt.length, 50))
    # merge adjacent equal pitches
    merged = []
    for s in segs:
        if merged and merged[-1][2] == s[2] and merged[-1][1] >= s[0]:
            merged[-1] = (merged[-1][0], s[1], s[2])
        else:
            merged.append(s)
    return merged


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def compile_entrainment(mvt, mode, global_start, total_length):
    segs = carrier_segments(mvt)
    beats = beat_points(mvt, mode, global_start, total_length)
    cc1 = sorted((c.tick, c.value) for c in mvt.ccs if c.track == 'ATMOS_CTRL' and c.cc == 1)
    notes, ccs, bends = [], [], []
    # --- binaural carriers as notes; the beat as pitch bend on the right ear
    for start, end, p in segs:
        if end <= start:
            continue
        notes.append(Note('BINAURAL_L', start, end - start - 1, p, 90, {'kind': 'carrier'}))
        notes.append(Note('BINAURAL_R', start, end - start - 1, p, 90, {'kind': 'carrier'}))
    ticks = sorted({t for t, _ in beats} | {s for s, _, _ in segs})
    for t in ticks:
        if t >= mvt.length:
            continue
        p = next(pp for s, e, pp in segs if s <= t < e)
        f = hz(p)
        b = value_at(beats, t)
        cents = 1200 * math.log2((f + b) / f)
        bends.append((t, int(round(cents / 200 * 8192))))       # pitch-bend range +-2 st
    # --- isochronic gate: notes at the grid subdivision, level from CC1
    iso_pts = _stepped_with_ramps(mvt.folio_spans, lambda sec: iso_period_for(SECTION_PROFILE[sec][0]))
    iso_segments = []
    for fname, sec, start, end in mvt.folio_spans:
        period = iso_period_for(SECTION_PROFILE[sec][0])
        iso_segments.append((start, end, period))
        t = (start // period) * period            # phase-locked to bar 1 of the movement
        if t < start:
            t += period
        while t < end and t < mvt.length:
            p = next(pp for s, e, pp in segs if s <= t < e) + 12
            level = value_at(cc1, t) if cc1 else 64
            vel = int(round(30 + 90 * level / 127))
            notes.append(Note('ISOCHRONIC', t, max(1, period // 2), p, vel, {'kind': 'iso'}))
            t += period
    # the take ends mid-word: no entrainment event may outlast the final glyph
    glyph_end = max((n.tick + n.dur for n in mvt.notes
                     if n.track == 'PARAGRAPH_VOICE' and n.meta.get('kind') in ('glyph', 'mute')), default=mvt.length)
    cap = min(mvt.length, glyph_end) - 1
    clipped = []
    for n in notes:
        if n.tick >= cap:
            continue
        n.dur = min(n.dur, cap - n.tick)
        clipped.append(n)
    notes = clipped
    segs = [(s_, min(e_, cap), p) for s_, e_, p in segs if s_ < cap]
    bends = [(t, b) for t, b in bends if t < cap]
    iso_segments = [(s_, min(e_, cap), per) for s_, e_, per in iso_segments if s_ < cap]
    mvt.entrainment = {'mode': mode, 'carriers': segs, 'beats': beats, 'bends': bends,
                       'iso': iso_segments, 'cap': cap}
    mvt.notes += notes
    return notes


def write_entrainment_csv(mvt, path):
    import csv
    e = mvt.entrainment
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['time_beats', 'carrier_hz', 'beat_hz', 'band', 'iso_rate_hz', 'pitch_bend_R'])
        ticks = sorted({t for t, _ in e['beats']} | {s for s, _, _ in e['carriers']} | {s for s, _, _ in e['iso']})
        for t in ticks:
            if t >= e.get('cap', mvt.length):
                continue
            p = next(pp for s, en, pp in e['carriers'] if s <= t < en)
            b = value_at(e['beats'], t)
            period = next((per for s, en, per in e['iso'] if s <= t < en), None)
            bend = next((bb for tt, bb in reversed(e['bends']) if tt <= t), 0)
            w.writerow([f'{t / PPQN:.4f}', f'{hz(p):.3f}', f'{b:.3f}', band_of(b),
                        f'{PPQN / period * BPM / 60:.3f}' if period else '', bend])
