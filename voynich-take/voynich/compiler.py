"""Text -> timed events. Everything here is derived word-by-word from the
transcription in manuscript order; the only randomness is humanization
jitter, art-displacement thinning and the burst-gap scheduler, all seeded."""
import math
from collections import Counter
from .constants import (SIXTEENTH, THIRTY_SECOND, BAR, POOL, FORBIDDEN_PAD_BASS,
                        HUMAN_TIMING_SD, HUMAN_TIMING_CLAMP, VEL_BASE, VEL_JITTER_SD,
                        INERTIA_THRESHOLD, BURSTINESS_TARGET)
from .events import Note, CC, WordPlacement, PlacedLine
from .pitch import apply_inertia, stem, pool_step

NOTE_DUR = 105       # a 16th (120) played slightly detached


def ceil_bar(t):
    return int(math.ceil(t / BAR)) * BAR


# --------------------------------------------------------------------------
# Folio subsampling and layout
# --------------------------------------------------------------------------

def line_len_16ths(words):
    return sum(len(w) for w in words) + max(0, len(words) - 1)


def folio_bars(fol):
    return sum(int(math.ceil(line_len_16ths(l.words) / 16)) for l in fol.text_lines if l.words)


def _lag1(xs):
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    den = sum((x - m) ** 2 for x in xs)
    return sum((xs[i] - m) * (xs[i + 1] - m) for i in range(n - 1)) / den if den else None


def _sample_fingerprint(fols):
    """Gallows-initial paragraph rate, m/g line-final rate (P-locus text) and
    word-length lag-1 autocorrelation of the running text."""
    ps = pf = le = lm = 0
    lens = []
    for f in fols:
        for l in f.text_lines:
            if not l.words:
                continue
            lens += [len(w) for w in l.words]
            if not l.locus.startswith('P'):
                continue
            if l.para_start:
                ps += 1
                pf += l.words[0][0] in 'ktpf'
            le += 1
            lm += l.words[-1][-1] in 'mg'
    return (pf / ps if ps else None), (lm / le if le else None), _lag1(lens)


def subsample_folios(fols, target_bars, fingerprint=None, end_sections=None):
    """Pick k evenly spaced folios (never reordered) so the movement lands
    inside 0.85..1.10 x target_bars. Among the even samples that fit, take
    the one whose paragraph-gallows rate, line-final m/g rate and word-length
    lag-1 autocorrelation are closest to the manuscript-wide fingerprint
    (87% / 18.2% / +0.12): a representative page
    sample, not a lucky one. Folios without running text are skipped; if
    even a single folio overruns the cap, that one folio is the movement.
    end_sections: if given, the sample must end on a folio of one of these
    sections (the last movement must end in the recipes)."""
    from .constants import FINGERPRINT
    fingerprint = fingerprint or FINGERPRINT
    fols = [f for f in fols if any(l.words for l in f.text_lines)]
    n = len(fols)
    bars = [folio_bars(f) for f in fols]
    if sum(bars) <= target_bars:
        return fols
    cands = []
    fallback, fallback_gap = None, None
    for k in range(n, 0, -1):
        for ph in range(10):                       # even spacing, any phase
            idx = sorted({min(n - 1, int((i + ph / 10) * n / k)) for i in range(k)})
            total = sum(bars[i] for i in idx)
            if total > target_bars * 1.10:
                continue
            if end_sections and fols[idx[-1]].section not in end_sections:
                continue
            gap = abs(total - target_bars)
            if fallback is None or gap < fallback_gap:
                fallback, fallback_gap = idx, gap
            if total >= target_bars * 0.85:
                sel = [fols[i] for i in idx]
                fr, mr, ac = _sample_fingerprint(sel)
                dist = 0.0
                if fr is not None:
                    dist += abs(fr - fingerprint['para_gallows_rate'])
                if mr is not None:
                    dist += abs(mr - fingerprint['line_final_mg_rate'])
                if ac is not None:
                    dist += abs(ac - fingerprint['wordlen_lag1_autocorr'])
                cands.append((dist, -len(idx), idx))
    if cands:
        best = min(cands)[2]
    else:
        best = fallback if fallback is not None else [int(0.5 * n)]
    return [fols[i] for i in best]


