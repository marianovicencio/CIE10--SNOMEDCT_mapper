"""Conservative documentary checks over explicitly typed evidence, not clinical inference."""
import re
import unicodedata


def normalize(text):
    text = text.casefold().replace('(es)', '').replace('(s)', '')
    text = text.translate(str.maketrans({'–': '-', '—': '-', '−': '-'}))
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD', text)
                            if not unicodedata.combining(c)).split())


def source(evidence, kind, role, fallback):
    return next((item for item in evidence if item['type'] == kind and
                 (item.get('role') == role or item['id'] == fallback)), None)


def unasserted(text, start):
    prefix = text[max(0, start - 80):start]
    return bool(re.search(r'\b(?:no|sin|niega|descarta|antecedente|sospecha)\b[^.;:]*$', prefix))


def renal_stage(text):
    text = normalize(text)
    if 'renal' not in text or 'cronic' not in text:
        return None
    values = []
    for match in re.finditer(r'\b(?:etapa|estadio|stage)\s+([1-5](?:[ab])?|iv|iii|ii|i|v)\b', text):
        if unasserted(text, match.start()):
            return None
        values.append({'i':'1', 'ii':'2', 'iii':'3', 'iv':'4', 'v':'5'}.get(match[1], match[1]))
    return values[0] if values and len(set(values)) == 1 else None


def diabetes_control(text):
    text = normalize(text)
    if 'diabet' not in text:
        return None
    values = []
    for match in re.finditer(r'\b(?:no controlad[ao]|mal controlad[ao]|bien controlad[ao]|controlad[ao])\b', text):
        if unasserted(text, match.start()):
            return None
        values.append('poor' if match[0].startswith(('no ', 'mal ')) else 'good')
    return values[0] if values and len(set(values)) == 1 else None


def affirmed(text, expression):
    text = normalize(text)
    return any(not unasserted(text, match.start()) for match in re.finditer(expression, text))


