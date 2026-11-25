"""Layout-aware candidates for the special tables in volume 3 of this PDF edition.

Cells are documentary evidence, not validated clinical recommendations.
"""

import re
import unicodedata
from collections import defaultdict
from itertools import product

import pdfplumber

from cie10.common import CODE_REF, code_references, normalize, provenance
from cie10.processing.extract import is_visible, is_watermark

VERSION = "7"
VERIFIED_HEADWORD_ALIASES = {
    'v3-p355-l55': ('útero o cuello uterino', 'útero'),
    'v3-p164-l29': ('medicamentos y drogas', 'medicamentos'),
    # Address variants checked against the printed destinations in this PDF.
    # They change navigation only; neither source labels nor codes are edited.
    'v3-p331-l19': ('izquierda', 'izquierdo'),
    'v3-p536-l69': ('ganglios linfáticos', 'ganglio linfático'),
    'v3-p360-l68': ('vasos', 'vaso'),
    'v3-p220-l71': ('mariscos', 'marisco'),
    'v3-p466-l109': ('membranas', 'membrana'),
    'v3-p196-l58': ('venoso intracraneal o intrarraquídea', 'venoso intracraneal'),
    'v3-p483-l111': ('congénito', 'congénita'),
    'v3-p155-l79': ('genitales', 'genital'),
    'v3-p59-l65': ('alimento', 'alimentos'),
    'v3-p199-l58': ('aórtica', 'aorta'),
    'v3-p228-l69': ('sacroilíaca', 'sacroilíaco'),
    'v3-p437-l32': ('experiencias negativas en la infancia', 'experiencias negativas'),
    'v3-p503-l93': ('por o debido a', 'por'),
    'v3-p518-l55': ('tubulointersticiales', 'tubulointersticial'),
    'v3-p309-l67': ('atención o instalaciones médicas', 'instalaciones médicas'),
    'v3-p29-l101': ('de la madre que afecta al feto o al recién nacido',
                    ('de la madre', 'de la madre que afecta al feto')),
    'v3-p435-l29': ('Presentación fetal', 'Presentación'),
    'v3-p631-l62': ('durante atención médica o quirúrgica', 'durante atención'),
    'v3-p632-l76': ('objeto extraño dejado en el organismo', 'objeto'),
    'v3-p164-l91': ('sustancia', 'sustancias'),
    'v3-p164-l103': ('radiactiva', 'radiactivas'),
    'v3-p243-l87': ('múltiple', 'múltiple NCOP'),
    'v3-p63-l69': ('aplásica, aplástica', 'aplástica'),
    'v3-p158-l120': ('miocárdica, miocardio', 'miocardio'),
    'v3-p538-l96': ('pulmón, pulmonar', 'pulmonar'),
    'v3-p287-l25': ('abdomen, abdominal', 'abdominal'),
    'v3-p287-l94': ('hiato, hiatal', 'hiatal'),
    'v3-p198-l32': ('vírica, viral, virus', 'viral'),
    'v3-p219-l62': ('viral, vírica', 'vírica'),
    'v3-p386-l21': ('viral, vírica, virus', 'vírica'),
    'v3-p329-l2': ('corazón, cardíaca', 'cardíaca'),
    'v3-p331-l15': ('ventrículo, ventricular', 'ventricular'),
    'v3-p55-l22': ('vómitos', 'vómito'),
    'v3-p171-l84': ('cuando complica el embarazo, el parto o el puerperio', 'cuando complica'),
    'v3-p295-l110': ('cuando complica el embarazo, el parto o el puerperio',
                    ('cuando complica', 'cuando complica, embarazo')),
    'v3-p70-l51': ('cromosomas, cromosómica', 'cromosoma'),
    'v3-p571-table-y4177': ('pulmón, pulmonar', 'pulmonar'),
    'v3-p394-l114': ('intestino', 'intestinal'),
    'v3-p152-l81': ('vitamina', 'vitaminas'),
    'v3-p217-l42': ('citomegálico', 'citomegálica'),
    'v3-p321-l50': ('atípicos', 'atípico'),
    'v3-p129-l81': ('válvula cardíaca', 'válvula'),
    'v3-p128-l13': ('fijación interna', 'fijación'),
    'v3-p131-l73': ('articular', 'articulación'),
    'v3-p631-l23': ('ropa', 'ropas'),
    'v3-p609-l4': ('para todo terreno o para uso fuera de la carretera',
                   ('para todo terreno', 'para todo terreno o fuera de la carretera')),
    'v3-p519-l88': ('cerebro, cerebral', 'cerebral'),
    'v3-p388-l106': ('compresión nervio', 'compresión'),
    'v3-p106-l2': ('riñón, renal', 'renal'),
    'v3-p105-l69': ('Cálculo, calculosa', 'Cálculos'),
    'v3-p90-l72': ('músculo, muscular', 'muscular'),
    'v3-p600-l34': ('jinete u ocupante de vehículo de tracción animal', 'jinete'),
    'v3-p604-l29': ('jinete u ocupante de vehículo de tracción animal', 'jinete'),
    'v3-p304-l94': ('uso de medicamentos', 'uso'),
    'v3-p227-l60': ('columna vertebral', 'columna'),
    'v3-p145-l62': ('nitridoide', 'nitritoide'),
    'v3-p670-l36': ('Batería eléctrica, ácido o líquido de', 'Batería'),
    'v3-p36-l53': ('defecto, coagulación defectuosa', 'defecto, coagulación'),
    'v3-p187-l30': ('Efectos adversos', 'Efecto adverso'),
    'v3-p278-l87': ('cerebral, cerebro', 'cerebro'),
    'v3-p33-l9': ('anoxemia, anoxia', 'anoxia'),
    'v3-p44-l43': ('infantilismo, infancia, infantil', 'infancia'),
    'v3-p104-l90': ('cerebro, cerebral', 'cerebral'),
    'v3-p330-l28': ('pulmón, pulmonar', 'pulmonar'),
    'v3-p407-l118': ('espástica, espasmódica', 'espasmódica'),
}
NEOPLASM_COLUMNS = ("malignant_primary", "malignant_secondary", "in_situ", "benign", "uncertain_or_unknown_behavior")
ABORTION_COLUMNS = (
    "o03_o06_complete_or_unspecified", "o03_o06_incomplete",
    "o08_subsequent_complication", "o07_nonmedical_or_unspecified", "o07_medical",
)
DRUG_COLUMNS = ("poisoning_chapter_xix", "accidental", "intentional_self_harm",
                "undetermined", "adverse_therapeutic_use")
