"""Pure-Python (numpy) preview synth: sine + 0.18 second harmonic, 3 ms
attack, exponential decay scaled to note length for struck/plucked tracks,
sustain envelopes for the pad and bass; CC1 -> a shaped, very quiet noise
wash; odd channels panned 20% left, even 20% right. 44.1 kHz / 16-bit.

Track gains are calibrated so each track lands at the RMS target below when
it is sounding (measured on the piece itself, see calibrate())."""
import math
import os
import wave
import numpy as np
from .constants import PPQN, BPM, TRACK_CHANNEL

SR = 44100
SEC_PER_TICK = 60.0 / BPM / PPQN
PEAK_DBFS = -1.5

# Target RMS (dBFS, while the track is sounding) BEFORE the final peak
# normalization; the normalization gain is ~+4 dB on this material.
RMS_TARGET = {'PARAGRAPH_VOICE': -25.0, 'ROSETTE_CANONS': -29.0, 'LABEL_HITS': -30.0,
              'BLUE_BELL': -28.0, 'YEAR_CLOCK': -30.0, 'ROOT_BASS': -28.0, 'GREEN_PAD': -31.0}
NOISE_RMS_DBFS = -58.0          # at CC1 = 127; the lane scales it down from there

# gain per track (linear), calibrated by calibrate(); 1.0 until calibrated
TRACK_GAIN = {'PARAGRAPH_VOICE': 0.3188, 'LABEL_HITS': 0.4682, 'ROOT_BASS': 0.2103,
              'GREEN_PAD': 0.1161, 'BLUE_BELL': 0.2542, 'YEAR_CLOCK': 0.2696,
              'ROSETTE_CANONS': 0.0932, 'ATMOS_CTRL': 0.0}
SUSTAIN_TRACKS = {'GREEN_PAD': (0.35, 0.6), 'ROOT_BASS': (0.02, 0.35)}   # attack s, release s
TRACK_DECAY = {'YEAR_CLOCK': 0.06, 'LABEL_HITS': 0.18, 'BLUE_BELL': 1.6}
RELEASE = 0.12


def _pan_gains(channel):
    pan = -0.2 if channel % 2 == 1 else 0.2
    a = (pan + 1) / 2 * math.pi / 2
    return math.cos(a), math.sin(a)


def _cc_curve(mvt, track, cc, n, default):
    evs = sorted((c.tick, c.value) for c in mvt.ccs if c.track == track and c.cc == cc)
    if not evs:
        return np.full(n, default / 127.0, dtype=np.float32)
    xs = np.array([t * SEC_PER_TICK * SR for t, _ in evs], dtype=np.float64)
    ys = np.array([v / 127.0 for _, v in evs], dtype=np.float64)
    idx = np.arange(n, dtype=np.float64)
    return np.interp(idx, xs, ys).astype(np.float32)


def _note_signal(note, n, start):
    """Return (signal, length) for one note, or (None, 0)."""
    dur_s = note.dur * SEC_PER_TICK
    if note.track in SUSTAIN_TRACKS:
        atk_s, rel_s = SUSTAIN_TRACKS[note.track]
        length = int((dur_s + rel_s * 5) * SR)
    else:
        rel_s = RELEASE
        length = int((dur_s + rel_s * 4) * SR)
    length = min(length, n - start)
    if length <= 0:
        return None, 0
    t = np.arange(length, dtype=np.float32) / SR
    f = 440.0 * 2 ** ((note.pitch - 69) / 12)
    sig = np.sin(2 * np.pi * f * t) + 0.18 * np.sin(4 * np.pi * f * t)
    held = min(length, int(dur_s * SR))
    if note.track in SUSTAIN_TRACKS:
        env = np.ones(length, dtype=np.float32)
        atk = min(held, max(1, int(atk_s * SR)))
        env[:atk] = np.linspace(0, 1, atk, dtype=np.float32)
        # a slow settle so long chords breathe rather than sit
        env[:held] *= (0.75 + 0.25 * np.exp(-t[:held] / 8.0)).astype(np.float32)
    else:
        tau = TRACK_DECAY.get(note.track, min(6.0, max(0.15, dur_s * 0.8)))
        env = np.exp(-t / tau).astype(np.float32)
        atk = min(length, int(0.003 * SR))
        env[:atk] *= np.linspace(0, 1, atk, dtype=np.float32)
    if held < length:
        env[held:] *= np.exp(-(t[held:] - t[held]) / rel_s).astype(np.float32)
    amp = (note.vel / 127.0) ** 1.5
    return sig * env * amp, length


def render_track(mvt, track, n):
    buf = np.zeros((n, 2), dtype=np.float32)
    gl, gr = _pan_gains(TRACK_CHANNEL[track])
    for note in mvt.notes:
        if note.track != track:
            continue
        start = int(note.tick * SEC_PER_TICK * SR)
        sig, length = _note_signal(note, n, start)
        if sig is None:
            continue
        buf[start:start + length, 0] += sig * gl
        buf[start:start + length, 1] += sig * gr
    return buf


