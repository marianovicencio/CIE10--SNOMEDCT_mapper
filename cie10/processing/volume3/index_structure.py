"""Source-limited closure of the 2018 alphabetical index hierarchy."""

SOURCE_SHA256 = 'c95ef4b76916e3aced0faaa599c26c16c58544c46c952d6d2e0c4ad9d8cb5c5f'

def attach_index_notes(records):
    """Notes belong to a printed entry/subtree, not to its disease name."""
    # A continued heading is an address of the original indexed subtree.
    anchors = {r['id']: r for r in records}
    notes = [r for r in records if r['kind'] == 'index_note' and r.get('scope_anchor_id')]
    for note in notes:
        anchor = anchors.get(note['scope_anchor_id'])
        if not anchor: continue
        prefix = anchor.get('term_path', [])
        for r in records:
            if r['kind'] != 'index_entry': continue
            path = r.get('term_path', [])
            if (r['id'] == anchor['id'] or anchor['id'] in r.get('ancestor_entry_refs', [])
                    or r.get('continuation_of') == anchor['id']):
                r.setdefault('index_note_refs', []).append(note['id'])


def review_source_hierarchy(records):
    """Do not invent a parent that is missing from the printed hierarchy."""
    verified = {'v3-p25-l85', 'v3-p26-l36', 'v3-p49-l70', 'v3-p52-l77',
                'v3-p78-l105', 'v3-p165-l77', 'v3-p690-l7', 'v3-p751-l24'}
    ambiguous_prefixes=[]
    for r in records:
        if '[missing_ancestor]' not in r.get('term_path', []): continue
        r['hierarchy_requires_review'] = True
        if r['id'] in verified and r['sources'][0].get('source_sha256') == SOURCE_SHA256:
            r['source_hierarchy_review'] = {
                'status': 'source_ambiguity_preserved',
                'finding': 'printed_dash_depth_has_no_intermediate_parent',
                'printed_depth': r['depth'], 'no_parent_invented': True}
            r['warnings'] = [w for w in r['warnings'] if w != 'missing_ancestor']
            r['warnings'].append('source_hierarchy_ambiguity_preserved')
            pos=r['term_path'].index('[missing_ancestor]')
            ambiguous_prefixes.append(r['term_path'][:pos+1])
        elif any(r['term_path'][:len(p)]==p for p in ambiguous_prefixes):
            r['warnings']=[w for w in r['warnings'] if w!='missing_ancestor']
            r['warnings'].append('inherited_hierarchy_ambiguity')
