#!/usr/bin/env python3
"""THE VOYNICH TAKE — build everything into outputs/."""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from voynich.constants import MOVEMENTS, SEED, BAR, BPM
from voynich.corpus import load_corpus, corpus_stats
from voynich.movements import build_movement, add_drift_lanes, enforce_no_reprise
from voynich.rosettes import load_rings
from voynich.midiwrite import write_midi
from voynich.automation import write_csvs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help='dir containing vjson/ and spatial/')
    ap.add_argument('--out', default=os.path.join(HERE, 'outputs'))
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--fallback', action='store_true', help='use the replica machine text')
    ap.add_argument('--no-entrainment', action='store_true', help='omit the binaural / isochronic layers')
    ap.add_argument('--band-mode', choices=['density', 'drift'], default='density',
                    help='beat frequency: glyph rate x section density (default) or one theta->beta drift across the piece')
    ap.add_argument('--wav-to', default=None, help='also copy the full uncompressed WAV to this file or directory (e.g. an external drive)')
    args = ap.parse_args()

    t0 = time.time()
    from voynich.pipeline import build_movements
    built = build_movements(args.data, band_mode=args.band_mode,
                            entrainment=not args.no_entrainment, fallback=args.fallback)
    movements, folios, used_fallback = built['movements'], built['folios'], built['used_fallback']
    ntok, ntyp = built['corpus']
    if used_fallback:
        print('!! transcription unavailable: using the replica machine (synthetic text)')
    print(f'corpus: {len(folios)} folios, {ntok} tokens, {ntyp} types')
    for m in movements:
        pv = m.stats['paragraph_voice']
        print(f"  {m.title}: {m.length / BAR:.1f} bars, {len(m.selected_folios)}/{len(m.all_folios)} folios, "
              f"{pv['words']} words rendered, {len(m.notes)} notes")
    print('reprise fixes (mirrored words):', built['fixes'])
    total = built['total']
    print(f'total {total / BAR:.1f} bars = {total / 480 / BPM:.1f} min')
    if not args.no_entrainment:
        print(f'entrainment layers compiled ({args.band_mode} mode)')

    out = args.out
    for sub in ('midi', 'automation', 'preview'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    midi_paths = []
    for m in movements:
        p = os.path.join(out, 'midi', f"{m.number:02d}_{m.slug}.mid")
        write_midi(m, p)
        midi_paths.append(p)
        write_csvs(m, os.path.join(out, 'automation'))
        if m.entrainment:
            from voynich.entrainment import write_entrainment_csv
            write_entrainment_csv(m, os.path.join(out, 'automation', f"{m.number:02d}_{m.slug}_entrainment.csv"))

    from voynich.battery import run_battery, battery_markdown
    results = run_battery(movements, folios, midi_paths, out, used_fallback,
                          render_expected=not args.no_render)
    if not args.no_render:
        from voynich.render import render_all
        render_all(movements, os.path.join(out, 'preview'))
        results = run_battery(movements, folios, midi_paths, out, used_fallback, render_expected=True)

    if args.wav_to and not args.no_render:
        import shutil
        dst = args.wav_to
        if os.path.isdir(dst):
            dst = os.path.join(dst, 'voynich_take_full.wav')
        shutil.copyfile(os.path.join(out, 'preview', 'voynich_take_full.wav'), dst)
        print('copied full WAV to', dst)

    from voynich.readme import write_readme
    write_readme(movements, results, out, used_fallback, (ntok, ntyp))
    print(battery_markdown(results))
    with open(os.path.join(out, 'battery.json'), 'w') as fh:
        json.dump(results, fh, indent=1)
    print(f'done in {time.time() - t0:.0f}s')
    return 0 if all(r['pass'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
