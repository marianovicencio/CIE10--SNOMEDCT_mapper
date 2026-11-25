"""Conservative structural parsers. Outputs are candidates, never a clinical gold standard."""

import re
from collections import Counter

from .common import CODE_REF, ROOT, code_references, in_range, normalize, provenance, read_json, sha256, write_json, write_jsonl
from .extract import normalize_page_record, EXTRACTOR_VERSION
from .tabular_notes import normalize_record_notes, VERSION as NOTE_VERSION
from .tabular_semantics import enrich_tabular
from .tabular_geometry import geometry_pages
from .tabular_text import classify_prose, strip_geometry
from .tabular_reviewed import reviewed_page_layout
from .tabular_review_v6 import join_detached_bullets
from .manual_semantics import enrich_manual_passages, annex_code_candidates, underlying_cause_candidates, association_blocks, VERSION as MANUAL_VERSION
from .manual_layout import attach_bold_outcomes, attach_rule_clauses, diabetes_sequence_candidates
from .volume3_special import (parse_abortion_table, parse_neoplasm_table,
                              parse_transport_matrix, parse_drug_table as parse_drug_table_layout,
                              resolve_remissions, special_table_metadata,
                              VERSION as SPECIAL_VERSION)

HEADING = re.compile(r"^([A-Z]\s*\d\s*\d(?:\s*\.\s*\d{1,2})?)(?:\s*([†*]))?(?:\s+(.*)|$)")
SECTION = re.compile(r"^([1-7](?:\.\d+){0,4})\.?\s+(.+)")
NOTE = re.compile(r"^(Incluye|Excluye|Nota|Notas)\s*:\s*(.*)$", re.I)
INSTRUCTION = re.compile(r"^(Use|Utilice|Codifique|Véase|Ver también|Ver |Para uso|Las siguientes subdivisiones)", re.I)
PREFIX = re.compile(r"^((?:[–—-]\s*)+)")
BRACES = re.compile(r"[⎫⎬⎭⎪{}]")
INDEX_VERSION = "3-" + SPECIAL_VERSION


def base_record(kind, page, line):
    return {"id": f"v{page['volume']}-p{page['pdf_page']}-l{line['id']}",
            "kind": kind, "review_status": "pending", "warnings": [],
            "sources": [provenance(page, line)]}


