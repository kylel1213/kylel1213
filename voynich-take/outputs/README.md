# THE VOYNICH TAKE — build outputs

A performance capture of Beinecke MS 408: every note event is derived word by word, in manuscript order, from the Takahashi (TTLI) transcription; every automation lane from the frozen per-section pixel profile; the rosette canons from the f85v–86r spatial data. Nothing is composed. Nothing resolves. The piece ends mid-word.

- Tempo 124 BPM, 4/4, PPQN 480. Total length **852 bars ≈ 27.5 min**.
- Corpus parsed: 36,906 tokens / 8,434 types.
- Deterministic build: seed 408 (`python build.py --data <dir>` regenerates everything bit-for-bit).

## Press play

- `preview/voynich_take_full.wav` — the complete preview render (44.1 kHz / 16-bit stereo, pure-Python synth, peak −1.5 dBFS). It is ~300 MB and is **not committed to git**; `preview/voynich_take_full.mp3` (160 kbps) is the committed listening copy. Run the build to regenerate the WAV and the per-movement `preview/mvt1..5.wav`.

## Movements

| # | movement | sections ($I) | folios used (of section) | bars | notes |
|---|---|---|---|---|---|
| 1 | I. HERBAL (Language A) | H | f10r, f21v, f32r, f43r, f53v, f95r2 (129) | 225.0 | BLUE_BELL window bars 39–47 (the f16v position). |
| 2 | II. ZODIAC (the year) | A, Z, C | f67v1, f70r1, f72v3 (32) | 147.0 | YEAR_CLOCK enters at bar 79, ends bar 146.4. |
| 3 | III. BIOLOGICAL (Language B) | B | f80r (20) | 184.0 |  |
| 4 | IV. PHARMA (the jars) | P | f88r, f100r (16) | 96.0 |  |
| 5 | V. ROSETTES -> RECIPES | S, T | f85v_86r + f107v (29) | 199.9 | Part A: 9 rosette rings (f85v–86r) bars 0–60; Part B: f107v. Ends after glyph 2 of 'lol' (3 glyphs). |

Folios are subsampled evenly within each section (never reordered) so each movement lands near its bar target; one manuscript line ≈ 2–4 bars at glyph = 16th, so a single dense folio is a movement-sized text wall.

## Track / patch manifest

| # | track | MIDI ch | GM placeholder | sound-design intent |
|---|---|---|---|---|
| 1 | `PARAGRAPH_VOICE` | 1 | 46 | plucked/keyed mono lead. The transcription itself, glyph = 16th. |
| 2 | `LABEL_HITS` | 2 | 12 | dry mallet, staccato. One hit per label word, bursty spacing. |
| 3 | `ROOT_BASS` | 3 | 32 | sub/low bass, one long note per paragraph (the isolated opening word). |
| 4 | `GREEN_PAD` | 4 | 89 | the workhorse wash: it is SUPPOSED to be everywhere. D4/F4 never sound. |
| 5 | `BLUE_BELL` | 5 | 9 | one precious bell. Do not add notes: scarcity is the instrument. |
| 6 | `YEAR_CLOCK` | 6 | 115 | dry, metronomic, un-produced woodblock. Zero humanization. |
| 7 | `ROSETTE_CANONS` | 7 | 11 | nine instances of the SAME patch (same compass), different octaves. |
| 8 | `ATMOS_CTRL` | 8 | — | no notes. CC1 = how much painting is on the page you are hearing. |
| 9 | `BINAURAL_L` | 9 | 78 | pure sine, hard-panned LEFT. Carrier = the sounding root, one octave up. |
| 10 | `BINAURAL_R` | 10 | 78 | the SAME sine patch, hard-panned RIGHT, pitch-bend range ±2 semitones: carries the beat. |
| 11 | `ISOCHRONIC` | 11 | 78 | pure sine one octave above the carrier, notes ARE the gate (50% duty); velocity = painting. |

CC lanes embedded in the .mid files (and duplicated in `automation/*.csv`):

- `PARAGRAPH_VOICE` CC64 (sustain: down per line, up = the m/g damped fall), CC74 (brightness 40→90, the single A→B drift across the whole piece).
- `GREEN_PAD` CC1 (atmosphere, per folio) and CC11 (green wash, per folio), 2-beat ramps at folio boundaries.
- `ATMOS_CTRL` CC1 (the same painting lane for anything you want to hang on it).

| section | density | CC1 | CC11 |
|---|---|---|---|
| H | 0.55 | 96 | 110 |
| A | 0.8 | 70 | 40 |
| Z | 0.8 | 70 | 40 |
| C | 0.8 | 70 | 40 |
| B | 0.85 | 80 | 95 |
| P | 0.75 | 76 | 70 |
| S | 1.0 | 30 | 15 |
| T | 1.0 | 30 | 15 |

