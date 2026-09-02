"""Standard MIDI File writer (Type 1, PPQN 480, tempo meta, named tracks)."""
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage
from .constants import PPQN, TEMPO_US, TRACKS, TRACK_CHANNEL, TRACK_PROGRAM


def write_midi(mvt, path):
    mid = MidiFile(type=1, ticks_per_beat=PPQN)
    meta = MidiTrack()
    meta.append(MetaMessage('track_name', name=f"VOYNICH_TAKE_{mvt.number:02d}", time=0))
    meta.append(MetaMessage('set_tempo', tempo=TEMPO_US, time=0))
    meta.append(MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    meta.append(MetaMessage('marker', text=mvt.title, time=0))
    for fname, sec, start, end in mvt.folio_spans:
        meta.append(MetaMessage('marker', text=f"{fname} [{sec}]", time=start))
    _to_delta(meta)
    meta.append(MetaMessage('end_of_track', time=0))
    mid.tracks.append(meta)
    for name, ch, prog in TRACKS:
        tr = MidiTrack()
        tr.append(MetaMessage('track_name', name=name, time=0))
        ch0 = ch - 1
        if prog is not None:
            tr.append(Message('program_change', channel=ch0, program=prog, time=0))
        evs = []
        for c in mvt.ccs:
            if c.track == name:
                evs.append((c.tick, 0, Message('control_change', channel=ch0, control=c.cc,
                                              value=max(0, min(127, c.value)), time=c.tick)))
        for n in mvt.notes:
            if n.track == name:
                p = max(0, min(127, n.pitch))
                evs.append((n.tick + n.dur, 1, Message('note_off', channel=ch0, note=p, velocity=0,
                                                     time=n.tick + n.dur)))
                evs.append((n.tick, 2, Message('note_on', channel=ch0, note=p,
                                              velocity=max(1, min(127, n.vel)), time=n.tick)))
        evs.sort(key=lambda e: (e[0], e[1]))
        for _, _, m in evs:
            tr.append(m)
        _to_delta(tr)
        tr.append(MetaMessage('end_of_track', time=0))
        mid.tracks.append(tr)
    mid.save(path)
    return path


def _to_delta(track):
    """Messages carry absolute ticks in .time (after the leading time=0 metas);
    convert to deltas in place."""
    last = 0
    for m in track:
        abs_t = m.time
        m.time = abs_t - last
        last = abs_t
