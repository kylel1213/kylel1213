#!/usr/bin/env python3
"""Render THE VOYNICH TAKE visual: the scans, read aloud, in sync with the WAV.

  python render_video.py --data data --out outputs/visual --jobs 6
  python render_video.py --data data --start 600 --duration 40 --frames 5   (excerpt + PNG stills)
"""
import argparse
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def find_font(candidates):
    """First existing font file (the HUD fonts differ per OS); None lets PIL fall back."""
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def prepare(args):
    from voynich.pipeline import build_movements
    from visual.cues import build_cues, write_cues
    built = build_movements(args.data, band_mode=args.band_mode, entrainment=not args.no_entrainment)
    cues = build_cues(built, preroll=args.preroll)
    os.makedirs(args.out, exist_ok=True)
    write_cues(cues, os.path.join(args.out, 'cues.json'))
    return built, cues


def ensure_pages(args, built, cues):
    scans = args.scans or os.path.join(args.data, 'scans')
    voy = os.path.join(args.data, 'voynichese')
    if args.mock:
        from visual.mock import make_mock
        mock_dir = os.path.join(args.data, 'mock')
        scans = os.path.join(mock_dir, 'scans'); voy = os.path.join(mock_dir, 'voynichese')
        if not os.path.exists(os.path.join(scans, 'f85v_86r.jpg')):
            print('generating mock pages (NOT the manuscript) ...')
            detail = set(cues['needed_folios'])
            make_mock(built['folios'], built['rings'], mock_dir,
                      os.path.join(args.data, 'spatial', 'fonts', 'eva-placa.ttf'), detail)
    missing = [f for f in cues['needed_folios'] if not os.path.exists(os.path.join(scans, f + '.jpg'))]
    if missing:
        sys.exit(f'missing scans for {missing}. Run: python -m visual.fetch --data {args.data} --all  (on a machine with internet)')
    return scans, voy


def build_geometries(args, built, cues, scans, voy):
    from visual.geometry import build_geometry
    cache = os.path.join(args.out, 'geometry' + ('_mock' if args.mock else ''))
    qa = os.path.join(args.out, 'qa') if args.qa else None
    manual_path = os.path.join(args.data, 'registration_overrides.json')
    manual = json.load(open(manual_path)) if os.path.exists(manual_path) else {}
    geoms = {}
    for f in cues['needed_folios']:
        t = time.time()
        if f == 'f85v_86r':
            g = build_geometry(f, None, os.path.join(scans, f + '.jpg'), None, cache, manual=manual.get(f),
                               rings=built['rings'], qa_dir=qa)
        else:
            g = build_geometry(f, built['folios'][f], os.path.join(scans, f + '.jpg'), voy, cache,
                               manual=manual.get(f), qa_dir=qa)
        geoms[f] = g
        print(f'  geometry {f}: match {g.match_rate:.0%}, reg {g.reg}, {time.time() - t:.1f}s')
    return geoms, cache


