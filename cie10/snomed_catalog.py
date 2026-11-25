"""Versioned local RF2 catalogues. No content download or licence inference."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3

from .mapping_context import ContextError
from .retrieval_evaluation import sha256, write_json

SYSTEM = 'http://snomed.info/sct'
VERSION = re.compile(r'^http://snomed\.info/sct/[1-9][0-9]{5,17}/version/([0-9]{8})$')
SCTID = re.compile(r'^[1-9][0-9]{5,17}$')
DESCRIPTION_TYPES = {'900000000000003001','900000000000013009'}


def dated_version(version):
    m = VERSION.fullmatch(version or '')
    if not m:raise ContextError('Se requiere la URI de una edición SNOMED con fecha exacta.')
    datetime.strptime(m[1],'%Y%m%d')
    return m[1]


def rf2_rows(path, required, release):
    path=Path(path)
    if 'Snapshot' not in path.name:raise ContextError('Se admiten archivos Snapshot explícitos, no Full/Delta.')
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,delimiter='\t')
        if not required <= set(reader.fieldnames or []):raise ContextError('Cabecera RF2 incompleta: '+path.name)
        for line,row in enumerate(reader,2):
            if None in row or any(row.get(k) is None for k in required):raise ContextError('Fila RF2 incompleta.')
            if not SCTID.fullmatch(row['id']) or row['active'] not in ('0','1'):
                raise ContextError(f'Componente RF2 inválido: {path.name}:{line}')
            date=row['effectiveTime']
            if not re.fullmatch('[0-9]{8}',date):raise ContextError('No se admiten cambios sin publicar.')
            datetime.strptime(date,'%Y%m%d')
            if date>release:raise ContextError('El archivo contiene componentes posteriores a la edición declarada.')
            yield row


def import_rf2(concepts, descriptions, version, output):
    """Caller supplies a composed Concept Snapshot and its description files."""
    release=dated_version(version)
    output=Path(output)
    if output.exists():raise ContextError('El catálogo de salida ya existe.')
    inputs=[('concept_snapshot',Path(concepts)),*[('description_snapshot',Path(p)) for p in descriptions]]
    if not descriptions or len({p.resolve() for role,p in inputs})!=len(inputs):
        raise ContextError('Se requieren archivos distintos de conceptos y descripciones.')
    sources=[{'role':role,'path':str(p.resolve()),'sha256':sha256(p)} for role,p in inputs]
    output.mkdir(parents=True)
    db=sqlite3.connect(output/'build.sqlite')
    counts={'concept_rows':0,'description_rows':0,'eligible_description_rows':0,'inactive_or_other_language_or_type':0}
    try:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA temp_store=FILE; CREATE TABLE concepts(id TEXT PRIMARY KEY,active INT); CREATE TABLE descriptions(id TEXT PRIMARY KEY,concept_id TEXT,term TEXT,type_id TEXT,module_id TEXT,effective_time TEXT);')
        for r in rf2_rows(concepts,{'id','effectiveTime','active','moduleId','definitionStatusId'},release):
            db.execute('INSERT INTO concepts VALUES (?,?)',(r['id'],int(r['active'])))
            counts['concept_rows']+=1
        for path in descriptions:
            for r in rf2_rows(path,{'id','effectiveTime','active','moduleId','conceptId','languageCode','typeId','term','caseSignificanceId'},release):
                counts['description_rows']+=1
                if r['active']!='1' or r['languageCode']!='es' or r['typeId'] not in DESCRIPTION_TYPES:
                    counts['inactive_or_other_language_or_type']+=1
                    continue
                if not r['term'].strip():raise ContextError('Descripción española vacía.')
                found=db.execute('SELECT active FROM concepts WHERE id=?',(r['conceptId'],)).fetchone()
                if found is None:raise ContextError('Falta el concepto de una descripción activa: '+r['conceptId'])
                if not found[0]:continue
                db.execute('INSERT INTO descriptions VALUES (?,?,?,?,?,?)',
                    (r['id'],r['conceptId'],r['term'],r['typeId'],r['moduleId'],r['effectiveTime']))
                counts['eligible_description_rows']+=1
        db.commit()
        db.execute('CREATE INDEX description_terms ON descriptions(concept_id,term)')
        aliases=output/'catalog.jsonl'
        n=0
        with aliases.open('w',encoding='utf-8') as stream:
            for r in db.execute('SELECT d.* FROM descriptions d JOIN (SELECT MIN(id) id FROM descriptions GROUP BY concept_id,term) first ON first.id=d.id ORDER BY d.concept_id,d.term'):
                item={'description_id':r[0],'concept_id':r[1],'term':r[2],'description_type_id':r[3],
                      'module_id':r[4],'effective_time':r[5],'active':True,'language':'es'}
                stream.write(json.dumps(item,ensure_ascii=False)+'\n'); n+=1
        if not n:raise ContextError('No hay descripciones activas en español para indexar.')
        counts.update(aliases=n,concepts=db.execute('SELECT COUNT(DISTINCT concept_id) FROM descriptions').fetchone()[0],
                      active_source_concepts=db.execute('SELECT COUNT(*) FROM concepts WHERE active=1').fetchone()[0])
        if any(sha256(p)!=s['sha256'] for (role,p),s in zip(inputs,sources,strict=True)):
            raise ContextError('Un archivo RF2 cambió durante la importación.')
        manifest={'schema_version':'0.1.0','status':'completed','kind':'snomed_rf2_snapshot',
            'system':SYSTEM,'version':version,'files':{'catalog.jsonl':sha256(aliases)},'sources':sources,'counts':counts,
            'coverage':'active_spanish_fsn_and_synonyms_in_supplied_composed_snapshot',
            'edition_binding':'operator_declared_composed_snapshot_not_server_verified',
            'display_policy':'matched_published_description_not_asserted_preferred_term',
            'module_dependencies_validated':False,'clinical_validation':False}
        write_json(output/'catalog.json',manifest)
    except Exception as e:
        write_json(output/'catalog-failed.json',{'status':'failed','error':str(e)})
        raise
    finally:
        db.close()
    (output/'build.sqlite').unlink()
    return manifest


def load_catalog(folder, allow_fixture=False):
    folder=Path(folder)
    if not (folder/'catalog.json').is_file():raise ContextError('target_catalog_unavailable')
    meta=json.loads((folder/'catalog.json').read_text())
    if meta.get('status')!='completed':raise ContextError('El catálogo no está completo.')
    if meta.get('kind')=='synthetic_fixture':
        if not allow_fixture or meta.get('system')!='urn:magister:synthetic-fixture':
            raise ContextError('El catálogo sintético requiere modo de prueba explícito.')
    elif meta.get('kind')=='snomed_rf2_snapshot':
        if meta.get('system')!=SYSTEM:raise ContextError('Sistema SNOMED inconsistente.')
        dated_version(meta.get('version'))
        if not meta.get('sources'):raise ContextError('Falta procedencia RF2.')
    else:raise ContextError('Tipo de catálogo no admitido.')
    if sha256(folder/'catalog.jsonl')!=meta.get('files',{}).get('catalog.jsonl'):
        raise ContextError('El catálogo cambió desde su manifiesto.')
    return meta


def aliases_from(folder, meta):
    with (Path(folder)/'catalog.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            if row.get('active') is not True or row.get('language')!='es' or not isinstance(row.get('term'),str) or not row['term'].strip():
                raise ContextError('Alias inactivo, no español o vacío.')
            identifier=row.get('concept_id')
            if meta['kind']=='synthetic_fixture':
                if not isinstance(identifier,str) or not identifier.startswith('fixture:'):raise ContextError('Un identificador sintético no es SCTID.')
            elif not isinstance(identifier,str) or not SCTID.fullmatch(identifier) or not SCTID.fullmatch(row.get('description_id','')):
                raise ContextError('Identificador RF2 inválido.')
            yield row
