"""Read-only, local documentary API for the three CIE-10 2018 volumes.

Bindings describe retrieval roles, not applicability to a patient/certificate.
No SNOMED mapping, diagnosis inference or automatic recoding is performed.
"""
import json
import hashlib
import re
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote
from cie10.common import ROOT, read_jsonl, read_json, write_json, sha256

VERSION='0.8'
CODE=re.compile(r'^[A-Z]\d{2}(?:\.\d{1,2})?$')
CODE_PREFIX = re.compile(r'[A-Z](?:[0-9]{0,2}|[0-9]{2}\.[0-9]{0,2})')
DB=ROOT/'data/compiled/full/context.sqlite'


def expression_bounds(expression):
    text=re.sub(r'[†*\s]','',expression.upper()).replace('–','-').replace('—','-')
    if re.fullmatch(r'[A-Z]\d{2}\.\-',text): return text[:3],text[:3]+'~','family'
    if CODE.fullmatch(text):
        return (text,text+'~','category') if len(text)==3 else (text,text,'exact')
    match=re.fullmatch(r'([A-Z]\d{2}(?:\.\d{1,2})?)-([A-Z]?\d{2}(?:\.\d{1,2})?)',text)
    if match:
        low,high=match.groups()
        if high[0].isdigit(): high=low[0]+high
        if low<=high: return low,high+'~','range'
    return None


def bindings(dataset,record):
    """Emit explicit links; incidental code mentions retain that distinct role."""
    def pairs(values,role): return [(v,role) for v in values if v]
    if dataset=='vol1_tabular': return pairs([record.get('code')],'tabular_heading')
    if dataset=='vol2_document_units':
        from cie10.processing.volume2.manual_units import STRUCTURED
        section=(record.get('section') or {}).get('number','')
        if not section or section.startswith(STRUCTURED): return []
        return pairs(record.get('code_references',[]),'documentary_code_mention')+pairs(record.get('context_code_expressions',[]),'parent_section_context')
    if dataset=='vol2_specific_notes':
        return pairs(record.get('subject_code_expressions',[]),'chapter_guidance' if record['kind']=='manual_chapter_guidance' else 'instruction_subject')+pairs(record.get('code_references',[]),'example_mention' if record['kind']=='manual_worked_example' else 'instruction_mention')
    if dataset=='vol2_association_blocks':
        links=pairs(record.get('subject_code_expressions',[]),'provisional_underlying_cause')
        for row in record.get('condition_rows',[]):
            links+=pairs(row.get('condition_code_expressions',[]),'association_condition')
            links+=pairs([o['code_expression'] for o in row.get('outcome_mentions',[])],'association_outcome')
        return links
    if dataset=='vol2_diabetes_sequences':
        return pairs([record.get('diabetes_code')],'causal_sequence_diabetes')+pairs([record.get('cause_code_expression')],'causal_sequence_cause')
    if dataset=='vol2_annex_code_candidates': return pairs([record.get('code_expression')],'annex_entry')
    if dataset=='vol2_code_rule_candidates': return pairs([record.get('code_expression')],'underlying_cause_restriction')+pairs(record.get('recode_candidates',[]),'conditional_recode_candidate')
    if dataset=='vol2_manual':
        section=(record.get('section') or {}).get('number','')
        if section.startswith(('4.2.5','4.3.7','4.5.4','7.3','7.4','7.6','7.7','7.8')):
            return []  # The structured datasets supply these links; original passages remain retrievable.
    if dataset.startswith('vol3_') and dataset!='vol3_transport_matrix' and record.get('cells'):
        links=[]
        for column,cell in record['cells'].items():
            if not cell: continue
            value=cell.get('documentary_interpretation',{}).get('code_expression') or cell['text']
            role='table_column:'+column
            if cell.get('review_status')=='source_ambiguity_preserved':
                links+=pairs(cell.get('candidate_code_expressions',[]),'ambiguous_table_candidate:'+column)
            elif cell.get('code_family'):
                links+=pairs([category+value for category in cell.get('category_scope',[cell['code_family']])],role)
            else: links+=pairs([value],role)
        return links
    if dataset=='vol3_index_conventions': return []
    if dataset.startswith('vol3_index'): return pairs(record.get('code_references',[]),'index_note_code_mention' if record['kind']=='index_note' else 'index_explicit_reference')
    if dataset=='vol3_transport_matrix':
        from cie10.common import code_references
        return [(expr,'transport_collision:'+column) for column,value in record.get('columns',{}).items() if value for expr in code_references(value)]
    if dataset=='vol3_remissions': return pairs(record.get('target_code_expressions',[]),'remission_code_target')
    if dataset=='vol3_index_conventions': return []
    return pairs(record.get('code_references',[]),'unresolved_code_mention')


