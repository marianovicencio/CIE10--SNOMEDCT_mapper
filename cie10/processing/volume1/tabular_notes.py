"""Interpret visible tabular conventions without supplying new clinical information.

OPS/OMS volume 2, sections 3.1.2 and 3.1.4: inclusion terms, colons,
braces, SAI and fourth-character hyphens. Original fragments remain available.
"""
import re
from itertools import groupby

from cie10.common import code_references, normalize
from cie10.processing.volume1.tabular_reviewed import apply_reviewed_layout

VERSION = "tabular-notes-v7"
BRACES = re.compile(r"[⎫⎬⎭⎪{}]")
TOP = re.compile(r"[⎫]")
BOTTOM = re.compile(r"[⎭]")
BULLET = re.compile(r"^\s*(?:[•●]|[-–—](?=\s)(?!\s*(?:ver|véase)\b)|\(cid:127\))\s*", re.I)
NARRATIVE = re.compile(
    r"^(?:El |La |Los |Las |Este |Esta |Estos |Estas |Se |Son |Es |"
    r"Incluye:|Excluye:|Nota:|Use |Utilice |Codifique |Ver |Véase |\[(?:Ver|Para|Véase))|"
    r"\b(?:se define|se refiere|se caracteriza|debe[n]? |puede[n]? |consiste en|"
    r"tales como|cuyo |cuya |para identificar|para indicar|que comienza|en la cual|por ejemplo)\b", re.I)


def unique_sources(items):
    result, seen = [], set()
    for source in items:
        key = (source.get("volume"), source.get("pdf_page"), source.get("line_id"))
        if key not in seen:
            result.append(source)
            seen.add(key)
    return result


def sources_of(fragment):
    return fragment.get("sources", [fragment["source"]])


def reference_details(text, polarity):
    references = []
    for raw in code_references(text):
        compact = re.sub(r"\s+", "", raw)
        unspecified = re.fullmatch(r"([A-Z]\d{2})\.[–—-]", compact)
        item = {"raw": raw, "polarity": polarity}
        if unspecified:
            item.update(kind="category_with_unspecified_fourth_character",
                        category=unspecified.group(1), scope="all_subcategories",
                        usable_as_final_code=False, requires_fourth_character_lookup=True,
                        requires_specificity_review=polarity != "exclusion")
        elif re.fullmatch(r"[A-Z]\d{2}", compact):
            item.update(kind="category", category=compact, scope="category_and_subcategories")
        elif re.fullmatch(r"[A-Z]\d{2}\.\d{1,2}[†*]?", compact):
            item.update(kind="subcategory", scope="specified_code")
        else:
            item.update(kind="range_or_compound_reference", scope="referenced_range", requires_structure_review=True)
        references.append(item)
    return references


def expand_simple_braces(fragments):
    """Resolve only closing braces with separate visible left/right text fragments.

    Full glyph bounds, at least two left members, one right qualifier and a
    single source page are required. Other arrangements are one unresolved group,
    never independent exclusions of individual brace pieces.
    """
    fragments = expand_positioned_braces(fragments)
    output, unresolved = [], []
    i = 0
    while i < len(fragments):
        first = fragments[i]
        if not BRACES.search(first["text"]):
            output.append(first)
            i += 1
            continue
        end = next((j for j in range(i, len(fragments)) if BOTTOM.search(fragments[j]["text"])), None)
        if not TOP.search(first["text"]) or end is None:
            # Keep all remaining fragments together when a boundary is not recoverable.
            chunk = fragments[i:]
            unresolved.append({"reason": "unresolved_brace_geometry", "fragments": chunk})
            break
        chunk = fragments[i:end + 1]
        standalone = [f for f in chunk if not BRACES.sub("", f["text"]).strip()]
        pages = {f["source"]["pdf_page"] for f in chunk}
        if standalone and len(pages) == 1:
            brace_x = min(f["source"]["bbox"][0] for f in standalone)
            left, right = [], []
            for fragment in chunk:
                clean = normalize(BRACES.sub("", fragment["text"]))
                if not clean:
                    continue
                f = dict(fragment, text=clean)
                x = fragment["source"]["bbox"][0]
                if x < brace_x - 3:
                    left.append(f)
                elif x > brace_x + 3:
                    right.append(f)
            safe = (len(left) >= 2 and len(right) == 1 and
                    len(left) + len(right) == sum(bool(normalize(BRACES.sub("", f["text"]))) for f in chunk)
                    and not any(f["text"].endswith(":") for f in left + right))
            if safe:
                shared = right[0]
                for member in left:
                    output.append(dict(member,
                        text=normalize(member["text"] + " " + shared["text"]),
                        sources=unique_sources(sources_of(member) + sources_of(shared) +
                                               [f["source"] for f in standalone]),
                        composition="brace_shared_qualifier", member_text=member["text"],
                        shared_qualifier=shared["text"]))
            else:
                unresolved.append({"reason": "unresolved_brace_geometry", "fragments": chunk})
        else:
            unresolved.append({"reason": "unresolved_brace_geometry", "fragments": chunk})
        i = end + 1
    return output, unresolved


