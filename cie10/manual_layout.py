"""Font- and geometry-aware review candidates from volume 2's verified PDF."""

import re
from collections import defaultdict

import pdfplumber

from .common import CODE_REF, code_references, provenance
from .extract import is_visible, is_watermark


def _filtered_page(page):
    box = page.cropbox or page.bbox
    visible = page.filter(lambda obj: obj["object_type"] != "char" or is_visible(obj, box))
    return visible.filter(lambda obj: obj["object_type"] != "char" or not is_watermark(obj))


def _line_for_word(page_record, word):
    lines = [line for line in page_record["lines"]
             if abs(line["bbox"][1] - word["top"]) <= 3
             and line["bbox"][0] - 3 <= word["x0"] <= line["bbox"][2] + 3]
    return min(lines, key=lambda line: abs(line["bbox"][1] - word["top"])) if lines else None


def _word_source(page_record, word, column):
    line = _line_for_word(page_record, word)
    source = provenance(page_record, line)
    source["bbox"] = [round(word[k], 2) for k in ("x0", "top", "x1", "bottom")]
    source["column"] = column
    return source


def attach_bold_outcomes(blocks, pages, pdf_path):
    """Attach codes whose glyphs are bold to the owning 4.2.5 block.

    A bold code is evidence of a printed outcome, not an executable mapping
    between every condition and every outcome in a multi-row block.
    """
    by_page_line = defaultdict(list)
    for block in blocks:
        block["outcome_mentions"] = []
        for source in block["sources"]:
            by_page_line[(source["pdf_page"], source["line_id"])].append(block)
    page_records = {p["pdf_page"]: p for p in pages}
    with pdfplumber.open(pdf_path) as pdf:
        for number in sorted({page for page, _ in by_page_line}):
            if not 83 <= number <= 118:
                continue
            record = page_records[number]
            view = _filtered_page(pdf.pages[number - 1])
            for word in view.extract_words(x_tolerance=1.5, y_tolerance=2, return_chars=True):
                matches = list(CODE_REF.finditer(word["text"]))
                if not matches:
                    continue
                code_chars = [c for c in word["chars"] if c["text"].isalnum() or c["text"] in ".–-†*"]
                if not code_chars:
                    continue
                bold = sum("bold" in c["fontname"].lower() for c in code_chars)
                if bold / len(code_chars) < 0.55:
                    continue
                line = _line_for_word(record, word)
                if line is None:
                    continue
                for block in by_page_line.get((number, line["id"]), []):
                    for match in matches:
                        ref = match.group(1)
                        block["outcome_mentions"].append({
                            "code_expression": ref,
                            "role": "printed_bold_outcome_candidate",
                            "source": _word_source(record, word, "body"),
                            "raw_word": word["text"],
                            "bold_fraction": round(bold / len(code_chars), 2),
                        })
    for block in blocks:
        _join_bold_range_outcomes(block)
        if block["outcome_mentions"]:
            block["warnings"] = [w for w in block["warnings"]
                                 if w != "bold_outcome_requires_visual_review"]
            block["warnings"].append("outcome_condition_pairing_requires_review")
        else:
            block["warnings"].append("bold_outcome_not_detected")
        if "cuarto carácter" in block["text"] or "cuarto caracter" in block["text"]:
            block["warnings"].append("fourth_character_result_requires_review")
    return blocks


def _table_dividers(pdf_page, side, start, end):
    left, right = (28, 195) if side == "left" else (200, 370)
    positions = []
    for edge in pdf_page.lines + pdf_page.rect_edges:
        if (abs(edge["top"] - edge["bottom"]) < 1 and
                left <= edge["x0"] <= right and
                left <= edge["x1"] <= right and
                edge["x1"] - edge["x0"] > 100 and
                start + 10 < edge["top"] < end - 10):
            positions.append(edge["top"])
    positions.sort()
    groups = []
    for pos in positions:
        if not groups or pos - groups[-1][-1] > 5:
            groups.append([pos])
        else:
            groups[-1].append(pos)
    return [sum(group) / len(group) for group in groups]


