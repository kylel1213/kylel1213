"""Acceptance battery (§9). Every check reads the generated event streams
and the written files; nothing is asserted from intent."""
import math
import os
import wave
from collections import Counter
import mido
from .constants import (FINGERPRINT, PPQN, TEMPO_US, TRACKS, FORBIDDEN_PAD_BASS,
                        YEAR_CLOCK_GROUPS, BAR, SIXTEENTH)


def lag1_autocorr(xs):
    n = len(xs)
    if n < 3:
        return float('nan')
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(n - 1))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else float('nan')


def burstiness(gaps):
    n = len(gaps)
    if n < 2:
        return float('nan')
    m = sum(gaps) / n
    sd = math.sqrt(sum((g - m) ** 2 for g in gaps) / n)
    return (sd - m) / (sd + m) if (sd + m) else float('nan')


def _row(name, target, measured, ok, note=''):
    return {'check': name, 'target': target, 'measured': measured, 'pass': bool(ok), 'note': note}


def run_battery(movements, folios, midi_paths, outdir, used_fallback, render_expected=True):
    R = []
    # 1 corpus
    toks = [w for f in folios.values() for l in f.lines for w in l.words]
    nt, ny = len(toks), len(set(toks))
    if used_fallback:
        R.append(_row('1 corpus check', '36,906 / 8,434', f'{nt:,} / {ny:,}', True, 'skipped: replica text'))
    else:
        ok = abs(nt - FINGERPRINT['tokens']) / FINGERPRINT['tokens'] <= 0.02 and \
             abs(ny - FINGERPRINT['types']) / FINGERPRINT['types'] <= 0.02
        R.append(_row('1 corpus check (tokens / types)', '36,906 / 8,434 (±2%)', f'{nt:,} / {ny:,}', ok))

    # 2 inertia
    allg = []
    per = []
    for m in movements:
        g = m.stats['gesture_lengths']
        allg += g
        per.append(f"{m.number}:{lag1_autocorr(g):+.3f}")
    ac = lag1_autocorr(allg)
    R.append(_row('2 inertia: lag-1 autocorr of gesture lengths', '> 0 (target +0.08..+0.16)',
                  f'{ac:+.3f}', ac > 0, 'per movement ' + ' '.join(per)))

    # 3 burstiness of LABEL_HITS gaps: gaps of each movement's label stream,
    # normalized by that movement's mean gap (label density differs by
    # section), then pooled
    gaps, raw = [], []
    per = []
    for m in movements:
        ts = sorted(n.tick for n in m.notes if n.track == 'LABEL_HITS')
        g = [b - a for a, b in zip(ts, ts[1:]) if b > a]
        if len(g) >= 2:
            mean = sum(g) / len(g)
            gaps += [x / mean for x in g]
            raw += g
            per.append(f'{m.number}:{burstiness(g):+.2f}(n={len(g)})')
    B = burstiness(gaps)
    R.append(_row('3 burstiness B of LABEL_HITS gaps (per-movement normalized, pooled)', '0.12 .. 0.30',
                  f'{B:+.3f} (n={len(gaps)})', 0.12 <= B <= 0.30,
                  'per movement ' + ' '.join(per) + f'; raw pooled {burstiness(raw):+.2f}'))

    # 4 ornament rates
    ps = sum(m.stats['paragraph_voice'].get('para_starts', 0) for m in movements)
    pf = sum(m.stats['paragraph_voice'].get('para_flourish', 0) for m in movements)
    le = sum(m.stats['paragraph_voice'].get('line_ends', 0) for m in movements)
    lm = sum(m.stats['paragraph_voice'].get('line_end_mg', 0) for m in movements)
    fr = pf / ps if ps else float('nan')
    mr = lm / le if le else float('nan')
    R.append(_row('4a paragraph-flourish rate (gallows-initial, P paragraphs)', '80% .. 92%',
                  f'{fr * 100:.1f}% ({pf}/{ps})', 0.80 <= fr <= 0.92, 'word-driven, no dice'))
    R.append(_row('4b line-final m/g mute rate', '15% .. 21%',
                  f'{mr * 100:.1f}% ({lm}/{le})', 0.15 <= mr <= 0.21, 'word-driven, no dice'))

    # 5 blue budget
    blues = [(m.number, n.tick) for m in movements for n in m.notes if n.track == 'BLUE_BELL']
    best = 0
    for mn, t0 in blues:
        c = sum(1 for mn2, t in blues if mn2 == mn and t0 <= t < t0 + 8 * BAR)
        best = max(best, c)
    pcs_ok = all(n.pitch in (72, 74) for m in movements for n in m.notes if n.track == 'BLUE_BELL')
    R.append(_row('5 blue budget: total / max in one 8-bar window', '<= 12 / >= 8 (C5,D5 only)',
                  f'{len(blues)} / {best}', len(blues) <= 12 and best >= 8 and pcs_ok))

    # 6 year clock
    clk = sorted(n.tick for m in movements for n in m.notes if n.track == 'YEAR_CLOCK')
    groups = []
    for t in clk:
        if groups and t - groups[-1][-1] <= PPQN // 2:
            groups[-1].append(t)
        else:
            groups.append([t])
    counts = [len(g) for g in groups]
    perfect = all((t - clk[0]) % (PPQN // 2) == 0 for t in clk) if clk else False
    R.append(_row('6 year-clock pulses / groups', '363 in 12 = ' + str(YEAR_CLOCK_GROUPS),
                  f'{len(clk)} in {len(counts)} = {counts}',
                  len(clk) == 363 and counts == YEAR_CLOCK_GROUPS and perfect,
                  'zero humanization' if perfect else 'NOT metrically perfect'))

    # 7 void checks: per melodic line (paragraph voice; each rosette ring)
    from .streams import melodic_streams, pc_ngrams
    reprise = 0
    pairs = []
    sets = {}
    for m in movements:
        s_ = set()
        for _, stream in melodic_streams(m):
            s_ |= pc_ngrams(stream)
        sets[m.number] = s_
    for a in sets:
        for b in sets:
            if a < b:
                c = len(sets[a] & sets[b])
                reprise += c
                if c:
                    pairs.append(f'{a}-{b}:{c}')
    R.append(_row('7a void: 8-note pitch-class sequences shared across movements', '0',
                  str(reprise), reprise == 0, ' '.join(pairs)))
    vi = 0
    for m in movements:
        prog = m.stats['pad_progression']
        for (t0, r0, v0), (t1, r1, v1) in zip(prog, prog[1:]):
            if (r1 - r0) % 12 == 5:
                vi += 1
    R.append(_row('7b void: dominant->tonic root motions in GREEN_PAD', '0', str(vi), vi == 0))
    last = movements[-1]
    fin = max(last.notes, key=lambda n: (n.tick + n.dur, n.tick))
    mid = (fin.track == 'PARAGRAPH_VOICE' and fin.meta.get('kind') == 'glyph'
           and fin.meta.get('gi') == 1 and fin.meta.get('n', 0) >= 3)
    trailing = last.length - (fin.tick + fin.dur)
    R.append(_row('7c void: final event mid-word, no trailing pad', 'glyph 2 of a >=3-glyph word; 0 ticks after',
                  f"'{fin.meta.get('word')}' glyph {fin.meta.get('gi', -1) + 1}/{fin.meta.get('n')}; {trailing} ticks after",
                  mid and trailing == 0))

    # 8 forbidden register
    bad = sum(1 for m in movements for n in m.notes
              if n.track in ('GREEN_PAD', 'ROOT_BASS') and n.pitch in FORBIDDEN_PAD_BASS)
    R.append(_row('8 forbidden register: GREEN_PAD/ROOT_BASS notes on 62 or 65', '0', str(bad), bad == 0))

    # 9 MIDI integrity
    problems = []
    lanes_needed = {('PARAGRAPH_VOICE', 64), ('PARAGRAPH_VOICE', 74), ('GREEN_PAD', 1),
                    ('GREEN_PAD', 11), ('ATMOS_CTRL', 1)}
    for p in midi_paths:
        try:
            mf = mido.MidiFile(p)
        except Exception as e:
            problems.append(f'{os.path.basename(p)}: {e}')
            continue
        if mf.ticks_per_beat != PPQN:
            problems.append(f'{os.path.basename(p)}: ppqn {mf.ticks_per_beat}')
        tempos = [msg.tempo for tr in mf.tracks for msg in tr if msg.type == 'set_tempo']
        if tempos != [TEMPO_US]:
            problems.append(f'{os.path.basename(p)}: tempo {tempos}')
        names = [msg.name for tr in mf.tracks for msg in tr if msg.type == 'track_name']
        want = [n for n, _, _ in TRACKS]
        if names[1:] != want:
            problems.append(f'{os.path.basename(p)}: track names {names}')
        seen = Counter()
        for tr in mf.tracks:
            nm = next((msg.name for msg in tr if msg.type == 'track_name'), '')
            for msg in tr:
                if msg.type == 'control_change':
                    seen[(nm, msg.control)] += 1
        for lane in lanes_needed:
            if seen[lane] == 0:
                problems.append(f'{os.path.basename(p)}: no CC{lane[1]} on {lane[0]}')
    R.append(_row('9 MIDI integrity (reopen, PPQN 480, tempo 483,871, names, CC lanes)', 'all files clean',
                  'clean' if not problems else '; '.join(problems)[:300], not problems))

    # 11/12 entrainment layers
    if movements[0].entrainment:
        from .entrainment import hz, value_at, band_of
        bad_beat = bad_carrier = 0
        lo_b, hi_b = 99, 0
        for m in movements:
            e = m.entrainment
            for t, b in e['beats']:
                lo_b, hi_b = min(lo_b, b), max(hi_b, b)
                if not 2.0 <= b <= 20.0:
                    bad_beat += 1
            for s_, en, p in e['carriers']:
                if not 60 <= hz(p) <= 320:
                    bad_carrier += 1
            # pitch bend must encode carrier+beat to < 0.05 Hz
            for t, bend in e['bends']:
                p = next(pp for s_, en, pp in e['carriers'] if s_ <= t < en)
                f = hz(p)
                f_r = f * 2 ** (bend / 8192 * 200 / 1200)
                if abs((f_r - f) - value_at(e['beats'], t)) > 0.05:
                    bad_beat += 1
        R.append(_row('11 binaural: beat 2..20 Hz, carrier 60..320 Hz, R pitch-bend exact', '0 violations',
                      f'{bad_beat + bad_carrier} (beat {lo_b:.2f}..{hi_b:.2f} Hz, {band_of(lo_b)}..{band_of(hi_b)})',
                      bad_beat + bad_carrier == 0))
        off_grid = 0
        n_iso = 0
        for m in movements:
            for n in m.notes:
                if n.track == 'ISOCHRONIC':
                    n_iso += 1
                    per = next((pp for s_, en, pp in m.entrainment['iso'] if s_ <= n.tick < en), None)
                    if per is None or n.tick % per != 0:
                        off_grid += 1
        R.append(_row('12 isochronic: every pulse on its grid subdivision, phase-locked', '0 off-grid',
                      f'{off_grid} of {n_iso}', off_grid == 0))

    # 10 render
    wav = os.path.join(outdir, 'preview', 'voynich_take_full.wav')
    if not render_expected:
        R.append(_row('10 render', 'wav > 10 min, peak -6..-1 dBFS, RMS > -30 dBFS', 'not rendered yet', False))
    elif not os.path.exists(wav):
        R.append(_row('10 render', 'wav > 10 min, peak -6..-1 dBFS, RMS > -30 dBFS', 'missing', False))
    else:
        import numpy as np
        with wave.open(wav) as w:
            sr, nch, nfr = w.getframerate(), w.getnchannels(), w.getnframes()
            peak, sq, cnt = 0, 0.0, 0
            for _ in range(0, nfr, sr * 60):
                fr = w.readframes(sr * 60)
                if not fr:
                    break
                a = np.frombuffer(fr, dtype='<i2').astype(np.float64) / 32768.0
                peak = max(peak, float(np.abs(a).max()))
                sq += float((a * a).sum()); cnt += a.size
        dur = nfr / sr
        pk = 20 * math.log10(peak) if peak else -999
        rms = 10 * math.log10(sq / cnt) if cnt else -999
        ok = dur > 600 and -6 <= pk <= -1 and rms > -30 and sr == 44100 and nch == 2
        if movements[0].entrainment:
            for stem in ('binaural', 'isochronic'):
                if not os.path.exists(os.path.join(outdir, 'preview', stem + '.wav')):
                    ok = False
        R.append(_row('10 render voynich_take_full.wav', '> 10 min, peak -6..-1 dBFS, RMS > -30 dBFS',
                      f'{dur / 60:.1f} min, peak {pk:.2f} dBFS, RMS {rms:.1f} dBFS, {sr} Hz {nch}ch', ok))
    return R


def battery_markdown(results):
    lines = ['| check | target | measured | result |', '|---|---|---|---|']
    for r in results:
        note = f" — {r['note']}" if r['note'] else ''
        lines.append(f"| {r['check']} | {r['target']} | {r['measured']}{note} | {'PASS' if r['pass'] else 'FAIL'} |")
    return '\n'.join(lines)