def documentary_constraint(evidence):
    title = source(evidence, 'CIE10', 'title', 'cie-title')
    term = source(evidence, 'SNOMED', 'candidate_term', 'snomed-term')
    diagnostic = next((x for x in evidence if x['type'] == 'INPUT'), None)
    if not title or not term:
        return None
    refs = [title['id'], term['id']] + ([diagnostic['id']] if diagnostic else [])
    def result(rule, assessment, reason, missing=None, evidence_refs=None):
        return dict(rule_id=rule, assessment=assessment, justification=reason,
                    additional_detail_needed=missing or [], evidence_refs=evidence_refs or refs)

    # A named epithelial lineage is an extra assertion, not implied by a site code.
    morphology = next((x for x in evidence if x['type'] == 'SNOMED'
                       and x.get('role') == '116676008' and 'epitelial' in normalize(x['text'])), None)
    if morphology and 'epitelial' in normalize(term['text']) and not affirmed(title['text'], r'\bepitelial(?:es)?\b'):
        if not diagnostic or not affirmed(diagnostic['text'], r'\bepitelial(?:es)?\b'):
            return result('epithelial_lineage_not_supported', 'undetermined',
                'El candidato SNOMED especifica una neoplasia epitelial, mientras que el código solo identifica el tumor maligno y su localización. Falta confirmar ese tipo histológico antes de proponer este candidato.',
                ['Confirmar el origen epitelial de la neoplasia.'], refs + [morphology['id']])

    # Compare the same explicit axis within the same disease family, not incidental numbers.
    code_stage, target_stage = renal_stage(title['text']), renal_stage(term['text'])
    if code_stage and target_stage:
        if code_stage[0] != target_stage[0] or (len(code_stage) > 1 and len(target_stage) > 1 and code_stage != target_stage):
            return result('explicit_renal_stage_conflict', 'incompatible',
                f'La CIE-10 indica estadio renal {code_stage} y el candidato SNOMED indica {target_stage}. Los estadios explícitos son distintos y no respaldan esta correspondencia.')
        if len(target_stage) > len(code_stage) and not (diagnostic and renal_stage(diagnostic['text']) == target_stage):
            return result('renal_substage_missing', 'undetermined',
                'El candidato añade un subestadio renal que el código no especifica. Falta respaldo para seleccionar ese detalle.', ['Confirmar el subestadio renal.'])
        if len(target_stage) < len(code_stage):
            return result('renal_substage_omitted', 'undetermined',
                'El código especifica un subestadio renal que el candidato no expresa. Debe comprobarse esa pérdida de detalle antes de seleccionar.', ['Comprobar la representación del subestadio renal.'])
        if diagnostic and 'renal' in normalize(diagnostic['text']) and 'cronic' in normalize(diagnostic['text']) and re.search(r'\b(?:etapa|estadio|stage)\b', normalize(diagnostic['text'])) and not renal_stage(diagnostic['text']):
            return result('diagnostic_renal_stage_ambiguous', 'undetermined',
                'El diagnóstico menciona estadios con negación, antecedentes o valores no unívocos. Debe aclararse el estadio actual antes de proponer la correspondencia.', ['Aclarar el estadio renal actual.'])
        if diagnostic and (input_stage := renal_stage(diagnostic['text'])):
            if input_stage[0] != code_stage[0] or (len(input_stage) > 1 and len(code_stage) > 1 and input_stage != code_stage):
                return result('diagnostic_renal_stage_conflict', 'incompatible',
                    f'El código indica estadio renal {code_stage}, pero el diagnóstico indica {input_stage}. Debe resolverse esta contradicción antes de proponer la correspondencia.')

    if 'diabet' in normalize(title['text']) and 'diabet' in normalize(term['text']):
        target_control = diabetes_control(term['text'])
        if target_control:
            code_control = diabetes_control(title['text'])
            input_control = diabetes_control(diagnostic['text']) if diagnostic else None
            if any(value and value != target_control for value in [code_control, input_control]):
                return result('explicit_diabetes_control_conflict', 'incompatible',
                    'El estado de control expresado en la entrada es distinto del que define el candidato SNOMED. Esa contradicción impide proponer la correspondencia.')
            if not code_control and not input_control:
                return result('diabetes_control_missing', 'undetermined',
                    'El candidato especifica un estado de control de la diabetes que la entrada no confirma. Las complicaciones no demuestran por sí mismas ese estado de control.', ['Confirmar el estado de control de la diabetes.'])
            if 'complicaciones multiples' in normalize(title['text']) and 'complicaciones multiples' not in normalize(term['text']):
                return result('diabetes_complications_not_control', 'undetermined',
                    'El código expresa complicaciones múltiples y el candidato expresa un estado de control. Son atributos diferentes; falta comprobar que el concepto represente el alcance requerido.', ['Comprobar la representación de las complicaciones múltiples.'])

    # An unspecified tissue is not an unspecified anatomical region. Do not turn
    # this scope check into an automatic positive equivalence.
    if diagnostic and scope_notes(evidence):
        region = re.fullmatch(r'(?:tumor maligno|neoplasia maligna) de(?:l| la)? (.+)', normalize(title['text']))
        unspecified = next((x for x in evidence if x['type'] == 'CIE10' and x.get('role') == 'exclusion'
                            and 'sitio no especificado' in normalize(x['text'])), None)
        if region and unspecified:
            words = set(re.findall(r'[a-z]+', region[1])) - {'de', 'del', 'la', 'el', 'y'}
            general = {'sitio', 'sitios', 'otro', 'otros', 'mal', 'definido', 'definidos', 'no', 'especificado', 'especificados'}
            if words and not words.intersection(general) and words <= set(re.findall(r'[a-z]+', normalize(diagnostic['text']))):
                return result('specified_region_unspecified_tissue', 'undetermined',
                    'La entrada identifica una región anatómica y declara que falta precisar el tejido. Esa ausencia no activa por sí sola la exclusión de sitio no especificado; debe revisarse el alcance del concepto antes de seleccionar.',
                    ['Comprobar que el alcance regional del candidato conserva la información disponible.'],
                    refs + [unspecified['id']])

    # A conditional inherited exclusion is applied only when its stated condition is explicit.
    poison = next((x for x in evidence if x['type'] == 'CIE10' and x.get('role') == 'hierarchy'
                   and 'envenenamiento por' in normalize(x['text'])), None)
    adverse = next((x for x in evidence if x['type'] == 'CIE10' and x.get('role') == 'exclusion'
                   and 'efectos adversos' in normalize(x['text'])
                   and 'administradas apropiadamente' in normalize(x['text'])), None)
    if poison and adverse and re.search(r'\b(?:alergia|reaccion alergica|efecto adverso|reaccion adversa)\b', normalize(term['text'])):
        use_refs = [poison['id'], adverse['id'], term['id']] + ([diagnostic['id']] if diagnostic else [])
        if diagnostic and affirmed(diagnostic['text'], r'\b(?:dosis correcta|dosis terapeutica|administrad[ao]s? apropiadamente)\b') and re.search(r'\b(?:no hubo sobredosis ni error|sin sobredosis ni error)\b', normalize(diagnostic['text'])):
            return result('proper_dose_adverse_effect_exclusion', 'incompatible',
                'El contexto CIE-10 corresponde a envenenamiento y excluye efectos adversos de sustancias administradas apropiadamente. El diagnóstico declara dosis correcta y ausencia de sobredosis y error; no respalda esta correspondencia.', evidence_refs=use_refs)
        return result('poisoning_not_allergy_equivalence', 'undetermined',
            'El contexto CIE-10 corresponde a envenenamiento y el candidato describe una alergia o reacción adversa. No puede asumirse equivalencia sin comprobar las circunstancias de administración.', ['Aclarar si hubo sobredosis, error o reacción a dosis apropiada.'], use_refs)
    return None


def scope_notes(evidence):
    diagnostic = next((x for x in evidence if x['type'] == 'INPUT'), None)
    if not diagnostic:
        return []
    if re.search(r'(?:sin|no)\s+(?:tejido de origen|histologia|tejido).*especific|sin especificar.*(?:tejido|histologia)', normalize(diagnostic['text'])):
        return ['No especificar tejido de origen o histología no equivale a no especificar la zona anatómica. Una exclusión de sitio no especificado no se activa solo por faltar histología.']
    return []