def _split_code_word(raw):
    # The original PDF prints Y46.2Y52.5 without a separator in the E13 cell.
    if raw == "Y46.2Y52.5":
        return ["Y46.2", "Y52.5"], ["adjacent_source_codes_require_review"]
    stripped = raw.strip("(),;.")
    if CODE_REF.fullmatch(stripped):
        return [stripped], []
    return [], []


def diabetes_sequence_candidates(pages, pdf_path):
    """Read Annex 7.6 by table side, separator, and continued merged cell."""
    page_records = {p["pdf_page"]: p for p in pages}
    bounds = {258: (455, 545), 259: (82, 550), 260: (82, 210)}
    facts = []
    active_type = None
    with pdfplumber.open(pdf_path) as pdf:
        for number, (start, end) in bounds.items():
            view = _filtered_page(pdf.pages[number - 1])
            words = view.extract_words(x_tolerance=1.5, y_tolerance=2)
            for side in ("left", "right"):
                if number == 260 and side == "right":
                    continue
                x_min, x_max = (25, 195) if side == "left" else (200, 370)
                side_words = [word for word in words
                              if start <= word["top"] <= end and
                              x_min <= word["x0"] < x_max]
                cuts = [start] + _table_dividers(pdf.pages[number - 1], side, start, end) + [end]
                for low, high in zip(cuts, cuts[1:]):
                    segment = sorted((w for w in side_words if low <= w["top"] < high),
                                     key=lambda w: (w["top"], w["x0"]))
                    type_words = [w for w in segment if re.fullmatch(r"E1[0-4]", w["text"])
                                  and (w["x0"] < 70 if side == "left" else w["x0"] < 235)]
                    if type_words:
                        active_type = type_words[0]["text"]
                    if active_type is None:
                        raise ValueError(f"Anexo 7.6 sin tipo de diabetes en página {number}")
                    for word in segment:
                        if word in type_words:
                            continue
                        if word["x0"] < (80 if side == "left" else 240):
                            continue
                        codes, warnings = _split_code_word(word["text"])
                        if not codes:
                            continue
                        neighbors = [w["text"] for w in segment
                                     if abs(w["top"] - word["top"]) <= 2 and
                                     word["x1"] <= w["x0"] and
                                     w["x0"] < x_max]
                        qualifier = "Solamente páncreas" if (word["text"] == "C78.8" and
                                      "Solamente" in " ".join(neighbors)) else None
                        for code in codes:
                            facts.append({
                                "id": f"v2-p{number}-{side}-{active_type}-{code}",
                                "kind": "manual_code_relation_candidate",
                                "review_status": "pending",
                                "section": "7.6",
                                "scope": "mortality_causal_sequence",
                                "relation": "accepted_diabetes_due_to_sequence",
                                "diabetes_code": active_type,
                                "cause_code_expression": code,
                                "qualifier": qualifier,
                                "source": _word_source(page_records[number], word, side),
                                "raw_word": word["text"],
                                "warnings": list(warnings),
                                "executable_rule": False,
                            })
    return facts

