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
    ap.add_argument('--wav-to', default=None, help='also copy the full uncompressed WAV to this file or directory (e.g. an external drive)')
    args = ap.parse_args()

    t0 = time.time()
    trans = os.path.join(args.data, 'vjson', 'voynich_transcriptions.json')
    used_fallback = False
    if args.fallback or not os.path.exists(trans):
        from voynich.replica import synthetic_corpus
        folios = synthetic_corpus(random.Random(SEED))
        used_fallback = True
        print('!! transcription unavailable: using the replica machine (synthetic text)')
    else:
        folios = load_corpus(trans)
    ntok, ntyp = corpus_stats(folios)
    print(f'corpus: {len(folios)} folios, {ntok} tokens, {ntyp} types')

    ros = os.path.join(args.data, 'spatial', 'rosettes')
    rings = load_rings(os.path.join(ros, 'polygons_f85v_86r.json'),
                       os.path.join(ros, 'tokens_f85v_86r.csv'),
                       os.path.join(ros, 'poly_transforms_f85v_86r.csv'))

    movements = []
    for spec in MOVEMENTS:
        m = build_movement(spec, folios, rings=rings, rng=random.Random(SEED + spec[0]))
        movements.append(m)
        pv = m.stats['paragraph_voice']
        print(f"  {m.title}: {m.length / BAR:.1f} bars, {len(m.selected_folios)}/{len(m.all_folios)} folios, "
              f"{pv['words']} words rendered, {len(m.notes)} notes")
    fixes = enforce_no_reprise(movements)
    print('reprise fixes (mirrored words):', fixes)
    total = add_drift_lanes(movements)
    print(f'total {total / BAR:.1f} bars = {total / 480 / BPM:.1f} min')

    out = args.out
    for sub in ('midi', 'automation', 'preview'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    midi_paths = []
    for m in movements:
        p = os.path.join(out, 'midi', f"{m.number:02d}_{m.slug}.mid")
        write_midi(m, p)
        midi_paths.append(p)
        write_csvs(m, os.path.join(out, 'automation'))

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