def render_noise(mvt, n):
    """Pink-ish noise band-limited to ~120 Hz - 3 kHz, RMS = NOISE_RMS_DBFS at
    CC1 = 127, following the ATMOS_CTRL CC1 lane and breathing with the pad."""
    rng = np.random.default_rng(mvt.number)
    white = rng.standard_normal(n).astype(np.float32)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    shape = np.zeros_like(freqs)
    band = (freqs >= 120) & (freqs <= 3000)
    shape[band] = 1.0 / np.sqrt(freqs[band] / 120.0)          # 1/f power: pink
    lo = (freqs > 60) & (freqs < 120)
    shape[lo] = (freqs[lo] - 60) / 60.0
    hi = (freqs > 3000) & (freqs < 6000)
    shape[hi] = (6000 - freqs[hi]) / 3000.0 / np.sqrt(3000 / 120.0)
    noise = np.fft.irfft(spec * shape, n).astype(np.float32)
    noise /= (np.sqrt(np.mean(noise ** 2)) + 1e-12)
    noise *= 10 ** (NOISE_RMS_DBFS / 20)
    cc1 = _cc_curve(mvt, 'ATMOS_CTRL', 1, n, 0)
    pad_active = np.zeros(n, dtype=np.float32)
    for note in mvt.notes:
        if note.track == 'GREEN_PAD':
            s = int(note.tick * SEC_PER_TICK * SR)
            e = min(n, int((note.tick + note.dur) * SEC_PER_TICK * SR))
            pad_active[s:e] = 1.0
    g = SR // 2
    csg = np.cumsum(np.concatenate([[0.0], pad_active], dtype=np.float64))
    gate = ((csg[g:] - csg[:-g]) / g).astype(np.float32)
    gate = np.concatenate([np.zeros(g, dtype=np.float32), gate])[:n]
    bed = noise * cc1 * (0.5 + 0.5 * gate)
    out = np.empty((n, 2), dtype=np.float32)
    out[:, 0] = bed
    out[:, 1] = np.roll(bed, 997) * 0.95           # decorrelated a little
    return out


def render_movement(mvt, tail=1.5, gains=None):
    gains = gains or TRACK_GAIN
    n = int(mvt.length * SEC_PER_TICK * SR) + int(tail * SR)
    buf = np.zeros((n, 2), dtype=np.float32)
    for track, gain in gains.items():
        if gain <= 0:
            continue
        buf += render_track(mvt, track, n) * gain
    buf += render_noise(mvt, n)
    return buf


def _write_wav(path, data16):
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data16.tobytes())


def _db(x):
    return 20 * math.log10(max(x, 1e-12))


def track_stats(movements, gains=None):
    """RMS (while sounding) and peak per track over the whole piece."""
    gains = gains or TRACK_GAIN
    acc = {}
    for m in movements:
        n = int(m.length * SEC_PER_TICK * SR) + int(1.5 * SR)
        for track, gain in gains.items():
            if gain <= 0 or not any(nt.track == track for nt in m.notes):
                continue
            b = render_track(m, track, n) * gain
            e = (b ** 2).sum(axis=1)
            act = e > 1e-8
            a = acc.setdefault(track, [0.0, 0, 0.0])
            a[0] += float(e[act].sum()); a[1] += int(act.sum()); a[2] = max(a[2], float(np.abs(b).max()))
        nb = render_noise(m, n)
        a = acc.setdefault('NOISE', [0.0, 0, 0.0])
        a[0] += float((nb ** 2).sum()); a[1] += nb.shape[0]; a[2] = max(a[2], float(np.abs(nb).max()))
    return {t: (_db(math.sqrt(s / c / 2)) if c else -99.0, _db(p)) for t, (s, c, p) in acc.items()}


def calibrate(movements):
    """Derive per-track gains that put each track at RMS_TARGET."""
    unity = {t: 1.0 for t in TRACK_GAIN}
    stats = track_stats(movements, unity)
    gains = {}
    for t, g in TRACK_GAIN.items():
        if t in stats and t in RMS_TARGET:
            gains[t] = round(10 ** ((RMS_TARGET[t] - stats[t][0]) / 20), 4)
        else:
            gains[t] = 0.0 if t == 'ATMOS_CTRL' else g
    return gains, stats


def render_all(movements, outdir, mp3=True):
    os.makedirs(outdir, exist_ok=True)
    bufs = []
    peak = 0.0
    for m in movements:
        b = render_movement(m)
        bufs.append(b)
        peak = max(peak, float(np.abs(b).max()))
        print(f'  rendered {m.slug}: {b.shape[0] / SR / 60:.1f} min, peak {_db(float(np.abs(b).max())):.1f} dBFS, '
              f'rms {_db(float(np.sqrt((b ** 2).mean()))):.1f} dBFS')
    scale = (10 ** (PEAK_DBFS / 20)) / peak if peak > 0 else 1.0
    print(f'  normalization gain {_db(scale):+.1f} dB')
    full = []
    for m, b in zip(movements, bufs):
        d16 = np.clip(b * scale * 32767.0, -32768, 32767).astype('<i2')
        _write_wav(os.path.join(outdir, f'mvt{m.number}.wav'), d16)
        full.append(d16)
    full = np.concatenate(full)
    _write_wav(os.path.join(outdir, 'voynich_take_full.wav'), full)
    if mp3:
        try:
            import lameenc
            enc = lameenc.Encoder()
            enc.set_bit_rate(160); enc.set_in_sample_rate(SR); enc.set_channels(2); enc.set_quality(2)
            out = bytearray()
            step = SR * 30 * 2
            flat = full.reshape(-1)
            for i in range(0, flat.size, step):
                out += enc.encode(flat[i:i + step].tobytes())
            out += enc.flush()
            with open(os.path.join(outdir, 'voynich_take_full.mp3'), 'wb') as fh:
                fh.write(bytes(out))
        except Exception as e:  # the mp3 is a convenience copy only
            print('mp3 skipped:', e)
    return full.shape[0] / SR
