# THE VOYNICH TAKE — handoff

Branch: `claude/voynich-sonification-build-sm0wyb` in `kylel1213/kylel1213`, folder `voynich-take/`.
Sessions: cloud build (no access to scans) https://claude.ai/code/session_01AFvstgTauVwXPVxJK8MRMa, then a local session on 2026-09-02 that ran the real data end to end (§0).

## 0. Local session, 2026-09-02: real scans, full render

**Delivered** (on the drive, which mounts as `/Volumes/Extreme SSD`, not `/Volumes/Extreme`):

- `/Volumes/Extreme SSD/VOYNICH_TAKE/voynich_take_full.wav` — 27.6 min, 44.1 kHz stereo, from `build.py` (battery: all 16 rows PASS; outputs byte-identical to the committed MIDI/CSV).
- `/Volumes/Extreme SSD/VOYNICH_TAKE/voynich_take_1920x1080.mp4` — the full visual, 1080p30 H.264 + AAC, 1654.9 s, 1.2 GB, rendered in 52 min on a 10-core Mac (8 workers, ~2.2 fps each).

**Data sources actually used**

- Scans: the Yale IIIF manifest (`collections.library.yale.edu/manifests/2002046`, v3, 213 canvases, image API v2 at `/iiif/2/<id>/full/full/0/default.jpg`; `/full/3000,/` is refused with 403). Single pages are ~2800×3800 px. `visual/fetch.py --all` matched 197 folios by label; the PDF in `~/Downloads` (Voynich_Manuscript.pdf, 209 pages) was not used: its embedded scans are only ~1100×1536 px.
- Foldout panels (47 transcription folios: f67–f73, f85/86, f89/90, f95, f101/102) are not separate Yale images; Yale photographs each foldout as a whole opening ("69v and 70r", "72v (part)"). **`visual/foldouts.py`** (new) downloads the 26 parent images, locates each panel's Voynichese boxes on its candidates and crops it at full resolution into `data/scans/<panel>.jpg` (`--install`). It uses the facts below: the panel frame is one page tall, and the panels of one opening tile it side by side (rectos left→right in numbering order, versos reversed), so every feasible assignment/order is scored with a windowed correlation. QA: `data/foldouts/qa/<parent>.jpg`, layout report `data/foldouts/report.json`.
- Word boxes: `voynichese_data.zip` (715 KB; the http URL 301s to https) → `data/voynichese/data/<folio>.xml`, 225 files, panel names match the transcription (f70r1, f72v3, f95r2 …). No XML for f68v, f101r, f101r2, f101v, f101v1, f116v (riffle only).

**Key finding that makes registration trivial**: the Voynichese frame of a folio is the Yale image scaled to 1500 px tall (widths agree within ~1–6 %; a few recipe versos are up to 16 % wider, i.e. the frame overhangs the photo on the left). So `scale ≈ scan_height / 1500` and the offset is near the origin (≤ ~7 %, plus overhang). `geometry.register()` now uses that prior with a windowed correlation instead of a free search; the free search locked onto plant drawings on real vellum.

**Retuned for real vellum (`visual/geometry.py`)**

