"""PDF -> visible, ordered lines, with coordinates and reproducible page caches."""

from collections import Counter
from importlib.metadata import version
from pathlib import Path
import re

import pdfplumber

from .common import ROOT, in_range, normalize, page_numbers, read_json, sha256, write_json

EXTRACTOR_VERSION = "2018-layout-v1"
NORMALIZATION_VERSION = "2018-lines-v3"


def normalize_page_record(record):
    """Repair reading-order artifacts using geometry, keeping original layout lines."""
    if record.get("normalization_version") == NORMALIZATION_VERSION:
        return record
    original = record.setdefault("layout_lines", record["lines"])
    bottom = record["crop_bbox"][3]
    # In volume 2 the certificate examples may contain a standalone "2"
    # near the bottom. It is body text, while the printed page lies within
    # 30 points of the page edge. Other volumes use different footer geometry.
    footer_zone = 30 if record["volume"] == 2 else 60
    footers = [line for line in original if line["text"].isdigit() and line["bbox"][1] >= bottom - footer_zone]
    if record["printed_page"] is None and len(footers) == 1:
        record["printed_page"] = footers[0]["text"]
    lines = [line for line in original if line not in footers]
    merged, consumed = {}, set()
    if record["volume"] == 1:
        for index, code in enumerate(lines):
            if not (code["start_bold"] and re.fullmatch(r"[A-Z]\d{2}(?:\.\d{1,2})?[†*]?", code["text"])):
                continue
            for neighbor in [index - 1, index + 1]:
                if neighbor < 0 or neighbor >= len(lines) or neighbor in consumed:
                    continue
                title = lines[neighbor]
                if (title["start_bold"] and "Helvetica" in title["start_font"] and
                        title["bbox"][0] > code["bbox"][2] + 10 and
                        abs(title["bbox"][1] - code["bbox"][1]) <= 4):
                    joined = dict(code)
                    joined["text"] = code["text"] + " " + title["text"]
                    joined["bbox"] = [min(code["bbox"][0], title["bbox"][0]),
                                      min(code["bbox"][1], title["bbox"][1]),
                                      max(code["bbox"][2], title["bbox"][2]),
                                      max(code["bbox"][3], title["bbox"][3])]
                    joined["merged_line_ids"] = [code["id"], title["id"]]
                    merged[min(index, neighbor)] = joined
                    consumed.update([index, neighbor])
                    break
    record["lines"] = [merged[i] if i in merged else line for i, line in enumerate(lines)
                       if i in merged or i not in consumed]
    record["text"] = "\n".join(line["text"] for line in record["lines"])
    record["normalization_version"] = NORMALIZATION_VERSION
    record["normalization_counts"] = {"footer_lines_removed": len(footers), "code_title_pairs_joined": len(merged)}
    return record


def is_watermark(char):
    # Observed diagonal training watermark, not a general deletion of large text.
    return "BookAntiqua" in char.get("fontname", "") and char.get("size", 0) > 20


def is_visible(char, box):
    return (box[0] <= (char["x0"] + char["x1"]) / 2 <= box[2]
            and box[1] <= (char["top"] + char["bottom"]) / 2 <= box[3])


def make_line(raw, column, index):
    chars = sorted((c for c in raw["chars"] if c["text"].strip()), key=lambda c: c["x0"])
    first = chars[0] if chars else {"fontname": "", "size": 0}
    fonts = Counter(c["fontname"].split("+")[-1] for c in chars)
    return {
        "id": index, "column": column, "text": normalize(raw["text"]),
        "bbox": [round(raw[k], 2) for k in ("x0", "top", "x1", "bottom")],
        "start_bold": "bold" in first["fontname"].lower(),
        "start_font": first["fontname"].split("+")[-1],
        "start_size": round(first["size"], 2),
        "max_size": round(max((c["size"] for c in chars), default=0), 2),
        "fonts": list(fonts),
    }


