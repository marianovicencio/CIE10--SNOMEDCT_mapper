"""Conservative semantic metadata and code-list candidates for CIE-10 volume 2."""

import re

from cie10.common import CODE_REF, code_references, provenance

VERSION = "2018-manual-v6"
EXAMPLE = re.compile(r"\bEjemplo\s+\d+\s*:", re.I)
RULE = re.compile(r"\b(?:Regla\s+(?:MB\d|P\d)|Paso\s+(?:SP\d|M\d))\b", re.I)


def manual_scope(section):
    number = (section or {}).get("number", "")
    if number.startswith("4.4"):
        return "perinatal_mortality"
    if number.startswith(("4.1", "4.2", "4.3")):
        return "mortality"
    if number.startswith("4.5"):
        return "morbidity"
    if number == "4":
        return "mortality_and_morbidity"
    if number.startswith("7.1"):
        return "mortality_certificate"
    if number.startswith("7.9"):
        return "mortality"
    if number.startswith(("7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8")):
        return "mortality_quality_control"
    if number.startswith("3"):
        return "classification_usage"
    if number.startswith("5"):
        return "statistical_presentation"
    if number.startswith("2"):
        return "classification_background"
    if number.startswith("6"):
        return "historical_background"
    if number == "1":
        return "manual_introduction"
    if number == "7":
        return "annex_overview"
    return "not_inferred"


def enrich_manual_passages(records):
    """Classify passages without promoting a code mention to a clinical rule."""
    for record in records:
        section = record.get("section") or {}
        number = section.get("number", "")
        text = record["text"]
        scope = manual_scope(section)
        if number.startswith("3"):
            content_type = "classification_convention" if number.startswith("3.1") else "usage_guidance"
        elif number.startswith("4"):
            content_type = "coding_guidance"
        elif number.startswith("5"):
            content_type = "statistical_guidance"
        elif number.startswith("6"):
            content_type = "historical_background"
        elif number.startswith("7"):
            content_type = "annex_reference"
        else:
            content_type = "background"
        roles = [content_type]
        if EXAMPLE.search(text):
            roles.append("worked_example")
        if RULE.search(text):
            roles.append("named_rule_or_step")
        if number.startswith("4.2.5"):
            roles.append("mortality_selection_reference")
            if "Con mención de:" in text or "Cuando se informa como la causa de:" in text:
                roles.append("conditional_association_table")
                record["warnings"].append("bold_outcome_requires_visual_review")
            if "no se deben utilizar" in text or "No debe usarse" in text:
                roles.append("underlying_cause_restriction")
        if number.startswith("7.6"):
            roles.append("two_column_table")
            record["warnings"].append("table_columns_require_visual_review")
        record["content_type"] = content_type
        record["content_roles"] = roles
        record["scope"] = scope
        record["applicability"] = scope
        record["requires_case_context"] = number.startswith("4")
        record["code_mentions"] = [
            {"reference": ref, "role": "unresolved_mention", "applicability_verified": False}
            for ref in record["code_references"]
        ]
        # A passage can mix examples and instructions. It is not executable merely
        # because it contains an imperative or a code.
        record["executable_rule"] = False
    return records


def _candidate(page, line, reference, relation, **fields):
    result = {
        "id": f"v2-p{page['pdf_page']}-l{line['id']}-{relation}-{reference}",
        "kind": "manual_code_fact_candidate",
        "review_status": "pending",
        "relation": relation,
        "code_expression": reference,
        "scope": "mortality_quality_control",
        "source": provenance(page, line),
        "raw_line": line["text"],
        "warnings": [],
    }
    result.update(fields)
    return result


def _priority_pairs(text):
    """Read code/rank pairs; never guess ranks from neighboring columns."""
    # The text layer has an extra dot in S05.8–.S05.9, absent visually.
    text = re.sub(r'(?<=\d)([-–—])\.(?=[ST]\d{2})', r'\1', text)
    pairs = []
    for match in CODE_REF.finditer(text):
        rank = re.match(r"\s+([1-6])(?=\s|$)", text[match.end():])
        if rank:
            pairs.append((match.group(1), int(rank.group(1))))
    return pairs