VERIFIED_REMISSION_DESTINATIONS = {
    # Source-specific documentary review, never approximate global matching.
    'v3-p292-l31-ref1': ('Hipercolesterolemia', 'v3-p292-l33', 'Hipercolesterolemia',
        'The other printed heading sends the reader back to the source; the substantive heading is retained.'),
    'v3-p313-l10-ref1': ('Carbunco', 'v3-p108-l43', 'Carbunco (ántrax)',
        'The source explicitly says ántrax, the parenthetical sense printed on this heading.'),
    'v3-p313-l30-ref1': ('Carbunco', 'v3-p108-l43', 'Carbunco (ántrax)',
        'The source prints Bacillus anthracis and A22.9; this heading prints A22.9 and its subtree names Bacillus anthracis.'),
    'v3-p313-l101-ref1': ('Carbunco', 'v3-p108-l43', 'Carbunco (ántrax)',
        'The source explicitly prints A22.9, also printed on this heading; the abscess sense points elsewhere.'),
    'v3-p764-l29-ref1': ('Ticloroetileno', 'v3-p764-l5', 'Tricloroetileno',
        'The literal direction omits r; the printed destination on this same PDF page is Tricloroetileno.'),
    'v3-p594-l26-ref1': ('Granulomatosis con poliangeitis', 'v3-p272-l39', 'poliangiítis',
        'Spelling differs from the printed Granulomatosis > con > poliangiítis branch.'),
    'v3-p272-l49-ref1': ('Granulomatosis, con, poliangitis', 'v3-p272-l39', 'poliangiítis',
        'Spelling differs from the destination printed on this same PDF page.'),
    'v3-p694-l39-ref1': ('Dimetilsulfóxido', 'v3-p693-l15', 'sulfóxido',
        'The compound word names the printed Dimetil > sulfóxido row; its medicinal child and all context columns remain separate.'),
}
EXACT_CODE = re.compile(r"^[A-Z]\d{2}(?:\.\d{1,2})?$|^[A-Z]\d{2}\.\s*[–-]$")
SUFFIX = re.compile(r"^\.\d$")
PREFIX = re.compile(r"^((?:[–—-]\s*)+)")
SEE = re.compile(r"\b(ver|véase)(?:\s+\(?\s*(tamb[ií][eé]n)\s*\)?,?)?\s+(.+?)(?=\)\s*(?:\(|[A-Z]\d{2}|NCOP\b|SAI\b|codifique\b|$)|\s*\(\s*(?:ver|véase)\b|\s+[–—-]\s+|$)", re.I)


def _continuation_key(path):
    from cie10.processing.volume3.index_documentary import term_label
    return tuple(re.sub(r'\s+ncop$', '', _key(term_label(p).split(',')[0])) for p in path)


def _source(page, bbox):
    source = provenance(page)
    source.update(bbox=[round(v, 2) for v in bbox], column=None)
    return source


def _base(kind, page, bbox, token):
    return {"id": f"v3-p{page['pdf_page']}-{token}", "kind": kind,
            "review_status": "pending", "warnings": [], "sources": [_source(page, bbox)],
            "usable_as_synonym": False}


def _visible_words(pdf_page):
    box = pdf_page.cropbox or pdf_page.bbox
    visible = pdf_page.filter(lambda obj: obj["object_type"] != "char" or
                              (is_visible(obj, box) and not is_watermark(obj)
                               and obj["top"] < box[3] - 22))
    return visible.extract_words(x_tolerance=1.5, y_tolerance=2)


def _rows(words, minimum, maximum):
    """Cluster words by baseline without mixing adjacent tabular rows."""
    selected = sorted((w for w in words if minimum <= w["top"] < maximum),
                      key=lambda w: (w["top"], w["x0"]))
    rows = []
    for word in selected:
        # Typeface differences can move a code by roughly one point.
        if not rows or word["top"] - rows[-1][0]["top"] > 2.6:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda w: w["x0"]) for row in rows]


def _bbox(words):
    return [min(w["x0"] for w in words), min(w["top"] for w in words),
            max(w["x1"] for w in words), max(w["bottom"] for w in words)]


def _clean_term(text):
    return normalize(re.sub(r"\.{2,}", " ", text)).strip(" .")


def _term_depth(text):
    prefix = PREFIX.match(text)
    return (len(re.findall(r"[–—-]", prefix.group(1))) if prefix else 0,
            _clean_term(text[prefix.end():] if prefix else text))