def extract_page(page, volume, source, config):
    number = page.page_number
    box = page.cropbox or page.bbox
    # pdfplumber can expose an adjacent spread outside the displayed crop box.
    visible = page.filter(lambda obj: obj["object_type"] != "char" or is_visible(obj, box))
    raw_text = visible.extract_text(x_tolerance=1.5, y_tolerance=2) or ""
    filtered = visible.filter(lambda obj: obj["object_type"] != "char" or not is_watermark(obj))
    header_bottom = box[1] + 30
    footer_top = box[3] - 22
    all_lines = filtered.extract_text_lines(x_tolerance=1.5, y_tolerance=2, return_chars=True)
    printed = [normalize(l["text"]) for l in all_lines
               if l["top"] >= footer_top and normalize(l["text"]).isdigit()]
    body = filtered.filter(lambda obj: obj["object_type"] != "char" or
                           header_bottom <= obj["top"] < footer_top)
    columns = volume == 3 and (in_range(number, config["index_disease_pages"])
                              or in_range(number, config["index_external_pages"]))
    regions = [(None, body)]
    if columns:
        middle = (box[0] + box[2]) / 2
        regions = [
            ("left", body.filter(lambda o: o["object_type"] != "char" or (o["x0"] + o["x1"]) / 2 < middle)),
            ("right", body.filter(lambda o: o["object_type"] != "char" or (o["x0"] + o["x1"]) / 2 >= middle)),
        ]
    lines = []
    for column, region in regions:
        for raw in region.extract_text_lines(x_tolerance=1.5, y_tolerance=2, return_chars=True):
            line = make_line(raw, column, len(lines) + 1)
            if volume == 1:
                line['glyphs'] = [{k:c[k] for k in ('text','x0','x1','top','bottom')} for c in raw['chars']]
            lines.append(line)
    words = []
    if volume == 3 and in_range(number, config["drug_table_pages"]):
        # Retain positions to distinguish the five code columns from synonyms.
        words = [{k: round(w[k], 2) if k != "text" else normalize(w[k])
                  for k in ("text", "x0", "x1", "top", "bottom")}
                 for w in body.extract_words(x_tolerance=1.5, y_tolerance=2)]
    warnings = []
    if not lines:
        warnings.append("no_body_text")
    if any("(cid:" in line["text"] or "�" in line["text"] for line in lines):
        warnings.append("unresolved_glyph")
    if len(printed) > 1:
        warnings.append("ambiguous_printed_page")
    return normalize_page_record({
        "schema_version": 1, "extractor_version": EXTRACTOR_VERSION,
        "pdfplumber_version": version("pdfplumber"), "volume": volume,
        "source_file": source.name, "source_sha256": config["sha256"],
        "pdf_page": number, "printed_page": printed[0] if len(printed) == 1 else None,
        "crop_bbox": list(box), "raw_visible_text": raw_text,
        "text": "\n".join(line["text"] for line in lines), "lines": lines, "table_words": words,
        "removed_watermark_chars": sum(is_watermark(c) for c in visible.chars),
        "outside_crop_chars": len(page.chars) - len(visible.chars), "warnings": warnings,
    })


def extract_volume(volume, config, mode, force=False):
    source = ROOT / "data" / "raw" / config["filename"]
    if not source.is_file():
        raise ValueError(f"Falta {source}. Ejecuta primero import-sources.")
    if sha256(source) != config["sha256"]:
        raise ValueError(f"La huella de {source.name} no coincide con la edición configurada.")
    numbers = page_numbers(config["pilot_pages"] if mode == "pilot" else "all", config["pages"])
    output = ROOT / "data" / "interim" / mode / f"vol{volume}"
    output.mkdir(parents=True, exist_ok=True)
    reused = 0
    with pdfplumber.open(source, unicode_norm="NFC") as pdf:
        if len(pdf.pages) != config["pages"]:
            raise ValueError(f"Cantidad inesperada de páginas: {source.name}")
        for position, number in enumerate(numbers, 1):
            path = output / f"page_{number:04d}.json"
            if path.exists() and not force:
                previous = read_json(path)
                if (previous.get("source_sha256") != config["sha256"] or
                        previous.get("extractor_version") != EXTRACTOR_VERSION or
                        previous.get("pdfplumber_version") != version("pdfplumber")):
                    raise ValueError(f"Caché incompatible: {path}. Reextrae con --force.")
                reused += 1
                if previous.get("normalization_version") != NORMALIZATION_VERSION:
                    write_json(path, normalize_page_record(previous))
            else:
                page = pdf.pages[number - 1]
                write_json(path, extract_page(page, volume, source, config))
                page.close()
            if position % 25 == 0 or position == len(numbers):
                print(f"Tomo {volume}: {position}/{len(numbers)} páginas ({reused} reutilizadas)", flush=True)
    summary = {"volume": volume, "mode": mode, "expected_pages": numbers,
               "source_sha256": config["sha256"], "extractor_version": EXTRACTOR_VERSION,
               "normalization_version": NORMALIZATION_VERSION,
               "pdfplumber_version": version("pdfplumber"), "pages": len(numbers)}
    write_json(output / "manifest.json", summary)
    return summary