def annex_code_candidates(pages):
    """Extract only annex entries whose code and relationship are explicit.

    Other annexes, especially the two-column diabetes table in 7.6, stay as
    passages flagged for visual review.
    """
    facts = []
    seen = set()
    section = ""
    for page in pages:
        for line in page["lines"]:
            text = line["text"]
            heading = re.match(r"^(7\.(?:\d+)(?:\.\d+)?)\s+", text)
            if heading:
                section = heading.group(1)
                continue
            if section in ("7.3", "7.4"):
                # In 7.3, codes may be parenthesized or several ranges may share
                # one narrow code column. The descriptions occupy another column.
                if section == "7.3":
                    refs = code_references(text) if line["bbox"][0] <= 50 else []
                else:
                    match = CODE_REF.match(text)
                    refs = [match.group(1)] if match else []
                relation = ("ill_defined_for_mortality_selection" if section == "7.3"
                            else "unlikely_to_cause_death")
                candidates = [_candidate(page, line, ref, relation, section=section)
                              for ref in refs]
            elif section == "7.7":
                candidates = [_candidate(page, line, ref, "injury_priority_for_mortality",
                                         section=section, priority=rank)
                              for ref, rank in _priority_pairs(text)]
                if 'S05.8' in text and 'S05.9' in text:
                    for candidate in candidates:
                        if candidate['code_expression'].startswith('S05.8'):
                            candidate['extraction_adjustments'] = ['extra_text_layer_dot_removed_from_range']
            elif section in ("7.8.1", "7.8.2"):
                sex = "female" if section == "7.8.1" else "male"
                candidates = [_candidate(page, line, ref, "sex_limited_or_more_likely",
                                         section=section, sex=sex, hard_exclusion=False)
                              for ref in code_references(text)]
            else:
                continue
            for fact in candidates:
                key = (fact["relation"], fact["code_expression"],
                       fact.get("sex"), fact.get("priority"))
                if key not in seen:
                    facts.append(fact)
                    seen.add(key)
    return facts

def underlying_cause_candidates(pages):
    """Read the explicit restriction lists at the end of section 4.2.5.

    Recoding targets remain alternatives, not automatic replacements. This does
    not interpret the preceding narrative association list or its bold targets.
    """
    facts = []
    section = ""
    mode = None
    for page in pages:
        for line in page["lines"]:
            text = line["text"]
            heading = re.match(r"^(4\.\d+(?:\.\d+)?)\s+", text)
            if heading:
                section = heading.group(1)
                if section != "4.2.5":
                    mode = None
            if section != "4.2.5":
                continue
            if "Códigos que no se deben utilizar si se conoce" in text:
                mode = "if_origin_known"
                continue
            if "Códigos que no se deben utilizar para" in text:
                mode = "always"
                continue
            if mode == "always" and "enfermedad infecciosa de origen" in text:
                mode = "infectious_origin_preferred"
                continue
            if mode is None or line["bbox"][0] > 50:
                continue
            match = CODE_REF.match(text)
            if not match:
                continue
            reference = match.group(1)
            directive = re.search(r"\(codifique\s+en\s+(.+?)\)", text, re.I)
            alternatives = code_references(directive.group(1)) if directive else []
            fact = _candidate(page, line, reference,
                              "not_for_underlying_cause_when_origin_known" if mode == "if_origin_known"
                              else "not_for_underlying_cause",
                              section="4.2.5", scope="mortality",
                              condition=mode, recode_candidates=alternatives,
                              requires_case_context=True)
            if mode == "always" and not alternatives:
                fact["fallback_if_no_indicated_code"] = "R99"
            if mode == "infectious_origin_preferred":
                fact["instruction"] = "Prefer infectious origin; parenthesized code applies if origin absent"
            if reference in ("I15.1", "I15.2") and "si no se conoce" in text:
                fact["recode_condition"] = "if_origin_unknown"
            if reference == "F17.-" and "causa resultante" in text:
                fact["condition"] = "if_resultant_condition_known"
            if reference in ("P07.-", "P08.-") and mode == "if_origin_known":
                fact["scope"] = "perinatal_mortality"
                fact["condition"] = "if_other_perinatal_cause_reported"
                fact["exceptions"] = ["only_reported_cause", "other_cause_is_P28.5"]
                fact["warnings"].append("condition_from_full_note_on_pdf_page_115")
            facts.append(fact)
    return facts

