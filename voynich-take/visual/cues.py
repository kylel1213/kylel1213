"""Cue sheet: everything the renderer needs, in seconds, derived from the
built movements. Written to outputs/visual/cues.json."""
import json
from voynich.constants import PPQN, BPM, BAR, SECTION_PROFILE
from voynich.corpus import folio_sort_key

SEC_PER_TICK = 60.0 / BPM / PPQN


def t_of(tick, offset):
    return offset + tick * SEC_PER_TICK


def build_cues(built, preroll=6.0):
    movements, folios = built['movements'], built['folios']
    order = [f for f in folios]                   # manuscript order
    pos = {f: i for i, f in enumerate(order)}
    cues = {'preroll': preroll, 'bpm': BPM, 'movements': [], 'folio_spans': [], 'riffles': [],
            'words': [], 'labels': [], 'bass': [], 'pad': [], 'blue': [], 'clock': [], 'rings': [],
            'iso': [], 'lanes': {'cc1': [], 'cc11': [], 'cc74': [], 'beat_hz': []}, 'folio_order': order}
    offset = preroll
    prev_folio_index = -1
    first = True
    for m in movements:
        m_start = offset
        cues['movements'].append({'number': m.number, 'title': m.title, 'start': m_start,
                                  'end': t_of(m.length, offset), 'sections': m.sections})
        for fname, sec, s, e in m.folio_spans:
            span = {'folio': fname, 'section': sec, 'start': t_of(s, offset), 'end': t_of(e, offset), 'mvt': m.number}
            cues['folio_spans'].append(span)
            # riffle: the folios skipped between the previous sonified page and this one
            key = 'f85v' if fname == 'f85v_86r' else fname
            idx = pos.get(key, pos.get(fname, None))
            if idx is None:
                idx = prev_folio_index + 1
            skipped = order[prev_folio_index + 1: idx] if idx > prev_folio_index + 1 else []
            if first:
                skipped = order[:idx]
            lead = preroll if first else min(2.5, max(0.8, 0.09 * len(skipped)))
            cues['riffles'].append({'to': fname, 'arrive': span['start'], 'skipped': skipped, 'lead': lead})
            prev_folio_index = max(prev_folio_index, idx)
            first = False
        # words (PARAGRAPH_VOICE), grouped by wid
        words = {}
        for n in m.notes:
            if n.track == 'PARAGRAPH_VOICE' and n.meta.get('kind') in ('glyph', 'mute'):
                w = words.setdefault(n.meta['wid'], {'folio': n.meta['folio'], 'lineno': n.meta['lineno'],
                                                     'wi': n.meta['wi'], 'word': n.meta['word'], 'mvt': m.number,
                                                     'glyphs': []})
                w['glyphs'].append([round(t_of(n.tick, offset), 4), n.pitch, n.vel, round(n.dur * SEC_PER_TICK, 4),
                                    n.meta['gi'], n.meta.get('kind') == 'mute'])
            elif n.track == 'PARAGRAPH_VOICE' and n.meta.get('kind') == 'grace':
                pass
        for wid in sorted(words):
            w = words[wid]
            w['glyphs'].sort()
            w['start'] = w['glyphs'][0][0]
            w['end'] = w['glyphs'][-1][0] + w['glyphs'][-1][3]
            cues['words'].append(w)
        # dropped words (art displacing text) for ghosting
        for line in m.lines:
            for wp in line.words:
                if not wp.kept:
                    cues['words'].append({'folio': line.folio, 'lineno': line.lineno, 'wi': wp.idx_in_line,
                                          'word': wp.word, 'mvt': m.number, 'dropped': True,
                                          'start': round(t_of(wp.tick, offset), 4),
                                          'end': round(t_of(wp.tick + (len(wp.word) + 1) * PPQN // 4, offset), 4),
                                          'glyphs': []})
        for n in m.notes:
            t = round(t_of(n.tick, offset), 4)
            if n.track == 'LABEL_HITS':
                cues['labels'].append({'t': t, 'folio': n.meta['folio'], 'lineno': n.meta['lineno'],
                                       'wi': n.meta['wi'], 'word': n.meta['word'], 'vel': n.vel, 'pitch': n.pitch})
            elif n.track == 'ROOT_BASS':
                cues['bass'].append({'t': t, 'end': round(t_of(n.tick + n.dur, offset), 4), 'pitch': n.pitch,
                                     'word': n.meta.get('word')})
            elif n.track == 'BLUE_BELL':
                cues['blue'].append({'t': t, 'pitch': n.pitch, 'folio': n.meta.get('folio')})
            elif n.track == 'YEAR_CLOCK':
                cues['clock'].append({'t': t, 'group': n.meta['group'], 'pitch': n.pitch})
            elif n.track == 'ROSETTE_CANONS':
                cues['rings'].append({'t': t, 'ring': n.meta['ring'], 'ti': n.meta['ti'], 'pitch': n.pitch, 'vel': n.vel})
        for start, root, voicing in m.stats['pad_progression']:
            cues['pad'].append({'t': round(t_of(start, offset), 4), 'root': root, 'voicing': list(voicing), 'mvt': m.number})
        for c in m.ccs:
            if c.track == 'ATMOS_CTRL' and c.cc == 1:
                cues['lanes']['cc1'].append([round(t_of(c.tick, offset), 4), c.value])
            elif c.track == 'GREEN_PAD' and c.cc == 11:
                cues['lanes']['cc11'].append([round(t_of(c.tick, offset), 4), c.value])
            elif c.track == 'PARAGRAPH_VOICE' and c.cc == 74:
                cues['lanes']['cc74'].append([round(t_of(c.tick, offset), 4), c.value])
        if m.entrainment:
            for t, hz in m.entrainment['beats']:
                cues['lanes']['beat_hz'].append([round(t_of(t, offset), 4), round(hz, 3)])
            for s, e, per in m.entrainment['iso']:
                cues['iso'].append({'start': round(t_of(s, offset), 4), 'end': round(t_of(e, offset), 4),
                                    'period': round(per * SEC_PER_TICK, 5)})
        offset = t_of(m.length, offset)
    # index the clock pulses: pulse k of group g -> the g-th zodiac folio's k-th Lz label
    z = [f for f in folios.values() if f.section == 'Z']
    z.sort(key=lambda f: folio_sort_key(f.name))
    zlabels = []
    for f in z:
        labs = [(l.lineno, i, w) for l in f.label_lines if l.locus == 'Lz' for i, w in enumerate(l.words)]
        zlabels.append((f.name, labs))
    counters = {}
    for c in cues['clock']:
        g = c['group']
        k = counters.get(g, 0)
        counters[g] = k + 1
        fname, labs = zlabels[g] if g < len(zlabels) else (None, [])
        c['folio'] = fname
        if k < len(labs):
            c['lineno'], c['wi'], c['word'] = labs[k]
    cues['zodiac_folios'] = [f for f, _ in zlabels]
    cues['total'] = offset
    cues['end_word'] = movements[-1].stats.get('ending', {})
    # every folio that must be on disk
    needed = sorted({s['folio'] for s in cues['folio_spans']} | {c['folio'] for c in cues['clock'] if c.get('folio')})
    cues['needed_folios'] = needed
    cues['sections'] = {f: fol.section for f, fol in folios.items()}
    return cues


def write_cues(cues, path):
    with open(path, 'w') as fh:
        json.dump(cues, fh)
