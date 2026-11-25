"""Structural QA and reference cases; not a clinical validation."""

import re
from collections import Counter

from .common import ROOT, read_json, read_jsonl, write_json, write_jsonl


def audit(mode):
    folder = ROOT / "data" / "processed" / mode
    report_dir = ROOT / "data" / "reports" / mode
    files = sorted(folder.glob("*.jsonl"))
    if not files:
        raise ValueError("No hay estructuras. Ejecuta parse o run primero.")
    counts, warnings, queue = {}, Counter(), []
    code_records = []
    tabular_records = []
    volume2_blocks = []
    volume2_diabetes = []
    volume2_restrictions = []
    volume2_annex = []
    volume2_contexts = []
    volume2_specific = []
    for file in files:
        records = list(read_jsonl(file))
        if file.name == 'vol1_tabular.jsonl':
            tabular_records = records
        elif file.name == 'vol2_association_blocks.jsonl':
            volume2_blocks = records
        elif file.name == 'vol2_diabetes_sequences.jsonl':
            volume2_diabetes = records
        elif file.name == 'vol2_code_rule_candidates.jsonl':
            volume2_restrictions = records
        elif file.name == 'vol2_annex_code_candidates.jsonl':
            volume2_annex = records
        elif file.name == 'vol2_reference_contexts.jsonl':
            volume2_contexts = records
        elif file.name == 'vol2_specific_notes.jsonl':
            volume2_specific = records
        counts[file.name] = len(records)
        for record in records:
            if record["kind"] == "code":
                code_records.append(record)
            warnings.update(record["warnings"])
            if record["warnings"]:
                queue.append({"file": file.name, "id": record["id"], "warnings": record["warnings"],
                              "sources": record.get("sources", [record["source"]] if record.get("source") else []),
                              "text": record.get("text", record.get("raw_line", record.get("description"))),
                              "semantic_review_issues": record.get("semantic_review_issues", []),
                              "note_structure_issues": record.get("note_structure_issues", [])})
    source_review_queue = []
    for block in volume2_blocks:
        if not block.get('condition_rows') and block.get('outcome_mentions'):
            source_review_queue.append({
                'id': block['id'], 'kind': 'direct_outcome_without_condition_rows',
                'subject_code_expressions': block['subject_code_expressions'],
                'trigger_types': block['trigger_types'],
                'outcome_mentions': block['outcome_mentions'],
                'text': block['text'], 'sources': block['sources'],
                'review_status': 'pending',
                'review_reason': 'Interpretar el alcance condicional de la instrucción directa',
            })
    for pair in volume2_diabetes:
        if 'adjacent_source_codes_require_review' in pair.get('warnings', []):
            source_review_queue.append({
                'id': pair['id'], 'kind': 'adjacent_diabetes_source_codes',
                'diabetes_code': pair['diabetes_code'],
                'cause_code_expression': pair['cause_code_expression'],
                'source': pair['source'], 'review_status': pair['review_status'],
                'review_reason': 'El PDF imprime Y46.2Y52.5 sin separador',
            })
    for record in volume2_blocks + volume2_diabetes + volume2_restrictions + volume2_annex + volume2_contexts + volume2_specific:
        if 'documentary_review_outdated' in record.get('warnings', []):
            source_review_queue.append({
                'id': record['id'], 'kind': 'documentary_review_outdated',
                'review_status': 'pending',
                'review_reason': 'El contenido o la fuente cambió respecto de la revisión registrada',
            })
    write_jsonl(report_dir / 'vol2_source_review_queue.jsonl', source_review_queue)
    codes = {record["code"]: record for record in code_records}
    checks = {}
    for code, expected in [("A00", "Cólera"), ("J12.9", "Neumonía viral, no especificada"),
                           ("J15.4", "Neumonía debida a otros estreptococos"),
                           ("J18.9", "Neumonía, no especificada")]:
        checks[f"description_{code}"] = codes.get(code, {}).get("description") == expected
    j18 = codes.get("J18", {})
    checks["J18_exclusion_kept_separate"] = any("J85.1" in x["text"] for x in j18.get("exclusions", []))
    checks["J18_no_viral_positive_inclusion"] = not any("viral" in x["text"].lower() for x in j18.get("inclusions", [])) and bool(j18)
    page_counts, page_warnings = {}, Counter()
    removed = Counter()
    for volume in (1, 2, 3):
        source_dir = ROOT / "data" / "interim" / mode / f"vol{volume}"
        extraction = read_json(source_dir / "manifest.json")
        expected = extraction["expected_pages"]
        existing = [n for n in expected if (source_dir / f"page_{n:04d}.json").exists()]
        checks[f"vol{volume}_all_requested_pages"] = existing == expected
        page_counts[str(volume)] = len(existing)
        for n in existing:
            p = read_json(source_dir / f"page_{n:04d}.json")
            page_warnings.update(p["warnings"])
            removed["watermark_chars"] += p["removed_watermark_chars"]
            removed["outside_crop_chars"] += p["outside_crop_chars"]
            if p["warnings"]:
                queue.append({"file": f"vol{volume}/page_{n:04d}.json", "warnings": p["warnings"],
                              "pdf_page": n, "volume": volume})
    if mode == "full":
        checks["full_page_count_2209"] = sum(page_counts.values()) == 2209
        c64 = codes.get("C64", {})
        c75 = codes.get("C75", {})
        c760 = codes.get("C76.0", {})
        checks["C64_shared_brace"] = [e["text"] for e in c64.get("exclusions", [])] == ["Cálices renal(es) (C65)", "Pelvis renal(es) (C65)"]
        checks["C75_prefix_and_siblings"] = [e["text"] for e in c75.get("exclusions", [])] == [
            "glándula suprarrenal (C74.–)", "glándula tiroides (C73)", "ovario (C56)",
            "páncreas endocrino (C25.4)", "testículo (C62.–)", "timo (C37)"]
        first = (c75.get("exclusions") or [{}])[0]
        checks["C75_family_reference"] = any(r.get("category") == "C74" and r.get("scope") == "all_subcategories" for r in first.get("references", []))
        checks["C760_contextual_implicit_inclusions"] = ([e["text"] for e in c760.get("inclusions", [])] == ["Mejilla SAI", "Nariz SAI"] and
            all("maligno" in e.get("classification_context", {}).get("description", "") for e in c760.get("inclusions", [])))
        checks['K27_shared_table'] = bool(codes.get('K27', {}).get('subdivision_scheme_refs'))
        checks['O03_shared_suffixes'] = codes.get('O03', {}).get('code_structure', {}).get('shared_suffixes') == ['.' + str(n) for n in range(10)]
        checks['A170_dual_code'] = any(r.get('manifestation_codes') == ['G01*'] and r.get('etiology_codes') == ['A17.0†'] for r in codes.get('A17.0', {}).get('coding_relations', []))
        checks['C008_numbered_note'] = any(r.get('resolution') == 'numbered_note_located' and r.get('target_note_number') == 5 for r in codes.get('C00.8', {}).get('coding_relations', []))
        checks['A064_dagger_in_symbol'] = codes.get('A06.4', {}).get('symbol')=='†'
        checks['A022_five_shared_terms'] = len(codes.get('A02.2', {}).get('inclusions', []))==5 and all(x['text'].endswith('debida a Salmonella') for x in codes.get('A02.2', {}).get('inclusions', []))
        checks['A161_referenced_conditions'] = any(x.get('text_role')=='referenced_condition_set' for x in codes.get('A16.1', {}).get('instructions', []))
        checks['S02_supplementary_table'] = bool(codes.get('S02', {}).get('supplementary_tables'))
        b58 = next((b for b in volume2_blocks if 'B58.-' in b.get('subject_code_expressions', [])), {})
        b25 = next((b for b in volume2_blocks if 'B25.0†' in b.get('subject_code_expressions', [])), {})
        checks['vol2_B58_bold_outcomes'] = {x['code_expression'] for x in b58.get('outcome_mentions', [])} == {'B20.7', 'B20.8', 'B22.7'}
        checks['vol2_B25_page_continuation'] = b25.get('subject_code_expressions') == ['B25.0†', 'B25.2†', 'B25.8', 'B25.9']
        checks['vol2_diabetes_cell_counts'] = dict(Counter(x['diabetes_code'] for x in volume2_diabetes)) == {'E10': 7, 'E11': 8, 'E12': 4, 'E13': 44, 'E14': 48}
        checks['vol2_diabetes_qualifier'] = all(any(x.get('qualifier') == 'Solamente páncreas' for x in volume2_diabetes if x['diabetes_code'] == code and x['cause_code_expression'] == 'C78.8') for code in ('E13', 'E14'))
        checks['vol2_restrictions_85'] = len(volume2_restrictions) == 85
        reviewed = volume2_blocks + volume2_diabetes + volume2_restrictions + volume2_annex + volume2_contexts + volume2_specific
        checks['vol2_documentary_review_current'] = bool(reviewed) and all(
            r.get('review_status') in ('source_verified', 'source_ambiguity_preserved') for r in reviewed)
        checks['vol2_specific_notes_70_blocks'] = len(volume2_specific)==70
        checks['vol2_specific_notes_examples_28'] = sum(r['kind']=='manual_worked_example' for r in volume2_specific)==28
        checks['vol2_specific_notes_not_executable'] = all(not r['executable_rule'] for r in volume2_specific)
        checks['vol2_annex_lists_complete'] = dict(Counter(r['section'] for r in volume2_annex)) == {
            '7.3': 13, '7.4': 429, '7.7': 417, '7.8.1': 792, '7.8.2': 128}
        checks['vol2_condition_rows_have_destinations'] = all(
            row['outcome_mentions'] for block in volume2_blocks
            for row in block.get('condition_rows', [])
            if row['row_type'] in ('condition', 'exception', 'combination'))
        i70 = next((b for b in volume2_blocks
                    if b.get('subject_code_expressions') == ['I70.-']), {})
        i42_codes = ['I42.0', 'I42.1', 'I42.2', 'I42.8', 'I42.9']
        checks['vol2_i70_alternative_group'] = any(
            row.get('condition_code_expressions') == i42_codes and
            [x['code_expression'] for x in row['outcome_mentions']] == ['I25.5']
            for row in i70.get('condition_rows', []))
        checks['vol2_i70_exception_scope'] = any(
            row.get('row_type') == 'exception' and
            row.get('exception_for_condition_code_expressions') == i42_codes
            for row in i70.get('condition_rows', []))
        abortion = list(read_jsonl(folder / 'vol3_abortion_table.jsonl'))
        neoplasm = list(read_jsonl(folder / 'vol3_neoplasm_table.jsonl'))
        transport = list(read_jsonl(folder / 'vol3_transport_matrix.jsonl'))
        drugs = list(read_jsonl(folder / 'vol3_drug_table.jsonl'))
        remissions = list(read_jsonl(folder / 'vol3_remissions.jsonl'))
        abscess = next((r for r in abortion if r.get('term_fragment', '').startswith('absceso genital')), {})
        checks['vol3_abortion_five_contexts'] = (len(abortion) >= 40 and
            abscess.get('cells', {}).get('o03_o06_complete_or_unspecified', {}).get('text') == '.5' and
            abscess.get('cells', {}).get('o03_o06_incomplete', {}).get('text') == '.0' and
            abscess.get('cells', {}).get('o08_subsequent_complication', {}).get('code_family') == 'O08')
        site = next((r for r in neoplasm if r.get('id') == 'v3-p555-table-y1030'), {})
        checks['vol3_neoplasm_columns'] = (len(neoplasm) >= 1500 and
            site.get('cells', {}).get('malignant_primary', {}).get('text') == 'C63.7' and
            site.get('cells', {}).get('uncertain_or_unknown_behavior', {}).get('text') == 'D40.7')
        checks['vol3_transport_matrix_9x11'] = (len(transport) == 9 and
            all(len(r.get('columns', {})) == 11 for r in transport) and
            transport[0]['columns'].get('noncollision_accident') is None)
        checks['vol3_drug_no_repeated_headers'] = (len(drugs) >= 5000 and
            not any(r.get('term_fragment', '').casefold() == 'sustancia' for r in drugs))
        checks['vol3_remissions_no_clinical_equivalence'] = (len(remissions) >= 7000 and
            any(r.get('resolution') == 'resolved_exact' for r in remissions) and
            all(r.get('implies_clinical_equivalence') is False for r in remissions))
    completeness = {key: {'records':sum(bool(r.get(key)) for r in tabular_records),
                          'items':sum(len(r.get(key, [])) for r in tabular_records)}
                    for key in ('unclassified','note_structure_issues','semantic_review_issues','clinical_input_requirements')}
    report = {"mode": mode, "clinical_validation": "pending", "page_counts": page_counts,
              "record_counts": counts, "code_headings": len(code_records), "unique_codes": len(codes),
              "structural_checks": checks, "structural_checks_passed": all(checks.values()),
              "record_warnings": dict(warnings), "page_warnings": dict(page_warnings),
              "filtered_characters": dict(removed), "review_queue_items": len(queue),
              'volume1_completeness':completeness,
              'volume1_fully_resolved':not any(completeness[k]['items'] for k in ('unclassified','note_structure_issues','semantic_review_issues'))}
    write_json(report_dir / "audit.json", report)
    write_jsonl(report_dir / "review_queue.jsonl", queue)
    lines = ["# Control de extracción CIE-10", "", f"Modo: **{mode}**. Validación clínica: **pendiente**.", "",
             "Los controles comprueban integridad y ejemplos concretos; no certifican todas las correspondencias.", "",
             "## Páginas", ""]
    lines += [f"- Tomo {v}: {n} páginas extraídas." for v, n in page_counts.items()]
    lines += ["", "## Estructuras candidatas", ""]
    lines += [f"- {name}: {n} registros." for name, n in counts.items()]
    lines += ["", f"Encabezados de códigos: {len(code_records)}; códigos únicos: {len(codes)}.", "",
              "## Comprobaciones", ""]
    lines += [f"- {'OK' if passed else 'REVISAR'}: {name}." for name, passed in checks.items()]
    lines += ["", "## Revisión prioritaria del tomo 2", "",
              f"Elementos en vol2_source_review_queue.jsonl: {len(source_review_queue)}.",
              "Son instrucciones sin condición estructurada o códigos adyacentes en 7.6; no son reglas aprobadas.", ""]
    lines += ["", "## Advertencias", "", f"Elementos en review_queue.jsonl: {len(queue)}.", ""]
    lines += ['Los controles de regresión pueden pasar aunque haya estructuras pendientes.', '']
    lines += [f"- Volumen 1, {k}: {v['records']} registros / {v['items']} elementos." for k,v in completeness.items()]
    lines += [f"- {key}: {n}." for key, n in (warnings + page_warnings).items()]
    lines += ["", "Todo registro mantiene review_status=pending, incluso si no activa una advertencia.",
              "Revisar especialmente llaves, saltos de página, términos partidos, rangos, doble codificación y tablas.",
              "Las instrucciones del tomo 2 no son reglas ejecutables; las entradas del tomo 3 no son sinónimos aprobados.", ""]
    (report_dir / "audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Control estructural: {'OK' if all(checks.values()) else 'REVISAR'}; informe: {report_dir / 'audit.md'}", flush=True)
    return report
