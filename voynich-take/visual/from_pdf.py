"""Turn a full-manuscript PDF into folio-named page images for the visual.

  python -m visual.from_pdf --pdf ~/Downloads/voynich.pdf --data data --sheet
  (inspect data/pdf_pages/contact_sheet_*.jpg, fix data/pdf_pages/mapping.json)
  python -m visual.from_pdf --pdf ~/Downloads/voynich.pdf --data data --apply

Pass 1 extracts every page at native scan resolution (the embedded image
when the page is a single scan, else a 300 dpi raster), writes a contact
sheet with page numbers, and proposes a mapping page -> folio by walking
the manuscript's folio order from --first-page (the PDF page that shows
f1r). Pass 2 (--apply) copies the mapped pages to data/scans/<folio>.jpg.
The Voynichese word boxes are a separate download (visual/fetch.py)."""
import argparse
import io
import json
import os
import re
import sys
import pymupdf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from voynich.corpus import folio_sort_key   # noqa: E402

Image.MAX_IMAGE_PIXELS = None


def folio_order(data_dir):
    """Manuscript order of every folio with text, from the transcription."""
    import json as _json
    trans = os.path.join(data_dir, 'vjson', 'voynich_transcriptions.json')
    pages = _json.load(open(trans))['pages']
    names = [n for n in pages if re.fullmatch(r'f\d+[rv]\d*', n)]
    return sorted(names, key=folio_sort_key)


def extract_pages(pdf_path, out_dir, dpi=300, first=1, last=None):
    os.makedirs(out_dir, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    n = doc.page_count
    last = min(last or n, n)
    paths = []
    for i in range(first - 1, last):
        dst = os.path.join(out_dir, f'page_{i + 1:04d}.jpg')
        if os.path.exists(dst):
            paths.append(dst)
            continue
        page = doc[i]
        imgs = page.get_images(full=True)
        saved = False
        if len(imgs) == 1:                       # the page IS the scan: keep native pixels
            xref = imgs[0][0]
            info = doc.extract_image(xref)
            try:
                im = Image.open(io.BytesIO(info['image'])).convert('RGB')
                if im.size[0] >= 800:
                    im.save(dst, quality=94)
                    saved = True
            except Exception:
                saved = False
        if not saved:
            pix = page.get_pixmap(dpi=dpi)
            Image.frombytes('RGB', (pix.width, pix.height), pix.samples).save(dst, quality=94)
        paths.append(dst)
    return paths, n


def contact_sheet(paths, out_path, cols=8, cell=(220, 300), labels=None):
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cell[0], rows * (cell[1] + 24)), (20, 18, 16))
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    except Exception:
        font = ImageFont.load_default()
    for k, p in enumerate(paths):
        im = Image.open(p)
        im.thumbnail(cell)
        x = (k % cols) * cell[0]
        y = (k // cols) * (cell[1] + 24)
        sheet.paste(im, (x + (cell[0] - im.size[0]) // 2, y))
        lab = os.path.basename(p).replace('page_', 'p').replace('.jpg', '')
        if labels and labels.get(p):
            lab += '  ' + labels[p]
        dr.text((x + 4, y + cell[1] + 4), lab, font=font, fill=(230, 220, 200))
    sheet.save(out_path, quality=80)


def propose_mapping(paths, order, first_page):
    """Walk the folio order from the PDF page showing f1r. The foldouts
    (f85v-86r rosettes, f67-73 panels, f89, f101, f102) commonly appear as
    one PDF page per physical opening; those rows need checking by eye."""
    mapping = {}
    k = 0
    for i, p in enumerate(paths):
        pn = int(re.search(r'page_(\d+)', p).group(1))
        if pn < first_page or k >= len(order):
            continue
        mapping[str(pn)] = order[k]
        k += 1
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--data', required=True)
    ap.add_argument('--first-page', type=int, default=1, help='PDF page that shows f1r')
    ap.add_argument('--dpi', type=int, default=300)
    ap.add_argument('--sheet', action='store_true', help='write the contact sheet + proposed mapping')
    ap.add_argument('--apply', action='store_true', help='copy mapped pages to data/scans')
    args = ap.parse_args()
    out = os.path.join(args.data, 'pdf_pages')
    paths, n = extract_pages(args.pdf, out, dpi=args.dpi)
    print(f'{n} PDF pages extracted to {out}')
    map_path = os.path.join(out, 'mapping.json')
    order = folio_order(args.data)
    if args.sheet or not os.path.exists(map_path):
        mapping = propose_mapping(paths, order, args.first_page)
        json.dump(mapping, open(map_path, 'w'), indent=1)
        labels = {p: mapping.get(str(int(re.search(r'page_(\d+)', p).group(1))), '') for p in paths}
        for c in range(0, len(paths), 96):
            contact_sheet(paths[c:c + 96], os.path.join(out, f'contact_sheet_{c // 96 + 1:02d}.jpg'), labels=labels)
        print(f'proposed mapping written to {map_path}; check the contact sheets, then run with --apply')
    if args.apply:
        mapping = json.load(open(map_path))
        scans = os.path.join(args.data, 'scans')
        os.makedirs(scans, exist_ok=True)
        done = 0
        for pn, folio in mapping.items():
            src = os.path.join(out, f'page_{int(pn):04d}.jpg')
            if os.path.exists(src) and folio:
                Image.open(src).convert('RGB').save(os.path.join(scans, folio + '.jpg'), quality=94)
                done += 1
        print(f'{done} folios written to {scans}. Missing from the mapping: '
              f'{[f for f in order if f not in set(mapping.values())][:20]} ...')


if __name__ == '__main__':
    main()
