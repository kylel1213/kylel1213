"""Glyph -> pitch mapping by frequency rank within a corpus, plus the
inertia rule (word-length lag-1 autocorrelation +0.12 made audible)."""
from collections import Counter
from .constants import POOL, RANK_TO_IDX, PREFIXES, SUFFIXES


class RankMap:
    def __init__(self, words):
        counts = Counter(g for w in words for g in w)
        self.order = [g for g, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        self.rank = {g: i for i, g in enumerate(self.order)}
        self.pitch_of = {}
        for g, r in self.rank.items():
            if r < len(RANK_TO_IDX):
                idx = RANK_TO_IDX[r]
            else:  # glyphs rarer than the pool is wide live at the extremes
                idx = len(POOL) - 1 if (r - len(RANK_TO_IDX)) % 2 == 0 else 0
            self.pitch_of[g] = POOL[idx]

    def pitch(self, glyph):
        return self.pitch_of.get(glyph, POOL[len(POOL) - 1])

    def word_pitches(self, word):
        return [self.pitch(g) for g in word]

    def glyph_rank(self, glyph):
        return self.rank.get(glyph, len(self.order))


def pool_step(pitch, steps):
    """Move `steps` positions along the pool (clamped)."""
    if pitch in POOL:
        i = POOL.index(pitch)
    else:
        i = min(range(len(POOL)), key=lambda k: abs(POOL[k] - pitch))
    return POOL[max(0, min(len(POOL) - 1, i + steps))]


def apply_inertia(pitches, prev_mean, threshold):
    """If the gesture's mean pitch is > threshold semitones from the previous
    word's mean, transpose the whole gesture one octave toward it, provided
    every note stays inside the pool's range."""
    if prev_mean is None or not pitches:
        return pitches
    mean = sum(pitches) / len(pitches)
    if abs(mean - prev_mean) <= threshold:
        return pitches
    shift = -12 if mean > prev_mean else 12
    moved = [p + shift for p in pitches]
    if all(POOL[0] <= p <= POOL[-1] for p in moved):
        return moved
    return pitches


def stem(word):
    """Strip the longest slot-grammar prefix and suffix; fall back to the word."""
    best_p = max((p for p in PREFIXES if p and word.startswith(p)), key=len, default='')
    rest = word[len(best_p):]
    best_s = max((s for s in SUFFIXES if s and rest.endswith(s) and len(rest) > len(s)), key=len, default='')
    core = rest[:len(rest) - len(best_s)] if best_s else rest
    return core or word