## Entrainment layers (binaural + isochronic)

Mode: **density**. The 124 BPM grid is already a brainwave clock: a quarter = 2.07 Hz (delta), an 8th = 4.13 Hz (theta, the year-clock pulse), a 16th = one glyph = 8.27 Hz (alpha), a 16th triplet = 12.4 Hz (low beta), a 32nd = 16.5 Hz (beta). Nothing is invented: tempo, section density, the paragraph roots and the painting lane are the only inputs.

- **Binaural bed** (headphones): `BINAURAL_L` = carrier, `BINAURAL_R` = carrier + beat. Carrier = the sounding `ROOT_BASS` one octave up (D3 where no paragraph root sounds), so it changes per paragraph from the opening word. Beat = glyph rate × section density, morphing over 2 beats at folio boundaries like the CC lanes.
- **Isochronic gate** (speakers OK): a carrier one octave above the binaural carrier, gated at a grid subdivision chosen by section density, phase-locked to bar 1, raised-cosine 50% duty; its level rides the CC1 painting lane. The pulse is the visible page; the binaural is the invisible text.
- The entrainment bands are a mapping, not a referent: the year-clock remains the only element that means anything.

| section | density | binaural beat (Hz) | band | isochronic gate | Hz |
|---|---|---|---|---|---|
| H | 0.55 | 4.55 | theta | 8th | 4.13 |
| A | 0.8 | 6.61 | theta | 16th | 8.27 |
| Z | 0.8 | 6.61 | theta | 16th | 8.27 |
| C | 0.8 | 6.61 | theta | 16th | 8.27 |
| B | 0.85 | 7.03 | theta | 16th | 8.27 |
| P | 0.75 | 6.20 | theta | 8th triplet | 6.20 |
| S | 1.0 | 8.27 | alpha | 16th triplet | 12.40 |
| T | 1.0 | 8.27 | alpha | 16th triplet | 12.40 |

**In Logic:** load the same pure-sine patch on `BINAURAL_L` and `BINAURAL_R`, pan them hard left / hard right, and set the pitch-bend range on the R instrument to ±2 semitones; the embedded pitch-bend on R is the beat, exact to 0.02 cent. `ISOCHRONIC` is plain notes on a sine: the notes are the gate. Or skip the MIDI and use the rendered stems `preview/binaural.wav` and `preview/isochronic.wav`, which are already at mix level. `automation/*_entrainment.csv` lists carrier Hz, beat Hz, band and gate rate against time for a Test Oscillator rebuild. Binaural content does not survive MP3 joint stereo well: the WAV is the listening copy. Rebuild with `--no-entrainment` for the plain take, `--band-mode drift` for the theta→beta version.

> Caution: this piece contains sustained 4–16 Hz pulsed and beating audio. People with epilepsy or a seizure history, and anyone operating machinery, should not use entrainment audio. It is not a medical device.

## Acceptance battery

| check | target | measured | result |
|---|---|---|---|
| 1 corpus check (tokens / types) | 36,906 / 8,434 (±2%) | 36,906 / 8,434 | PASS |
| 2 inertia: lag-1 autocorr of gesture lengths | > 0 (target +0.08..+0.16) | +0.063 — per movement 1:+0.065 2:+0.058 3:+0.024 4:-0.001 5:+0.119 | PASS |
| 3 burstiness B of LABEL_HITS gaps (per-movement normalized, pooled) | 0.12 .. 0.30 | +0.169 (n=42) — per movement 3:+0.19(n=9) 4:+0.16(n=33); raw pooled +0.34 | PASS |
| 4a paragraph-flourish rate (gallows-initial, P paragraphs) | 80% .. 92% | 91.9% (34/37) — word-driven, no dice | PASS |
| 4b line-final m/g mute rate | 15% .. 21% | 17.3% (40/231) — word-driven, no dice | PASS |
| 5 blue budget: total / max in one 8-bar window | <= 12 / >= 8 (C5,D5 only) | 10 / 8 | PASS |
| 6 year-clock pulses / groups | 363 in 12 = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31] | 363 in 12 = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31] — zero humanization | PASS |
| 7a void: 8-note pitch-class sequences shared across movements | 0 | 0 | PASS |
| 7b void: dominant->tonic root motions in GREEN_PAD | 0 | 0 | PASS |
| 7c void: final event mid-word, no trailing pad | glyph 2 of a >=3-glyph word; 0 ticks after | 'lol' glyph 2/3; 0 ticks after | PASS |
| 8 forbidden register: GREEN_PAD/ROOT_BASS notes on 62 or 65 | 0 | 0 | PASS |
| 9 MIDI integrity (reopen, PPQN 480, tempo 483,871, names, CC lanes) | all files clean | clean | PASS |
| 11 binaural: beat 2..20 Hz, carrier 60..320 Hz, R pitch-bend exact | 0 violations | 0 (beat 4.55..8.27 Hz, theta..alpha) | PASS |
| 12 isochronic: every pulse on its grid subdivision, phase-locked | 0 off-grid | 0 of 11954 | PASS |
| 10 render voynich_take_full.wav | > 10 min, peak -6..-1 dBFS, RMS > -30 dBFS | 27.6 min, peak -1.50 dBFS, RMS -17.0 dBFS, 44100 Hz 2ch | PASS |