def _table_rows(page_records, source_pdf, first, last, kind):
    available = {p["pdf_page"]: p for p in page_records if first <= p["pdf_page"] <= last}
    if not available:
        return []
    result = []
    stack = ["Tumor (de)"] if kind == "neoplasm_table_row" else ["Aborto"]
    canonical = {}
    with pdfplumber.open(source_pdf, unicode_norm="NFC") as pdf:
        for number in sorted(available):
            page = available[number]
            minimum = 272 if number == 544 else 140 if number == 14 else 99 if number == 15 else 79
            maximum = 225 if number == 15 else 218 if number == 581 else 740
            boundaries = [185, 221, 255, 288, 322] if kind == "neoplasm_table_row" else [165, 205, 247, 300, 339]
            columns = NEOPLASM_COLUMNS if kind == "neoplasm_table_row" else ABORTION_COLUMNS
            for words in _rows(_visible_words(pdf.pages[number - 1]), minimum, maximum):
                cells = [[] for _ in range(6)]
                for word in words:
                    cells[sum(word["x0"] >= x for x in boundaries)].append(word)
                raw_term = normalize(" ".join(w["text"] for w in cells[0]))
                if not raw_term:
                    continue
                if re.match(r"^(?:Tumor\s*\(de\)|Aborto)[—–-]?\s*continuaci[oó]n", raw_term, re.I):
                    continue
                # Some leaders and the first code are one PDF word (e.g. p. 555).
                embedded = re.search(r"([A-Z]\d{2}(?:\.\d{1,2})?)\s*$", raw_term)
                if kind == "neoplasm_table_row" and embedded and "ver " in raw_term.lower() and not cells[1]:
                    cells[1] = [{"text": embedded.group(1), **{k: cells[0][-1][k] for k in ("x0", "x1", "top", "bottom")}}]
                    raw_term = raw_term[:embedded.start()]
                depth, fragment = _term_depth(raw_term)
                continued = bool(re.search(r"[–—-]\s*continuaci[oó]n\s*$", fragment, re.I))
                fragment = re.sub(r"[–—-]\s*continuaci[oó]n\s*$", "", fragment, flags=re.I).strip()
                if not fragment or fragment in {"♢", "#"}:
                    continue
                previous_gap = (words[0]["top"] - result[-1]["sources"][-1]["bbox"][3]
                                if result and result[-1]["sources"][-1]["pdf_page"] == number else float("inf"))
                if not depth and fragment.isdigit():
                    continue
                if (not depth and result and result[-1]["kind"] == kind and not any(cells[1:])
                        and 0 <= previous_gap <= 4):
                    # Printed line wrap, e.g. "peritoneo, / peritoneal".
                    result[-1]["term_fragment"] += " " + fragment
                    result[-1]["term_path"][-1] += " " + fragment
                    result[-1]["raw_term"] += " " + raw_term
                    result[-1]["sources"].append(_source(page, _bbox(words)))
                    if stack and stack[-1] + " " + fragment == result[-1]["term_path"][-1]:
                        stack[-1] = result[-1]["term_path"][-1]
                    continue
                # A wrapped text line can contain the row's numeric cells.
                if (not depth and result and result[-1]["kind"] == kind and any(cells[1:])
                        and 0 <= previous_gap <= 4):
                    previous = result[-1]
                    if previous["sources"][-1]["pdf_page"] == number and not any(previous["cells"].values()):
                        previous["term_fragment"] += " " + fragment
                        previous["term_path"][-1] += " " + fragment
                        previous["raw_term"] += " " + raw_term
                        previous["sources"].append(_source(page, _bbox(words)))
                        target = previous
                    else:
                        target = None
                else:
                    target = None
                if target is None:
                    if depth == 0:
                        # Not a term of this table.
                        continue
                    ancestors = stack[:depth]
                    if len(ancestors) < depth:
                        ancestors += ["[missing_ancestor]"] * (depth - len(ancestors))
                    target = _base(kind, page, _bbox(words), f"table-y{round(words[0]['top'] * 10)}")
                    target.update(depth=depth, ancestors=ancestors, term_fragment=fragment,
                                  term_path=ancestors + [fragment], raw_term=raw_term,
                                  cells={name: None for name in columns},
                                  code_references=[], is_continuation=continued)
                    if continued:
                        target["warnings"].append("page_continuation_heading")
                    if "[missing_ancestor]" in ancestors:
                        target["warnings"].append("missing_ancestor")
                    key = _continuation_key(target["term_path"])
                    if continued:
                        if key in canonical:
                            target["continuation_of"] = canonical[key]
                        else:
                            target["warnings"].append("continuation_target_not_found")
                    else:
                        canonical[key] = target["id"]
                    result.append(target)
                    if not continued or stack[:depth + 1] != ancestors + [fragment]:
                        stack = ancestors + [fragment]
                for index, name in enumerate(columns, 1):
                    if not cells[index]:
                        continue
                    value = normalize(" ".join(w["text"] for w in cells[index]))
                    valid = bool(EXACT_CODE.fullmatch(value)) if kind == "neoplasm_table_row" else bool(SUFFIX.fullmatch(value))
                    target["cells"][name] = {"text": value, "source": _source(page, _bbox(cells[index])),
                                            "valid_shape": valid}
                    if not valid:
                        target["warnings"].append(f"invalid_cell_{name}")
                    elif kind == "neoplasm_table_row":
                        target["code_references"].append(value)
                    else:
                        family = "O03–O06" if index <= 2 else "O08" if index == 3 else "O07"
                        target["cells"][name]["code_family"] = family
                        if family == "O03–O06":
                            target["cells"][name]["category_scope"] = ["O03", "O04", "O05", "O06"]
                        if family != "O03–O06":
                            target["code_references"].append(family + value)
                target["code_references"] = list(dict.fromkeys(target["code_references"]))
                if kind == "abortion_table_row":
                    target["code_family_references"] = ["O03", "O04", "O05", "O06", "O08", "O07"]
    return result


def parse_neoplasm_table(page_records, source_pdf):
    return bind_reviewed_table_wraps(_table_rows(page_records, source_pdf, 544, 581, "neoplasm_table_row"))


def bind_reviewed_table_wraps(rows):
    """Keep both physical rows and cells, but locate a wrapped see-address."""
    from cie10.processing.volume3.index_structure import SOURCE_SHA256
    byid={r['id']:r for r in rows}
    heading=byid.get('v3-p545-table-y4509')
    directive=byid.get('v3-p545-table-y4601')
    if (heading and directive
        and heading.get('raw_term')=='– ariepiglótico, aritenoepiglótico (pliegue)'
        and directive.get('raw_term')=='– ver Tumor, pliegue, ariepiglótico'
        and not any(heading['cells'].values()) and not any(directive['cells'].values())
        and all(s.get('source_sha256')==SOURCE_SHA256 for r in (heading,directive) for s in r.get('sources',[]))):
        directive['continuation_of']=heading['id']
        directive['term_path']=heading['term_path'][:]
        directive['ancestors']=heading['ancestors'][:]
        directive['documentary_segmentation']={'method':'visually_verified_wrapped_table_remission',
          'source_literal_preserved':True,'physical_row_id_preserved':True,'no_code_inherited':True}
    return rows