def expand_positioned_braces(fragments):
    """Resolve a single vertical closing brace from character positions.

    Both delimiter ends, all member text and a shared right-hand phrase must be
    present. Nested/overlapping axes remain in the legacy review path.
    """
    result = list(fragments)
    pages = {f['source']['pdf_page'] for f in result}
    for page in pages:
        fs = [f for f in result if f['source']['pdf_page']==page]
        marks = [(f,c) for f in fs for c in f.get('glyphs',[]) if BRACES.search(c['text'])]
        for _, top in [x for x in marks if TOP.search(x[1]['text'])]:
            x = top['x0']
            ends = [c for _,c in marks if BOTTOM.search(c['text']) and abs(c['x0']-x)<2 and c['top']>top['top']]
            if not ends:
                continue
            bottom = min(ends,key=lambda c:c['top'])
            y0,y1 = top['top']-8,bottom['bottom']
            if any(abs(c['x0']-x)>2 and y0 <= c['top'] <= y1 for _,c in marks):
                continue
            chunk = [f for f in fs if y0 <= f['source']['bbox'][1] <= y1-5
                     and not (f['source']['bbox'][1]>bottom['top'] and f['text'].endswith(':'))]
            if not chunk or any(not f.get('glyphs') for f in chunk):
                continue
            left,right = [],[]
            for f in chunk:
                glyphs=[c for c in f['glyphs'] if not BRACES.search(c['text'])]
                def phrase(cs):
                    text, previous = '', None
                    for c in sorted(cs,key=lambda c:c['x0']):
                        if previous is not None and c['x0']-previous['x1']>1.5:
                            text += ' '
                        text += c['text']
                        previous=c
                    return normalize(text)
                a=phrase([c for c in glyphs if c['x1']<=x+1])
                a=re.sub(r'^(?:Incluye|Excluye):\s*', '', a, flags=re.I)
                b=phrase([c for c in glyphs if c['x0']>x+3])
                if a: left.append((f,a))
                if b: right.append((f,b))
            if len(left)<2 or not right:
                continue
            joined_left=[]
            for f,t in left:
                if (joined_left and t[0].islower() and not BULLET.match(t)
                        and re.search(r'\b(?:o|de|las vías|respiratorias superiores)$',joined_left[-1][1])):
                    previous, phrase_text=joined_left[-1]
                    joined_left[-1]=(previous,normalize(phrase_text+' '+t))
                else:
                    joined_left.append((f,t))
            left=joined_left
            if len(left)<2:
                continue
            if any(t.endswith(':') for _,t in left):
                local=[dict(f,text=t,glyphs=[]) for f,t in left]
                leaves,issues=logical_notes(local,'inclusion',{},'brace_members')
                if issues:
                    continue
                left=[(leaf,leaf['text']) for leaf in leaves]
            shared=normalize(' '.join(t for _,t in right))
            sources=unique_sources([f['source'] for f in chunk])
            composed=[dict(f,text=normalize(t+' '+shared),glyphs=[],sources=sources,
                composition='brace_shared_qualifier',member_text=t,shared_qualifier=shared) for f,t in left]
            start=min(result.index(f) for f in chunk if f in result)
            result=[f for f in result if f not in chunk]
            result[start:start]=composed
    return result