def layout(fols, density, rng, start_tick=0, para_offset=0):
    """Place every running-text line of the given folios on the 16th grid,
    line = bar group, padded to the next barline. Returns
    (placed_lines, folio_spans, para_spans, end_tick)."""
    cursor = start_tick
    lines, folio_spans, para_spans = [], [], []
    para_id = para_offset - 1
    cur_para = None
    for fol in fols:
        fstart = cursor
        for line in fol.text_lines:
            if not line.words:
                continue
            if line.para_start:
                if cur_para is not None:
                    para_spans.append(cur_para)
                para_id += 1
                cur_para = [para_id, cursor, None, line.words[0], fol.name, fol.section]
            t = cursor
            # the very first downbeat of a movement cannot host grace notes
            # before it: the flourish takes the first two 32nds instead
            if t == start_tick and line.para_start and line.words[0][0] in 'ktpf':
                t += SIXTEENTH
            n = len(line.words)
            # art displacing text: a drawing occupies a CONTIGUOUS stretch of
            # the line, so the dropped interior words form one run whose
            # length is Binomial(interior, 1 - density); first and last
            # words of a line never drop. Runs keep the surviving words
            # adjacent, which is what carries the +0.12 inertia.
            interior = max(0, n - 2)
            n_drop = sum(1 for _ in range(interior) if rng.random() >= density)
            off = rng.randrange(0, interior - n_drop + 1) if n_drop < interior else 0
            dropped = set(range(1 + off, 1 + off + n_drop))
            wps = []
            for i, w in enumerate(line.words):
                wps.append(WordPlacement(w, t, i not in dropped, i, n))
                t += len(w) * SIXTEENTH + SIXTEENTH
            line_end = t - SIXTEENTH
            end = ceil_bar(line_end)
            if end == line_end:      # a line that fills its container exactly
                end = line_end
            lines.append(PlacedLine(fol.name, fol.section, line.locus, para_id,
                                    line.para_start, cursor, end, wps))
            cursor = end
        if cursor == fstart:
            continue
        folio_spans.append((fol.name, fol.section, fstart, cursor))
    if cur_para is not None:
        para_spans.append(cur_para)
    # close paragraph spans at the next paragraph start (or the end)
    for i, ps in enumerate(para_spans):
        ps[2] = para_spans[i + 1][1] if i + 1 < len(para_spans) else cursor
    return lines, folio_spans, [tuple(p) for p in para_spans], cursor


# --------------------------------------------------------------------------
# PARAGRAPH_VOICE
# --------------------------------------------------------------------------

def _jitter(rng):
    off = rng.gauss(0, HUMAN_TIMING_SD)
    return int(max(-HUMAN_TIMING_CLAMP, min(HUMAN_TIMING_CLAMP, round(off))))