def parse_abortion_table(page_records, source_pdf):
    return _table_rows(page_records, source_pdf, 14, 15, "abortion_table_row")


TRANSPORT_COLUMNS = (
    "pedestrian_or_animal", "pedal_cycle", "two_or_three_wheeled_motor_vehicle",
    "car_pickup_or_van", "heavy_transport_or_bus", "other_motor_vehicle",
    "train_or_rail_vehicle", "other_nonmotor_vehicle", "fixed_or_stationary_object",
    "noncollision_accident", "other_or_unspecified_accident",
)
TRANSPORT_ROWS = (
    (173, "Peatón"), (191, "Ciclista"), (210, "Motociclista"),
    (246, "Ocupante de vehículo de tres ruedas"), (265, "Ocupante de automóvil"),
    (283, "Ocupante de camioneta o furgoneta"),
    (302, "Ocupante de vehículo de transporte pesado"), (311, "Ocupante de autobús"),
    (329, "Ocupante de vehículo de tracción animal"),
)
TRANSPORT_TOKEN = re.compile(r"\(?[A-Z]\d{2}(?:\.(?:\d+|[–-]))?\)?|(?<!\.)–")


def parse_transport_matrix(page_records, source_pdf):
    page = next((p for p in page_records if p["pdf_page"] == 605), None)
    if page is None:
        return []
    with pdfplumber.open(source_pdf, unicode_norm="NFC") as pdf:
        sheet = pdf.pages[604]
        box = sheet.cropbox or sheet.bbox
        chars = [c for c in sheet.chars if not c["upright"] and c["text"].strip()
                 and is_visible(c, box) and not is_watermark(c)]
    bands = defaultdict(list)
    for char in chars:
        bands[round(char["x0"])].append(char)
    records = []
    for x, label in TRANSPORT_ROWS:
        row_chars = bands.get(x, [])
        if not row_chars:
            continue
        row_chars.sort(key=lambda c: -c["top"])
        raw = "".join(c["text"] for c in row_chars)
        tokens = TRANSPORT_TOKEN.findall(raw)
        # Row labels may start with a dash. The final 11 tokens are table cells.
        tokens = tokens[-11:]
        record = _base("transport_matrix_row", page,
                       [min(c["x0"] for c in row_chars), min(c["top"] for c in row_chars),
                        max(c["x1"] for c in row_chars), max(c["bottom"] for c in row_chars)],
                       f"matrix-x{x}")
        record.update(victim_mode=label, raw_rotated_text=raw,
                      columns={name: (tokens[i] if i < len(tokens) and tokens[i] != "–" else None)
                               for i, name in enumerate(TRANSPORT_COLUMNS)},
                      code_references=[t.strip("()") for t in tokens if t != "–"],
                      source_orientation="rotated_90_degrees")
        if len(tokens) != 11:
            record["warnings"].append("matrix_cell_count_mismatch")
        records.append(record)
    return records


def special_table_metadata(page_records):
    """Keep the printed headings and explanatory prose beside extracted cells."""
    pages = {p["pdf_page"]: p for p in page_records}
    specs = (
        ("abortion", 14, [14, 15], ABORTION_COLUMNS, 140),
        ("neoplasm", 544, list(range(544, 582)), NEOPLASM_COLUMNS, 272),
        ("transport_matrix", 605, [605], TRANSPORT_COLUMNS, 160),
        ("drug", 654, list(range(654,774)), DRUG_COLUMNS, 140),
    )
    result = []
    for name, lead, range_pages, columns, cutoff in specs:
        if lead not in pages:
            continue
        page = pages[lead]
        lines = [line for line in page["lines"] if line["bbox"][1] < cutoff]
        record = _base("special_table_metadata", page, page["crop_bbox"], f"{name}-metadata")
        record.update(table=name, pdf_pages=range_pages, columns=list(columns),
                      header_fragments=[{"text": line["text"], "source": provenance(page, line)}
                                        for line in lines],
                      executable_rule=False)
        result.append(record)
    return result


