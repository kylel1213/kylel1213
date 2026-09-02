"""Load the TTLI (Takahashi) transcription of Beinecke MS 408 and structure it
as folios -> lines -> words, in manuscript order, with paragraph boundaries,
locus types and illustration types."""
import json
import os
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import List, Optional

TRANSCRIBER = 'TTLI'


def clean(rec):
    """Validated record cleaner (returns list of EVA words)."""
    rec = re.sub(r'<[^>]*>', '', rec)
    rec = re.sub(r'\{[^}]*\}', '', rec)
    rec = rec.replace('!', '').replace('*', '').replace('%', '')
    return [w for w in re.split(r'[.,\s]+', rec.strip()) if re.fullmatch(r'[a-z]+', w)]


def folio_sort_key(folio):
    """Manuscript order: number, then r before v, then panel index."""
    m = re.fullmatch(r'f(\d+)([rv])(\d*)', folio)
    if not m:
        return (10**6, folio, 0)
    return (int(m.group(1)), 0 if m.group(2) == 'r' else 1, int(m.group(3) or 0))


@dataclass
class Line:
    folio: str
    section: str
    lineno: str
    locus: str          # e.g. 'P0', 'Lz', 'Cc', 'Ri'
    locator_char: str   # '@' '*' '+' '=' '&' '~'
    words: List[str]
    para_end: bool      # raw record carried <$>
    kind: str = 'text'  # 'text' (P/C/R) or 'label' (L)
    para_start: bool = False


@dataclass
class Folio:
    name: str
    section: Optional[str]
    lines: List[Line] = field(default_factory=list)

    @property
    def text_lines(self):
        return [l for l in self.lines if l.kind == 'text']

    @property
    def label_lines(self):
        return [l for l in self.lines if l.kind == 'label']


def _illustration_type(page):
    for src in page.get('folio_notes', {}).get('sources', {}).values():
        for raw in src.get('raw_lines', []):
            m = re.search(r'\$I=(\w)', raw)
            if m:
                return m.group(1)
    return None


def load_corpus(path):
    """Return OrderedDict folio-name -> Folio, in manuscript order.
    Pages without an IVTFF $I illustration type (alternate-name duplicates)
    are dropped; they carry no TTLI text."""
    with open(path) as fh:
        data = json.load(fh)
    pages = data['pages']
    folios = OrderedDict()
    for name in sorted(pages, key=folio_sort_key):
        page = pages[name]
        sec = _illustration_type(page)
        if sec is None:
            continue
        fol = Folio(name, sec)
        # lines in transcription order (keys are numeric strings)
        for lineno in sorted(page['lines'], key=lambda k: int(k) if k.isdigit() else 10**6):
            for src in page['lines'][lineno]['sources'].values():
                if src['transcriber_id'] != TRANSCRIBER:
                    continue
                raw = src['views']['raw']['record']
                loc = src['locator']
                locus = loc['locus_type']
                words = clean(raw)
                kind = 'label' if locus.startswith('L') else 'text'
                fol.lines.append(Line(name, sec, lineno, locus,
                                      loc.get('locator_char') or '+',
                                      words, '<$>' in raw, kind))
        _mark_paragraphs(fol)
        folios[name] = fol
    return folios


def _mark_paragraphs(fol):
    """A running-text line starts a paragraph when its locator is '@' or '*'
    (IVTFF: first locus of a unit / new paragraph) or when the previous
    running-text line closed with <$>."""
    prev_end = True
    for line in fol.text_lines:
        line.para_start = (line.locator_char in '@*') or prev_end
        prev_end = line.para_end


def corpus_stats(folios):
    toks = [w for f in folios.values() for l in f.lines for w in l.words]
    return len(toks), len(set(toks))


def folios_in_sections(folios, sections):
    return [f for f in folios.values() if f.section in sections]


def all_words(folios, kinds=('text',)):
    return [w for f in folios.values() for l in f.lines if l.kind in kinds for w in l.words]


if __name__ == '__main__':
    import sys
    fols = load_corpus(sys.argv[1])
    print('folios', len(fols), 'tokens/types', corpus_stats(fols))
    secs = Counter(f.section for f in fols.values())
    print(secs)
    for sec in 'HAZCBPST':
        fs = [f for f in fols.values() if f.section == sec]
        nt = sum(len(l.words) for f in fs for l in f.text_lines)
        nP = sum(len(l.words) for f in fs for l in f.text_lines if l.locus.startswith('P'))
        nl = sum(len(l.words) for f in fs for l in f.label_lines)
        npara = sum(1 for f in fs for l in f.text_lines if l.para_start)
        nlines = sum(len(f.text_lines) for f in fs)
        print(sec, 'folios', len(fs), 'text tokens', nt, '(P only', nP, ') label tokens', nl, 'lines', nlines, 'paras', npara)
    print([f.name for f in fols.values()][:8], '...', [f.name for f in fols.values()][-8:])
