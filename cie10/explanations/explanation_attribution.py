"""Check attribution boundaries per claim; this is not clinical entailment validation."""
import re
from cie10.explanations.explanation_constraints import normalize, unasserted


def source_category(item):
    if item['type'] == 'INPUT': return 'input'
    if item.get('volume') == 2: return 'manual'
    if item.get('volume') == 3: return 'index'
    if item['type'] == 'SNOMED': return 'snomed'
    return item.get('role', 'tabular')


def comparable(text):
    return re.sub(r'[^a-z0-9 ]', '', normalize(text))


def validate_claim_attribution(text, refs, sources):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('La afirmación debe contener texto.')
    cited = [sources[ref] for ref in refs]
    categories = {source_category(item) for item in cited}
    prose = normalize(text)
    if re.search(r'\b(?:candidate_term|user_text|finding_site|associated_morphology)\b', prose):
        raise ValueError('Elimina nombres internos de campos; usa los nombres de las fuentes.')
    cited_text = normalize(' '.join(item['text'] for item in cited))
    for stem in ('citotoxic','fisiopatolog','mediado por celulas','mecanismo inmun'):
        if stem in prose and stem not in cited_text:
            raise ValueError('La afirmación añade un mecanismo que las fuentes citadas no respaldan.')
    if re.search(r'\bpaciente (?:presenta|tiene|padece|sufre)\b|\b(?:condicion|enfermedad) se caracteriza por\b|caracterizad[ao] por',prose):
        raise ValueError('Explica la comparación documental, no un diagnóstico ni una descripción fisiopatológica del paciente.')
    requirements = [
        (r'\b(?:diagnostico|texto aportado|entrada del usuario|paciente)\b', 'input', 'La afirmación sobre el diagnóstico o paciente debe citar su entrada; el libro no demuestra hechos del paciente.'),
        (r'\b(?:titulo|categoria cie|codigo cie)\b', 'title', 'La afirmación sobre el título CIE-10 debe citar el título.'),
        (r'\b(?:manual|guia|tomo (?:2|ii)|volumen (?:2|ii))\b', 'manual', 'La afirmación invoca el manual sin citar ese pasaje.'),
        (r'indice alfabetico|indice cie(?:-?10)?|ruta del indice|tomo (?:3|iii)\b|volumen (?:3|iii)\b|tabla de (?:tumores|medicamentos)', 'index', 'La afirmación invoca el índice sin citar esa fuente.'),
        (r'\binclusion(?:es)?\b', 'inclusions', 'Un atributo SNOMED no es una inclusión CIE-10: cita la inclusión real.'),
        (r'\b(?:exclusion(?:es)?|excluye)\b', 'exclusion', 'La afirmación sobre una exclusión debe citar esa exclusión.'),
    ]
    for pattern, category, message in requirements:
        if any(category != 'input' or not unasserted(prose, match.start()) for match in re.finditer(pattern, prose)) and category not in categories:
            raise ValueError(message)
    # Literal quotations must come from sources of this claim. When an explicit
    # source label precedes the quote, validate against that category, not any book.
    for match in re.finditer(r'[«“‘"]([^»”’"]{12,})[»”’"]', text):
        prefix = normalize(text[max(0, match.start()-80):match.start()])
        prefix = re.split(r'[.;\n]',prefix)[-1]
        markers = []
        for category, pattern in [('input',r'diagnostico|texto aportado|entrada del usuario'),
                                  ('title',r'titulo(?: cie-?10)?|codigo cie-?10|termino cie-?10|categoria cie-?10'),
                                  ('snomed',r'termino snomed|concepto snomed|candidato snomed|codigo snomed'),
                                  ('inclusions',r'inclusion'),('exclusion',r'exclusion')]:
            markers.extend((m.start(),category) for m in re.finditer(pattern,prefix))
        category = max(markers)[1] if markers else None
        possible = [item for item in cited if not category or source_category(item)==category]
        quote = comparable(match[1])
        if not any(quote in comparable(item['text']) for item in possible):
            raise ValueError('La cita textual no pertenece a la fuente atribuida en esta afirmación.')


def source_label(item):
    category=source_category(item)
    labels={'input':'Entrada del usuario','manual':'Manual · tomo 2','index':'Índice · tomo 3',
            'title':'Título CIE-10','inclusions':'Inclusión CIE-10','exclusion':'Exclusión CIE-10',
            'hierarchy':'Jerarquía CIE-10','notes':'Nota CIE-10'}
    if category=='snomed':
        if item.get('role')=='parent': return 'Concepto superior SNOMED CT'
        if item.get('role') in ('component_alignment','component_subsumption'):
            return 'Componente o relación SNOMED verificada'
        return 'Descripción alternativa oficial SNOMED' if item.get('role')=='candidate_alias' else 'Término del candidato SNOMED' if item.get('role')=='candidate_term' else 'Atributo o jerarquía SNOMED'
    return labels.get(category,'Contexto tabular CIE-10')


def validate_mapping_comparison(text):
    """Reject a disease summary that does not explain the documentary comparison."""
    prose=normalize(text)
    has_cie=re.search(r'cie[- ]?10|\bcodigo\b|\bcategoria\b|\btitulo\b',prose)
    has_target=re.search(r'snomed|\bcandidato\b|\bconcepto\b',prose)
    has_relation=re.search(r'coincid|compart|correspond|compar|difer|contradi|encaj|compatib|concuerd|especific|falta|omite|requiere',prose)
    if not (has_cie and has_target and has_relation):
        raise ValueError('Explica la relación entre CIE-10 y el candidato SNOMED: qué comparten, qué difiere o qué falta. No basta resumir la enfermedad.')
    if re.search(r'\bse define como\b|\bse caracteriza por\b|\bcaracterizad[ao] por\b',prose):
        raise ValueError('Elimina definiciones clínicas o fisiopatología: explica únicamente la comparación respaldada por las fuentes.')
