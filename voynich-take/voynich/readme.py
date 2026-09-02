"""README generator: battery table, manifest, Logic Pro import steps."""
import os
from .constants import TRACKS, BAR, BPM, PPQN, SECTION_PROFILE
from .battery import battery_markdown

INTENT = {
    'PARAGRAPH_VOICE': 'plucked/keyed mono lead. The transcription itself, glyph = 16th.',
    'LABEL_HITS': 'dry mallet, staccato. One hit per label word, bursty spacing.',
    'ROOT_BASS': 'sub/low bass, one long note per paragraph (the isolated opening word).',
    'GREEN_PAD': 'the workhorse wash: it is SUPPOSED to be everywhere. D4/F4 never sound.',
    'BLUE_BELL': 'one precious bell. Do not add notes: scarcity is the instrument.',
    'YEAR_CLOCK': 'dry, metronomic, un-produced woodblock. Zero humanization.',
    'ROSETTE_CANONS': 'nine instances of the SAME patch (same compass), different octaves.',
    'ATMOS_CTRL': 'no notes. CC1 = how much painting is on the page you are hearing.',
}


def write_readme(movements, results, outdir, used_fallback, corpus_counts):
    total_ticks = sum(m.length for m in movements)
    minutes = total_ticks / PPQN / BPM
    L = []
    L.append('# THE VOYNICH TAKE — build outputs\n')
    L.append('A performance capture of Beinecke MS 408: every note event is derived word by word, in manuscript order, '
             'from the Takahashi (TTLI) transcription; every automation lane from the frozen per-section pixel profile; '
             'the rosette canons from the f85v–86r spatial data. Nothing is composed. Nothing resolves. '
             'The piece ends mid-word.\n')
    if used_fallback:
        L.append('> **WARNING: the transcription could not be fetched; this build used the replica machine (synthetic text, §8).** '
                 'Known deviations from the real manuscript: hapax 40% vs 70%, Zipf −0.77 vs −1.03. Re-run with network access for the real take.\n')
    L.append(f'- Tempo {BPM} BPM, 4/4, PPQN {PPQN}. Total length **{total_ticks / BAR:.0f} bars ≈ {minutes:.1f} min**.')
    L.append(f'- Corpus parsed: {corpus_counts[0]:,} tokens / {corpus_counts[1]:,} types.')
    L.append('- Deterministic build: seed 408 (`python build.py --data <dir>` regenerates everything bit-for-bit).\n')

    L.append('## Press play\n')
    L.append('- `preview/voynich_take_full.wav` — the complete preview render (44.1 kHz / 16-bit stereo, pure-Python synth, peak −1.5 dBFS). '
             'It is ~300 MB and is **not committed to git**; `preview/voynich_take_full.mp3` (160 kbps) is the committed listening copy. '
             'Run the build to regenerate the WAV and the per-movement `preview/mvt1..5.wav`.\n')

    L.append('## Movements\n')
    L.append('| # | movement | sections ($I) | folios used (of section) | bars | notes |')
    L.append('|---|---|---|---|---|---|')
    for m in movements:
        fol = ', '.join(m.selected_folios)
        extra = ''
        if m.number == 5:
            extra = 'Part A: 9 rosette rings (f85v–86r) bars 0–60; Part B: ' + fol + '. '
            e = m.stats['ending']
            extra += f"Ends after glyph 2 of '{e['word']}' ({e['word_length']} glyphs)."
            fol = 'f85v_86r + ' + fol
        if m.number == 2:
            yc = m.stats['year_clock']
            extra = f"YEAR_CLOCK enters at bar {yc['start'] / BAR:.0f}, ends bar {yc['end'] / BAR:.1f}."
        if m.number == 1:
            w0, w1 = m.stats['blue_window']
            extra = f'BLUE_BELL window bars {w0 / BAR:.0f}–{w1 / BAR:.0f} (the f16v position).'
        L.append(f"| {m.number} | {m.title} | {', '.join(m.sections)} | {fol} ({len(m.all_folios)}) | "
                 f"{m.length / BAR:.1f} | {extra} |")
    L.append('')
    L.append('Folios are subsampled evenly within each section (never reordered) so each movement lands near its bar target; '
             'one manuscript line ≈ 2–4 bars at glyph = 16th, so a single dense folio is a movement-sized text wall.\n')

    L.append('## Track / patch manifest\n')
    L.append('| # | track | MIDI ch | GM placeholder | sound-design intent |')
    L.append('|---|---|---|---|---|')
    for i, (name, ch, prog) in enumerate(TRACKS, 1):
        L.append(f"| {i} | `{name}` | {ch} | {prog if prog is not None else '—'} | {INTENT[name]} |")
    L.append('')
    L.append('CC lanes embedded in the .mid files (and duplicated in `automation/*.csv`):\n')
    L.append('- `PARAGRAPH_VOICE` CC64 (sustain: down per line, up = the m/g damped fall), CC74 (brightness 40→90, the single A→B drift across the whole piece).')
    L.append('- `GREEN_PAD` CC1 (atmosphere, per folio) and CC11 (green wash, per folio), 2-beat ramps at folio boundaries.')
    L.append('- `ATMOS_CTRL` CC1 (the same painting lane for anything you want to hang on it).\n')
    L.append('| section | density | CC1 | CC11 |')
    L.append('|---|---|---|---|')
    for k in 'HAZCBPST':
        d, c1, c11 = SECTION_PROFILE[k]
        L.append(f'| {k} | {d} | {c1} | {c11} |')
    L.append('')

    L.append('## Acceptance battery\n')
    L.append(battery_markdown(results))
    L.append('')
    allpass = all(r['pass'] for r in results)
    L.append(f"**Overall: {'ALL PASS' if allpass else 'FAILURES PRESENT'}.**\n")

    L.append('## Logic Pro import\n')
    L.append('1. Drag each `.mid` into an empty Logic project (or all five sequentially onto the Tracks area at bar 1 of consecutive markers). When Logic asks **“Import tempo?” → Yes** (sets 124).')
    L.append('2. Each MIDI track lands as its own software-instrument track named from the file. Swap the placeholder patch per the manifest table; everything else transfers. Folio boundaries arrive as markers.')
    L.append('3. CC automation arrives as **MIDI Draw** (region-based). To promote it to track automation: select the regions → `Mix ▸ Convert MIDI Draw to Track Automation` (Functions menu in older versions). CC1 = mod, CC11 = expression, CC64 = sustain, CC74 = brightness — map or leave patch-native.')
    L.append('4. `automation/*.csv` is the backup path if any lane is dropped: columns `time_beats, cc, value, track` at 124 BPM.')
    L.append('5. Sound-design intent per track is in the manifest above. The rosette canons are nine loops on ONE track (ch. 7): split by octave region if you want nine instances.\n')

    L.append('## What is derived from what\n')
    L.append('- Pitch: glyph → frequency rank within the movement’s corpus → D Dorian pool, common glyphs orbit D3, rare glyphs live at the registral extremes.')
    L.append('- Time: glyph = 16th, word gap = 16th, line = bar group padded to the next barline (justified text, fixed container).')
    L.append('- Inertia: a word whose mean pitch leaps > 7 semitones from the previous word is pulled an octave toward it (the +0.12 word-length autocorrelation, made audible). Part B of V uses 5 semitones.')
    L.append('- Ornaments: paragraph-initial gallows flourish, line-final m/g damped fall, line-initial y/d legato pickup, immediate repeats played bare — each fired by the actual word, never by dice.')
    L.append('- Art displacing text: interior words dropped with probability (1 − section density); first and last words of a line never drop.')
    L.append('- Harmony: GREEN_PAD chords change at paragraph boundaries only, by minimal voice-leading from the previous chord in the white-note field, root motion up a fourth forbidden, D4/F4 forbidden (unpainted vellum).')
    L.append('- Labels: one staccato hit per label word, scattered over its folio with lognormal (bursty) gaps; o-initial labels soft. Pharma: a label never sits on the sounding root (transposed +1 pool step: the zero-match result as systematic near-miss).')
    L.append('- Year-clock: 363 pulses = the real zodiac label counts per ring, f70v1…f73v, 8ths, 2-bar gaps, E3/B3 alternating, zero humanization.')
    L.append('- Rosettes: the nine `C*.ring` polygons of f85v–86r; tokens ordered by angle around each ring centre; loop = the ring’s text; entry staggered by the ring’s real centre x (0–16 bars); transposed by radius rank; last pitch steps to first; bursty dropout.')
    L.append('- Ending: the final word of the recipes text wall is cut after its 2nd glyph. No padding, no cadence.\n')
    rs = movements[-1].stats.get('rosettes', [])
    if rs:
        L.append('### Rosette rings\n')
        L.append('| ring id | role | tokens | glyphs | loop (bars) | entry bar | pool shift | radius px |')
        L.append('|---|---|---|---|---|---|---|---|')
        for r in rs:
            L.append(f"| {r['ring']} | {r['role']} | {r['tokens']} | {r['glyphs']} | {r['loop_ticks'] / BAR:.2f} | {r['entry_bar']} | {r['pool_shift']:+d} | {r['radius_px']} |")
        L.append('')
    with open(os.path.join(outdir, 'README.md'), 'w') as fh:
        fh.write('\n'.join(L))
