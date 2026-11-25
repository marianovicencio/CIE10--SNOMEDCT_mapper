"""Select complete comparison evidence without changing official stored content."""
import re
from cie10.explanations.explanation_constraints import normalize

STOP = {'enfermedad','tumor','neoplasia','maligno','maligna','trastorno','codigo','snomed',
        'tipo','paciente','una','uno','del','las','los','con','sin','por','para','que','como',
        'esta','este','estos','estas','sai','ncop'}


def terms(text):
    return {word[:6] for word in re.findall(r'[a-z]{3,}', normalize(text)) if word not in STOP}


def focus_evidence(evidence):
    anchors = [x for x in evidence if x.get('role') == 'candidate_term' or x['type']=='INPUT']
    query = terms(' '.join(x['text'] for x in anchors))
    diagnostic = normalize(' '.join(x['text'] for x in evidence if x['type']=='INPUT'))
    episode = bool(re.search(r'afeccion principal|episodio|motivo.{0,20}atencion', diagnostic))
    selected, omitted = [], []
    for item in evidence:
        role=item.get('role')
        reason=None
        words=terms(item.get('reading_text', item['text']))
        overlap=len(query & words)
        relevant=bool(words and (words <= query or overlap >= 2))
        heading=normalize(item['text'])
        if role in ('component_alignment','component_subsumption'):
            reason='verified_component_context_used_by_constraints_not_prompt_padding'
        elif role=='candidate_alias' and normalize(item['text']) not in diagnostic:
            reason='official_alias_retained_for_structural_comparison_not_prompt_padding'
        elif role=='manual_convention' and heading.startswith(('terminos de inclusion','terminos de exclusion')):
            reason='general_definition_available_for_review_not_case_evidence'
        elif role=='manual_guidance' and 'a continuacion se presentan ejemplos' in heading:
            reason='general_examples_not_specific_comparison_evidence'
        elif role=='manual_example':reason='worked_example_not_patient_evidence'
        elif role=='manual_support' and not relevant:reason='unrelated_documentary_dependency'
        elif role=='manual_guidance' and item.get('coding_context')=='main_condition_in_episode_of_care' and not episode:
            reason='episode_selection_not_requested'
        elif role in ('index_entry','index_table','index_note','index_remission') and item.get('selection_score',20)<20:
            reason='index_route_without_candidate_or_input_overlap'
        elif role in ('inclusions','notes','general_context'):
            if item.get('kind')=='classification_overview':reason='chapter_contents_not_comparison_evidence'
            elif not relevant:reason='no_specific_candidate_or_input_overlap'
        if reason:
            omitted.append(dict(id=item['id'],role=role,reason=reason))
        else:selected.append(item)
    # Do not pad absent relevant context with general definitions or worked examples.
    return selected, dict(method='whole_item_comparison_focus_v2',available_items=len(evidence),
                          selected_items=len(selected),omitted_items=omitted,patient_facts_inferred=False)
