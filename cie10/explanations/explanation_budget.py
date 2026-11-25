"""Fit complete evidence items to the actual local tokenizer; report every omission."""
import json
from cie10.explanations.explanation_limits import (
    LOCAL_MAX_NEW_TOKENS,
    LOCAL_REPAIR_RESERVE_TOKENS,
    LOCAL_CONTEXT_TOKENS,
)
from urllib.request import Request, urlopen
from cie10.explanations.candidate_explanation import ExplanationError, generation_setup, gemma_turn
from cie10.explanations.explanation_focus import focus_evidence


def fit_model_evidence(concept_id, diagnostic, evidence, endpoint, tokenizer=None):
    def count(items):
        _, prompt = generation_setup(concept_id, diagnostic, items, profile="local")
        rendered = gemma_turn(prompt, bool(diagnostic))
        if tokenizer:
            return tokenizer(rendered)
        request = Request(endpoint.rstrip('/') + '/tokenize',
            data=json.dumps(dict(content=rendered, add_special=False, parse_special=True)).encode(),
            headers={'Content-Type':'application/json'})
        try:
            with urlopen(request, timeout=15) as response:
                return len(json.load(response)['tokens'])
        except (OSError, ValueError, KeyError) as error:
            raise ExplanationError('No se pudo comprobar el tamaño del contexto.') from error
    selected, relevance = focus_evidence(evidence)
    omitted = list(relevance['omitted_items'])
    # Titles, local terms, input, exclusions, inclusions, instructions and SNOMED
    # site/morphology stay intact. Optional supporting items may be omitted whole.
    priority = {'general_context':0, 'manual_example':1, 'manual_support':2,
                'hierarchy':3, 'parent':4, 'notes':5, 'manual_guidance':6, 'manual_convention':7,
                'index_note':5, 'index_remission':7, 'index_entry':8, 'index_table':8}
    while (tokens := count(selected)) + LOCAL_MAX_NEW_TOKENS + LOCAL_REPAIR_RESERVE_TOKENS > LOCAL_CONTEXT_TOKENS:
        volume_counts = {volume: sum(x.get('volume') == volume for x in selected) for volume in (2,3)}
        removable = [x for x in selected if x.get('role') in priority
                     and not (x.get('volume') in volume_counts and volume_counts[x['volume']] <= 1)]
        if not removable:
            raise ExplanationError('El núcleo obligatorio y las fuentes documentales mínimas exceden la ventana del modelo.')
        item = min(removable, key=lambda x:(priority[x['role']], x.get('selection_score',0), -len(x['text']), x['id']))
        selected.remove(item)
        omitted.append(dict(id=item['id'], role=item.get('role'), reason='whole_item_token_budget'))
    return selected, dict(input_tokens=tokens, max_new_tokens=LOCAL_MAX_NEW_TOKENS, repair_reserve_tokens=LOCAL_REPAIR_RESERVE_TOKENS, context_limit=LOCAL_CONTEXT_TOKENS,
        included_evidence_ids=[x['id'] for x in selected], omitted_items=omitted,
        truncated_text=False, relevance_selection=relevance, coverage='selected_whole_items_not_all_retrieved_context')