**Overall: ALL PASS.**

## Logic Pro import

1. Drag each `.mid` into an empty Logic project (or all five sequentially onto the Tracks area at bar 1 of consecutive markers). When Logic asks **“Import tempo?” → Yes** (sets 124).
2. Each MIDI track lands as its own software-instrument track named from the file. Swap the placeholder patch per the manifest table; everything else transfers. Folio boundaries arrive as markers.
3. CC automation arrives as **MIDI Draw** (region-based). To promote it to track automation: select the regions → `Mix ▸ Convert MIDI Draw to Track Automation` (Functions menu in older versions). CC1 = mod, CC11 = expression, CC64 = sustain, CC74 = brightness — map or leave patch-native.
4. `automation/*.csv` is the backup path if any lane is dropped: columns `time_beats, cc, value, track` at 124 BPM.
5. Sound-design intent per track is in the manifest above. The rosette canons are nine loops on ONE track (ch. 7): split by octave region if you want nine instances.

## What is derived from what

- Pitch: glyph → frequency rank within the movement’s corpus → D Dorian pool, common glyphs orbit D3, rare glyphs live at the registral extremes.
- Time: glyph = 16th, word gap = 16th, line = bar group padded to the next barline (justified text, fixed container).
- Inertia: a word whose mean pitch leaps > 7 semitones from the previous word is pulled an octave toward it (the +0.12 word-length autocorrelation, made audible). Part B of V uses 5 semitones.
- Ornaments: paragraph-initial gallows flourish, line-final m/g damped fall, line-initial y/d legato pickup, immediate repeats played bare — each fired by the actual word, never by dice.
- Art displacing text: interior words dropped with probability (1 − section density); first and last words of a line never drop.
- Harmony: GREEN_PAD chords change at paragraph boundaries only, by minimal voice-leading from the previous chord in the white-note field, root motion up a fourth forbidden, D4/F4 forbidden (unpainted vellum).
- Labels: one staccato hit per label word, scattered over its folio with lognormal (bursty) gaps; o-initial labels soft. Pharma: a label never sits on the sounding root (transposed +1 pool step: the zero-match result as systematic near-miss).
- Year-clock: 363 pulses = the real zodiac label counts per ring, f70v1…f73v, 8ths, 2-bar gaps, E3/B3 alternating, zero humanization.
- Rosettes: the nine `C*.ring` polygons of f85v–86r; tokens ordered by angle around each ring centre; loop = the ring’s text; entry staggered by the ring’s real centre x (0–16 bars); transposed by radius rank; last pitch steps to first; bursty dropout.
- Ending: the final word of the recipes text wall is cut after its 2nd glyph. No padding, no cadence.

### Rosette rings

| ring id | role | tokens | glyphs | loop (bars) | entry bar | pool shift | radius px |
|---|---|---|---|---|---|---|---|
| 1 | C5.ring | 47 | 188 | 14.62 | 8.12 | -5 | 347.5 |
| 6 | C1.ring | 33 | 151 | 11.44 | 0.0 | +2 | 282.0 |
| 8 | C4.ring | 43 | 160 | 12.62 | 8.44 | -1 | 283.8 |
| 11 | C7.ring | 35 | 164 | 12.38 | 16.0 | +1 | 283.0 |
| 14 | C8.ring | 32 | 163 | 12.12 | 15.69 | +3 | 280.1 |
| 16 | C9.ring | 29 | 144 | 10.75 | 15.25 | +0 | 283.3 |
| 20 | C6.ring | 34 | 153 | 11.62 | 7.81 | -2 | 285.5 |
| 23 | C3.ring | 36 | 162 | 12.31 | 0.38 | -3 | 286.0 |
| 27 | C2.ring | 32 | 158 | 11.81 | 0.19 | +5 | 279.0 |
