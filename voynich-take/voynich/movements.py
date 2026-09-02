"""Assemble the five movements from the corpus."""
import math
import random
from collections import Counter
from .constants import (MOVEMENTS, SECTION_PROFILE, BAR, SIXTEENTH, PPQN, SEED,
                        YEAR_CLOCK_GROUPS, ROSETTE_BARS, THIRTY_SECOND)
from .events import Movement, Note, CC
from .pitch import RankMap
from .compiler import (subsample_folios, layout, compile_paragraph_voice, compile_label_hits,
                       compile_root_bass, compile_green_pad)
from .automation import folio_stepped_lanes, drift_lane
from .rosettes import compile_rosette_canons


def _rankmap_for(fols, extra_words=()):
    words = [w for f in fols for l in f.lines for w in l.words] + list(extra_words)
    return RankMap(words)


def build_movement(spec, folios, rings=None, rng=None):
    number, slug, title, sections, target_bars = spec
    rng = rng or random.Random(SEED + number)
    all_fols = [f for f in folios.values() if f.section in sections]
    mvt = Movement(number, slug, title, sections)
    mvt.all_folios = [f.name for f in all_fols]
    extra = [w for r in rings for w in r['words']] if (rings and number == 5) else []
    rm = _rankmap_for(all_fols, extra)
    mvt.rankmap = rm
    density = min(SECTION_PROFILE[s][0] for s in sections)
    inertia = 7 if number != 5 else 5          # Part B: maximum inertia
    start = ROSETTE_BARS * BAR if number == 5 else 0

    selected = subsample_folios(all_fols, target_bars,
                                end_sections=('S',) if number == 5 else None)
    mvt.selected_folios = [f.name for f in selected]
    lines, folio_spans, para_spans, end = layout(selected, density, rng, start_tick=start)
    mvt.lines, mvt.folio_spans, mvt.para_spans = lines, folio_spans, para_spans
    mvt.length = end

    # --- tracks
    pv_notes, pv_ccs, pv_stats, gestures = compile_paragraph_voice(lines, rm, rng, inertia)
    mvt.notes += pv_notes
    mvt.ccs += pv_ccs
    mvt.stats['paragraph_voice'] = pv_stats
    mvt.stats['gesture_lengths'] = gestures

    bass_vel = 92 if number == 4 else 72
    bass = compile_root_bass(para_spans, rm, vel=bass_vel)
    mvt.notes += bass

    pad, progression = compile_green_pad(para_spans, rm)
    mvt.notes += pad
    mvt.stats['pad_progression'] = progression

    if number != 2:          # zodiac: labels ARE the clock
        bass_pc_at = None
        if number == 4:
            spans = [(n.tick, n.tick + n.dur, n.pitch % 12) for n in bass]
            def bass_pc_at(t, spans=spans):
                for s, e, pc in spans:
                    if s <= t < e:
                        return pc
                return None
        labels, lstats = compile_label_hits(folio_spans, folios, rm, rng, bass_pc_at=bass_pc_at)
        mvt.notes += labels
        mvt.stats['label_hits'] = lstats

    if number == 1:
        mvt.notes += blue_bell_herbal(mvt, all_fols, rm)
    if number == 3:
        mvt.notes += blue_bell_stray(mvt, rm, 1)

    if number == 2:
        clock = compile_year_clock(mvt)
        mvt.notes += clock

    if number == 5:
        canons, info = compile_rosette_canons(rings, rm, rng, 0, ROSETTE_BARS)
        mvt.notes += canons
        mvt.stats['rosettes'] = info
        # rosettes page (f85v-86r) is cosmological: give the canon bars the C profile
        mvt.folio_spans = [('f85v_86r', 'C', 0, ROSETTE_BARS * BAR)] + mvt.folio_spans
        truncate_mid_word(mvt, target_tick=(ROSETTE_BARS + target_bars) * BAR)

    # --- imagery lanes (stepped per folio, 2-beat ramps)
    mvt.ccs += folio_stepped_lanes(mvt.folio_spans, [('ATMOS_CTRL', 1, 1),
                                                     ('GREEN_PAD', 1, 1),
                                                     ('GREEN_PAD', 11, 2)])
    mvt.notes.sort(key=lambda n: (n.tick, n.track))
    return mvt


