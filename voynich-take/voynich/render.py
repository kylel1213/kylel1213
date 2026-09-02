"""Pure-Python (numpy) preview synth: sine + 0.18 second harmonic, 3 ms
attack, exponential decay scaled to note length; CC1 -> noise-washed pad
level; odd channels panned 20% left, even 20% right. 44.1 kHz / 16-bit."""
import math
import os
import wave
import numpy as np
from .constants import PPQN, BPM, TRACK_CHANNEL

SR = 44100
SEC_PER_TICK = 60.0 / BPM / PPQN
TRACK_GAIN = {'PARAGRAPH_VOICE': 0.85, 'LABEL_HITS': 0.6, 'ROOT_BASS': 0.9, 'GREEN_PAD': 0.22,
              'BLUE_BELL': 0.7, 'YEAR_CLOCK': 0.55, 'ROSETTE_CANONS': 0.38, 'ATMOS_CTRL': 0.0}
TRACK_DECAY = {'YEAR_CLOCK': 0.06, 'LABEL_HITS': 0.18, 'BLUE_BELL': 1.6}
RELEASE = 0.12
PEAK_DBFS = -1.5


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


def render_movement(mvt, tail=1.5):
    n = int(mvt.length * SEC_PER_TICK * SR) + int(tail * SR)
    buf = np.zeros((n, 2), dtype=np.float32)
    for note in mvt.notes:
        gain = TRACK_GAIN.get(note.track, 0.5)
        if gain <= 0:
            continue
        start = int(note.tick * SEC_PER_TICK * SR)
        dur_s = note.dur * SEC_PER_TICK
        tau = TRACK_DECAY.get(note.track, min(6.0, max(0.15, dur_s * 0.8)))
        length = int((dur_s + RELEASE * 4) * SR)
        length = min(length, n - start)
        if length <= 0:
            continue
        t = np.arange(length, dtype=np.float32) / SR
        f = 440.0 * 2 ** ((note.pitch - 69) / 12)
        sig = np.sin(2 * np.pi * f * t) + 0.18 * np.sin(4 * np.pi * f * t)
        env = np.exp(-t / tau)
        atk = int(0.003 * SR)
        env[:atk] *= np.linspace(0, 1, atk, dtype=np.float32)
        held = int(dur_s * SR)
        if held < length:
            env[held:] *= np.exp(-(t[held:] - t[held]) / RELEASE)
        amp = gain * (note.vel / 127.0) ** 1.5 * 0.3
        sig *= env * amp
        gl, gr = _pan_gains(TRACK_CHANNEL[note.track])
        buf[start:start + length, 0] += sig * gl
        buf[start:start + length, 1] += sig * gr
    # noise-washed pad bed from the CC1 (atmosphere) lane
    cc1 = _cc_curve(mvt, 'ATMOS_CTRL', 1, n, 0)
    rng = np.random.default_rng(mvt.number)
    noise = rng.standard_normal(n).astype(np.float32)
    k = 96
    cs = np.cumsum(np.concatenate([[0.0], noise], dtype=np.float64))
    noise = ((cs[k:] - cs[:-k]) / k).astype(np.float32)
    noise = np.concatenate([np.zeros(k, dtype=np.float32), noise])[:n]
    pad_active = np.zeros(n, dtype=np.float32)
    for note in mvt.notes:
        if note.track == 'GREEN_PAD':
            s = int(note.tick * SEC_PER_TICK * SR)
            e = min(n, int((note.tick + note.dur) * SEC_PER_TICK * SR))
            pad_active[s:e] = 1.0
    # smooth the gate
    g = 4410
    csg = np.cumsum(np.concatenate([[0.0], pad_active], dtype=np.float64))
    gate = ((csg[g:] - csg[:-g]) / g).astype(np.float32)
    gate = np.concatenate([np.zeros(g, dtype=np.float32), gate])[:n]
    bed = noise * cc1 * (0.35 + 0.65 * gate) * 0.9
    buf[:, 0] += bed
    buf[:, 1] += bed * 0.9
    return buf


def _write_wav(path, data16):
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data16.tobytes())


def render_all(movements, outdir, mp3=True):
    os.makedirs(outdir, exist_ok=True)
    bufs = []
    peak = 0.0
    for m in movements:
        b = render_movement(m)
        bufs.append(b)
        peak = max(peak, float(np.abs(b).max()))
        print(f'  rendered {m.slug}: {b.shape[0] / SR / 60:.1f} min, peak {peak:.3f}')
    scale = (10 ** (PEAK_DBFS / 20)) / peak if peak > 0 else 1.0
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
