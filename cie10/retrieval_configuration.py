"""Choose a completed local index explicitly; never silently fall back on error."""
import json
from pathlib import Path
from .mapping_context import ContextError
from .retrieval_evaluation import sha256

EDITION='http://snomed.info/sct/449081005/version/20261110'

def load_active_index(root):
    root=Path(root).resolve();base=(root/'data/indexes/snomed').resolve()
    config=root/'infra/retrieval/active-index.json'
    pointer=json.loads(config.read_text()) if config.is_file() else {'path':'data/indexes/snomed/pilot-20261110-v1'}
    if not isinstance(pointer,dict) or not isinstance(pointer.get('path'),str):raise ContextError('Configuración de índice inválida.')
    index=(root/pointer['path']).resolve()
    if not index.is_relative_to(base) or index==base:raise ContextError('El índice debe estar dentro del directorio de índices SNOMED.')
    manifest=index/'index.json'
    info=json.loads(manifest.read_text())
    if pointer.get('index_manifest_sha256') and pointer['index_manifest_sha256']!=sha256(manifest):raise ContextError('Cambió el manifiesto del índice activo.')
    if info.get('status')!='completed' or info.get('schema_version') not in ('0.1.0','0.2.0'):raise ContextError('Índice activo incompleto o incompatible.')
    if info.get('catalog',{}).get('version')!=EDITION:raise ContextError('El índice activo pertenece a otra edición SNOMED.')
    return index,info