# --------------------------------------------------------------------------

def blue_bell_herbal(mvt, all_fols, rm, n_window=9, track='BLUE_BELL'):
    """<= 12 blue events in the whole piece; 9 of them inside one 8-bar window
    at the f16v position of the herbal sequence, plus one stray speck."""
    names = [f.name for f in all_fols]
    frac = names.index('f16v') / len(names) if 'f16v' in names else 0.27
    target = frac * mvt.length
    # snap to the start of the folio that contains that position
    fstart = max((s for _, _, s, _ in mvt.folio_spans if s <= target), default=0)
    w0, w1 = fstart, fstart + 8 * BAR
    notes = []
    starts = [l for l in mvt.lines if w0 <= l.start < w1 and any(w.kept for w in l.words)]
    for l in starts[:n_window]:
        g = l.words[0].word[0]
        pitch = 72 if rm.glyph_rank(g) % 2 == 0 else 74
        notes.append(Note(track, l.start, PPQN, pitch, 80, {'kind': 'blue', 'folio': l.folio}))
    # fill from bar starts inside the window if the folio has fewer line starts
    b = w0
    while len(notes) < n_window and b < w1:
        if all(n.tick != b for n in notes):
            notes.append(Note(track, b, PPQN, 72, 80, {'kind': 'blue', 'folio': 'window'}))
        b += BAR
    mvt.stats['blue_window'] = (w0, w1)
    notes += blue_bell_stray(mvt, rm, 1, avoid=(w0, w1))
    return notes


def blue_bell_stray(mvt, rm, count, avoid=None, track='BLUE_BELL'):
    """A single speck: the first line start of the folio nearest 75% through."""
    target = 0.75 * mvt.length
    cands = [l for l in mvt.lines if not (avoid and avoid[0] <= l.start < avoid[1])]
    if not cands:
        return []
    l = min(cands, key=lambda l: abs(l.start - target))
    pitch = 74 if rm.glyph_rank(l.words[0].word[0]) % 2 == 0 else 72
    return [Note(track, l.start, PPQN, pitch, 70, {'kind': 'blue', 'folio': l.folio})][:count]


def compile_year_clock(mvt, track='YEAR_CLOCK'):
    """363 metrically perfect woodblock pulses in 12 groups (the real per-ring
    label counts, f70v1..f73v), 8th notes, 2-bar gaps, E3/B3 alternating."""
    z_starts = [s for _, sec, s, _ in mvt.folio_spans if sec == 'Z']
    t = min(z_starts) if z_starts else 0
    notes = []
    for gi, count in enumerate(YEAR_CLOCK_GROUPS):
        pitch = 52 if gi % 2 == 0 else 59
        for k in range(count):
            notes.append(Note(track, t, THIRTY_SECOND, pitch, 100, {'kind': 'clock', 'group': gi}))
            t += PPQN // 2
        t += 2 * BAR
    clock_end = t - 2 * BAR
    if clock_end > mvt.length:
        mvt.length = int(math.ceil(clock_end / BAR)) * BAR
    mvt.stats['year_clock'] = {'start': min(z_starts) if z_starts else 0, 'end': clock_end,
                               'groups': list(YEAR_CLOCK_GROUPS)}
    return notes