def association_blocks(pages):
    """Delimit section 4.2.5 rules, preserving subjects across page breaks.

    Font-derived outcomes are attached separately. The blocks remain review
    candidates because one block may encode several conditional alternatives.
    """
    blocks = []
    active = False
    summary = False
    subject_refs = []
    fragments = []

    def trigger_types(body):
        result = []
        if re.search(r"con menci[oó]n de\b", body, re.I):
            result.append("with_mention_of")
        if re.search(r"(?:cuando se informa|como)\s+como?\s+la causa de\b", body, re.I) or re.search(r"\bcomo la causa de\s*:", body, re.I) or re.search(r"\bcomo causa de afecciones en\s*:", body, re.I):
            result.append("reported_as_cause_of")
        if re.search(r"causa antecedente originaria de", body, re.I):
            result.append("antecedent_cause_of")
        if not result and re.search(r"\bcodifique\b", body, re.I):
            result.append("direct_instruction")
        if not result and re.search(r"\bno (?:se )?debe[n]? utilizar|\bno (?:se )?debe[n]? usar", body, re.I):
            result.append("usage_restriction")
        return result

    def has_directive():
        body = "\n".join(line["text"] for _, line in fragments)
        # Narrative instructions can lack an imperative (HIV notes). They are
        # complete blocks, not additional subjects of the next association.
        return bool(trigger_types(body) or re.search(
            r"\b(?:deben codificarse|debe utilizarse|no deben estar vinculados)\b", body, re.I))

    def flush():
        nonlocal subject_refs, fragments
        if subject_refs and fragments:
            body = "\n".join(line["text"] for _, line in fragments)
            triggers = trigger_types(body)
            if triggers or has_directive():
                first_page, first_line = fragments[0]
                record = {
                    "id": f"v2-p{first_page['pdf_page']}-l{first_line['id']}-association",
                    "kind": "manual_rule_block_candidate",
                    "review_status": "pending",
                    "section": "4.2.5",
                    "scope": "mortality",
                    "subject_code_expressions": list(subject_refs),
                    "trigger_types": triggers or ["general_guidance"],
                    "code_mentions": code_references(body),
                    "text": body,
                    "sources": [provenance(page, line) for page, line in fragments],
                    "executable_rule": False,
                    "warnings": ["bold_outcome_requires_visual_review"],
                }
                if len(subject_refs) > 1:
                    record["warnings"].append("subject_group_requires_visual_review")
                # Qualifiers printed after a subject (B00.8, K75.8, K86.1)
                # are retained per subject, not applied to the whole group.
                subject_entries = []
                for page, line in fragments:
                    match = CODE_REF.match(line["text"]) if line["bbox"][0] <= 50 else None
                    if match and match.group(1) in subject_refs and not line["text"][match.end():].lstrip().startswith("("):
                        subject_entries.append({"code_expression": match.group(1), "text": line["text"], "sources": [provenance(page, line)]})
                    elif subject_entries and not trigger_types(line["text"]):
                        subject_entries[-1]["text"] += "\n" + line["text"]
                        subject_entries[-1]["sources"].append(provenance(page, line))
                    else:
                        break
                record["subject_entries"] = subject_entries
                record["selection_context"] = {
                    "scope": "mortality", "step": "M1",
                    "subject_role": "provisional_underlying_cause",
                    "outcome_role": "new_provisional_underlying_cause",
                    "with_mention_of": "other_condition_anywhere_on_death_certificate",
                    "reported_as_cause_of": "subject_reported_as_cause_of_other_condition_in_valid_causal_relationship",
                    "source_pdf_page": 83,
                }
                blocks.append(record)
        subject_refs = []
        fragments = []

    for page in pages:
        for line in page["lines"]:
            text = line["text"]
            heading = re.match(r"^(4\.\d+(?:\.\d+)?)\s+", text)
            if heading:
                if heading.group(1) == "4.2.5":
                    active = True
                elif active:
                    flush()
                    active = False
                continue
            if not active:
                continue
            if text.startswith("Resumen de los códigos que no deben utilizarse"):
                flush()
                summary = True
            if summary:
                continue
            match = CODE_REF.match(text) if line["bbox"][0] <= 50 else None
            # An indented parenthesized description at a page top can be laid
            # out at the left margin (e.g. O35.4 on PDF page 100). It is a
            # condition continuing the previous subject, not a new subject.
            parenthesized_condition = bool(match and text[match.end():].lstrip().startswith("("))
            if match and not parenthesized_condition:
                if subject_refs and has_directive():
                    flush()
                subject_refs.append(match.group(1))
                fragments.append((page, line))
            elif subject_refs:
                fragments.append((page, line))
    flush()
    return blocks