def logical_notes(fragments, polarity, context, basis):
    result, issues = [], []
    # Reset prefix inheritance at every explicit Incluye/Excluye block.
    for _, block_iter in groupby(fragments, lambda f: f.get("block_id")):
        block = list(block_iter)
        block, brace_issues = expand_simple_braces(block)
        issues.extend(dict(issue, polarity=polarity) for issue in brace_issues)
        stack = []
        last = None
        returned_to_root = False
        right_margin=max((f['source']['bbox'][2] for f in block),default=0)

        def close_prefixes(depth=0):
            nonlocal stack
            for prefix in stack[depth:]:
                if not prefix["used"]:
                    issues.append({"reason": "prefix_without_resolved_children", "polarity": polarity,
                                   "fragments": [prefix["fragment"]]})
            stack = stack[:depth]

        for index, fragment in enumerate(block):
            text = normalize(fragment["text"])
            if not text:
                continue
            source = fragment["source"]
            x = fragment.get('layout_x', source["bbox"][0])
            bullet = BULLET.match(text) is not None
            bare = BULLET.sub("", text)
            next_bullet = index+1<len(block) and bool(BULLET.match(block[index+1]['text']))
            next_is_brace_member = (index+1<len(block) and
                block[index+1].get('composition', '').startswith('brace_') and
                block[index+1].get('starts_independent_brace_group',False))
            grammatical_prefix = not bullet and next_bullet and bool(re.search(r'\((?:de\b|del\b|en\b)[^)]*\)$', bare))
            # Wrapped lines (including a code on its own) continue the previous leaf.
            if (not bullet and last is not None and
                    not fragment.get('composition','').startswith(('brace_','visually_reviewed','reviewed_')) and
                    not last['entry'].get('composition','').startswith(('brace_','visually_reviewed','reviewed_'))):
                same_page = source["pdf_page"] == last["last_source"]["pdf_page"]
                y_gap = source["bbox"][1] - last["last_source"]["bbox"][3]
                indented = (x > last["x"] + 2 or (bare.startswith('[') and not NARRATIVE.search(bare))
                            or bool(re.match(r'^[—–-]\s*(?:ver|véase)\b',bare,re.I)))
                complete_reference = re.search(r"\([A-Z]\d{2}[^)]*\)\s*$", last["entry"]["text"])
                # Full-width terms also wrap at the same left margin. A close
                # baseline, a long preceding line and lower-case continuation
                # are required; a completed destination code closes the term.
                previous_box = last['last_source']['bbox']
                aligned_wrap = (abs(x-previous_box[0])<=2 and y_gap<=2 and
                    previous_box[2]-previous_box[0]>200 and
                    previous_box[2]>=right_margin-12 and
                    len(last['entry']['text'])>55 and bare[0].islower() and
                    not re.search(r'[.;!?]$',last['entry']['text']))
                if (same_page and -2 <= y_gap <= 14 and (indented or aligned_wrap)
                        and not complete_reference and (not bare.endswith(':') or
                            (len(last['entry']['text'])>55 and previous_box[2]-previous_box[0]>200
                             and (len(last['entry']['sources'])==1 or abs(last['x']-previous_box[0])<=2)))):
                    entry = last["entry"]
                    entry["text"] = normalize(entry["text"] + " " + bare)
                    entry["sources"] = unique_sources(entry["sources"] + sources_of(fragment))
                    entry["composition"] = "wrapped_" + entry["composition"]
                    last["last_source"] = source
                    if bare.endswith(':'):
                        # A prefix may itself span multiple physical lines.
                        # Remove the provisional leaf before opening its list.
                        result.remove(entry)
                        stack.append({'text':entry['text'].rstrip(':').strip(),
                                      'x':last['x'],'bullet':False,'fragment':entry,'used':False})
                        last = None
                    elif next_bullet and not stack and not last['bullet'] and not next_is_brace_member:
                        stem = re.sub(r'\s*\([^()]*[A-Z]\d{2}[^()]*\)\s*$', '', entry['text']).strip()
                        stack.append({'text':stem,'x':last['x'],'bullet':False,
                                      'fragment':entry,'used':False,'implicit_root':True})
                    continue
            if bullet:
                while stack:
                    prefix=stack[-1]
                    if prefix['bullet'] and x<=prefix['x']+2:
                        close_prefixes(len(stack)-1)
                    elif (not prefix['bullet'] and not prefix.get('implicit_root') and prefix.get('child_x') is not None
                          and abs(x-prefix['x'])<=2 and x<prefix['child_x']-2):
                        # Unbulleted labels end too when the list returns to
                        # its outer margin (e.g. supervision vs obstetric tetanus).
                        close_prefixes(len(stack)-1)
                        returned_to_root = not stack
                    else:
                        break
            else:
                # A colon can introduce indented children without printed bullets.
                if any(p.get("bullet_children") for p in stack):
                    close_prefixes()
                while stack and x <= stack[-1]["x"] + 2:
                    if (not stack[-1]['bullet'] and re.search(r'debid[oa] a$|\((?:de\b|del\b|en\b)[^)]*\)$',stack[-1]['text'],re.I)
                            and abs(x-stack[-1]['x'])<=2):
                        break
                    close_prefixes(len(stack) - 1)
            if bare.endswith(":") or grammatical_prefix:
                if bullet:
                    for prefix in stack:
                        prefix.setdefault('child_x',x)
                stack.append({"text": bare.rstrip(':').strip(), "x": x, "bullet": bullet,
                              "fragment": fragment, "used": False})
                last = None
                continue
            ancestors = [p["text"] for p in stack]
            for prefix in stack:
                prefix["used"] = True
                if bullet:
                    prefix["bullet_children"] = True
                    prefix.setdefault('child_x', x)
            entry = {
                "text": normalize(" ".join(ancestors + [bare])),
                "source": source,
                "sources": unique_sources([s for p in stack for s in sources_of(p["fragment"])] + sources_of(fragment)),
                "composition": fragment.get("composition", "colon_prefix" if ancestors else "literal"),
                "prefix_path": ancestors, "basis": basis,
                "classification_context": dict(context),
            }
            for key in ("member_text", "shared_qualifier", "examples", "scope_statement", "source_ambiguity_preserved"):
                if key in fragment:
                    entry[key] = fragment[key]
            if bullet and not stack and not returned_to_root and basis not in ('implicit_under_code_heading','brace_members') and not fragment.get('composition','').startswith('brace_'):
                entry["requires_structure_review"] = True
                issues.append({"reason": "bullet_without_prefix", "polarity": polarity, "fragments": [fragment]})
            result.append(entry)
            last = {"entry": entry, "x": x, "last_source": source, 'bullet':bullet}
            if not bullet and next_bullet and not next_is_brace_member and not bare.endswith(':'):
                # A codable root can also qualify subsequent bullets. The root's
                # destination is not inherited by children with their own codes.
                stem = re.sub(r'\s*\([^()]*[A-Z]\d{2}[^()]*\)\s*$', '', bare).strip()
                stack.append({'text':stem,'x':x,'bullet':False,'fragment':fragment,'used':False,'implicit_root':True})
        close_prefixes()
    for entry in result:
        entry["references"] = reference_details(entry["text"], polarity)
        entry["qualifiers"] = ([{"token": "SAI", "meaning": "sin otra indicación"}]
                               if re.search(r"\bSAI\b", entry["text"]) else [])
    return result, issues