def build_database(mode='full',destination=None):
    source=ROOT/'data/processed'/mode
    destination=destination or ROOT/'data/compiled'/mode/'context.sqlite'
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=destination.with_suffix('.building.sqlite')
    if staging.exists(): raise ValueError('Existe una compilación incompleta; revisar el archivo .building.sqlite antes de repetir.')
    db=sqlite3.connect(staging)
    try:
        db.executescript('CREATE TABLE records(id TEXT PRIMARY KEY,dataset TEXT,body TEXT); CREATE TABLE links(record_id TEXT,expression TEXT,role TEXT,low TEXT,high TEXT,match_type TEXT,scope TEXT); CREATE TABLE codes(code TEXT,record_id TEXT,derivation TEXT,PRIMARY KEY(code,record_id)); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE manual_units(address TEXT,record_id TEXT,position INTEGER);')
        hashes={}; count=0; v1=[]; units=[]; manuals=[]
        for path in sorted(source.glob('*.jsonl')):
            dataset=path.stem;hashes[path.name]=sha256(path)
            for r in read_jsonl(path):
                db.execute('INSERT INTO records VALUES(?,?,?)',(r['id'],dataset,json.dumps(r,ensure_ascii=False)))
                count+=1
                if dataset=='vol1_tabular': v1.append(r)
                if dataset=='vol2_document_units':
                    units.append(r);db.execute('INSERT INTO manual_units VALUES(?,?,?)',(r['section_address'],r['id'],len(units)))
                if dataset.startswith('vol2_'):manuals.append(r)
                scope=r.get('scope','classification_usage') if dataset.startswith('vol2') else 'classification_usage'
                if isinstance(scope,dict): scope='not_inferred'
                record_bindings=[] if dataset=='vol2_manual' and (source/'vol2_document_units.jsonl').exists() else bindings(dataset,r)
                for expr,role in set(record_bindings):
                    bounds=expression_bounds(expr)
                    if bounds: db.execute('INSERT INTO links VALUES(?,?,?,?,?,?,?)',(r['id'],expr,role,*bounds,scope))
        if units:
            from cie10.processing.volume2.manual_units import manual_references
            for r in manuals:
                refs=manual_references(r,units)
                if refs:
                    r['manual_references']=refs
                    db.execute('UPDATE records SET body=? WHERE id=?',(json.dumps(r,ensure_ascii=False),r['id']))
        # A printed "ver" address is also useful when querying its destination
        # code. These are retrieval links only: source code_references stay
        # untouched and no synonym/equivalence or recoding is inferred.
        navigation_links=0;navigation_seen=set()
        for (body,) in db.execute("SELECT body FROM records WHERE dataset='vol3_remissions'").fetchall():
            edge=json.loads(body)
            if edge['resolution'] not in ('resolved_exact','resolved_table_instruction','resolved_contextual_navigation'): continue
            ids=edge.get('target_ids') or ([edge['target_id']] if edge.get('target_id') else [])
            if edge['resolution']=='resolved_contextual_navigation':
                selector=edge.get('navigation_selector',{})
                # A navigation anchor/prefix is not a destination code. Only
                # explicitly reviewed alternatives receive reverse links.
                if selector.get('anchor_is_navigation_only') or selector.get('option_refs_are_examples'):continue
                ids=selector.get('option_refs',[])
            explicit=[]
            for identifier in ids:
                target=db.execute('SELECT dataset,body FROM records WHERE id=?',(identifier,)).fetchone()
                if not target:continue
                dataset,body=target;r=json.loads(body);bound=bindings(dataset,r)
                if r.get('cells'):
                    columns=edge.get('table_selector',{}).get('candidate_columns',[])
                    bound=[(expr,role) for expr,role in bound if role.startswith('table_column:') and role.split(':',1)[1] in columns]
                elif r['kind']!='index_entry':continue
                explicit+=bound
            for expr,role in set(explicit):
                bounds=expression_bounds(expr)
                if bounds and (edge['source_id'],expr) not in navigation_seen:
                    db.execute('INSERT INTO links VALUES(?,?,?,?,?,?,?)',(edge['source_id'],expr,'index_remission_navigation',*bounds,'classification_usage'))
                    navigation_links+=1
                    navigation_seen.add((edge['source_id'],expr))
        byid={r['id']:r for r in v1}
        for r in v1:
            if r.get('code'):
                db.execute('INSERT OR IGNORE INTO codes VALUES(?,?,?)',(r['code'],r['id'],None))
        for r in v1:
            if r.get('code'):
                for suffix in r.get('code_structure',{}).get('shared_suffixes',[]):
                    if db.execute('SELECT 1 FROM codes WHERE code=?',(r['code']+suffix,)).fetchone(): continue
                    rows=[{'scheme_ref':ref,'row':row} for ref in r.get('subdivision_scheme_refs',[]) for row in byid.get(ref,{}).get('subdivision_table',{}).get('rows',[]) if row['suffix']==suffix]
                    if rows: db.execute('INSERT OR IGNORE INTO codes VALUES(?,?,?)',(r['code']+suffix,r['id'],json.dumps(rows,ensure_ascii=False)))
        db.executescript('CREATE INDEX link_bounds ON links(low,high); CREATE INDEX link_record ON links(record_id);')
        meta={'api_version':VERSION,'processed_manifest':read_json(source/'manifest.json'),
              'input_sha256':hashes,'record_count':count,'scope':'documentary_retrieval',
              'clinical_validation':'not_performed','vol3_visual_review':'systematic_structural_queue_and_targeted_source_review'}
        meta['manual_document_units']=len(units)
        meta['index_remission_navigation_links']=navigation_links
        db.execute('INSERT INTO metadata VALUES(?,?)',('manifest',json.dumps(meta,ensure_ascii=False)));db.commit()
    except Exception:
        db.close();staging.unlink(missing_ok=True);raise
    db.close();staging.replace(destination)
    return {'database':str(destination),'records':count}