def compile_paragraph_voice(lines, rankmap, rng, inertia_threshold=INERTIA_THRESHOLD,
                            track='PARAGRAPH_VOICE'):
    notes, ccs = [], []
    stats = Counter()
    gesture_lengths = []            # glyphs per rendered word, in order
    prev_mean = None
    prev_word = None
    prev_word_notes = None
    for line in lines:
        kept = [wp for wp in line.words if wp.kept]
        if not kept:
            continue
        ccs.append(CC(track, line.start, 64, 127))       # pedal down for the line
        first_wp, last_wp = kept[0], kept[-1]
        for wp in kept:
            word = wp.word
            pitches = rankmap.word_pitches(word)
            is_repeat = (prev_word == word and prev_word_notes is not None
                         and wp.idx_in_line > 0 and line.words[wp.idx_in_line - 1].kept)
            if is_repeat:
                # bare autopilot: identical pitches, velocity -12, no variation
                pitches = [n.pitch for n in prev_word_notes]
                vels = [max(1, n.vel - 12) for n in prev_word_notes]
                offs = [0] * len(word)
                stats['repeats'] += 1
            else:
                pitches = apply_inertia(pitches, prev_mean, inertia_threshold)
                vels = [int(max(20, min(120, round(VEL_BASE + rng.gauss(0, VEL_JITTER_SD)))))
                        for _ in word]
                offs = [_jitter(rng) for _ in word]
            word_notes = []
            # the 87% gallows statistic is a property of P-locus paragraphs;
            # circular/radial units carry no flourish rule
            para_first = (line.para_start and wp is first_wp and wp.idx_in_line == 0
                          and line.locus.startswith('P'))
            legato = (wp is first_wp and wp.idx_in_line == 0 and word[0] in 'yd')
            if wp.idx_in_line == 0:
                stats['line_starts'] += 1
                if word[0] in 'yd':
                    stats['line_start_yd'] += 1
            if para_first:
                stats['para_starts'] += 1
                if word[0] in 'ktpf':
                    stats['para_flourish'] += 1
                    p0 = pitches[0]
                    g0 = max(0, wp.tick - SIXTEENTH)
                    notes.append(Note(track, g0, THIRTY_SECOND - 5, min(127, p0 + 12), 100,
                                      {'kind': 'grace', 'word': word, 'line': id(line)}))
                    notes.append(Note(track, g0 + THIRTY_SECOND, THIRTY_SECOND - 5,
                                      min(127, p0 + 7), 100,
                                      {'kind': 'grace', 'word': word, 'line': id(line)}))
                    vels[0] = min(127, vels[0] + 18)
            for gi, (g, p, v, off) in enumerate(zip(word, pitches, vels, offs)):
                t = wp.tick + gi * SIXTEENTH + off
                if t < 0:
                    t = 0
                dur = NOTE_DUR + (30 if legato else 0)
                word_notes.append(Note(track, t, dur, p, v,
                                       {'kind': 'glyph', 'word': word, 'glyph': g,
                                        'gi': gi, 'n': len(word), 'folio': line.folio,
                                        'wid': len(gesture_lengths),
                                        'para': line.para_id, 'line': id(line)}))
            # line-final m/g mute: damped fall at the barline
            if wp is last_wp and wp.idx_in_line == len(line.words) - 1:
                stats['line_ends'] += 1
                if word[-1] in 'mg':
                    stats['line_end_mg'] += 1
                    fin = word_notes[-1]
                    fin.dur = THIRTY_SECOND
                    if fin.pitch - 12 >= POOL[0]:
                        fin.pitch -= 12
                    fin.meta['kind'] = 'mute'
                    ccs.append(CC(track, fin.tick, 64, 0))
            notes.extend(word_notes)
            gesture_lengths.append(len(word))
            prev_mean = sum(n.pitch for n in word_notes) / len(word_notes)
            prev_word, prev_word_notes = word, word_notes
    stats['words'] = len(gesture_lengths)
    return notes, ccs, dict(stats), gesture_lengths


# --------------------------------------------------------------------------
# LABEL_HITS with the burst-gap scheduler
# --------------------------------------------------------------------------

def lognormal_sigma(B=BURSTINESS_TARGET):
    cv = (1 + B) / (1 - B)
    return math.sqrt(math.log(1 + cv * cv))


def burst_gaps(n, rng, sigma=None):
    sigma = sigma or lognormal_sigma()
    return [rng.lognormvariate(0.0, sigma) for _ in range(n)]


def _burstiness(gaps):
    n = len(gaps)
    if n < 2:
        return None
    m = sum(gaps) / n
    sd = math.sqrt(sum((g - m) ** 2 for g in gaps) / n)
    return (sd - m) / (sd + m) if sd + m else None


def compile_label_hits(folio_spans, folios_by_name, rankmap, rng, exclude_locus=('Lz',),
                       bass_pc_at=None, track='LABEL_HITS', target_B=BURSTINESS_TARGET,
                       tol=0.04, max_tries=400):
    """One staccato event per label word, scattered over its folio's span
    with lognormal gaps. The gap set is re-drawn (seeded) until the realized
    recurrence-gap burstiness of the movement's label stream sits within
    target_B +- tol: appear in clusters, vanish, return. bass_pc_at(tick)
    -> pitch class enables the Pharma anti-crib rule (near-miss against the
    sounding ROOT_BASS)."""
    per_folio = []
    for fname, sec, start, end in folio_spans:
        fol = folios_by_name[fname]
        labels = [w for l in fol.label_lines if l.locus not in exclude_locus for w in l.words]
        if labels:
            per_folio.append((fname, start, end, labels))
    if not per_folio:
        return [], {'labels': 0}

    def draw():
        ticks = []
        for fname, start, end, labels in per_folio:
            span = end - start
            gaps = burst_gaps(len(labels) + 1, rng)
            total = sum(gaps)
            acc = 0.0
            for w, g in zip(labels, gaps):
                acc += g
                t = start + int(round(acc / total * span / SIXTEENTH)) * SIXTEENTH
                ticks.append((min(t, end - SIXTEENTH), w, fname))
        return ticks

    best, best_err = None, None
    for _ in range(max_tries):
        ticks = draw()
        ts = sorted(t for t, _, _ in ticks)
        B = _burstiness([b - a for a, b in zip(ts, ts[1:]) if b > a])
        err = abs(B - target_B) if B is not None else 0.0
        if best is None or err < best_err:
            best, best_err = ticks, err
        if err <= tol:
            break
    notes = []
    stats = Counter()
    for t, w, fname in best:
        pitch = min(127, rankmap.pitch(w[0]) + 12)
        if bass_pc_at is not None:
            bpc = bass_pc_at(t)
            if bpc is not None and pitch % 12 == bpc:
                pitch = pool_step(pitch - 12, 1) + 12
                stats['anticrib_shifts'] += 1
        vel = 58 if w[0] == 'o' else 76
        stats['o_initial' if w[0] == 'o' else 'other'] += 1
        notes.append(Note(track, t, SIXTEENTH, pitch, vel,
                          {'kind': 'label', 'word': w, 'folio': fname}))
    notes.sort(key=lambda n: n.tick)
    stats['labels'] = len(notes)
    stats['burstiness_fit_error'] = round(best_err, 3)
    return notes, dict(stats)