- `ink_mask`: confined to the eroded vellum (Yale's black ground and the book edges are excluded); threshold relative to the *local* vellum brightness (4 % of the width box mean) with an adaptive floor so the darkest 4 % of the page always count (the zodiac versos f72v1–3 are extremely faint); green/blue/red pigment excluded by hue; thick blobs removed as before.
- Rosettes (f85v_86r): the spatial-data frame has a different aspect than the photo (sx 2.44 vs sy 2.69 scan px per unit) → anisotropic fit (`reg['sy']`), then each ring is refitted rigidly (position + radius factor) with an annulus-edge template on a darkness map (`ring_fits`); fits that run to the search edge fall back to the global fit. Two rings are corrected by hand.
- Manual corrections live in **`data/registration_overrides.json`** (used by `render_video.py`): `f85v_86r.ring_fits` for rings 27 and 23, and a full manual reg for f72v2 (faint page; used only by the year-clock inset). `f72v3` has a hand crop (`CROP_OVERRIDES` in `visual/foldouts.py`).
- Every needed folio was checked on its QA sheet (`outputs/visual/qa/<folio>.jpg`): single pages, all panels used by the take (f67v1 f70r1 f70v1 f70v2 f72r1–3 f72v1–3 f95r2), and the nine rosette rings, all sit on their words. Registration `score` remains uninformative (0.02–0.08 for correct fits); use the sheets.

**Known leftovers**

- `f86v5` and `f86v6` were both placed on the same region of parent 1006230 (the 85/86 group has no clean tiling); one is wrong. Riffle-only (90 ms). Same caveat for the 89v/90 and 101/102 free-search placements.
- `render_video.py` needed OS font fallbacks (DejaVu is a Linux path); it now picks Arial/Georgia on macOS (`find_font`).
- Full render + `--jobs 8` writes ~1.2 GB; segments are deleted after the mux. The render log is buffered through `grep -v Warning`; watch `outputs/visual/segments/` for progress.
- Local layout: `/Users/kylensch/Voynich Project/` holds the clone at `repo/`, a Python 3.14 venv at `venv/`, and the run logs.

## 1. Where things stand

**Done and verified**

- Audio build (`build.py`): five movements from the real TTLI transcription (36,906 tokens / 8,434 types, exact), Type-1 MIDI with CC lanes, CSV automation, pure-Python preview render, 16-row acceptance battery **all passing** (table at the end). Total 852 bars = 27.6 min at 124 BPM.
- Entrainment layers: BINAURAL_L/R (carrier = ROOT_BASS + 12, beat as pitch bend on R, beat = 8.267 Hz × section density) and ISOCHRONIC (octave-up carrier gated at a grid subdivision, level on CC1). Hz-exact stems `preview/binaural.wav`, `preview/isochronic.wav`. Verified by FFT (L 87.25 Hz / R 91.88 Hz = 4.6 Hz theta at minute 1; iso envelope 4.125 Hz).
- Mix recalibrated: shaped noise bed −58 dBFS at full CC1 (piece-wide −63), sustain envelopes on pad/bass, per-track RMS targets (lead −25, bass/bell −28, rosettes −29, labels/clock −30, pad −31 dBFS). Program −18.6 dBFS RMS, peak −1.5.
- Visual pipeline (`render_video.py` + `visual/`): cue sheet from the built movements, Voynichese XML alignment + registration onto scans, pigment masks, frame renderer (camera FULL/PARA/LINE, additive word light with glyph cursor and trails, dropped-word veils, pigment washes, label flashes, blue flare, year-clock inset counting real zodiac labels, rosette ring lights, entrainment pulses, HUD, annotation strip), cinematic page-turn riffle, chunked parallel ffmpeg encode with audio mux. **Tested end to end on MOCK pages only**: a full 27.6-min 540p15 render completed with no errors; 1080p excerpts reviewed frame by frame.
- Registration validated on mock scans: recovered scale within 1 % and offsets within ~10 px of ground truth on all 13 folios + the rosettes foldout.

**Never touched real data (the first thing to verify locally)**

1. `visual/fetch.py`: Yale IIIF manifest URL/format guesses (`collections.library.yale.edu/manifests/2002046`, catalog-record fallback). Indexer unit-tested on synthetic v2/v3 manifests only.
2. `voynichese_data.zip` download and its folder layout (parser searches recursively for `<folio>.xml` or `<folio name=...>`).
3. Registration on real scans (ink mask thresholds: dark < 0.68 × median luminance, low saturation, thick blobs removed). Check every `outputs/visual/qa/<folio>.jpg`.
4. Pigment masks on real vellum (HSV bands in `visual/geometry.py: paint_masks`); expect to retune `smin` thresholds.
5. PDF page → folio mapping for foldouts (f67–f73 panels, f85v–86r rosettes, f89, f101, f102).
6. Camera zoom on 3000–4000 px scans (zoom clamp 1.6 screen px per scan px in `choose_camera`).

## 2. Immediate task: real pages from the PDF in ~/Downloads

```bash
cd kylel1213/voynich-take && git pull
pip install mido numpy lameenc pillow imageio-ffmpeg pymupdf
mkdir -p data && cd data
git clone --depth 1 https://github.com/OrcusLabs/voynich.science.git vjson
git clone --depth 1 https://github.com/alessandroplaca-uro/voynich-spatial-data.git spatial
cd ..
python build.py --data data --wav-to "/Volumes/Extreme/"        # audio + battery + WAV to the drive

# pages from the PDF
python -m visual.from_pdf --pdf ~/Downloads/<file>.pdf --data data --first-page <PDF page showing f1r> --sheet
#   -> data/pdf_pages/contact_sheet_*.jpg + mapping.json (page -> folio). Fix foldouts by eye, then:
python -m visual.from_pdf --pdf ~/Downloads/<file>.pdf --data data --apply

# word boxes (Apache 2.0): http://www.voynichese.com/1/data/folio/voynichese_data.zip -> data/voynichese/
python -m visual.fetch --data data --folios f10r      # fetches the zip; scans already in place from the PDF
#   if voynichese.com is down, tell the session: fall back to deriving line/word boxes from the scans

# registration check, then the render
python render_video.py --data data --qa --start 6 --duration 40 --frames 2 --jobs 4
#   -> outputs/visual/qa/*.jpg (every word box drawn on its scan), stills/, excerpt mp4
#   corrections: data/registration_overrides.json  {"f10r": {"scale": .., "ox": .., "oy": ..}}
python render_video.py --data data --jobs 6           # full 1080p30, ~20–30 min on a fast Mac
```

Needed folios (sonified + clock inset): f10r f21v f32r f43r f53v f95r2 f67v1 f70r1 f70v1 f70v2 f71r f71v f72r1 f72r2 f72r3 f72v1 f72v2 f72v3 f73r f73v f80r f88r f100r f107v f85v_86r. All 226 for the riffle. The rosettes foldout must be one image named `f85v_86r.jpg`; the spatial data's token coordinates are registered onto it as points.

## 3. Decision log (why things are the way they are)

- **Aesthetic contract** (from the brief): derived never composed; no functional harmony; the year-clock is the only referent; ends mid-word; every deliverable passes the battery.
- Running voice = P + C + R loci (zodiac pages have no P text); labels = L loci; Lz labels are the clock.
- Folio subsampling: even samples within each section, never reordered; among samples inside 0.85–1.10 × the bar target, the one whose gallows/m-g/word-length-autocorr stats are closest to the manuscript fingerprint. Movement V must end in an S folio (f107v). Per-movement bar targets honoured (they sum to ~28 min, not the brief's 18–24).
- Art displacing text drops a **contiguous run** of interior words per line (independent drops destroyed the +0.12 inertia).
- No-reprise rule: an 8-note pitch-class sequence heard in an earlier movement is answered by mirroring the completing word's pool position (D↔D, F↔C, G↔A), per melodic line (paragraph voice; each rosette ring).
- Burstiness measured on per-movement-normalized label gaps (label density differs by section).
- Entrainment: beat = glyph rate × density (mode `density`); `--band-mode drift` = one theta→beta morph. Carriers clipped before the final glyph. Caution note in the README.
- Visual mapping: PARAGRAPH_VOICE → word light + glyph cursor; GREEN_PAD → green pigment breathing (CC11); ROOT_BASS → red-brown pigment pulse; LABEL_HITS → label box flash; BLUE_BELL → blue pigment flare + bloom; YEAR_CLOCK → inset of the counted zodiac folio with its labels lit in order; ROSETTE_CANONS → ring tokens lit in the ring's hue; isochronic → 2.5 % frame breath; binaural → page edges alternating. CC74 morphs the reading light gold → cool.
- Camera: FULL for the first 4 s of a folio, for A/Z/C/P pages, the rosettes, and the blue-bell window; PARA for 3 s at paragraph starts; LINE follow-zoom otherwise. Annotation strip in movements 2 and 5 and for 12 s after each arrival.
- Riffle: every skipped folio turns in order (eased sequence, fold at the spine with cast shadow, motion blur, push-in landing on the establishing framing). Pre-roll 6 s of silence before the first note.

## 4. Knobs

| what | where |
|---|---|
| track RMS targets / gains | `voynich/render.py: RMS_TARGET, TRACK_GAIN` (recalibrate with `calibrate()`) |
| noise bed level | `voynich/render.py: NOISE_RMS_DBFS` |
| entrainment levels | `voynich/render.py: BINAURAL_RMS_DBFS, ISO_RMS_DBFS` |
| riffle speed | `visual/cues.py` (`lead = min(2.5, max(0.8, 0.09 * len(skipped)))`, pre-roll = 6 s) |
| turn look (shadow, darkening) | `visual/render.py: _turn` |
| camera zoom clamp, line framing | `visual/render.py: choose_camera` |
| word light colours / sizes | `visual/render.py: GOLD, COOL, draw_words` |
| strip placement | `visual/render.py: draw_strip` (bottom-right, 724×100) |
| section profile (density, CC1, CC11) | `voynich/constants.py: SECTION_PROFILE` |

## 5. Known issues / ideas

- Annotation strip covers page text at high zoom in movements 2 and 5 (by design, but could move to the table area when the page fills the frame).
- Registration `score` values are small (~0.05–0.12); rely on the QA sheets, not the score.
- Render speed ~100 ms/frame at 1080p uncontended; the pool splits the timeline into `--jobs` segments.
- MP3 joint stereo smears the binaural beat: the WAV is the listening copy. The 160 kbps MP3 is committed; WAVs are gitignored.
- The mock pages (`--mock`) are stand-ins for testing only; the real build must never use them.
- Open question from the brief: total length (27.6 min vs the 18–24 target). Scaling all bar targets by 0.8 would land in range.

## 6. Battery (current build)

| 1 | I. HERBAL (Language A) | H | f10r, f21v, f32r, f43r, f53v, f95r2 (129) | 225.0 | BLUE_BELL window bars 39–47 (the f16v position). |
| 2 | II. ZODIAC (the year) | A, Z, C | f67v1, f70r1, f72v3 (32) | 147.0 | YEAR_CLOCK enters at bar 79, ends bar 146.4. |
| 3 | III. BIOLOGICAL (Language B) | B | f80r (20) | 184.0 |  |
| 4 | IV. PHARMA (the jars) | P | f88r, f100r (16) | 96.0 |  |
| 5 | V. ROSETTES -> RECIPES | S, T | f85v_86r + f107v (29) | 199.9 | Part A: 9 rosette rings (f85v–86r) bars 0–60; Part B: f107v. Ends after glyph 2 of 'lol' (3 glyphs). |
| 1 | `PARAGRAPH_VOICE` | 1 | 46 | plucked/keyed mono lead. The transcription itself, glyph = 16th. |
| 2 | `LABEL_HITS` | 2 | 12 | dry mallet, staccato. One hit per label word, bursty spacing. |
| 3 | `ROOT_BASS` | 3 | 32 | sub/low bass, one long note per paragraph (the isolated opening word). |
| 4 | `GREEN_PAD` | 4 | 89 | the workhorse wash: it is SUPPOSED to be everywhere. D4/F4 never sound. |
| 5 | `BLUE_BELL` | 5 | 9 | one precious bell. Do not add notes: scarcity is the instrument. |
| 6 | `YEAR_CLOCK` | 6 | 115 | dry, metronomic, un-produced woodblock. Zero humanization. |
| 7 | `ROSETTE_CANONS` | 7 | 11 | nine instances of the SAME patch (same compass), different octaves. |
| 8 | `ATMOS_CTRL` | 8 | |
| 9 | `BINAURAL_L` | 9 | 78 | pure sine, hard-panned LEFT. Carrier = the sounding root, one octave up. |
| 10 | `BINAURAL_R` | 10 | 78 | the SAME sine patch, hard-panned RIGHT, pitch-bend range ±2 semitones: carries the beat. |
| 11 | `ISOCHRONIC` | 11 | 78 | pure sine one octave above the carrier, notes ARE the gate (50% duty); velocity = painting. |
| 1 corpus check (tokens / types) | 36,906 / 8,434 (±2%) | 36,906 / 8,434 | PASS |
| 2 inertia: lag-1 autocorr of gesture lengths | > 0 (target +0.08..+0.16) | +0.063 |
| 3 burstiness B of LABEL_HITS gaps (per-movement normalized, pooled) | 0.12 .. 0.30 | +0.169 (n=42) |
| 4a paragraph-flourish rate (gallows-initial, P paragraphs) | 80% .. 92% | 91.9% (34/37) |
| 4b line-final m/g mute rate | 15% .. 21% | 17.3% (40/231) |
| 5 blue budget: total / max in one 8-bar window | <= 12 / >= 8 (C5,D5 only) | 10 / 8 | PASS |
| 6 year-clock pulses / groups | 363 in 12 = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31] | 363 in 12 = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31] |
| 7a void: 8-note pitch-class sequences shared across movements | 0 | 0 | PASS |
| 7b void: dominant->tonic root motions in GREEN_PAD | 0 | 0 | PASS |
| 7c void: final event mid-word, no trailing pad | glyph 2 of a >=3-glyph word; 0 ticks after | 'lol' glyph 2/3; 0 ticks after | PASS |
| 8 forbidden register: GREEN_PAD/ROOT_BASS notes on 62 or 65 | 0 | 0 | PASS |
| 9 MIDI integrity (reopen, PPQN 480, tempo 483,871, names, CC lanes) | all files clean | clean | PASS |
| 11 binaural: beat 2..20 Hz, carrier 60..320 Hz, R pitch-bend exact | 0 violations | 0 (beat 4.55..8.27 Hz, theta..alpha) | PASS |
| 12 isochronic: every pulse on its grid subdivision, phase-locked | 0 off-grid | 0 of 11954 | PASS |
| 10 render voynich_take_full.wav | > 10 min, peak -6..-1 dBFS, RMS > -30 dBFS | 27.6 min, peak -1.50 dBFS, RMS -17.0 dBFS, 44100 Hz 2ch | PASS |
| 1 | C5.ring | 47 | 188 | 14.62 | 8.12 | -5 | 347.5 |
| 6 | C1.ring | 33 | 151 | 11.44 | 0.0 | +2 | 282.0 |
| 8 | C4.ring | 43 | 160 | 12.62 | 8.44 | -1 | 283.8 |
| 11 | C7.ring | 35 | 164 | 12.38 | 16.0 | +1 | 283.0 |
| 14 | C8.ring | 32 | 163 | 12.12 | 15.69 | +3 | 280.1 |
| 16 | C9.ring | 29 | 144 | 10.75 | 15.25 | +0 | 283.3 |
| 20 | C6.ring | 34 | 153 | 11.62 | 7.81 | -2 | 285.5 |
| 23 | C3.ring | 36 | 162 | 12.31 | 0.38 | -3 | 286.0 |
| 27 | C2.ring | 32 | 158 | 11.81 | 0.19 | +5 | 279.0 |

## 7. Recent commits

- ddbd6ce visual/from_pdf: full-manuscript PDF -> folio-named pages with contact sheet and mapping
- 06f84a8 visual/fetch: manifest discovery via catalog record, --manifest and --images-dir fallbacks
- a688e10 Visual: cinematic page turns for the riffle (eased sequence, fold with shadow, motion blur, push-in)
- 2c6dfa4 Point the generated outputs README at the visual build
- 69396d4 Visual: Pillow-path compositor, additive word light, strip layout
- dbe6305 Add the visual build: scans read aloud in sync with the take
- d98de71 Add binaural and isochronic entrainment layers derived from the grid and page density
- b7fddb9 Recalibrate preview mix: shaped -58 dBFS noise bed, sustain envelopes, per-track RMS targets
- 18d7ded Add --wav-to option to copy the full WAV to an external path
- 184b899 Add THE VOYNICH TAKE: derived sonification build of Beinecke MS 408
- 4b0db29 Add swift-key-detection to public code
- b4ccf58 Add profile README
