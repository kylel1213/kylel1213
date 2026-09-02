"""Fetch the public-domain Beinecke MS 408 scans (Yale IIIF) and the
Voynichese word-position data. Runs on a machine with normal internet
access (the remote build container cannot reach these hosts).

  python -m visual.fetch --data data --folios f10r,f21v,...   (or --all)

Writes data/scans/<folio>.jpg, data/scans/manifest_index.json and
data/voynichese/*.xml. Unmatched folios are listed so you can map them by
hand in data/scans/folio_map.json ({"f85v_86r": "<image url>"})."""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

MANIFEST_CANDIDATES = [
    'https://collections.library.yale.edu/manifests/2002046',
    'https://collections.library.yale.edu/manifests/2002046.json',
]
VOYNICHESE_ZIP = 'http://www.voynichese.com/1/data/folio/voynichese_data.zip'
UA = {'User-Agent': 'voynich-take/1.0 (research; public-domain scans)'}


def get(url, binary=True, retries=4):
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            return data if binary else data.decode('utf-8')
        except Exception as e:
            if k == retries - 1:
                raise
            time.sleep(2 ** k)


def _labels(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        out = []
        for x in v.values():
            out += _labels(x)
        return out
    if isinstance(v, list):
        out = []
        for x in v:
            out += _labels(x)
        return out
    return []


def norm_folio(label):
    """'f10r', 'Folio 10r', '10r', 'f85v-f86r (rosettes)' -> canonical folio id or None."""
    s = label.lower().replace(' ', '')
    if re.search(r'85v.*86r|rosett', s):
        return 'f85v_86r'
    m = re.search(r'(?<![0-9])f?(\d{1,3})([rv])(\d?)(?![0-9])', s)
    if not m:
        return None
    return f"f{int(m.group(1))}{m.group(2)}{m.group(3)}"


def index_manifest(man):
    """folio -> best-effort full-size image URL (IIIF v2 or v3)."""
    canvases = []
    if 'sequences' in man:
        for seq in man['sequences']:
            canvases += seq.get('canvases', [])
    canvases += man.get('items', [])
    out, unmatched = {}, []
    for c in canvases:
        label = ' | '.join(_labels(c.get('label', '')))
        url = None
        # v2
        for im in c.get('images', []):
            res = im.get('resource', {})
            svc = res.get('service', {})
            sid = svc.get('@id') or svc.get('id')
            url = (sid.rstrip('/') + '/full/full/0/default.jpg') if sid else res.get('@id')
        # v3
        for ap in c.get('items', []):
            for an in ap.get('items', []):
                body = an.get('body', {})
                svc = body.get('service', [])
                svc = svc[0] if isinstance(svc, list) and svc else (svc if isinstance(svc, dict) else {})
                sid = svc.get('@id') or svc.get('id')
                url = (sid.rstrip('/') + '/full/max/0/default.jpg') if sid else body.get('id')
        fid = norm_folio(label)
        if fid and url and fid not in out:
            out[fid] = {'url': url, 'label': label}
        else:
            unmatched.append({'label': label, 'url': url})
    return out, unmatched


def fetch_scans(data_dir, folios, all_folios=False):
    scans = os.path.join(data_dir, 'scans')
    os.makedirs(scans, exist_ok=True)
    idx_path = os.path.join(scans, 'manifest_index.json')
    if os.path.exists(idx_path):
        index = json.load(open(idx_path))
    else:
        man = None
        for url in MANIFEST_CANDIDATES:
            try:
                man = json.loads(get(url, binary=False))
                break
            except Exception as e:
                print('manifest failed:', url, e)
        if man is None:
            sys.exit('could not fetch the IIIF manifest; download page images by hand into data/scans/<folio>.jpg')
        matched, unmatched = index_manifest(man)
        index = {'matched': matched, 'unmatched': unmatched}
        json.dump(index, open(idx_path, 'w'), indent=1)
        print(f'manifest: {len(matched)} folios matched, {len(unmatched)} canvases unmatched (see manifest_index.json)')
    manual_path = os.path.join(scans, 'folio_map.json')
    manual = json.load(open(manual_path)) if os.path.exists(manual_path) else {}
    want = list(index['matched'].keys()) if all_folios else folios
    missing = []
    for f in want:
        dst = os.path.join(scans, f + '.jpg')
        if os.path.exists(dst) and os.path.getsize(dst) > 10000:
            continue
        url = manual.get(f) or index['matched'].get(f, {}).get('url')
        if not url:
            missing.append(f)
            continue
        print('fetching', f, url)
        try:
            data = get(url)
        except Exception as e:
            # some servers reject /full/full; try a bounded size
            alt = re.sub(r'/full/(full|max)/', '/full/3000,/', url)
            print('  retry', alt, '(', e, ')')
            data = get(alt)
        with open(dst, 'wb') as fh:
            fh.write(data)
    if missing:
        print('NOT FOUND in manifest (add to data/scans/folio_map.json):', missing)
    return missing


def fetch_voynichese(data_dir):
    dst = os.path.join(data_dir, 'voynichese')
    if os.path.isdir(dst) and any(n.endswith('.xml') for n in os.listdir(dst)):
        return
    os.makedirs(dst, exist_ok=True)
    print('fetching', VOYNICHESE_ZIP)
    data = get(VOYNICHESE_ZIP)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(dst)
    print('voynichese data extracted to', dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--folios', default='', help='comma-separated folio ids (default: from outputs/visual/cues.json)')
    ap.add_argument('--all', action='store_true', help='fetch every folio in the manifest (needed for the riffle)')
    args = ap.parse_args()
    folios = [f for f in args.folios.split(',') if f]
    if not folios and not args.all:
        cues = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'outputs', 'visual', 'cues.json')
        if os.path.exists(cues):
            folios = json.load(open(cues))['needed_folios']
    fetch_voynichese(args.data)
    fetch_scans(args.data, folios, all_folios=args.all)


if __name__ == '__main__':
    main()