# --------------------------------------------------------------------------
# ROOT_BASS
# --------------------------------------------------------------------------

def compile_root_bass(para_spans, rankmap, vel=72, track='ROOT_BASS'):
    notes = []
    for pid, start, end, first_word, folio, sec in para_spans:
        core = stem(first_word)
        counts = Counter(core)
        g = min(counts, key=lambda x: (-counts[x], rankmap.glyph_rank(x)))
        p = rankmap.pitch(g) - 24
        while p < 26:
            p += 12
        assert p not in FORBIDDEN_PAD_BASS
        dur = max(BAR, end - start)
        notes.append(Note(track, start, dur - 10, p, vel,
                          {'kind': 'root', 'word': first_word, 'stem': core, 'para': pid}))
    return notes


# --------------------------------------------------------------------------
# GREEN_PAD: harmonic memory <= 3 events, no dominant->tonic, no reprise
# --------------------------------------------------------------------------

WHITE = [0, 2, 4, 5, 7, 9, 11]          # C D E F G A B
PAD_LO, PAD_HI = 48, 71


def _chords():
    """All 4-voice diatonic seventh chords in the D Dorian white-note field,
    voiced inside C3..B4, never touching D4/F4."""
    out = []
    for ri, root in enumerate(WHITE):
        pcs = [WHITE[(ri + k) % 7] for k in (0, 2, 4, 6)]
        options = []
        for pc in pcs:
            options.append([p for p in range(PAD_LO, PAD_HI + 1)
                            if p % 12 == pc and p not in FORBIDDEN_PAD_BASS])
        def rec(i, cur):
            if i == len(options):
                v = sorted(cur)
                if v[-1] - v[0] <= 19 and len(set(v)) == 4:
                    out.append((root, tuple(v)))
                return
            for p in options[i]:
                rec(i + 1, cur + [p])
        rec(0, [])
    return out


CHORDS = _chords()


def _vl_distance(a, b):
    return sum(abs(x - y) for x, y in zip(sorted(a), sorted(b)))


def compile_green_pad(para_spans, rankmap, vel=56, track='GREEN_PAD'):
    notes = []
    prev = None
    progression = []
    for pid, start, end, first_word, folio, sec in para_spans:
        if prev is None:
            root_pc = (rankmap.pitch(stem(first_word)[0])) % 12
            cands = [c for c in CHORDS if c[0] == root_pc] or CHORDS
            # lowest-spread voicing of that root
            chord = min(cands, key=lambda c: (c[1][-1] - c[1][0], c[1]))
        else:
            proot, pv = prev
            cands = []
            for root, v in CHORDS:
                if set(v) == set(pv):
                    continue                                   # must change
                if (root - proot) % 12 == 5:
                    continue                                   # V -> I forbidden (up a 4th)
                cands.append((_vl_distance(pv, v), root, v))
            dmin = min(c[0] for c in cands)
            ties = sorted(c for c in cands if c[0] == dmin)
            pick = ties[rankmap.glyph_rank(first_word[0]) % len(ties)]
            chord = (pick[1], pick[2])
        prev = chord
        progression.append((start, chord[0], chord[1]))
        dur = max(BAR, end - start)
        for p in chord[1]:
            assert p not in FORBIDDEN_PAD_BASS
            notes.append(Note(track, start, dur - 10, p, vel,
                              {'kind': 'pad', 'root': chord[0], 'para': pid}))
    return notes, progression
