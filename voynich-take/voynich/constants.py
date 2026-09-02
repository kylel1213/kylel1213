"""Frozen constants: grid, pool, section profiles, measured fingerprint."""

BPM = 124
PPQN = 480
SIXTEENTH = PPQN // 4          # 120 ticks
THIRTY_SECOND = PPQN // 8      # 60 ticks
BAR = PPQN * 4                 # 1920 ticks
TEMPO_US = round(60_000_000 / BPM)   # 483871 microseconds per quarter

SEED = 408                     # Beinecke MS 408

# D Dorian pentatonic-extended pool, low to high (D2 .. D5)
POOL = [38, 41, 43, 45, 48, 50, 53, 55, 57, 60, 62, 65, 67, 69, 72, 74]
POOL_CENTER_IDX = 5            # D3
FORBIDDEN_PAD_BASS = {62, 65}  # D4, F4: reserved-white register

# rank -> pool index, alternating outward from the center
RANK_TO_IDX = []
_lo, _hi = POOL_CENTER_IDX, POOL_CENTER_IDX + 1
RANK_TO_IDX.append(POOL_CENTER_IDX)
_lo -= 1
_step = 0
while len(RANK_TO_IDX) < len(POOL):
    if _step % 2 == 0 and _hi < len(POOL):
        RANK_TO_IDX.append(_hi); _hi += 1
    elif _lo >= 0:
        RANK_TO_IDX.append(_lo); _lo -= 1
    elif _hi < len(POOL):
        RANK_TO_IDX.append(_hi); _hi += 1
    _step += 1
# => [5,6,4,7,3,8,2,9,1,10,0,11,12,13,14,15]

HUMAN_TIMING_SD = 6
HUMAN_TIMING_CLAMP = 18
VEL_BASE = 84
VEL_JITTER_SD = 7

INERTIA_THRESHOLD = 7          # semitones (mean pitch of word vs previous word)

# Track architecture: name -> (channel 1-based, GM program or None)
TRACKS = [
    ("PARAGRAPH_VOICE", 1, 46),
    ("LABEL_HITS",      2, 12),
    ("ROOT_BASS",       3, 32),
    ("GREEN_PAD",       4, 89),
    ("BLUE_BELL",       5, 9),
    ("YEAR_CLOCK",      6, 115),
    ("ROSETTE_CANONS",  7, 11),
    ("ATMOS_CTRL",      8, None),
    ("BINAURAL_L",      9, 78),    # entrainment: carrier, left ear
    ("BINAURAL_R",     10, 78),    # entrainment: carrier + beat, right ear (pitch bend, range +-2 st)
    ("ISOCHRONIC",     11, 78),    # entrainment: gated carrier one octave up
]
TRACK_CHANNEL = {n: ch for n, ch, _ in TRACKS}
TRACK_PROGRAM = {n: pg for n, _, pg in TRACKS}

# Frozen per-section pixel profile: $I -> (rel density, CC1 target, CC11 green wash)
SECTION_PROFILE = {
    'H': (0.55, 96, 110),
    'A': (0.80, 70, 40), 'Z': (0.80, 70, 40), 'C': (0.80, 70, 40),
    'B': (0.85, 80, 95),
    'P': (0.75, 76, 70),
    'S': (1.00, 30, 15), 'T': (1.00, 30, 15),
}

# Zodiac label counts per ring in manuscript order (f70v1 .. f73v): the year-clock
YEAR_CLOCK_GROUPS = [26, 37, 19, 22, 24, 32, 47, 30, 32, 34, 29, 31]
assert sum(YEAR_CLOCK_GROUPS) == 363

# Movement definitions: (number, slug, title, sections, target bars)
MOVEMENTS = [
    (1, "herbal",     "I. HERBAL (Language A)",          ['H'],           260),
    (2, "zodiac",     "II. ZODIAC (the year)",           ['A', 'Z', 'C'], 130),
    (3, "biological", "III. BIOLOGICAL (Language B)",    ['B'],           170),
    (4, "pharma",     "IV. PHARMA (the jars)",           ['P'],           110),
    (5, "rosettes",   "V. ROSETTES -> RECIPES",          ['S', 'T'],      140),
]
ROSETTE_BARS = 60
STAGGER_BARS = 16
BURSTINESS_TARGET = 0.20

# Replica-machine slot grammar (fallback only) and stem stripping
PREFIXES = ['qo', 'o', 'ch', 'sh', 'y', 'd', 's', 'k', 't', '']
PREFIX_W = [14, 22, 13, 9, 6, 7, 4, 3, 2, 20]
SUFFIXES = ['y', 'dy', 'edy', 'aiin', 'ain', 'in', 'ol', 'or', 'ar', 'al', 'am', '']
SUFFIX_W = [18, 12, 10, 14, 5, 4, 9, 7, 6, 4, 2, 9]

FINGERPRINT = {
    'tokens': 36906, 'types': 8434,
    'wordlen_lag1_autocorr': 0.12,
    'burstiness': 0.20,
    'para_gallows_rate': 0.87,
    'line_final_mg_rate': 0.182,
}