class ContextStore:
    def __init__(self,path=DB):
        if not path.is_file(): raise FileNotFoundError('Primero ejecutar build-context --mode full.')
        self.path=path
    def connect(self): return closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True))
    def get(self,db,identifier):
        value=db.execute('SELECT body FROM records WHERE id=?',(identifier,)).fetchone()
        return json.loads(value[0]) if value else None
    def snapshot(self,db):
        metadata=json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        payload=json.dumps(metadata,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()
    def record(self,identifier):
        with self.connect() as db:
            r=self.get(db,identifier)
            if r is None: raise KeyError(identifier)
            result={'record':r,'source_snapshot_sha256':self.snapshot(db)};return compact_sources(result)
    def manual_section(self,address,view='readable'):
        if view not in ('readable','evidence'):raise ValueError('view debe ser readable o evidence.')
        if not re.fullmatch(r'(?:[1-7](?:\.\d+){0,4}(?: [A-Z])?(?: [a-z])?|SP\d+|M\d+)',address):raise ValueError('Dirección de sección inválida.')
        with self.connect() as db:
            ids=[x[0] for x in db.execute('SELECT record_id FROM manual_units WHERE address=? OR address LIKE ? OR address LIKE ? OR address LIKE ? ORDER BY position',(address,address+' %',address+' | %',address+'.%'))]
            if not ids:raise KeyError(address)
            result=compact_sources({'api_version':VERSION,'section_address':address,'records':{i:self.get(db,i) for i in ids}})
            if view=='evidence':return result
            from cie10.api.context_readable import Reader
            reader=Reader(result)
            return {'api_version':VERSION,'view':'readable','section_address':address,'units':[reader.manual(r,[]) for r in result['records'].values()], 'automatic_recoding':False}
    def manual_unit(self,identifier):
        result=self.record(identifier)
        if result['record']['kind']!='manual_document_unit':raise KeyError(identifier)
        from cie10.api.context_readable import Reader
        reader=Reader({**result,'records':{identifier:result['record']}})
        return {'api_version':VERSION,'view':'readable','unit':reader.manual(result['record'],[])}
    def suggest_codes(self, prefix, limit=12):
        """Return indexed tabular headings and shared subdivisions by code prefix."""
        from cie10.api.context_readable import Reader

        prefix = prefix.upper()
        if not CODE_PREFIX.fullmatch(prefix) or not 1 <= limit <= 50:
            raise ValueError('Se requiere un prefijo CIE-10 y un límite de 1 a 50.')
        reader = Reader({'records': {}, 'source_locations': {}})
        with self.connect() as db:
            rows = db.execute("""
                SELECT c.code, c.derivation, r.body
                FROM codes c JOIN records r ON r.id = c.record_id
                WHERE c.code >= ? AND c.code < ?
                ORDER BY c.code, c.record_id
            """, (prefix, prefix + '~'))
            suggestions = []
            for code, derivation, body in rows:
                if not CODE.fullmatch(code) or (suggestions and suggestions[-1]['code'] == code):
                    continue
                heading = json.loads(body)
                title = reader.text(heading.get('description', ''), heading)
                if derivation:
                    subdivisions = dict.fromkeys(
                        reader.text(item['row']['text'], self.get(db, item['scheme_ref']))
                        for item in json.loads(derivation)
                    )
                    title = ' — '.join([title, *subdivisions])
                suggestions.append({'code': code, 'title': title})
                if len(suggestions) == limit:
                    break
        return suggestions

    def context(self,code,scope='all',limit=50,offset=0,view='readable'):
        if view not in ('readable','evidence'): raise ValueError('view debe ser readable o evidence.')
        evidence=self.evidence_context(code,scope,limit,offset)
        if view=='evidence': return evidence
        from cie10.api.context_readable import readable_context
        return readable_context(evidence)
    def evidence_context(self,code,scope='all',limit=50,offset=0):
        code=code.strip().upper()
        if not CODE.fullmatch(code): raise ValueError('Formato de código inválido.')
        if scope not in ('all','mortality','morbidity'): raise ValueError('scope debe ser all, mortality o morbidity.')
        if not 1<=limit<=200 or offset<0: raise ValueError('limit debe ser 1–200 y offset no negativo.')
        with self.connect() as db:
            catalogue=db.execute('SELECT record_id,derivation FROM codes WHERE code=? ORDER BY record_id',(code,)).fetchall()
            if not catalogue: raise KeyError(code)
            headings=[self.get(db,c[0]) for c in catalogue];derived=[json.loads(c[1]) for c in catalogue if c[1]]
            recordmap={r['id']:r for r in headings};hierarchy=[];effective=[];schemes=[]
            for r in headings:
                for identifier in r.get('ancestor_refs',[]):
                    a=self.get(db,identifier)
                    if a: recordmap[identifier]=a;hierarchy.append(identifier)
                for identifier in r.get('subdivision_scheme_refs',[]):
                    a=self.get(db,identifier)
                    if a: recordmap[identifier]=a;schemes.append(identifier)
                for ref in r.get('applicable_note_refs',[]):
                    a=self.get(db,ref['record_id'])
                    if a:
                        recordmap[a['id']]=a
                        effective.append({'origin_record_id':a['id'],'origin_code':a.get('code'),
                             'inherited':True,'scope':ref['scope'],
                             'fields':{field:a.get(field,[]) for field in ref['fields']},'sources':ref['sources']})
                effective.append({'origin_record_id':r['id'],'origin_code':r.get('code'),
                    'inherited':bool(derived),'scope':'this_code',
                    'fields':{f:r.get(f,[]) for f in ('inclusions','exclusions','instructions','notes','coding_relations')},'sources':r['sources']})
            clause='l.low<=? AND l.high>=? AND r.dataset<>?';params=[code,code,'vol1_tabular']
            if scope!='all':
                shared=['classification_usage','mortality_and_morbidity']
                if scope=='mortality':shared.append('perinatal_mortality')
                clause+=' AND (l.scope=? OR l.scope LIKE ? OR l.scope IN ('+','.join('?' for _ in shared)+'))';params += [scope,scope+'_%',*shared]
            total=db.execute('SELECT COUNT(DISTINCT l.record_id) FROM links l JOIN records r ON r.id=l.record_id WHERE '+clause,params).fetchone()[0]
            ids=[x[0] for x in db.execute('SELECT DISTINCT l.record_id FROM links l JOIN records r ON r.id=l.record_id WHERE '+clause+' ORDER BY l.record_id LIMIT ? OFFSET ?',params+[limit,offset])]
            links=[]
            for identifier in ids:
                r=self.get(db,identifier);recordmap[identifier]=r
                for expr,role,kind in db.execute('SELECT expression,role,match_type FROM links WHERE record_id=? AND low<=? AND high>=? ORDER BY role,expression',(identifier,code,code)):
                    links.append({'record_id':identifier,'matched_expression':expr,'role':role,'match_type':kind,
                                  'case_applicability':'not_evaluated'})
                dependencies=[]
                dependencies+=r.get('ancestor_unit_refs',[])
                dependencies+=r.get('index_note_refs',[])
                if r.get('context_ref'): dependencies.append(r['context_ref'])
                dependencies += [e['target_id'] for e in r.get('remissions',[]) if e.get('target_id')]
                dependencies += [i for e in r.get('remissions',[]) for i in e.get('target_ids',[])]
                dependencies += [e['partial_navigation']['anchor_id'] for e in r.get('remissions',[]) if e.get('partial_navigation')]
                dependencies += [i for e in r.get('remissions',[]) for i in e.get('candidate_ids',[])]
                dependencies += [i for e in r.get('remissions',[]) for i in e.get('duplicate_target_ids',[])]
                dependencies += [i for e in r.get('remissions',[]) for i in e.get('documentary_review',{}).get('compared_target_ids',[])]
                dependencies += [i for e in r.get('remissions',[]) for i in e.get('documentary_review',{}).get('proof_ids',[])]
                dataset=db.execute('SELECT dataset FROM records WHERE id=?',(identifier,)).fetchone()[0]
                table={'vol3_drug_table':'v3-p654-drug-metadata','vol3_neoplasm_table':'v3-p544-neoplasm-metadata','vol3_abortion_table':'v3-p14-abortion-metadata','vol3_transport_matrix':'v3-p605-transport_matrix-metadata'}.get(dataset)
                if table: dependencies.append(table)
                if dataset=='vol2_association_blocks':dependencies.append('v2-p83-4.2.5-context')
                for dep in dependencies:
                    a=self.get(db,dep)
                    if a: recordmap[dep]=a
            # References are documentary dependencies, never patient applicability.
            # Expand precise targets once; broad sections have dedicated URLs.
            reference_links=[];supporting=set(recordmap)-set(ids)-set(hierarchy)-{r['id'] for r in headings}-set(schemes)
            for r in list(recordmap.values()):
                for ref in r.get('manual_references',[]):
                    edge={'source_record_id':r['id'],**ref};reference_links.append(edge)
                    targets=ref['target_unit_refs']
                    if len(targets)==1:
                        target=self.get(db,targets[0])
                        if target:
                            recordmap[target['id']]=target;supporting.add(target['id'])
                            for ancestor in target.get('ancestor_unit_refs',[]):
                                a=self.get(db,ancestor)
                                if a:recordmap[ancestor]=a;supporting.add(ancestor)
                    # A conflicting printed number is not silently repaired.
                    # Its explicit-title candidate is supplied as documentary
                    # support, retaining the conflict and the exact source label.
                    for candidate in ref.get('candidate_unit_refs',[]):
                        a=self.get(db,candidate)
                        if a:recordmap[candidate]=a;supporting.add(candidate)
            supporting-=set(ids)|set(hierarchy)|{r['id'] for r in headings}|set(schemes)
            # Conventions are shared context, never code applicability inferred from examples.
            general=[]
            for identifier,body in db.execute("SELECT id,body FROM records WHERE dataset='vol2_manual'"):
                r=json.loads(body)
                if (r.get('section') or {}).get('number','').split('.')[0]=='3':
                    general.append(identifier)
            general += [r[0] for r in db.execute("SELECT id FROM records WHERE dataset='vol3_index_conventions' ORDER BY id")]
            metadata=json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
            result={'api_version':VERSION,'code':code,'edition':'OPS/OMS CIE-10 2018',
                'source_snapshot_sha256':self.snapshot(db),
                'classification':{'heading_refs':[r['id'] for r in headings], 'representation':'shared_subdivision' if derived else 'explicit_heading',
                                  'shared_subdivision_rows':derived,'hierarchy_refs':list(dict.fromkeys(hierarchy)),
                                  'subdivision_scheme_refs':list(dict.fromkeys(schemes))},
                'effective_tabular_notes':effective,'context_links':links,
                'manual_reference_links':reference_links,'supporting_manual_unit_refs':sorted(i for i in supporting if recordmap[i]['kind']=='manual_document_unit'),
                'pagination':{'scope':scope,'offset':offset,'limit':limit,'total_records':total,
                              'next_offset':offset+limit if offset+limit<total else None,
                              'complete':offset==0 and total<=limit},
                'general_convention_refs':general,'records':recordmap,
                'quality':{'clinical_validation':'not_performed','automatic_recoding':False,
                           'vol3_visual_review':metadata['vol3_visual_review'],
                           'pending_or_ambiguous_record_refs':[r['id'] for r in recordmap.values() if r.get('review_status') not in ('source_verified',)]},
                'source_manifest':metadata['processed_manifest']['sources']}
            return compact_sources(result)


def compact_sources(response):
    documents={};sources={};keys={}
    def visit(value):
        if isinstance(value,dict):
            if all(k in value for k in ('volume','source_file','source_sha256','pdf_page')):
                key=json.dumps(value,sort_keys=True,ensure_ascii=False)
                if key not in keys:
                    ref='s'+str(len(keys)+1);keys[key]=ref;doc='vol'+str(value['volume'])
                    documents[doc]={'volume':value['volume'],'filename':value['source_file'],'sha256':value['source_sha256']}
                    sources[ref]={'document_ref':doc,**{k:v for k,v in value.items() if k not in ('volume','source_file','source_sha256')}}
                return {'source_ref':keys[key]}
            return {k:visit(v) for k,v in value.items()}
        if isinstance(value,list):return [visit(v) for v in value]
        return value
    compact=visit(response);compact['documents']=documents;compact['source_locations']=sources
    return compact


def serve(path=DB,host='127.0.0.1',port=8000):
    store=ContextStore(path)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed=urlsplit(self.path);query=parse_qs(parsed.query,keep_blank_values=True)
            try:
                if parsed.path=='/health': result={'status':'ok','api_version':VERSION}
                elif parsed.path == '/v1/codes':
                    if set(query) - {'prefix', 'limit'} or any(len(v) != 1 for v in query.values()):
                        raise ValueError('Parámetros inválidos.')
                    result = {'items': store.suggest_codes(query.get('prefix', [''])[0], int(query.get('limit', ['12'])[0]))}
                elif parsed.path.startswith('/v1/codes/'):
                    if set(query)-{'scope','limit','offset','view'} or any(len(v)!=1 for v in query.values()): raise ValueError('Parámetros inválidos.')
                    result=store.context(unquote(parsed.path[len('/v1/codes/'):]),query.get('scope',['all'])[0],int(query.get('limit',['50'])[0]),int(query.get('offset',['0'])[0]),query.get('view',['readable'])[0])
                elif parsed.path.startswith('/v1/records/'):
                    if query: raise ValueError('Este recurso no acepta parámetros.')
                    result=store.record(unquote(parsed.path[len('/v1/records/'):]))
                elif parsed.path.startswith('/v1/manual/sections/'):
                    if set(query)-{'view'} or any(len(v)!=1 for v in query.values()):raise ValueError('Parámetros inválidos.')
                    result=store.manual_section(unquote(parsed.path[len('/v1/manual/sections/'):]),query.get('view',['readable'])[0])
                elif parsed.path.startswith('/v1/manual/units/'):
                    if query:raise ValueError('Este recurso no acepta parámetros.')
                    result=store.manual_unit(unquote(parsed.path[len('/v1/manual/units/'):]))
                else: raise KeyError(parsed.path)
                status=200
            except ValueError as error: result={'error':'invalid_request','message':str(error)};status=400
            except KeyError: result={'error':'not_found'};status=404
            data=json.dumps(result,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'API documental local: http://{host}:{port}/v1/codes/C76.4',flush=True)
    try: server.serve_forever()
    finally:server.server_close()
