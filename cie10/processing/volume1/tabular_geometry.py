"""Lazy per-page glyph enrichment for tabular braces; original line text is unchanged."""
import re
import pdfplumber
from cie10.common import ROOT, read_json, write_json
from cie10.processing.extract import is_visible, is_watermark, make_line

BRACE = re.compile(r'[⎫⎬⎭⎪{}]')


def geometry_pages(pages, config, mode):
    pdf = None
    try:
        for page in pages:
            if not any(BRACE.search(l['text']) for l in page['lines']):
                yield page
                continue
            path = ROOT / 'data/interim' / mode / 'vol1' / f"geometry_{page['pdf_page']:04d}.json"
            cached = read_json(path) if path.exists() else {}
            if cached.get('source_sha256') != config['sha256']:
                if pdf is None:
                    pdf = pdfplumber.open(ROOT / 'data/raw' / config['filename'], unicode_norm='NFC')
                p = pdf.pages[page['pdf_page']-1]
                box = p.cropbox or p.bbox
                body = p.filter(lambda o: o['object_type'] != 'char' or
                    (is_visible(o, box) and not is_watermark(o) and box[1]+30 <= o['top'] < box[3]-22))
                raw = body.extract_text_lines(x_tolerance=1.5,y_tolerance=2,return_chars=True)
                data = {}
                for i, line in enumerate(raw, 1):
                    data[str(i)] = dict(text=make_line(line,None,i)['text'], glyphs=[
                        {k:c[k] for k in ('text','x0','x1','top','bottom')} for c in line['chars']])
                cached = dict(source_sha256=config['sha256'], lines=data)
                write_json(path,cached)
            for line in page['lines']:
                item = cached['lines'].get(str(line['id']),{})
                if item.get('text') == line['text']:
                    line['glyphs'] = item['glyphs']
            yield page
    finally:
        if pdf is not None:
            pdf.close()
