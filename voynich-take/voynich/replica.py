"""Replica machine (§8): fallback text generator used ONLY when the
transcription cannot be fetched. Produces Folio/Line objects with the same
structure as corpus.load_corpus so the pipeline runs unchanged."""
import random
from collections import OrderedDict
from .constants import PREFIXES, PREFIX_W, SUFFIXES, SUFFIX_W
from .corpus import Folio, Line, _mark_paragraphs

SEED_TEXT = 'fachys ykal ar ataiin shol shory kor sholdy daiin ol chey chol dar shey keol'.split()
STEM_CHARS = 'aeohcklrst'


def _split(word):
    p = max((p for p in PREFIXES if p and word.startswith(p)), key=len, default='')
    rest = word[len(p):]
    s = max((s for s in SUFFIXES if s and rest.endswith(s) and len(rest) > len(s)), key=len, default='')
    core = rest[:len(rest) - len(s)] if s else rest
    return p, core, s


def _mutate(word, rng):
    p, core, s = _split(word)
    r = rng.random()
    if r < 0.42:
        p = rng.choices(PREFIXES, PREFIX_W)[0]
    elif r < 0.84:
        s = rng.choices(SUFFIXES, SUFFIX_W)[0]
    else:
        if core and rng.random() < 0.5:
            i = rng.randrange(len(core))
            core = core[:i] + rng.choice(STEM_CHARS) + core[i + 1:]
        else:
            core = core + rng.choice(STEM_CHARS)
    w = p + core + s
    return w if w else word


def synthetic_corpus(rng, layout=None):
    """layout: list of (folio_name, section, n_lines, n_labels)."""
    if layout is None:
        layout = []
        for i in range(1, 60):
            layout.append((f'f{i}r', 'H', 12, 0)); layout.append((f'f{i}v', 'H', 12, 0))
        for i in range(67, 74):
            layout.append((f'f{i}r', 'A' if i < 70 else 'Z', 3, 30)); layout.append((f'f{i}v', 'Z', 3, 30))
        for i in range(75, 85):
            layout.append((f'f{i}r', 'B', 40, 5)); layout.append((f'f{i}v', 'B', 40, 5))
        for i in range(88, 103):
            layout.append((f'f{i}r', 'P', 14, 15)); layout.append((f'f{i}v', 'P', 14, 15))
        for i in range(103, 117):
            layout.append((f'f{i}r', 'S', 45, 0)); layout.append((f'f{i}v', 'S', 45, 0))
    memory = list(SEED_TEXT)
    folios = OrderedDict()
    for name, sec, nlines, nlabels in layout:
        fol = Folio(name, sec)
        page_words = []
        above = []
        for li in range(nlines):
            n = max(3, int(rng.gauss(9, 2.5)))
            words = []
            for wi in range(n):
                r = rng.random()
                if r < 0.28 and above:
                    w = rng.choice(above)
                elif r < 0.60 and page_words:
                    w = rng.choice(page_words)
                elif r < 0.97 and memory:
                    w = rng.choice(memory)
                else:
                    w = rng.choice(SEED_TEXT)
                if rng.random() < 0.30:
                    w = _mutate(w, rng)
                if words and w == words[-1] and rng.random() < 0.75:
                    w = _mutate(w, rng)
                words.append(w)
            page_words += words
            memory += words
            if len(memory) > 4000:
                memory = memory[-4000:]
            above = words
            para_start = (li % 6 == 0)
            fol.lines.append(Line(name, sec, str(li + 1), 'P0', '@' if para_start else '+', words,
                                  para_end=(li % 6 == 5), kind='text'))
        for k in range(nlabels):
            w = rng.choice(memory)
            if rng.random() < 0.5:
                w = 'o' + _split(w)[1] + rng.choices(SUFFIXES, SUFFIX_W)[0]
            fol.lines.append(Line(name, sec, f'L{k}', 'Lz' if sec == 'Z' else 'L0', '@', [w], False, kind='label'))
        _mark_paragraphs(fol)
        folios[name] = fol
    return folios
