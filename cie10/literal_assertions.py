"""Narrow literal checks, not a clinical NLP or diagnostic inference engine.

Only identical condition heads after removing listed qualifiers are compared.
Unknown paraphrases, scope and qualifiers remain for the normal review path.
"""
import re
from .explanation_constraints import normalize,source,unasserted

AXES={
 'course':{'chronic':r'\bcronic[ao]s?\b','acute':r'\bagud[ao]s?\b'},
 'etiology':{'bacterial':r'\bbacterian[ao]s?\b','viral':r'\b(?:viral(?:es)?|viric[ao]s?)\b'}}
QUESTIONS={'course':'Precisar el curso agudo o crónico de la afección.','etiology':'Precisar la etiología de la afección.'}
OTHER=r'\b(?:su|mi|el|la|un|una)\s+(?:madre|padre|herman[ao]|hij[ao]|acompanante|familiar)\b'

def clauses(text):
 return [p.strip() for p in re.split(r'[.;:!?\n]+|\bpero\b|\bsin embargo\b|\baunque\b',normalize(text)) if p.strip()]

def qualifiers(text):
 return {axis:{name for name,pattern in values.items() if re.search(pattern,normalize(text))} for axis,values in AXES.items()}

def head(text):
 text=normalize(text)
 text=re.sub(r'\((?:trastorno|hallazgo)\)','',text)
 text=re.sub(r'\b(?:no especificad[ao]s?|sin otra especificacion|sin especificar|sai)\b','',text)
 for values in AXES.values():
  for pattern in values.values():text=re.sub(pattern,'',text)
 return ' '.join(re.findall(r'[a-z0-9]+',text))

def literal_constraint(evidence):
 title=source(evidence,'CIE10','title','cie-title');term=source(evidence,'SNOMED','candidate_term','snomed-term')
 entry=next((x for x in evidence if x['type']=='INPUT'),None)
 if not title or not term:return None
 base=head(title['text'])
 if len(base)<3 or base!=head(term['text']):return None
 pattern=r'\b'+re.escape(base).replace(r'\ ',r'\s+')+r'\b'
 refs=[title['id'],term['id']]+([entry['id']] if entry else [])
 def result(rule,assessment,reason,missing=None):
  return {'rule_id':'literal_'+rule,'assessment':assessment,'justification':reason,'additional_detail_needed':missing or [],'evidence_refs':refs}
 text=normalize(entry['text']) if entry else '';parts=clauses(text)
 # Exact unqualified denials only; no broad negation-window inference.
 term_phrase=normalize(term['text']);term_phrase=re.sub(r'\((?:trastorno|hallazgo)\)','',term_phrase).strip()
 denial_pattern='(?:'+pattern+'|'+r'\b'+re.escape(term_phrase).replace(r'\ ',r'\s+')+r'\b)'
 neg=r'\b(?:no\s+(?:hay|tiene|presenta|padece)|niega|sin|se\s+descarta)\s+(?:(?:la|el|un|una)\s+)?'+denial_pattern+r'\s*$'
 negatives=[];affirmations=[];uncertain=False
 for part in parts:
  found=re.search(neg,part)
  if found:
   prefix=part[:found.start()]
   contextual=bool(re.search(r'\b(?:si|cuando|posible|sospecha|antecedente|antecedentes|historia)\b',prefix))
   other=bool(re.search(OTHER,part)) and not re.search(r'\bpaciente\b',prefix)
   double=bool(re.search(r'\bno\s*$',prefix))
   if contextual or other or double:uncertain=True
   else:negatives.append(part)
  positive=re.search(r'\b(?:hay|tiene|presenta|padece|se confirma|se diagnostica)\s+(?:(?:la|el|un|una)\s+)?'+pattern,part)
  if positive and not unasserted(part,positive.start()) and not re.search(OTHER,part):affirmations.append(part)
  if re.search(r'\bno se descarta\s+'+pattern,part):uncertain=True
 if negatives:
  if affirmations:return result('contradictory_input','undetermined','La entrada contiene afirmaciones y negaciones de la misma afección que comparan CIE-10 y SNOMED. Debe aclararse esa contradicción antes de proponer el candidato.',['Aclarar si la afección está afirmada en el diagnóstico actual.'])
  return result('condition_explicitly_denied','incompatible','La entrada niega explícitamente la afección que comparan CIE-10 y SNOMED. Esa contradicción impide proponer este candidato; debe aclararse el diagnóstico registrado.')
 if uncertain:return result('condition_assertion_uncertain','undetermined','La entrada menciona la afección en un contexto hipotético, negado o referido a otra persona. Ese texto no basta para respaldar la comparación CIE-10 y SNOMED.',['Aclarar la afirmación actual de la afección en la entrada.'])
 if entry and any(re.search(pattern,p) and re.search(OTHER,p) for p in parts) and not affirmations:
  return result('other_subject','undetermined','La entrada relaciona la afección con otra persona y no confirma su atribución al caso consultado. La comparación CIE-10 y SNOMED requiere aclarar ese alcance.',['Confirmar a quién corresponde la afección mencionada.'])
 target=qualifiers(term['text']);coded=qualifiers(title['text']);missing=[]
 relevant=[part for part in parts if re.search(pattern,part)]
 for axis,values in target.items():
  if len(values)!=1:continue
  value=next(iter(values))
  if value in coded[axis]:continue
  # Unrecognized paraphrases are delegated; they are never auto-approved.
  if entry and not relevant:continue
  supported=any(any(not unasserted(part,m.start()) for m in re.finditer(AXES[axis][value],part)) for part in relevant)
  if not supported:missing.append(QUESTIONS[axis])
 if missing:return result('additional_qualifier_unconfirmed','undetermined','El candidato SNOMED añade un calificador que el título CIE-10 y la entrada disponible no respaldan explícitamente. Falta precisar ese detalle antes de proponer la correspondencia.',missing)
 return None
