"""Compose published RF2 snapshots on disk; export all active Spanish names."""
import csv
from datetime import datetime
from functools import lru_cache
import io
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from .mapping_context import ContextError
from .snomed_catalog import SYSTEM,SCTID,DESCRIPTION_TYPES,dated_version
from .retrieval_core import sha256,write_json


@lru_cache(maxsize=10000)
def published_date(value):
    if not isinstance(value,str) or len(value)!=8 or not value.isdigit():raise ContextError('Fecha RF2 no publicada o inválida.')
    datetime.strptime(value,'%Y%m%d')
    return value


def member(z,kind):
    found=[n for n in z.namelist() if '/Snapshot/Terminology/sct2_'+kind+'_' in n and n.endswith('.txt')]
    if len(found)!=1:raise ContextError('Se requiere exactamente un Snapshot de '+kind+'.')
    return found[0]


def rows(z,name,required):
    with z.open(name) as raw:
        reader=csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig',newline=''),delimiter='\t',quoting=csv.QUOTE_NONE)
        if not required<=set(reader.fieldnames or []):raise ContextError('Cabecera RF2 incompleta.')
        for row in reader:
            if None in row or any(row.get(k) is None for k in required):raise ContextError('Fila RF2 incompleta.')
            yield row


def current_dependencies(z,release,base_release):
    names=[n for n in z.namelist() if '/Snapshot/Refset/Metadata/' in n and 'ModuleDependency' in n and n.endswith('.txt')]
    if len(names)!=1:raise ContextError('No se encontró un ModuleDependency Snapshot unívoco.')
    required={'id','effectiveTime','active','moduleId','referencedComponentId','sourceEffectiveTime','targetEffectiveTime'}
    current=[]
    for row in rows(z,names[0],required):
        published_date(row['effectiveTime']);published_date(row['sourceEffectiveTime']);published_date(row['targetEffectiveTime'])
        if row['active']=='1' and row['sourceEffectiveTime']==release:
            if row['targetEffectiveTime']!=base_release:raise ContextError('La dependencia requiere otra edición internacional.')
            current.append(row)
    if not current:raise ContextError('Faltan dependencias publicadas para la edición española solicitada.')
    return current,names[0]


def insert_component(db,table,values):
    """Newest component state wins; conflicting same-date states are rejected."""
    try:db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values)+')',values)
    except sqlite3.IntegrityError:
        old=db.execute('SELECT * FROM '+table+' WHERE id=?',(values[0],)).fetchone()
        if old is None:raise
        if old[1]==values[1] and old!=values:raise ContextError('Estados RF2 contradictorios en una misma fecha.')
        if old[1]<values[1]:
            names=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
            db.execute('UPDATE '+table+' SET '+','.join(n+'=?' for n in names[1:])+' WHERE id=?',(*values[1:],values[0]))


