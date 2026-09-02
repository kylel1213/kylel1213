"""Event model shared by the compiler, writer, battery and renderer."""
from dataclasses import dataclass, field


@dataclass
class Note:
    track: str
    tick: int
    dur: int
    pitch: int
    vel: int
    meta: dict = field(default_factory=dict)

    @property
    def end(self):
        return self.tick + self.dur


@dataclass
class CC:
    track: str
    tick: int
    cc: int
    value: int


@dataclass
class WordPlacement:
    word: str
    tick: int          # onset of first glyph
    kept: bool         # False = displaced by artwork (rest)
    idx_in_line: int
    n_in_line: int


@dataclass
class PlacedLine:
    folio: str
    section: str
    locus: str
    para_id: int
    para_start: bool
    start: int         # bar-aligned start
    end: int           # next barline after last event
    words: list        # WordPlacement


@dataclass
class Movement:
    number: int
    slug: str
    title: str
    sections: list
    lines: list = field(default_factory=list)      # PlacedLine
    folio_spans: list = field(default_factory=list)  # (folio_name, section, start, end)
    para_spans: list = field(default_factory=list)   # (para_id, start, end, first_word, folio)
    notes: list = field(default_factory=list)
    ccs: list = field(default_factory=list)
    length: int = 0
    stats: dict = field(default_factory=dict)
    selected_folios: list = field(default_factory=list)
    all_folios: list = field(default_factory=list)
    rankmap: object = None

    def notes_on(self, track):
        return [n for n in self.notes if n.track == track]

    def ccs_on(self, track, cc=None):
        return [c for c in self.ccs if c.track == track and (cc is None or c.cc == cc)]