def truncate_mid_word(mvt, target_tick=None):
    """The book has no colophon: cut the final movement after the 2nd glyph
    of the word sounding at target_tick (default: the last word), no padding,
    no cadence, and cut every other track there."""
    glyph_notes = [n for n in mvt.notes if n.track == 'PARAGRAPH_VOICE' and n.meta.get('kind') in ('glyph', 'mute')]
    # last rendered word with >= 3 glyphs
    words = {}
    for n in glyph_notes:
        words.setdefault(n.meta['wid'], []).append(n)
    ordered = sorted(words.values(), key=lambda ns: ns[0].tick)
    target = None
    for ns in reversed(ordered):
        if ns[0].meta['n'] >= 3 and (target_tick is None or ns[0].tick <= target_tick):
            target = ns
            break
    second = sorted(target, key=lambda n: n.meta['gi'])[1]
    cut = second.tick + second.dur
    keep = []
    for n in mvt.notes:
        if n.tick >= cut and n is not second:
            continue
        if n.tick <= second.tick and n in target and n.meta['gi'] > 1:
            continue
        if n.end > cut:
            n.dur = max(1, cut - n.tick)
        keep.append(n)
    # drop later glyphs of the same word even if jitter put them earlier
    later = {id(n) for n in target if n.meta['gi'] > 1}
    keep = [n for n in keep if id(n) not in later]
    mvt.notes = keep
    mvt.ccs = [c for c in mvt.ccs if c.tick < cut]
    mvt.length = cut
    mvt.folio_spans = [(f, s, a, min(b, cut)) for f, s, a, b in mvt.folio_spans if a < cut]
    mvt.para_spans = [(p, a, min(b, cut), w, f, s) for p, a, b, w, f, s in mvt.para_spans if a < cut]
    mvt.stats['ending'] = {'cut_tick': cut, 'word': second.meta['word'],
                           'glyphs_played': 2, 'word_length': second.meta['n']}


def add_drift_lanes(movements):
    """CC74 brightness 40->90 on PARAGRAPH_VOICE as ONE morph across the piece."""
    total = sum(m.length for m in movements)
    g = 0
    for m in movements:
        m.ccs += drift_lane('PARAGRAPH_VOICE', 74, g, m.length, total)
        m.ccs.sort(key=lambda c: (c.tick, c.track, c.cc))
        g += m.length
    return total


def enforce_no_reprise(movements, k=8, max_fixes=5000):
    """Never reprise material across movements: any k-note pitch-class
    sequence (within one melodic line: the paragraph voice, or one rosette
    ring) that already occurred in an earlier movement is answered on the
    word that completes it. First answer: reverse its pool position
    (idx -> 15 - idx: D<->D, F<->C, G<->A, a mirrored gesture). If that word
    has already been answered, the next word back in the window is taken;
    when every word in the window has been mirrored, the word is moved one
    pool step instead. Literal repetition in the manuscript is thereby heard
    as a mirrored or displaced gesture, never a reprise."""
    from .constants import POOL
    from .pitch import pool_step
    from .streams import melodic_streams, pc_ngrams
    seen = set()
    fixes = Counter()
    residual = 0
    for m in movements:
        for sname, stream in melodic_streams(m):
            def word_key(n):
                return n.meta['wid'] if 'wid' in n.meta else (n.meta['ring'], n.meta['word'])
            groups = {}
            for n in stream:
                groups.setdefault(word_key(n), []).append(n)
            count = Counter()

            def answer(key):
                c = count[key]
                for n in groups[key]:
                    drop = 0
                    p = n.pitch
                    if p not in POOL and p + 12 in POOL:     # octave-dropped mute
                        p, drop = p + 12, 12
                    if p not in POOL:
                        continue
                    if c == 0:
                        p = POOL[len(POOL) - 1 - POOL.index(p)]
                    else:
                        p = pool_step(p, 1 if c % 2 else -1)
                    n.pitch = p - drop
                count[key] += 1

            n_fix = 0
            for _pass in range(40):                 # a ring word recurs in every cycle:
                fixed_this_pass = 0                 # iterate to a fixed point
                i = 0
                while i <= len(stream) - k and n_fix < max_fixes:
                    gram = tuple(n.pitch % 12 for n in stream[i:i + k])
                    if gram in seen:
                        keys = []
                        for n in reversed(stream[i:i + k]):
                            kk = word_key(n)
                            if kk not in keys:
                                keys.append(kk)
                        key = min(keys, key=lambda kk: (count[kk], keys.index(kk)))
                        answer(key)
                        n_fix += 1
                        fixed_this_pass += 1
                        fixes[(m.number, sname.split('/')[0])] += 1
                        i = max(0, i - k)           # re-check the neighbourhood
                        continue
                    i += 1
                if not fixed_this_pass:
                    break
            grams = pc_ngrams(stream, k)
            residual += len(grams & seen)
            seen |= grams
    fixes['residual'] = residual
    return dict(fixes)