def import_archives(international,spanish,version,base_release,output):
    release=dated_version(version);published_date(base_release)
    output=Path(output)
    if output.exists():raise ContextError('El catálogo de salida ya existe.')
    international,spanish=Path(international),Path(spanish)
    sources=[dict(role=role,path=str(path.resolve()),sha256=sha256(path)) for role,path in
             [('international_snapshot_archive',international),('spanish_snapshot_archive',spanish)]]
    output.mkdir(parents=True)
    db=sqlite3.connect(output/'build.sqlite')
    counts=dict(concept_rows=0,description_rows=0)
    members={};base_modules=set()
    try:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-65536; PRAGMA temp_store=FILE; CREATE TABLE concepts(id TEXT PRIMARY KEY,effective_time TEXT,active INT,module_id TEXT,definition_status TEXT); CREATE TABLE descriptions(id TEXT PRIMARY KEY,effective_time TEXT,active INT,concept_id TEXT,language TEXT,type_id TEXT,term TEXT,module_id TEXT,case_significance TEXT);')
        with ZipFile(international) as base, ZipFile(spanish) as es:
            dependencies,dep_member=current_dependencies(es,release,base_release)
            base_dependencies,base_dep_member=current_dependencies(base,base_release,base_release)
            base_modules.update(x['moduleId'] for x in base_dependencies)
            base_modules.update(x['referencedComponentId'] for x in base_dependencies)
            for label,z,last_date in [('international',base,base_release),('spanish',es,release)]:
                concept_member=member(z,'Concept');description_member=member(z,'Description')
                members[label]=dict(concepts=concept_member,descriptions=description_member)
                for row in rows(z,concept_member,{'id','effectiveTime','active','moduleId','definitionStatusId'}):
                    if not SCTID.fullmatch(row['id']) or row['active'] not in ('0','1') or not SCTID.fullmatch(row['moduleId']):raise ContextError('Concepto RF2 inválido.')
                    if published_date(row['effectiveTime'])>last_date:raise ContextError('Concepto posterior a su paquete declarado.')
                    if label=='international':base_modules.add(row['moduleId'])
                    insert_component(db,'concepts',(row['id'],row['effectiveTime'],int(row['active']),row['moduleId'],row['definitionStatusId']))
                    counts['concept_rows']+=1
                    if counts['concept_rows']%100000==0:print(json.dumps(dict(stage='import_concepts',rows=counts['concept_rows'])),flush=True)
                db.commit()
                for row in rows(z,description_member,{'id','effectiveTime','active','moduleId','conceptId','languageCode','typeId','term','caseSignificanceId'}):
                    if not SCTID.fullmatch(row['id']) or not SCTID.fullmatch(row['conceptId']) or row['active'] not in ('0','1'):raise ContextError('Descripción RF2 inválida.')
                    if published_date(row['effectiveTime'])>last_date:raise ContextError('Descripción posterior a su paquete declarado.')
                    if not row['term'].strip():raise ContextError('Descripción vacía.')
                    insert_component(db,'descriptions',(row['id'],row['effectiveTime'],int(row['active']),row['conceptId'],row['languageCode'],row['typeId'],row['term'],row['moduleId'],row['caseSignificanceId']))
                    counts['description_rows']+=1
                    if counts['description_rows']%100000==0:
                        db.commit();print(json.dumps(dict(stage='import_descriptions',rows=counts['description_rows'])),flush=True)
                db.commit()
        if not {r['referencedComponentId'] for r in dependencies}<=base_modules:raise ContextError('Falta un módulo internacional requerido por la edición española.')
        orphan=db.execute("SELECT d.concept_id FROM descriptions d LEFT JOIN concepts c ON c.id=d.concept_id WHERE d.active=1 AND d.language='es' AND c.id IS NULL LIMIT 1").fetchone()
        if orphan:raise ContextError('Una descripción española activa carece de concepto compuesto.')
        db.execute("CREATE TABLE eligible AS SELECT d.* FROM descriptions d JOIN concepts c ON c.id=d.concept_id WHERE d.active=1 AND c.active=1 AND d.language='es' AND d.type_id IN ('900000000000003001','900000000000013009')")
        db.execute('CREATE UNIQUE INDEX eligible_id ON eligible(id)')
        db.execute('CREATE INDEX eligible_terms ON eligible(concept_id,term,id)')
        db.commit()
        aliases=0
        with (output/'catalog.jsonl').open('w',encoding='utf-8') as stream:
            query='SELECT e.* FROM eligible e JOIN (SELECT MIN(id) id FROM eligible GROUP BY concept_id,term) selected ON selected.id=e.id ORDER BY e.concept_id,e.term'
            for row in db.execute(query):
                item=dict(description_id=row[0],effective_time=row[1],active=True,concept_id=row[3],language='es',description_type_id=row[5],term=row[6],module_id=row[7])
                stream.write(json.dumps(item,ensure_ascii=False)+'\n');aliases+=1
        if not aliases:raise ContextError('El catálogo compuesto no contiene denominaciones españolas activas.')
        counts.update(aliases=aliases,concepts=db.execute('SELECT COUNT(DISTINCT concept_id) FROM eligible').fetchone()[0],
            active_source_concepts=db.execute('SELECT COUNT(*) FROM concepts WHERE active=1').fetchone()[0],
            composed_concepts=db.execute('SELECT COUNT(*) FROM concepts').fetchone()[0],composed_descriptions=db.execute('SELECT COUNT(*) FROM descriptions').fetchone()[0],
            eligible_description_rows=db.execute('SELECT COUNT(*) FROM eligible').fetchone()[0])
        if [sha256(p) for p in (international,spanish)]!=[x['sha256'] for x in sources]:raise ContextError('Un archivo fuente cambió durante la importación.')
        info=dict(schema_version='0.2.0',status='completed',kind='snomed_rf2_snapshot',system=SYSTEM,version=version,
            files={'catalog.jsonl':sha256(output/'catalog.jsonl')},sources=sources,counts=counts,
            coverage='all_active_spanish_fsn_and_synonyms_in_composed_archives_no_thematic_sampling',
            composition_policy='newest_effective_time_per_component_same_date_conflicts_rejected',
            archive_members=members,module_dependencies_validated=True,module_dependencies=dependencies,module_dependency_member=dep_member,
            international_module_dependencies=base_dependencies,international_dependency_member=base_dep_member,
            international_release=base_release,edition_binding='rf2_module_dependency_validated',
            display_policy='matched_published_description_not_asserted_preferred_term',clinical_validation=False,
            implementation_sha256=sha256(__file__))
        write_json(output/'catalog.json',info)
    except Exception as error:
        write_json(output/'catalog-failed.json',dict(status='failed',error=str(error)))
        raise
    finally:db.close()
    (output/'build.sqlite').unlink()
    return info