def attach_rule_clauses(blocks):
    """Pair condition rows with printed outcomes without collapsing alternatives."""
    for block in blocks:
        block["condition_rows"] = []
        trigger = None
        current = None
        subject_fourth = None
        trigger_text = None
        outcomes_by_line = defaultdict(list)
        for outcome in block.get("outcome_mentions", []):
            source = outcome["source"]
            outcomes_by_line[(source["pdf_page"], source["line_id"])].append(outcome)

        def flush():
            nonlocal current
            if current is not None:
                current["text"] = "\n".join(current.pop("_lines"))
                text = current["text"]
                instruction = re.search(r"\b(?:codifi-?\s*que|utilice)(?:\s+en)?\s+", text, re.I)
                destination_text = text[instruction.end():] if instruction else ""
                fourth = re.search(r"cuarto\s+car[aá]cter\s*\.?\s*(\d)\b", destination_text, re.I)
                if fourth:
                    current["fourth_character_literal"] = "." + fourth.group(1)
                elif 'cuarto carácter' in text and 'etapa más avanzada' in text:
                    current['fourth_character_selection'] = 'more_advanced_stage_reported'
                if current.get('trigger_text', '').lower().startswith('cuando no se especifica la causa'):
                    current['trigger_qualifiers'] = ['cause_not_specified']
                if re.search(r"\b(?:excepto|a menos que|si no|según corresponda)\b", text, re.I):
                    current["warnings"].append("conditional_qualifier_requires_review")
                if not current["outcome_mentions"]:
                    if instruction:
                        for destination in CODE_REF.finditer(text, instruction.end()):
                            line_index = text.count("\n", 0, destination.start())
                            current["outcome_mentions"].append({
                                "code_expression": code_references(destination.group(1))[0],
                                "role": "printed_explicit_destination_candidate",
                                "source": current["sources"][line_index],
                                "source_precision": "line",
                                "raw_word": destination.group(1),
                            })
                            current["warnings"].append("destination_not_bold_in_source")
                            if "explicit_destination_not_bold_in_source" not in block["warnings"]:
                                block["warnings"].append("explicit_destination_not_bold_in_source")
                current["requires_case_context"] = True
                current["executable_rule"] = False
                current["document_references"] = list(dict.fromkeys(re.findall(
                    r"\b(?:[347]\.\d+(?:\.\d+)?|Volumen\s+3|SP[1-8]|Paso\s+M[1-4])\b", text)))
                block["condition_rows"].append(current)
            current = None

        for text, source in zip(block["text"].splitlines(), block["sources"]):
            lowered = text.lower()
            # Only a complete printed header changes causal context. A phrase
            # inside an exception (A17/A18) is not another header.
            if re.fullmatch(r"(?:Cuando no se especifica la causa,\s*)?Con menci[oó]n de:?\s*", text, re.I):
                flush()
                trigger = "with_mention_of"
                trigger_text = text
                continue
            if re.fullmatch(r"(?:Cuando se informa )?como (?:la causa de|causa de afecciones en|la causa antecedente originaria de):\s*", text, re.I):
                flush()
                trigger = ("antecedent_cause_of" if "antecedente originaria" in lowered
                           else "reported_as_cause_of")
                trigger_text = text
                continue
            fourth_heading = re.match(r"Cuarto car[aá]cter\s*(\.\d)\s*\(", text, re.I)
            if fourth_heading:
                flush()
                subject_fourth = fourth_heading.group(1)
                trigger = None
                continue
            if trigger is None:
                continue
            leading = CODE_REF.match(text)
            x0 = source["bbox"][0]
            condition_start = bool(leading and (65 <= x0 <= 110 or
                                    (x0 <= 50 and text[leading.end():].lstrip().startswith("("))))
            text_condition = bool(subject_fourth and not leading and
                                  re.match(r"(?:Síndrome|Estado|Trastorno)\b", text))
            combination_start = bool(re.match(r"Cualquiera? (?:combinación de los anteriores|de los anteriores en combinación)", text, re.I))
            exception_start = text.lstrip().lower().startswith("excepción:")
            if condition_start and current is not None:
                previous = current["_lines"][-1] if current["_lines"] else ""
                joined_alternative = (current["row_type"] == "condition" and
                                      bool(re.search(r",\s*[ou]\s*$", previous, re.I)))
                continued_exception = (bool(re.search(r"codifique\s+en\s*$", previous, re.I)) or
                                       (current["row_type"] == "exception" and
                                        bool(re.search(r"[-–—]\s*$", previous))))
                if joined_alternative:
                    current["condition_code_expressions"].append(leading.group(1))
                    if "alternative_condition_group_requires_review" not in current["warnings"]:
                        current["warnings"].append("alternative_condition_group_requires_review")
                    if "alternative_condition_group_requires_review" not in block["warnings"]:
                        block["warnings"].append("alternative_condition_group_requires_review")
                    condition_start = False
                elif continued_exception:
                    condition_start = False
            if condition_start or exception_start or text_condition or combination_start:
                exception_for = (list(current["condition_code_expressions"])
                                 if exception_start and current is not None and
                                 current["row_type"] == "condition" else [])
                flush()
                current = {
                    "condition_code_expressions": code_references(text.split("(", 1)[0]) if condition_start else [],
                    "trigger_type": trigger,
                    "trigger_text": trigger_text,
                    "row_type": "exception" if exception_start else "combination" if combination_start else "condition",
                    "sources": [],
                    "outcome_mentions": [],
                    "review_status": "pending",
                    "warnings": [],
                    "_lines": [],
                }
                if exception_start:
                    current["exception_for_condition_code_expressions"] = exception_for
                if subject_fourth:
                    current["subject_fourth_character"] = subject_fourth
                if text_condition:
                    suffix = re.search(r"\((\.\d)\)", text)
                    current["condition_fourth_character"] = suffix.group(1) if suffix else None
                if combination_start:
                    current["combination_of_previous_rows"] = [
                        i for i, r in enumerate(block["condition_rows"])
                        if r["trigger_type"] == trigger and r["row_type"] == "condition"]
            if current is not None:
                current["_lines"].append(text)
                current["sources"].append(source)
                current["outcome_mentions"].extend(outcomes_by_line[(source["pdf_page"], source["line_id"])])
        flush()
        # Restrictions and narrative notes have no condition table. Preserve
        # their whole wording and explicit results rather than inventing a
        # condition from every code mention.
        if not block["condition_rows"]:
            body_lines = list(zip(block["text"].splitlines(), block["sources"]))
            current = {
                "condition_code_expressions": [], "trigger_type": "direct_instruction",
                "row_type": "usage_restriction" if re.search(r"No (?:se )?debe", block["text"], re.I) else "general_guidance",
                "sources": [s for _, s in body_lines],
                "outcome_mentions": list(block.get("outcome_mentions", [])),
                "review_status": "pending", "warnings": [],
                "_lines": [t for t, _ in body_lines],
            }
            flush()
        # F10–F19 .0 precedes the .1/.2/.5 conditional tables in the same
        # block and must survive independently.
        prefix = []
        for t, s in zip(block["text"].splitlines(), block["sources"]):
            if re.match(r"Cuarto car[aá]cter", t, re.I):
                break
            prefix.append((t, s))
        if any(re.match(r"F10[-–]F19\s+Cuarto", t) for t, _ in prefix) and block["condition_rows"] and block["condition_rows"][0]["row_type"] == "condition":
            text = "\n".join(t for t, _ in prefix)
            destination = text.split("codifique en", 1)[1]
            block["condition_rows"].insert(0, {
                "row_type": "direct_instruction", "trigger_type": "direct_instruction",
                "subject_fourth_character": ".0", "condition_code_expressions": [],
                "text": text, "sources": [s for _, s in prefix],
                "outcome_mentions": [o for o in block["outcome_mentions"] if o["code_expression"] in code_references(destination)],
                "warnings": [], "review_status": "pending", "requires_case_context": True,
                "executable_rule": False,
            })
    return blocks