def parse_tabular(pages):
    records = []
    current = None
    active_note = None
    context_id = None
    description_open = False
    previous_page = None
    note_block = None
    definition = None
    definition_mode = False

    def fragment(text, page, line):
        result = {"text": text, "source": provenance(page, line), "block_id": note_block}
        if line.get('glyphs'):
            result['glyphs'] = line['glyphs']
        return result

    def finish():
        nonlocal current, definition, definition_mode
        if current:
            current["description"] = normalize(current["description"])
            current["code_references"] = code_references("\n".join(current["raw_lines"]))
            if BRACES.search("\n".join(current["raw_lines"])):
                current["warnings"].append("brace_group_requires_visual_review")
            if re.search(r"\b[A-Z][lIO]\d\.\d", "\n".join(current["raw_lines"])):
                current["warnings"].append("suspected_code_glyph_error_not_corrected")
            if current["kind"] == "code" and not current["description"]:
                current["warnings"].append("empty_description")
            normalize_record_notes(current)
            from .tabular_definitions import normalize_definitions
            normalize_definitions(current)
            classify_prose(current)
            strip_geometry(current)
            records.append(current)
        current = None
        definition = None
        definition_mode = False

    def new(kind, page, line, description):
        return dict(base_record(kind, page, line), description=description, raw_lines=[line["text"]],
                    inclusions=[], exclusions=[], instructions=[], notes=[], unclassified=[], context_ref=context_id)

    for page in pages:
        page = reviewed_page_layout(page)
        page = join_detached_bullets(page)
        if previous_page is not None and page["pdf_page"] != previous_page + 1:
            if current:
                current["warnings"].append("non_contiguous_source_pages")
            finish()
            context_id = None
            active_note = None
            note_block = None
            description_open = False
        previous_page = page["pdf_page"]
        for line in page["lines"]:
            text = line["text"]
            if re.match(r"^Las siguientes subdivisiones de cuarto", text, re.I):
                finish()
                current = new("shared_subdivision_scheme", page, line, text)
                active_note = "notes"
                note_block = current["id"]
                description_open = False
                continue
            match = HEADING.match(text)
            is_code = match and line["start_bold"] and line["start_size"] >= 9
            # Chapter/group titles stop notes belonging to the preceding code.
            is_context = ((line["start_size"] >= 13 and 'Symbol' not in line['start_font']) or text.startswith("CAPÍTULO")) and not is_code and bool(BRACES.sub("", text).strip())
            if is_code:
                finish()
                current = new("code", page, line, match.group(3) or "")
                code = re.sub(r'\s+','',match.group(1))
                current.update(code=code, symbol=match.group(2) or '',
                               parent_code=code[:3] if "." in code else None)
                active_note = None
                note_block = None
                description_open = True
                continue
            if is_context:
                # Adjacent large lines compose a single group heading, including its range.
                if current and current["kind"] == "context" and description_open:
                    current["description"] += " " + text
                    current["raw_lines"].append(text)
                    current["sources"].append(provenance(page, line))
                else:
                    finish()
                    current = new("context", page, line, text)
                    context_id = current["id"]
                active_note = None
                note_block = None
                description_open = True
                continue
            if current is None:
                current = new("unassigned_tabular_block", page, line, "")
                current["raw_lines"] = []
                current["warnings"].append("missing_prior_context")
            current["raw_lines"].append(text)
            current["sources"].append(provenance(page, line))
            if current['kind'] == 'shared_subdivision_scheme' and re.match(r'^\.\d{1,2}[†*]?\s+', text) and line['start_bold']:
                current.setdefault('subdivision_heading_line_refs', []).append(provenance(page, line))
            note = NOTE.match(re.sub(r'^E\s+xcluye:', 'Excluye:', text, flags=re.I))
            # The chapter explicitly introduces injury *types* for S, T00–T14
            # and T90–T98. These local definitions are not chapter-wide terms.
            if (current['kind']=='context' and 'S00–T98' in current['description']
                    and text=='Traumatismo superficial, inclusive:'):
                definition_mode = True
            if definition_mode and line['start_bold'] and line['start_font']=='Times-Bold' and not note:
                definition = {'id':f"v1-p{page['pdf_page']}-l{line['id']}-definition",
                    'title':text,'scope':'injury_type_definition',
                    'declared_code_ranges':['S00–S99','T00–T14','T90–T98'],
                    'automatic_applicability':False,'sources':[provenance(page,line)],
                    'raw_fragments':[], 'inclusions':[], 'exclusions':[], 'notes':[]}
                current.setdefault('definition_blocks',[]).append(definition)
                active_note = 'inclusions' if text.endswith('inclusive:') else 'notes'
                note_block = definition['id']
                description_open = False
            elif definition is not None:
                definition['sources'].append(provenance(page,line))
                definition['raw_fragments'].append(fragment(text,page,line))
                if note:
                    active_note = {'incluye':'inclusions','excluye':'exclusions'}.get(note.group(1).lower(),'notes')
                    note_block = f"v1-p{page['pdf_page']}-l{line['id']}"
                    definition[active_note].append(fragment(note.group(2),page,line))
                else:
                    definition[active_note].append(fragment(text,page,line))
                description_open = False
            elif (current['kind']=='context' and current['description'].startswith('Definiciones relacionadas con accidentes de transporte')
                    and re.match(r'^\([a-z]\)\s+',text)):
                active_note='notes'
                note_block=f"v{page['volume']}-p{page['pdf_page']}-l{line['id']}"
                current['notes'].append(dict(fragment(text,page,line),text_role='transport_definition'))
                description_open=False
            elif re.match(r'^Este capítulo contiene|^Este grupo contiene|^Las categorías de asterisco', text, re.I):
                active_note = 'notes'
                note_block = f"v{page['volume']}-p{page['pdf_page']}-l{line['id']}"
                current[active_note].append(dict(fragment(text,page,line), text_role='classification_overview'))
                description_open = False
            elif re.match(r'^Las siguientes subdivisiones', text, re.I):
                active_note = 'notes'
                note_block = f"v{page['volume']}-p{page['pdf_page']}-l{line['id']}"
                current[active_note].append(dict(fragment(text,page,line), text_role='supplementary_scheme_preamble'))
                description_open = False
            elif note:
                active_note = {"incluye": "inclusions", "excluye": "exclusions"}.get(note.group(1).lower(), "notes")
                note_block = f"v{page['volume']}-p{page['pdf_page']}-l{line['id']}"
                current[active_note].append(fragment(note.group(2), page, line))
                description_open = False
            elif INSTRUCTION.match(text):
                active_note = "instructions"
                note_block = f"v{page['volume']}-p{page['pdf_page']}-l{line['id']}"
                current[active_note].append(fragment(text, page, line))
                description_open = False
            elif description_open and line["start_bold"] and "Helvetica" in line["start_font"]:
                current["description"] += " " + text
            else:
                if BRACES.sub('', text).strip():
                    description_open = False
                current[active_note or "unclassified"].append(fragment(text, page, line))
    finish()
    counts = Counter(r["code"] for r in records if r["kind"] == "code")
    for record in records:
        if record.get("code") and counts[record["code"]] > 1:
            record["warnings"].append("duplicate_code_heading")
    return enrich_tabular(records)


