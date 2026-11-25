"""Versioned local RF2 catalogues. No content download or licence inference."""
from datetime import datetime
import json
from pathlib import Path
import re

from cie10.api.mapping_context import ContextError
from cie10.retrieval.retrieval_core import sha256

SYSTEM = 'http://snomed.info/sct'
VERSION = re.compile(r'^http://snomed\.info/sct/[1-9][0-9]{5,17}/version/([0-9]{8})$')
SCTID = re.compile(r'^[1-9][0-9]{5,17}$')
DESCRIPTION_TYPES = {'900000000000003001','900000000000013009'}


def dated_version(version):
    m = VERSION.fullmatch(version or '')
    if not m:raise ContextError('Se requiere la URI de una edición SNOMED con fecha exacta.')
    datetime.strptime(m[1],'%Y%m%d')
    return m[1]


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