def is_implicit_term_list(fragments):
    """Accept short subordinate term lists, not general explanatory prose.

    This conservative boundary deliberately leaves glossary paragraphs, brackets,
    instructions and uncertain layouts pending rather than calling every line a term.
    """
    texts = [f["text"] for f in fragments if f["text"].strip()]
    return bool(texts) and all(
        len(t) <= 140 and not NARRATIVE.search(BRACES.sub("", t).strip())
        and not re.search(r"[.!?]$", t) and f["source"]["bbox"][0] >= 79
        for f in fragments if (t := f["text"].strip())
    )


def normalize_record_notes(record):
    record["tabular_note_version"] = VERSION
    record["raw_note_fragments"] = {key: record[key] for key in ("inclusions", "exclusions", "unclassified")}
    apply_reviewed_layout(record)
    from cie10.processing.volume1.tabular_review_v6 import apply_reviewed_blocks
    apply_reviewed_blocks(record)
    record['variants']=[]
    if record['unclassified'] and record['unclassified'][0]['text'].strip().lower()=='variante:':
        original=record['unclassified']
        if all(not BULLET.match(f['text']) and not f['text'].endswith(':') for f in original[1:]):
            record['variants']=[dict(text=f['text'], source=f['source'], sources=[original[0]['source'],f['source']],
                                     applies_to_code=record.get('code')) for f in original[1:]]
            record['unclassified']=[]
    context = {"code": record.get("code"), "description": record["description"]}
    issues = []
    for key, polarity in [("inclusions", "inclusion"), ("exclusions", "exclusion")]:
        record[key], found = logical_notes(record[key], polarity, context, "explicit_label")
        issues.extend(found)
    if record["kind"] == "code" and is_implicit_term_list(record["unclassified"]):
        implicit, found = logical_notes(record["unclassified"], "inclusion", context, "implicit_under_code_heading")
        record["inclusions"].extend(implicit)
        record["unclassified"] = []
        issues.extend(found)
    record["note_structure_issues"] = issues
    unresolved_braces = any("brace" in issue["reason"] for issue in issues) or any(
        BRACES.search(f["text"]) for key in ("unclassified", "instructions", "notes") for f in record[key])
    if not unresolved_braces:
        record["warnings"] = [w for w in record["warnings"] if w != "brace_group_requires_visual_review"]
    if any("prefix" in issue["reason"] for issue in issues):
        record["warnings"].append("note_prefix_requires_review")
    return record
