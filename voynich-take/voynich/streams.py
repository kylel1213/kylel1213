"""Canonical melodic streams used by both the no-reprise rule and the battery:
PARAGRAPH_VOICE is one line; each rosette ring is its own line. Order is by
tick only (stable), never by pitch, so re-pitching never reorders a stream."""

MELODIC_KINDS = ('glyph', 'mute', 'ring')


def melodic_streams(mvt):
    """Return list of (name, notes) in a fixed order."""
    out = []
    pv = [n for n in mvt.notes if n.track == 'PARAGRAPH_VOICE' and n.meta.get('kind') in MELODIC_KINDS]
    pv.sort(key=lambda n: n.tick)
    if pv:
        out.append(('PARAGRAPH_VOICE', pv))
    rings = {}
    for n in mvt.notes:
        if n.track == 'ROSETTE_CANONS' and n.meta.get('kind') == 'ring':
            rings.setdefault(n.meta['ring'], []).append(n)
    for rid in sorted(rings):
        ns = sorted(rings[rid], key=lambda n: n.tick)
        out.append((f'ROSETTE_CANONS/ring{rid}', ns))
    return out


def pc_ngrams(notes, k=8):
    pcs = [n.pitch % 12 for n in notes]
    return {tuple(pcs[i:i + k]) for i in range(len(pcs) - k + 1)}
