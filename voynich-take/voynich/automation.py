"""CC lanes derived from the frozen per-section pixel profile, plus CSV export."""
import csv
import os
from .constants import SECTION_PROFILE, BAR, SIXTEENTH, PPQN
from .events import CC

RAMP = 2 * PPQN          # 2 beats of linear interpolation at folio boundaries


def _ramp(track, cc, t0, v_from, v_to, out):
    if v_from is None or v_from == v_to:
        out.append(CC(track, t0, cc, v_to))
        return
    steps = RAMP // SIXTEENTH
    for k in range(steps + 1):
        v = round(v_from + (v_to - v_from) * k / steps)
        out.append(CC(track, t0 + k * SIXTEENTH, cc, v))


def folio_stepped_lanes(folio_spans, targets):
    """targets: list of (track, cc, index into SECTION_PROFILE tuple)."""
    out = []
    prev = {}
    for fname, sec, start, end in folio_spans:
        prof = SECTION_PROFILE[sec]
        for track, cc, idx in targets:
            v = prof[idx]
            _ramp(track, cc, start, prev.get((track, cc)), v, out)
            prev[(track, cc)] = v
    return out


def drift_lane(track, cc, mvt_start_global, mvt_length, total_length, v0=40, v1=90):
    """One continuous A->B morph across the whole piece; one point per bar."""
    out = []
    t = 0
    while t <= mvt_length:
        frac = (mvt_start_global + t) / total_length
        out.append(CC(track, t, cc, int(round(v0 + (v1 - v0) * frac))))
        t += BAR
    return out


def write_csvs(mvt, outdir):
    os.makedirs(outdir, exist_ok=True)
    lanes = {}
    for c in mvt.ccs:
        lanes.setdefault((c.track, c.cc), []).append(c)
    written = []
    for (track, cc), evs in sorted(lanes.items()):
        path = os.path.join(outdir, f"{mvt.number:02d}_{mvt.slug}_{track}_cc{cc}.csv")
        with open(path, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['time_beats', 'cc', 'value', 'track'])
            for e in sorted(evs, key=lambda e: e.tick):
                w.writerow([f"{e.tick / PPQN:.4f}", cc, e.value, track])
        written.append((path, len(evs)))
    return written