def parse_manual(pages):
    records = []
    section = None
    previous = None
    for page in pages:
        if previous is not None and previous + 1 != page["pdf_page"]:
            section = None
        previous = page["pdf_page"]
        current = None
        for line in page["lines"]:
            text = line["text"]
            heading = SECTION.match(text)
            is_heading = heading and ("Arial" in line["start_font"] or
                                      "Helvetica" in line["start_font"]) and line["start_size"] >= 10.8
            if is_heading:
                section = {"number": heading.group(1), "title": heading.group(2)}
            if current is None or is_heading or len(current["text"]) > 1300:
                if current:
                    records.append(current)
                current = dict(base_record("manual_passage", page, line), section=section,
                               text=text, applicability="not_inferred", executable_rule=False)
            else:
                current["text"] += "\n" + text
                current["sources"].append(provenance(page, line))
        if current:
            records.append(current)
    for record in records:
        record["code_references"] = code_references(record["text"])
        if BRACES.search(record["text"]):
            record["warnings"].append("brace_group_requires_visual_review")
    return records


def parse_index(pages, section):
    records = []
    stack = []
    canonical_by_path = {}
    current = None
    previous_page = None
    stack_ids = []

    def path_key(segments):
        # The repeated page heading can abbreviate a main term: e.g.
        # "Diabetes" continues "Diabetes, diabético(a) (mellitus)...".
        return tuple(re.sub(r"\W+", " ", re.split(r"\s+[–—-]\s+|,|\(|\[", part, maxsplit=1)[0].casefold()).strip()
                     for part in segments)

    def finish():
        nonlocal current, stack, stack_ids
        if current is None:
            return
        text = normalize(" ".join(current.pop("raw_lines")))
        depth = current["depth"]
        stripped = PREFIX.sub("", text)
        continuation_suffix = r"(?:[–—-]\s*)?continuaci[oó]n\s*$"
        continued = bool(re.search(continuation_suffix, stripped, re.I))
        stripped = re.sub(continuation_suffix, "", stripped, flags=re.I).strip()
        label = normalize(CODE_REF.sub("", stripped)).rstrip(" ,;")
        from .index_structure import SOURCE_SHA256
        reviewed_source = current['sources'][0].get('source_sha256') == SOURCE_SHA256
        unmarked = {'v3-p231-l33':'Espongioblastoma', 'v3-p296-l1':'Hipertensión', 'v3-p418-l1':'Pérdida (de)',
                    'v3-p115-l92':'Celulitis', 'v3-p591-l10':'varicosa'}
        if reviewed_source and current['id'] in unmarked and label == unmarked[current['id']] and depth<len(stack) and path_key([stack[depth]]) == path_key([label]):
            continued = True
            current['documentary_layout_review'] = 'unmarked_repeated_bold_heading_visually_verified'
        current.update(text=text, term_fragment=label, code_references=code_references(stripped),
                       is_continuation=continued,
                       has_cross_reference=bool(re.search(r"\b(?:ver|véase)\b", stripped, re.I)))
        if current['kind'] == 'index_note':
            current.update(ancestors=stack[:], term_path=[], scope_path=stack[:],
                           scope_anchor_id=stack_ids[-1] if stack_ids else None,
                           scope_type='index_entry_subtree', executable_rule=False,
                           code_mentions_are_context=True)
            records.append(current)
            current = None
            return
        # Explicit continuation headings may omit intermediate ancestors.
        # Keep the active branch until a substantive sibling replaces it.
        if continued and depth < len(stack):
            original_key = path_key([stack[depth]])[0]
            incoming_key = path_key([label])[0]
            if reviewed_source and current['id'] == 'v3-p81-l3' and label == 'transtorno':
                incoming_key = 'trastorno'  # Printed typo visually verified.
            if original_key == incoming_key or original_key.startswith(incoming_key + ' '):
                current['continuation_of'] = stack_ids[depth]
                current['continuation_resolution'] = 'explicit_heading_on_active_source_branch'
        if len(stack) < depth:
            current["warnings"].append("missing_ancestor")
        ancestors = stack[:depth] + ['[missing_ancestor]'] * max(0, depth - len(stack))
        ancestor_ids = stack_ids[:depth] + [None] * max(0, depth - len(stack_ids))
        current["ancestors"] = ancestors
        current['ancestor_entry_refs'] = [ref for ref in ancestor_ids if ref]
        current["term_path"] = ancestors + [label]
        key = path_key(current["term_path"])
        if continued:
            if current.get('continuation_of'):
                pass
            elif key in canonical_by_path:
                current["continuation_of"] = canonical_by_path[key]
            else:
                current["warnings"].append("continuation_target_not_found")
                canonical_by_path[key] = current["id"]
        else:
            canonical_by_path[key] = current["id"]
        if current["has_cross_reference"]:
            current["warnings"].append("cross_reference_not_resolved")
        if any("–" in code or "-" in code or "—" in code for code in current["code_references"]):
            current["warnings"].append("range_or_unspecified_subcategory")
        # No inheritance of codes: nested modifiers may change the target completely.
        if continued and current.get('continuation_of'):
            stack = stack[:depth] + [label] + stack[depth + 1:]
            stack_ids = stack_ids[:depth] + [current['continuation_of']] + stack_ids[depth + 1:]
        else:
            stack = ancestors + [label]
            stack_ids = ancestor_ids + [current['id']]
        records.append(current)
        if reviewed_source and current['id'] == 'v3-p371-l92' and text == 'Miembro – ver también estado patológico – de la familia':
            # Two hierarchy levels share a baseline in the printed source.
            from copy import deepcopy
            current['term_fragment'] = 'Miembro – ver también estado patológico'
            current['term_path'] = [current['term_fragment']]
            child = deepcopy(current)
            child.update(id=current['id']+'-family', text='– de la familia', term_fragment='de la familia',
                         depth=1, ancestors=current['term_path'][:], term_path=current['term_path']+['de la familia'],
                         ancestor_entry_refs=[current['id']],
                         has_cross_reference=False,
                         documentary_segmentation={'source_id':current['id'], 'method':'inline_child_visually_verified'})
            child['warnings'] = []
            records.append(child)
            stack = child['term_path'][:]
            stack_ids = [current['id'],child['id']]
        current = None

    for page in pages:
        if previous_page is not None and page["pdf_page"] != previous_page + 1:
            finish()
            stack = []
            stack_ids = []
            canonical_by_path = {}
        previous_page = page["pdf_page"]
        for line in page["lines"]:
            text = line["text"]
            if line["max_size"] > 15 or text.startswith("SECCIÓN"):
                continue
            if len(text)<=1:
                # A one-letter type at a wrapped see-address is content, not
                # an alphabet divider (e.g. Hepatitis, viral, tipo, / B).
                last=current['sources'][-1] if current else None
                trailing=current['raw_lines'][-1] if current else ''
                if (len(text)==1 and text.isalpha() and not line['start_bold'] and last
                    and last['pdf_page']==page['pdf_page'] and last['column']==line['column']
                    and 0<=line['bbox'][1]-last['bbox'][3]<=3.5
                    and line['bbox'][0]-current['sources'][0]['bbox'][0]>=4.5
                    and trailing.rstrip().endswith(',')
                    and re.search(r'\b(?:ver|véase)\b',' '.join(current['raw_lines']),re.I)):
                    current['raw_lines'].append(text);current['sources'].append(provenance(page,line))
                continue
            prefix = PREFIX.match(text)
            note_start = bool(re.match(r'^Nota\s*[:–—-]', text, re.I))
            candidate = prefix is not None or (line["start_bold"] and text[0].isalpha())
            last = current["sources"][-1] if current else None
            same_column = (last is not None and last["pdf_page"] == page["pdf_page"]
                           and last["column"] == line["column"])
            line_gap = line["bbox"][1] - last["bbox"][3] if same_column else float("inf")
            current_text = normalize(" ".join(current["raw_lines"])) if current else ""
            complete_reference = bool(CODE_REF.search(current_text))
            complete_see = (bool(re.search(r"\b(?:ver|véase)\b", current_text, re.I))
                            and current_text.count("(") <= current_text.count(")")
                            and not re.search(r"\b(?:ver|véase|también|de)\s*$", current_text, re.I))
            marker_line = bool(re.fullmatch(r"[–—-]\s*continuaci[oó]n", text, re.I))
            directive_line = bool(re.match(r'^[–—-]\s*(?:ver|véase)\b', text, re.I))
            indented_wrap = (candidate and same_column and line["start_size"] >= 7
                             and 0 <= line_gap <= 3.5
                             and (marker_line or not complete_reference and not complete_see)
                             and (directive_line or line["bbox"][0] - current["sources"][0]["bbox"][0] >= 4.5))
            starts_entry = note_start or candidate and not indented_wrap
            if starts_entry or current is None:
                finish()
                depth = sum(c in "–—-" for c in prefix.group(1)) if prefix else 0
                current = dict(base_record("index_note" if note_start else "index_entry", page, line), section=section,
                               depth=depth, raw_lines=[text], usable_as_synonym=False)
                if not starts_entry:
                    current["warnings"].append("unattached_continuation_line")
            else:
                current["raw_lines"].append(text)
                current["sources"].append(provenance(page, line))
    finish()
    from .index_structure import attach_index_notes, review_source_hierarchy
    attach_index_notes(records)
    review_source_hierarchy(records)
    return records


