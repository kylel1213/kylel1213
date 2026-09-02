"""One entry point that builds the five movements (used by build.py and by
the visual renderer so both see the identical take)."""
import os
import random
from .constants import MOVEMENTS, SEED
from .corpus import load_corpus, corpus_stats
from .movements import build_movement, add_drift_lanes, enforce_no_reprise
from .rosettes import load_rings


def build_movements(data_dir, band_mode='density', entrainment=True, fallback=False):
    trans = os.path.join(data_dir, 'vjson', 'voynich_transcriptions.json')
    used_fallback = False
    if fallback or not os.path.exists(trans):
        from .replica import synthetic_corpus
        folios = synthetic_corpus(random.Random(SEED))
        used_fallback = True
    else:
        folios = load_corpus(trans)
    ros = os.path.join(data_dir, 'spatial', 'rosettes')
    rings = load_rings(os.path.join(ros, 'polygons_f85v_86r.json'),
                       os.path.join(ros, 'tokens_f85v_86r.csv'),
                       os.path.join(ros, 'poly_transforms_f85v_86r.csv'))
    movements = []
    for spec in MOVEMENTS:
        movements.append(build_movement(spec, folios, rings=rings, rng=random.Random(SEED + spec[0])))
    fixes = enforce_no_reprise(movements)
    total = add_drift_lanes(movements)
    if entrainment:
        from .entrainment import compile_entrainment
        g = 0
        for m in movements:
            compile_entrainment(m, band_mode, g, total)
            g += m.length
    return {'movements': movements, 'folios': folios, 'rings': rings, 'total': total,
            'fixes': fixes, 'used_fallback': used_fallback, 'corpus': corpus_stats(folios)}