def render_segment(job):
    """Render frames [f0, f1) to an .mp4 segment (video only)."""
    (seg_path, f0, f1, fps, W, H, cues_path, scans, geom_cache, needed, fonts, stills_dir, stills_every) = job
    import numpy as np
    from visual.render import Renderer
    from visual.geometry import build_geometry
    cues = json.load(open(cues_path))
    geoms = {}
    for f in needed:
        geoms[f] = build_geometry(f, None, os.path.join(scans, f + '.jpg'), None, geom_cache)  # cached
    r = Renderer(cues, scans, geoms, W, H, fps, fonts)
    cmd = [ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
           '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
           '-pix_fmt', 'yuv420p', seg_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    for i in range(f0, f1):
        t = i / fps
        frame = r.frame(t)
        p.stdin.write(frame.tobytes())
        if stills_dir and stills_every and (i - f0) % int(stills_every * fps) == 0:
            from PIL import Image
            Image.fromarray(frame).save(os.path.join(stills_dir, f'{t:08.2f}.png'))
    p.stdin.close()
    p.wait()
    return seg_path, f1 - f0, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--scans', default=None)
    ap.add_argument('--out', default=os.path.join(HERE, 'outputs', 'visual'))
    ap.add_argument('--audio', default=os.path.join(HERE, 'outputs', 'preview', 'voynich_take_full.wav'))
    ap.add_argument('--width', type=int, default=1920)
    ap.add_argument('--height', type=int, default=1080)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--preroll', type=float, default=6.0)
    ap.add_argument('--start', type=float, default=0.0, help='excerpt start (s, video time)')
    ap.add_argument('--duration', type=float, default=None)
    ap.add_argument('--jobs', type=int, default=max(1, mp.cpu_count() - 1))
    ap.add_argument('--frames', type=float, default=0, help='also save a PNG still every N seconds')
    ap.add_argument('--qa', action='store_true', help='write registration QA sheets')
    ap.add_argument('--mock', action='store_true', help='use generated mock pages (testing only)')
    ap.add_argument('--band-mode', default='density')
    ap.add_argument('--no-entrainment', action='store_true')
    ap.add_argument('--name', default=None)
    args = ap.parse_args()

    t_all = time.time()
    built, cues = prepare(args)
    scans, voy = ensure_pages(args, built, cues)
    geoms, geom_cache = build_geometries(args, built, cues, scans, voy)
    fonts = {'eva': os.path.join(args.data, 'spatial', 'fonts', 'eva-placa.ttf'),
             'sans': find_font(['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                                '/System/Library/Fonts/Supplemental/DejaVuSans.ttf',
                                '/System/Library/Fonts/Supplemental/Arial.ttf', '/Library/Fonts/Arial.ttf',
                                'C:/Windows/Fonts/arial.ttf']),
             'serif': find_font(['/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
                                 '/System/Library/Fonts/Supplemental/DejaVuSerif.ttf',
                                 '/System/Library/Fonts/Supplemental/Georgia.ttf',
                                 '/System/Library/Fonts/Supplemental/Times New Roman.ttf',
                                 'C:/Windows/Fonts/georgia.ttf'])}
    total = cues['total']
    start = args.start
    end = min(total, start + args.duration) if args.duration else total
    fps, W, H = args.fps, args.width, args.height
    f0, f1 = int(start * fps), int(end * fps)
    n = f1 - f0
    jobs = max(1, min(args.jobs, n // (fps * 20) or 1))
    seg_dir = os.path.join(args.out, 'segments')
    shutil.rmtree(seg_dir, ignore_errors=True)
    os.makedirs(seg_dir, exist_ok=True)
    stills = os.path.join(args.out, 'stills') if args.frames else None
    if stills:
        shutil.rmtree(stills, ignore_errors=True); os.makedirs(stills)
    bounds = [f0 + (n * k) // jobs for k in range(jobs + 1)]
    cues_path = os.path.join(args.out, 'cues.json')
    joblist = [(os.path.join(seg_dir, f'seg{k:03d}.mp4'), bounds[k], bounds[k + 1], fps, W, H, cues_path, scans,
                geom_cache, cues['needed_folios'], fonts, stills, args.frames) for k in range(jobs)]
    print(f'rendering {n} frames ({(end - start) / 60:.1f} min) at {W}x{H}@{fps} in {jobs} segment(s) ...')
    if jobs == 1:
        results = [render_segment(joblist[0])]
    else:
        with mp.Pool(jobs) as pool:
            results = pool.map(render_segment, joblist)
    for seg, nf, dt in results:
        print(f'  {os.path.basename(seg)}: {nf} frames in {dt:.0f}s ({nf / max(dt, 1e-6):.1f} fps)')
    # audio: preroll of silence + the WAV, trimmed to the excerpt
    with wave.open(args.audio) as w:
        sr, nch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        a0 = max(0, int((start - args.preroll) * sr))
        a1 = int((end - args.preroll) * sr)
        w.setpos(min(a0, w.getnframes()))
        frames = w.readframes(max(0, min(a1, w.getnframes()) - a0))
    lead = max(0.0, args.preroll - start)
    tmp_wav = os.path.join(args.out, 'segment_audio.wav')
    with wave.open(tmp_wav, 'wb') as o:
        o.setnchannels(nch); o.setsampwidth(sw); o.setframerate(sr)
        o.writeframes(b'\x00' * int(lead * sr) * nch * sw + frames)
    concat = os.path.join(seg_dir, 'list.txt')
    with open(concat, 'w') as fh:
        for seg, _, _ in results:
            fh.write(f"file '{os.path.abspath(seg)}'\n")
    name = args.name or ('voynich_take_' + (f'{W}x{H}' if not args.duration else f'excerpt_{int(start)}s') + ('_mock' if args.mock else '') + '.mp4')
    out = os.path.join(args.out, name)
    cmd = [ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', concat, '-i', tmp_wav,
           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '320k', '-shortest', '-movflags', '+faststart', out]
    subprocess.run(cmd, check=True)
    os.remove(tmp_wav)
    shutil.rmtree(seg_dir, ignore_errors=True)
    print(f'wrote {out}  ({os.path.getsize(out) / 2**20:.1f} MiB) in {(time.time() - t_all) / 60:.1f} min')


if __name__ == '__main__':
    main()