def _join_bold_range_outcomes(block):
    """Preserve ranges when their two bold endpoints occupy separate PDF words."""
    lines = list(zip(block["text"].splitlines(), block["sources"]))
    positions = {(source["pdf_page"], source["line_id"]): i
                 for i, (_, source) in enumerate(lines)}
    outcomes = block["outcome_mentions"]
    joined = []
    i = 0
    while i < len(outcomes):
        merged = None
        if i + 1 < len(outcomes):
            first, second = outcomes[i], outcomes[i + 1]
            a = (first["source"]["pdf_page"], first["source"]["line_id"])
            b = (second["source"]["pdf_page"], second["source"]["line_id"])
            ia, ib = positions.get(a), positions.get(b)
            if ia is not None and ib is not None and 0 <= ib - ia <= 1:
                text = lines[ia][0] + (" " + lines[ib][0] if ib != ia else "")
                for ref in code_references(text):
                    match = re.fullmatch(
                        r"([A-Z]\d{2}(?:\.\d{1,2})?)\s*[-–—]\s*([A-Z]\d{2}(?:\.\d{1,2})?)",
                        ref,
                    )
                    if match and (first["code_expression"], second["code_expression"]) == match.groups():
                        merged = dict(first)
                        merged["code_expression"] = match.group(1) + "–" + match.group(2)
                        merged["raw_expression"] = ref
                        merged["raw_word"] = first["raw_word"] + " " + second["raw_word"]
                        merged["source_fragments"] = [first["source"], second["source"]]
                        merged["warnings"] = ["range_joined_from_bold_tokens"]
                        break
        if merged is not None:
            joined.append(merged)
            i += 2
        else:
            joined.append(outcomes[i])
            i += 1
    block["outcome_mentions"] = joined