def parse_drug_table(pages):
    return parse_drug_table_layout(pages)


def without_special_layout(page):
    """The matrix tables are parsed from their PDF coordinates, not as two-column index."""
    number = page["pdf_page"]
    if number in (14, 544, 605) or 545 <= number <= 580:
        kept = []
    elif number == 15:
        kept = [line for line in page["lines"] if line["bbox"][1] >= 235]
    elif number == 581:
        kept = [line for line in page["lines"] if line["bbox"][1] >= 220]
    else:
        return page
    return {**page, "lines": kept}


def load_pages(mode, volume, config):
    folder = ROOT / "data" / "interim" / mode / f"vol{volume}"
    manifest = read_json(folder / "manifest.json")
    if manifest["source_sha256"] != config["sha256"]:
        raise ValueError(f"Fuente incompatible en {folder}")
    for number in manifest["expected_pages"]:
        page = read_json(folder / f"page_{number:04d}.json")
        if page["source_sha256"] != config["sha256"] or page.get("extractor_version") != EXTRACTOR_VERSION:
            raise ValueError(f"Huella incompatible en página {number}")
        yield normalize_page_record(page)


def parse_all(mode, manifest, volumes=(1, 2, 3)):
    configs = manifest["volumes"]
    out = ROOT / "data" / "processed" / mode
    v1 = configs["1"]
    if 1 in volumes:
        pages = (p for p in load_pages(mode, 1, v1) if in_range(p["pdf_page"], v1["tabular_pages"]))
        write_jsonl(out / "vol1_tabular.jsonl", parse_tabular(geometry_pages(pages, v1, mode)))
    v2 = configs["2"]
    if 2 in volumes:
        manual_pages = [p for p in load_pages(mode, 2, v2) if in_range(p["pdf_page"], v2["manual_pages"])]
        manual_records = enrich_manual_passages(parse_manual(manual_pages))
        write_jsonl(out / "vol2_manual.jsonl", manual_records)
        from .manual_units import document_units
        write_jsonl(out / 'vol2_document_units.jsonl', document_units(manual_pages))
        source_pdf = ROOT / "data" / "raw" / v2["filename"]
        if sha256(source_pdf) != v2["sha256"]:
            raise ValueError(f"Fuente incompatible para reglas del volumen 2: {source_pdf}")
        from .manual_annex import annex_tables
        from .manual_documentary import attach_documentary_review, manual_reference_contexts, write_readable_review
        annex = attach_documentary_review(annex_tables(manual_pages, source_pdf, annex_code_candidates(manual_pages)), "annex")
        restrictions = attach_documentary_review(underlying_cause_candidates(manual_pages), "restrictions")
        contexts = attach_documentary_review(manual_reference_contexts(manual_pages), "contexts")
        write_jsonl(out / "vol2_annex_code_candidates.jsonl", annex)
        write_jsonl(out / "vol2_code_rule_candidates.jsonl", restrictions)
        write_jsonl(out / "vol2_reference_contexts.jsonl", contexts)
        from .manual_specific import specific_notes, write_specific_review
        specific = attach_documentary_review(specific_notes(manual_pages), "specific")
        write_jsonl(out / "vol2_specific_notes.jsonl", specific)
        write_specific_review(specific, mode)
        blocks = attach_rule_clauses(attach_bold_outcomes(association_blocks(manual_pages), manual_pages, source_pdf))
        attach_documentary_review(blocks, "blocks")
        write_jsonl(out / "vol2_association_blocks.jsonl", blocks)
        available_pages = {page["pdf_page"] for page in manual_pages}
        diabetes = diabetes_sequence_candidates(manual_pages, source_pdf) if {258, 259, 260} <= available_pages else []
        attach_documentary_review(diabetes, "diabetes")
        write_jsonl(out / "vol2_diabetes_sequences.jsonl", diabetes)
        write_readable_review(blocks, annex, diabetes, restrictions, contexts, mode)
    v3 = configs["3"]
    if 3 in volumes:
        pages = list(load_pages(mode, 3, v3))
        source_pdf = ROOT / "data" / "raw" / v3["filename"]
        if sha256(source_pdf) != v3["sha256"]:
            raise ValueError(f"Fuente incompatible para tablas del volumen 3: {source_pdf}")
        diseases = parse_index((without_special_layout(p) for p in pages
                                if in_range(p["pdf_page"], v3["index_disease_pages"])), "diseases")
        external = parse_index((without_special_layout(p) for p in pages
                                if in_range(p["pdf_page"], v3["index_external_pages"])), "external_causes")
        from .index_documentary import repair_joined_entries
        diseases = repair_joined_entries(diseases)
        external = repair_joined_entries(external)
        abortion = parse_abortion_table(pages, source_pdf)
        neoplasm = parse_neoplasm_table(pages, source_pdf)
        transport = parse_transport_matrix(pages, source_pdf)
        metadata = special_table_metadata(pages)
        conventions = []
        for page in pages:
            if 5 <= page['pdf_page'] <= 11 and page['lines']:
                conventions.append({'id':f"v3-p{page['pdf_page']}-conventions",'kind':'index_usage_conventions',
                    'review_status':'pending','warnings':[],'executable_rule':False,
                    'text':'\n'.join(line['text'] for line in page['lines']),
                    'sources':[provenance(page,line) for line in page['lines']],
                    'code_references':code_references(page['text']), 'code_mentions_are_examples':True})
        drugs = parse_drug_table(p for p in pages if in_range(p["pdf_page"], v3["drug_table_pages"]))
        from .index_structure import review_source_hierarchy
        review_source_hierarchy(drugs)
        from .volume3_review import review_cells
        review_cells(neoplasm)
        review_cells(drugs)
        remissions = resolve_remissions(diseases + external + drugs + abortion + neoplasm,
                                       abortion + neoplasm, metadata)
        for name, rows in (("index_diseases", diseases), ("index_external_causes", external),
                           ("abortion_table", abortion), ("neoplasm_table", neoplasm),
                           ("transport_matrix", transport), ("drug_table", drugs),
                           ("remissions", remissions), ("special_table_metadata", metadata)):
            write_jsonl(out / f"vol3_{name}.jsonl", rows)
        write_jsonl(out / 'vol3_index_conventions.jsonl', conventions)
    previous = read_json(out / "manifest.json") if (out / "manifest.json").exists() else {}
    versions = previous.get("volume_schema_versions", {})
    for volume in volumes:
        versions[str(volume)] = NOTE_VERSION if volume == 1 else MANUAL_VERSION if volume == 2 else INDEX_VERSION
    write_json(out / "manifest.json", {"mode": mode, "schema_version": 2,
               "manual_document_units_version": '1' if 2 in volumes else previous.get('manual_document_units_version'),
               "volume_schema_versions": versions,
               "clinical_validation": "pending", "sources": manifest,
               "note": "Los tres tomos se preservan completos en interim/full. La estructura clínica es una extracción candidata."})
    print(f"Estructuras guardadas en {out}", flush=True)