def _key(text):
    text = unicodedata.normalize("NFD", text.casefold())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Nested optional modifiers must disappear together, not leave a suffix
    # from the outer parenthesis in the lookup key.
    while re.search(r'\([^()]*\)', text):
        text = re.sub(r'\([^()]*\)', '', text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _path_aliases(path):
    """Literal printed headwords/inflections, never inferred medical synonyms."""
    from cie10.processing.volume3.index_documentary import term_label
    variants = []
    for position,segment in enumerate(path):
        label = term_label(segment)
        texts = [(label,0), (label.split(',')[0],1)]
        # Single-word alternatives explicitly enumerated on the same label.
        words = re.sub(r'\s+NCOP$', '', label.split('(')[0].strip(),flags=re.I)
        for pos, part in enumerate(words.split(',')):
            alternatives = re.split(r'\s+[ou]\s+', part.strip())
            # A trailing qualifier ("rubéola, congénita") is not an
            # alternative headword named "congénita".
            if (pos==0 or position==0) and all(re.fullmatch(r'[\wáéíóúüñ–-]+', w.strip()) for w in alternatives):
                texts += [(w,1 if pos==0 else 2) for w in alternatives]
        # An address may explicitly name a printed optional modifier, e.g.
        # "Procedimiento quirúrgico" or "Adenomatosis, endocrina múltiple".
        base=_key(label)
        for optional in re.findall(r'\(([^()]+)\)',label):
            if (optional.strip().casefold() not in ('s','es') and len(optional)<75
                    and not CODE_REF.search(optional) and not re.search(r'\b(?:ver|véase)\b',optional,re.I)):
                texts.append((base+' '+optional,1))
        # Printed branch labels can end in a connecting preposition. Retain
        # the complete label while also exposing the shorter branch address.
        texts += [(re.sub(r'\s+(?:de|del|a|en|por|y)$','',t,flags=re.I),rank+1) for t,rank in list(texts)]
        # Parenthetical optional plural letters are part of the printed word.
        texts += [(re.sub(r'(\w)\s*\((s|es)\)', r'\1\2', t, flags=re.I),rank) for t,rank in texts]
        keys = {}
        for t, rank in texts:
            key = _key(t)
            for k,score in ((key,rank),(re.sub(r'\s+ncop$', '', key),rank+1)):
                if k: keys[k] = min(score,keys.get(k,score))
        variants.append(list(keys.items()))
    result = {}
    for parts in product(*variants):
        key = _key(', '.join(p[0] for p in parts));rank=sum(p[1] for p in parts)
        result[key] = min(rank,result.get(key,rank))
    return result


def _namespace(record):
    return record.get('section') or record.get('kind')


def _select_destinations(ids, text, source, targets, ranks):
    """Disambiguate documentary addresses; do not prefer a clinical code."""
    key=_key(text)
    ids=sorted(set(ids))
    same=[i for i in ids if _namespace(targets[i])==_namespace(source)]
    if same:ids=same
    if ids:
        minimum=min(ranks.get((key,i),0) for i in ids)
        ids=[i for i in ids if ranks.get((key,i),0)==minimum]
    # An undivided main heading is a closer address than a multi-level path
    # that happens to flatten to the same text: "Atención materna".
    from cie10.processing.volume3.index_documentary import term_label
    direct=[i for i in ids if len(targets[i].get('term_path',[]))==1
            and _key(term_label(targets[i]['term_path'][0]))==key]
    if direct:ids=direct
    if len(ids)>1:
        others=[i for i in ids if i not in (source['id'],source.get('continuation_of'))]
        if others:ids=others
    duplicates=[]
    if len(ids)>1:
        def signature(r):
            # Keep optional qualifiers in the signature. Two headwords with
            # different parenthetical senses are not documentary duplicates.
            path=tuple(normalize(term_label(p)).casefold() for p in r.get('term_path',[]))
            cells=tuple((k,c.get('text') if c else None) for k,c in r.get('cells',{}).items())
            directives=tuple(m.groups() for m in SEE.finditer(r.get('text',r.get('raw_term',''))))
            return (_namespace(r),path,tuple(r.get('code_references',[])),cells,directives)
        from cie10.processing.volume3.index_structure import SOURCE_SHA256
        source_attested=all(targets[i].get('sources') and
            targets[i]['sources'][0].get('source_sha256')==SOURCE_SHA256 for i in ids)
        if source_attested and len({signature(targets[i]) for i in ids})==1:
            ids.sort(key=lambda i:(targets[i]['sources'][0]['pdf_page'],targets[i]['sources'][0].get('line_id',0) or 0,i))
            duplicates=ids[1:];ids=ids[:1]
    return ids,duplicates


def resolve_remissions(records, table_records=(), table_metadata=()):
    """Attach only unique, exact documentary targets; never inherit a target code."""
    lookup = defaultdict(set)
    ranks = {}
    attestations = {}
    targets = {r['id']: r for r in list(records) + list(table_records) + list(table_metadata)}
    for record in list(records) + list(table_records):
        path = record.get("term_path")
        if not path:
            continue
        from cie10.processing.volume3.index_documentary import term_label
        paths = [(path, [])]
        parents = record.get('ancestor_entry_refs', [])
        if len(parents) == len(path)-1 and all(i in targets for i in parents):
            paths.append(([targets[i].get('term_fragment',targets[i]['term_path'][-1]) for i in parents] + [record.get('term_fragment',path[-1])], []))
        if len(parents)==len(path)-1:
            from cie10.processing.volume3.index_structure import SOURCE_SHA256
            aliases=[];reviewed_nodes=[]
            for pos,identifier in enumerate(parents+[record['id']]):
                original=targets.get(identifier,record)
                spec=VERIFIED_HEADWORD_ALIASES.get(identifier)
                if (spec and original.get('term_fragment','').startswith(spec[0])
                    and original.get('sources') and original['sources'][0].get('source_sha256')==SOURCE_SHA256):
                    values=spec[1] if isinstance(spec[1],tuple) else (spec[1],)
                    aliases.append((original.get('term_fragment',path[pos]),)+values)
                    reviewed_nodes.append(identifier)
                else:aliases.append((original.get('term_fragment',path[pos]),))
            if reviewed_nodes:paths.extend((list(p),reviewed_nodes) for p in product(*aliases))
        else:
            # Table paths do not carry entry IDs for each ancestor; a verified
            # alias of the row itself still has its exact source identity.
            from cie10.processing.volume3.index_structure import SOURCE_SHA256
            spec=VERIFIED_HEADWORD_ALIASES.get(record['id'])
            if (spec and record.get('term_fragment','').startswith(spec[0])
                and record.get('sources') and record['sources'][0].get('source_sha256')==SOURCE_SHA256):
                values=spec[1] if isinstance(spec[1],tuple) else (spec[1],)
                paths.extend((path[:-1]+[v],[record['id']]) for v in values)
        # This abbreviation is printed repeatedly in remissions under Herida
        # abierta (PDF 284–287), including the ocular row visually checked.
        if record.get('section')=='diseases' and path[0].startswith('Herida abierta'):
            paths.append((['Herida']+path[1:], []))
        for p,reviewed_nodes in paths:
            for key,rank in _path_aliases(p).items():
                target = record.get('continuation_of') or record['id']
                if reviewed_nodes and (key,target) not in ranks:
                    attestations[key,target]=reviewed_nodes
                lookup[key].add(target)
                ranks[key,target] = min(rank,ranks.get((key,target),rank))
    edges = []
    table_ids={r['id'] for r in table_metadata}
    for record in records:
        matches = list(SEE.finditer(record.get("text", record.get("raw_term", ""))))
        if not matches:
            record["remissions"] = []
            continue
        record['remissions']=[]
        for position,match in enumerate(matches,1):
            _remission(record, match, position, lookup, edges, table_ids, targets, ranks, attestations)
        if all(e['resolution'] in ('resolved_exact','resolved_contextual_navigation','resolved_table_instruction','contextual_instruction','code_expression_preserved') for e in record['remissions']):
            record['warnings']=[w for w in record['warnings'] if w!='cross_reference_not_resolved']
    return edges


def _remission(record, match, position, lookup, edges, table_ids, targets, ranks, attestations):
        from cie10.processing.volume3.index_structure import SOURCE_SHA256
        raw_target = match.group(3).strip(" .;")
        if raw_target.count('(')>raw_target.count(')'):
            source_text=record.get('text',record.get('raw_term',''))
            if source_text[match.end():match.end()+1]==')': raw_target+=')'
        while raw_target.endswith(')') and raw_target.count(')')>raw_target.count('('):
            raw_target = raw_target[:-1].rstrip()
        code_target = bool(re.match(r"^categor[ií]as?\b", raw_target, re.I) or CODE_REF.match(raw_target))
        target_text = (raw_target if code_target else
                       re.sub(r"\s+" + CODE_REF.pattern + r".*$", "", raw_target)).strip(" .;")
        target_text = re.sub(r"\s+[–—-]\s*(?:continuaci[oó]n).*$", "", target_text, flags=re.I)
        lookup_text = re.sub(r'^primero\s+', '', target_text, flags=re.I)
        directive = "see_also" if match.group(2) else "see"
        table_target = "tabla" in target_text.casefold() or "cuadro" in target_text.casefold()
        contextual = bool(re.fullmatch(
            r'estado patol[oó]gico(?: o problema)?|condici[oó]n(?: o afecci[oó]n)?|condici[oó]n,\s*afecci[oó]n|'
            r'afecci[oó]n y sitio|naturaleza y sitio (?:de la lesi[oó]n|del traumatismo)|'
            r'(?:sitio anat[oó]mico|[oó]rgano) afectado|bajo el [oó]rgano mencionado|'
            r'(?:tipo de lesi[oó]n|sustancia) especificad[ao]|el otro componente o radical|'
            r'por (?:tipo|sitio|regi[oó]n|grado|cromosoma|[oó]rgano|nombre|miembro|articulaci[oó]n|'
            r'agente|motivo|circunstancia|raz[oó]n|complicaci[oó]n|problema|afecci[oó]n)\b.*|'
            r'Complicaciones del procedimiento en cuesti[oó]n',target_text,re.I))
        external_reference=bool(re.search(r'\bVol(?:umen)?\.?\s*1\b|\b(?:nota|glosario)\b.*\bcategor[ií]a\b',target_text,re.I))
        if external_reference:contextual=True
        table_id = ('v3-p654-drug-metadata' if re.fullmatch(r'Tabla de medicamentos y productos qu[ií]micos',target_text,re.I) else None)
        behavior = re.fullmatch(r'Tumor(?:\s*\(neoplasia\))?[,\s]+(?:por sitio,\s*)?(maligno|benigno|in situ|secundario|comportamiento incierto(?: o desconocido)?)',target_text,re.I)
        if behavior: table_id='v3-p544-neoplasm-metadata'
        if re.fullmatch(r'Tabla de accidentes de transporte terrestre',target_text,re.I):
            table_id='v3-p605-transport_matrix-metadata'
        if re.fullmatch(r'tabla en la pr[oó]xima p[aá]gina',target_text,re.I):
            following=[i for i in table_ids if targets.get(i,{}).get('sources',[{}])[0].get('pdf_page')==record['sources'][0]['pdf_page']+1]
            if len(following)==1:table_id=following[0]
        named_substance=re.fullmatch(r'Tabla de medicamentos y productos (?:qu[ií]micos|t[oó]xicos),\s*(.+)',target_text,re.I)
        if named_substance:
            substance_ids=[i for i in lookup.get(_key(named_substance[1]),()) if targets[i]['kind']=='drug_table_row']
            if len(substance_ids)==1:table_id=substance_ids[0]
        if table_id not in table_ids and (not table_id or targets.get(table_id,{}).get('kind')!='drug_table_row'): table_id=None
        target_kind = "contextual_lookup" if contextual else "table" if table_target else "code_expression" if code_target else "index_term"
        ids = sorted(lookup.get(_key(lookup_text), ())) if target_kind == "index_term" else []
        if not ids and re.match(r'^(?:las?|los?|el)\s+', target_text, re.I):
            ids = sorted(lookup.get(_key(re.sub(r'^(?:las?|los?|el)\s+', '', target_text, flags=re.I)), ()))
        method = 'literal_printed_headword_or_inflection'
        ids,duplicates=_select_destinations(ids,lookup_text,record,targets,ranks)
        if duplicates:method='identical_repeated_documentary_destination'
        reviewed=None
        spec=VERIFIED_REMISSION_DESTINATIONS.get(record['id']+f'-ref{position}')
        if spec and target_text==spec[0] and spec[1] in targets:
            from cie10.processing.volume3.index_structure import SOURCE_SHA256
            destination=targets[spec[1]]
            if (record.get('sources') and destination.get('sources')
                and record['sources'][0].get('source_sha256')==SOURCE_SHA256
                and destination['sources'][0].get('source_sha256')==SOURCE_SHA256
                and destination.get('term_fragment','').startswith(spec[2])):
                reviewed={'status':'visually_verified_documentary_destination',
                    'source_sha256':SOURCE_SHA256,'compared_target_ids':ids,
                    'finding':spec[3],'source_literal_preserved':True}
                ids=[spec[1]];method='source_specific_visual_review'
        selector = None
        navigation = None
        if not ids and not table_id and not contextual and not code_target:
            dynamic = re.search(r'\bpor (?:sitios?|regi[oó]n|tipo|grado|[oó]rgano|miembro|articulaci[oó]n|dispositivo|agente|nombre)\b', target_text, re.I)
            if dynamic:
                anchor_text = target_text[:dynamic.start()].strip(' ,;')
                anchor_ids = sorted(lookup.get(_key(anchor_text), ()))
                anchor_ids,anchor_duplicates=_select_destinations(anchor_ids,anchor_text,record,targets,ranks)
                if len(anchor_ids)==1:
                    ids = anchor_ids
                    duplicates=anchor_duplicates
                    navigation = {'instruction_literal':target_text[dynamic.start():],
                                  'missing_patient_selector':True, 'anchor_is_navigation_only':True}
        site_behavior = re.fullmatch(r'(Tumor,\s*.+),\s*(maligno|benigno|in situ|comportamiento incierto)', target_text, re.I)
        behavior_first=re.fullmatch(r'Tumor,\s*(maligno|benigno|in situ|comportamiento incierto),\s*(.+)',target_text,re.I)
        if behavior_first:
            site_behavior=re.fullmatch(r'(Tumor,\s*.+),\s*(maligno|benigno|in situ|comportamiento incierto)',
                'Tumor, '+behavior_first[2]+', '+behavior_first[1],re.I)
        if not ids and not table_id and site_behavior:
            site_ids = [i for i in lookup.get(_key(site_behavior.group(1)), ())
                        if targets[i]['kind'] == 'neoplasm_table_row']
            if site_ids:
                minimum=min(ranks.get((_key(site_behavior.group(1)),i),0) for i in site_ids)
                site_ids=[i for i in site_ids if ranks.get((_key(site_behavior.group(1)),i),0)==minimum]
            if len(site_ids) == 1:
                table_id = site_ids[0]
                literal = site_behavior.group(2).casefold()
                columns = {'maligno':['malignant_primary','malignant_secondary'], 'benigno':['benign'],
                           'in situ':['in_situ'], 'comportamiento incierto':['uncertain_or_unknown_behavior']}[literal]
                selector = {'behavior_literal':literal, 'candidate_columns':columns,
                            'site_literal':site_behavior.group(1), 'anatomic_site_or_substance_required':False,
                            'blank_cells_are_preserved':True}
        resolution = ("resolved_table_instruction" if table_id else "contextual_instruction" if contextual else "code_expression_preserved" if code_target and code_references(raw_target) else
                      "resolved_contextual_navigation" if navigation else
                      "resolved_exact" if len(ids) == 1 else "ambiguous" if ids else "unresolved")
        edge = {"id": record["id"] + f"-ref{position}", "kind": "index_remission",
                "review_status": "pending", "warnings": [],
                "source_id": record["id"], "directive": directive,
                "target_text": target_text, "target_kind": target_kind,
                "target_code_expressions": code_references(raw_target) if code_target else [],
                "resolution": resolution, "target_id": ids[0] if len(ids) == 1 else None,
                "candidate_ids": ids if len(ids) > 1 else [], "sources": record["sources"],
                "implies_clinical_equivalence": False, 'requires_case_context':contextual,
                'documentary_matching_method':method}
        if duplicates:edge['duplicate_target_ids']=duplicates
        if reviewed:edge['documentary_review']=reviewed
        elif len(ids)==1 and attestations.get((_key(lookup_text),ids[0])):
            edge['documentary_matching_method']='visually_verified_printed_address_variant'
            edge['documentary_review']={'status':'visually_verified_address_variant',
                'reviewed_heading_ids':attestations[_key(lookup_text),ids[0]],
                'source_literal_preserved':True,'no_code_inherited':True}
        if external_reference:
            edge.update(target_kind='external_document_reference',
                target_text=raw_target,
                external_document_reference={'volume':1,'instruction_literal':raw_target,
                    'code_expressions':code_references(raw_target), 'exact_note_not_resolved':True})
        if navigation:
            edge.update(target_kind='contextual_lookup', requires_case_context=True, navigation_selector=navigation)
        if code_target:
            edge['requires_case_context']=True
        if resolution in ('ambiguous','unresolved'):
            edge['resolution_issue'] = ('multiple_printed_destinations' if ids else 'literal_destination_not_found')
            # Recover an exact navigation anchor without pretending that the
            # remaining modifier has been resolved. Expose both facts.
            if not ids:
                parts=target_text.split(',')
                for end in range(len(parts)-1,0,-1):
                    prefix=', '.join(p.strip() for p in parts[:end])
                    candidates=sorted(lookup.get(_key(prefix),()))
                    same=[i for i in candidates if _namespace(targets[i])==_namespace(record)]
                    if same:candidates=same
                    if candidates:
                        minimum=min(ranks.get((_key(prefix),i),0) for i in candidates)
                        candidates=[i for i in candidates if ranks.get((_key(prefix),i),0)==minimum]
                    if len(candidates)==1:
                        edge['partial_navigation']={'anchor_id':candidates[0], 'matched_prefix':prefix,
                          'unresolved_literal':', '.join(p.strip() for p in parts[end:]),
                          'is_complete_resolution':False}
                        break
            if record.get('sources') and record['sources'][0].get('source_sha256')==SOURCE_SHA256:
                finding=None
                if re.match(r'Hepatitis,\s*viral,\s*tipo\b',target_text,re.I):
                    finding='El PDF 284 imprime A/B/C bajo «secuela de», sin encabezado «tipo». No se inventó ni se reasignó ese nivel.'
                elif target_text in ('Mastoiditis maxila, maxilar','o quiste'):
                    finding='La dirección incompleta o concatenada aparece así en el PDF 317; no es una pérdida de palabras de la extracción.'
                elif target_text=='Parálisis, cerebral, espástica':
                    finding='El PDF 407 imprime subtipos con «espástica», pero no esa rama general. Se conservan los niveles impresos.'
                elif target_text=='Paresoa':
                    finding='El PDF 407 imprime literalmente «Paresoa»; no se sustituyó automáticamente por otra entrada.'
                elif target_text=='Accidente, transporte, vehículo, para' and record['id']=='v3-p607-l82':
                    finding='La remisión termina incompleta en el PDF 607, antes de la siguiente entrada; no se completó por semejanza.'
                if finding:
                    edge['documentary_review']={'status':'source_discrepancy_preserved',
                        'finding':finding,'source_literal_preserved':True,'no_destination_invented':True}
        edge['printed_target_text']=raw_target
        record["remissions"].append(edge)
        if table_id:
            if not selector and targets.get(table_id,{}).get('cells'):
                selector={'candidate_columns':list(targets[table_id]['cells']),
                    'column_required_from_case_context':True,'anatomic_site_or_substance_required':False}
            edge.update(target_kind='table_lookup',target_id=table_id,requires_case_context=True,
                        table_selector=selector or {'behavior_literal':behavior.group(1) if behavior else None,
                                        'anatomic_site_or_substance_required':True})
        elif resolution=='resolved_exact' and targets[ids[0]].get('cells'):
            # A substance/site address locates a row, not a particular coding
            # column. The clinical/certificate context must select the column.
            edge.update(resolution='resolved_table_instruction',target_kind='table_lookup',requires_case_context=True,
                        table_selector={'candidate_columns':list(targets[ids[0]]['cells']),
                                        'column_required_from_case_context':True,
                                        'anatomic_site_or_substance_required':False})
        from cie10.processing.volume3.index_remission_review import reviewed_remission
        reviewed_remission(edge,record,targets)
        record["has_cross_reference"] = True
        if edge['resolution'] in ('resolved_exact','resolved_contextual_navigation','resolved_table_instruction','contextual_instruction','code_expression_preserved'):
            record["warnings"] = [w for w in record["warnings"] if w != "cross_reference_not_resolved"]
        elif "cross_reference_not_resolved" not in record["warnings"]:
            record["warnings"].append("cross_reference_not_resolved")
        edges.append(edge)


def independent_cell_references(values):
    # A dash at the end of one cell must never create a range with the next column.
    return list(dict.fromkeys(c for value in values.values() if value for c in code_references(value)))


def parse_drug_table(pages):
    """Read substance hierarchy and the five independent code columns."""
    records, stack, canonical = [], [], {}
    boundaries = [155, 205, 246, 282, 327]
    for page in pages:
        for line in page["lines"]:
            if line["bbox"][1] < 80 or line["max_size"] > 15:
                continue
            words = sorted((w for w in page["table_words"] if abs(w["top"] - line["bbox"][1]) < 2.7),
                           key=lambda w: w["x0"])
            cells = [[] for _ in range(6)]
            for word in words:
                cells[sum(word["x0"] >= x for x in boundaries)].append(word)
            raw_term = normalize(" ".join(w["text"] for w in cells[0]))
            if not raw_term or re.search(r"^Sustancia$|^Cap[ií]tulo", raw_term, re.I):
                continue
            values = {name: normalize(" ".join(w["text"] for w in cells[i + 1])) or None
                      for i, name in enumerate(DRUG_COLUMNS)}
            if not any(values.values()) and raw_term.casefold() in {"accidental", "suicidio", "terapéutico"}:
                continue
            depth, fragment = _term_depth(raw_term)
            continued = bool(re.search(r"[–—-]\s*continuaci[oó]n\s*$", fragment, re.I))
            fragment = re.sub(r"[–—-]\s*continuaci[oó]n\s*$", "", fragment, flags=re.I).strip()
            if not fragment:
                continue
            # An indented parenthesis continues the preceding substance row.
            from cie10.processing.volume3.index_structure import SOURCE_SHA256
            verified_wrap = (page.get('source_sha256') == SOURCE_SHA256 and page['pdf_page'] == 751 and line['id'] == 23 and fragment == 'anestésico'
                             and records and records[-1]['term_fragment'] == 'relajante muscular, músculo')
            pending_directive = bool(records and not depth
                and re.search(r'\b(?:ver|véase)(?:\s+tamb[ií][eé]n)?\s*$',records[-1]['text'],re.I)
                and page['pdf_page']-records[-1]['sources'][-1]['pdf_page'] in (0,1))
            if (records and not depth and cells[0] and (cells[0][0]["x0"] >= 37 or verified_wrap)
                    and (fragment.startswith("(") or not any(records[-1]["codes_by_context"].values()))
                    and page["pdf_page"] == records[-1]["sources"][-1]["pdf_page"]):
                previous = records[-1]
                previous["term_fragment"] += " " + fragment
                previous["term_path"][-1] += " " + fragment
                previous["text"] += " " + line["text"]
                previous["sources"].append(provenance(page, line))
                stack[-1] = previous['term_path'][-1]
                canonical[_continuation_key(previous['term_path'])] = previous['id']
                for name, value in values.items():
                    if value:
                        previous["codes_by_context"][name] = value
                previous["code_references"] = independent_cell_references(previous["codes_by_context"])
                continue
            if pending_directive:
                # The next physical line is the missing printed destination,
                # even when it returns to the first-column margin.
                previous=records[-1]
                previous['term_fragment']+=' '+fragment
                previous['term_path'][-1]+=' '+fragment
                previous['text']+=' '+line['text']
                previous['sources'].append(provenance(page,line))
                previous.setdefault('documentary_line_joining',[]).append({
                    'reason':'destination_after_incomplete_see_directive','source':provenance(page,line)})
                for name,value in values.items():
                    if value:previous['codes_by_context'][name]=value
                previous['code_references']=independent_cell_references(previous['codes_by_context'])
                stack[-1]=previous['term_path'][-1]
                canonical[_continuation_key(previous['term_path'])]=previous['id']
                continue
            ancestors = stack[:depth]
            if len(ancestors) < depth:
                ancestors += ["[missing_ancestor]"] * (depth - len(ancestors))
            record = {"id": f"v3-p{page['pdf_page']}-l{line['id']}", "kind": "drug_table_row",
                      "review_status": "pending", "warnings": [], "sources": [provenance(page, line)],
                      "usable_as_synonym": False, "text": line["text"], "term_fragment": fragment,
                      "depth": depth, "ancestors": ancestors, "term_path": ancestors + [fragment],
                      "is_continuation": continued, "codes_by_context": values,
                      "code_references": independent_cell_references(values)}
            for name, value in values.items():
                if value and not EXACT_CODE.fullmatch(value):
                    record["warnings"].append(f"invalid_cell_{name}")
            if "[missing_ancestor]" in ancestors:
                record["warnings"].append("missing_ancestor")
            key = _continuation_key(record["term_path"])
            if continued:
                if key in canonical:
                    record["continuation_of"] = canonical[key]
                else:
                    record["warnings"].append("continuation_target_not_found")
            else:
                canonical[key] = record["id"]
            stack = ancestors + [fragment]
            records.append(record)
    return records
