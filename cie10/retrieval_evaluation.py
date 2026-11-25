"""Offline, versioned candidate-retrieval experiments, never clinical mapping.

The standard-library path prepares a CIE-10 documentary proxy and a lexical
baseline. Neural dependencies are optional and imported only for a neural run.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import platform
import re
import time
import unicodedata

VERSION = '0.1.0'
PIN = re.compile(r'^[0-9a-f]{40}$')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def normalize(text):
    # This is lexical token normalization, never a modification of the evidence.
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+', text))


def ngrams(text):
    value = ' ' + normalize(text) + ' '
    return Counter(value[i:i+n] for n in (3, 4, 5) for i in range(len(value)-n+1))


def concept_ranking(alias_rows, scores, k):
    """Every concept occupies one position, using its best matching alias."""
    best = {}
    for row, raw_score in zip(alias_rows, scores, strict=True):
        score = float(raw_score)
        if not math.isfinite(score):
            raise ValueError('La búsqueda produjo una puntuación no finita.')
        candidate = {'concept_id': row['concept_id'], 'term': row['term'], 'score': score}
        old = best.get(row['concept_id'])
        if old is None or score > old['score'] or (score == old['score'] and row['term'] < old['term']):
            best[row['concept_id']] = candidate
    return sorted(best.values(), key=lambda x: (-x['score'], x['concept_id']))[:k]


def metrics(results, cases, cutoffs=(1, 5, 10, 20, 50)):
    """Do not score prospective/unlabelled cases as if they were failures."""
    by_id = {case['id']: case for case in cases}
    scored = [(row, by_id[row['case_id']]) for row in results
              if by_id[row['case_id']].get('expected_ids')]
    if not scored:
        return {'labelled_cases': 0, 'unlabelled_cases': len(cases), 'hit_at': None,
                'recall_at': None, 'mrr': None}
    hits, recall, reciprocal = {}, {}, []
    for k in cutoffs:
        pairs = [(set(c['expected_ids']), {x['concept_id'] for x in r['candidates'][:k]})
                 for r, c in scored]
        hits[str(k)] = sum(bool(a & b) for a, b in pairs) / len(pairs)
        recall[str(k)] = sum(len(a & b) / len(a) for a, b in pairs) / len(pairs)
    for result, case in scored:
        ranks = [i for i, item in enumerate(result['candidates'], 1)
                 if item['concept_id'] in case['expected_ids']]
        reciprocal.append(1 / min(ranks) if ranks else 0)
    return {'labelled_cases': len(scored), 'unlabelled_cases': len(cases)-len(scored),
            'hit_at': hits, 'recall_at': recall, 'mrr': sum(reciprocal)/len(reciprocal)}


def load_dataset(directory):
    directory = Path(directory)
    meta = json.loads((directory/'dataset.json').read_text(encoding='utf-8'))
    if meta.get('kind') not in ('cie10_documentary_proxy', 'snomed_retrieval_benchmark'):
        raise ValueError('Tipo de experimento no admitido.')
    if not meta.get('edition') or not meta.get('label_basis'):
        raise ValueError('Faltan edición y procedencia de etiquetas.')
    for filename in ('catalog.jsonl', 'cases.jsonl'):
        if sha256(directory/filename) != meta.get('sha256', {}).get(filename):
            raise ValueError('El conjunto cambió: ' + filename)
    aliases = read_jsonl(directory/'catalog.jsonl')
    cases = read_jsonl(directory/'cases.jsonl')
    if not aliases or not cases:
        raise ValueError('El catálogo y los casos deben contener registros.')
    alias_seen, case_seen = set(), set()
    for row in aliases:
        if not isinstance(row.get('concept_id'), str) or not row['concept_id'].strip():
            raise ValueError('Identificador de concepto inválido.')
        if not isinstance(row.get('term'), str) or not normalize(row['term']):
            raise ValueError('Término de búsqueda vacío.')
        key = (row['concept_id'], row['term'])
        if key in alias_seen:
            raise ValueError('Alias duplicado dentro del concepto.')
        alias_seen.add(key)
        if row.get('active') is not True or row.get('language') != 'es':
            raise ValueError('Esta comparación exige términos activos en español.')
    ids = {a['concept_id'] for a in aliases}
    for case in cases:
        if not isinstance(case.get('id'), str) or not case['id'] or case['id'] in case_seen:
            raise ValueError('Caso con identificador vacío o duplicado.')
        case_seen.add(case['id'])
        if not isinstance(case.get('query'), str) or not normalize(case['query']):
            raise ValueError('Consulta vacía.')
        expected = case.get('expected_ids', [])
        if not isinstance(expected, list) or any(not isinstance(x, str) for x in expected):
            raise ValueError('expected_ids debe ser una lista de identificadores.')
        if len(expected) != len(set(expected)) or not set(expected) <= ids:
            raise ValueError('Etiquetas repetidas o fuera del catálogo elegible.')
    return meta, aliases, cases


def prepare_proxy(tabular, output, limit=30):
    """Official membership is a documentary proxy, not semantic equivalence."""
    if not 1 <= limit <= 500:
        raise ValueError('limit debe estar entre 1 y 500.')
    output = Path(output)
    if output.exists():
        raise ValueError('La carpeta de salida ya existe; usa una nueva.')
    records = read_jsonl(tabular)
    codes = {}
    for record in records:
        if record.get('kind') == 'code' and record.get('code') and record.get('description'):
            if record['code'] in codes:
                raise ValueError('Encabezado de código duplicado en la fuente.')
            codes[record['code']] = record
    aliases = [{'concept_id': code, 'term': r['description'], 'active': True, 'language': 'es',
                'source_record': r['id']} for code, r in sorted(codes.items())]
    pool = []
    for code, r in sorted(codes.items()):
        for i, inclusion in enumerate(r.get('inclusions', [])):
            term = inclusion.get('text', '').strip()
            if not 12 <= len(term) <= 160 or term.endswith(':') or len(term.split()) < 2:
                continue
            if re.search(r'\b[A-Z][0-9]{2}|[\uf8fc-\uf8ff]', term):
                continue
            if normalize(term) == normalize(r['description']):
                continue
            # At most one inclusion per code and deterministic sampling unrelated
            # to model performance. Exclusions and index mentions are never used.
            pool.append({'id': f'proxy-{code}-{i}', 'query': term, 'expected_ids': [code],
                         'input_mode': 'official_inclusion', 'source_record': r['id'],
                         'source_review_status': r.get('review_status'),
                         'source_warnings': r.get('warnings', []),
                         'provenance': inclusion.get('sources') or [inclusion.get('source')],
                         'label_basis': 'inclusion_list_membership_not_clinical_equivalence'})
            break
    # Seeded by an explicit stable hash; never pick examples by successful ranks.
    pool.sort(key=lambda row: hashlib.sha256(('proxy-v1:'+row['id']).encode()).hexdigest())
    cases = pool[:limit]
    if not cases:
        raise ValueError('No se encontraron inclusiones elegibles.')
    output.mkdir(parents=True)
    write_jsonl(output/'catalog.jsonl', aliases)
    write_jsonl(output/'cases.jsonl', cases)
    meta = {'schema_version': VERSION, 'kind': 'cie10_documentary_proxy',
            'edition': 'OPS/OMS CIE-10 español 2018',
            'label_basis': 'official_inclusion_membership_in_processed_volume_1',
            'selection': 'sha256(proxy-v1:case_id), one inclusion per code',
            'source_sha256': sha256(tabular), 'source_path': str(Path(tabular).resolve()),
            'clinical_validation': False, 'snomed_mapping_evaluation': False,
            'limitations': ['La pertenencia a una lista no prueba sinonimia ni equivalencia clínica.',
                            'Las etiquetas y textos dependen de la extracción existente.',
                            'No permite elegir el mejor modelo para CIE-10 a SNOMED.',
                            'Otros códigos pueden ser pertinentes; no es un gold standard exhaustivo.'],
            'sha256': {name: sha256(output/name) for name in ('catalog.jsonl', 'cases.jsonl')}}
    write_json(output/'dataset.json', meta)
    return {'status': 'proxy_prepared', 'catalog_concepts': len(codes), 'cases': len(cases),
            'output': str(output), 'snomed_mapping_evaluation': False}


class LexicalRetriever:
    def __init__(self, aliases):
        self.aliases = aliases
        self.postings = defaultdict(list)
        counts = [ngrams(a['term']) for a in aliases]
        frequency = Counter(key for count in counts for key in count)
        self.idf = {key: math.log((1+len(aliases))/(1+n))+1 for key, n in frequency.items()}
        for i, count in enumerate(counts):
            vector = {key: value*self.idf[key] for key, value in count.items()}
            norm = math.sqrt(sum(value*value for value in vector.values()))
            for key, value in vector.items():
                self.postings[key].append((i, value/norm))

    def search(self, queries, k):
        results = []
        for query in queries:
            vector = {key: value*self.idf[key] for key, value in ngrams(query).items() if key in self.idf}
            norm = math.sqrt(sum(v*v for v in vector.values()))
            scores = defaultdict(float)
            if norm:
                for key, value in vector.items():
                    for i, candidate_weight in self.postings[key]:
                        scores[i] += value/norm*candidate_weight
            positions = sorted(scores)
            results.append(concept_ranking([self.aliases[i] for i in positions],
                                           [scores[i] for i in positions], k))
        return results


class TransformerRetriever:
    def __init__(self, spec, device, cache_dir, max_length, batch_size):
        import torch
        from transformers import AutoModel, AutoTokenizer
        import numpy as np
        if not PIN.fullmatch(spec.get('revision', '')) or spec.get('pooling') != 'cls':
            raise ValueError('Modelo sin revisión fija o pooling CLS explícito.')
        if device == 'cuda' and not torch.cuda.is_available():
            raise ValueError('CUDA no está disponible; no se cambia a CPU silenciosamente.')
        self.torch, self.np = torch, np
        self.device, self.batch_size, self.max_length = device, batch_size, max_length
        self.truncations = []
        torch.set_num_threads(4)
        torch.manual_seed(0)
        if device == 'cuda':
            torch.backends.cuda.matmul.allow_tf32 = False
        shared = {'revision': spec['revision'], 'cache_dir': cache_dir, 'trust_remote_code': False}
        self.tokenizer = AutoTokenizer.from_pretrained(spec['repository'], **shared)
        self.model = AutoModel.from_pretrained(spec['repository'], weights_only=True, **shared)
        if max_length > self.model.config.max_position_embeddings - 2:
            raise ValueError('Presupuesto de tokens fuera de la capacidad del modelo.')
        self.model = self.model.float().eval().to(device)
        if device == 'cuda':
            torch.cuda.reset_peak_memory_stats()

    def encode(self, texts, identifiers, role):
        rows = []
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset:offset+self.batch_size]
            raw = self.tokenizer(batch, add_special_tokens=True, truncation=False)['input_ids']
            for i, ids in enumerate(raw):
                if len(ids) > self.max_length:
                    self.truncations.append({'role': role, 'id': identifiers[offset+i],
                                             'tokens': len(ids), 'kept': self.max_length})
            tokens = self.tokenizer(batch, padding=True, truncation=True,
                                    max_length=self.max_length, return_tensors='pt').to(self.device)
            with self.torch.inference_mode():
                values = self.model(**tokens).last_hidden_state[:, 0, :].float()
                values = self.torch.nn.functional.normalize(values, p=2, dim=1)
            rows.append(values.cpu().numpy())
            if offset == 0 or (offset+self.batch_size) % 512 == 0:
                print(json.dumps({'stage': 'encoding', 'role': role,
                                  'done': min(offset+self.batch_size, len(texts)),
                                  'total': len(texts)}), flush=True)
        return self.np.concatenate(rows)

    def search(self, aliases, cases, k):
        started = time.perf_counter()
        matrix = self.encode([a['term'] for a in aliases],
                             [a['concept_id'] for a in aliases], 'catalog')
        indexed = time.perf_counter()
        queries = self.encode([c['query'] for c in cases], [c['id'] for c in cases], 'query')
        encoded = time.perf_counter()
        rankings = [concept_ranking(aliases, matrix @ query, k) for query in queries]
        finished = time.perf_counter()
        self.details = {'catalog_encoding_seconds': indexed-started,
                        'query_batch_encoding_seconds': encoded-indexed,
                        'ranking_seconds': finished-encoded, 'embedding_dimension': int(matrix.shape[1]),
                        'index_bytes': int(matrix.nbytes), 'truncations': self.truncations,
                        'dtype': 'float32', 'pooling': 'cls', 'normalization': 'l2',
                        'gpu_peak_allocated_bytes': self.torch.cuda.max_memory_allocated() if self.device == 'cuda' else None,
                        'gpu_name': self.torch.cuda.get_device_name() if self.device == 'cuda' else None}
        return rankings

    def close(self):
        del self.model
        gc.collect()
        if self.device == 'cuda':
            self.torch.cuda.empty_cache()


def run(dataset, output, model='lexical', model_config=None, device='cuda',
        cache_dir=None, max_length=64, batch_size=8, top_k=50):
    if not 1 <= top_k <= 1000 or not 4 <= max_length <= 512 or not 1 <= batch_size <= 64:
        raise ValueError('Presupuesto de búsqueda, tokens o lote inválido.')
    output = Path(output)
    if output.exists():
        raise ValueError('La carpeta de salida ya existe; usa otra para conservar los resultados.')
    meta, aliases, cases = load_dataset(dataset)
    spec = None
    if model != 'lexical':
        specs = json.loads(Path(model_config).read_text(encoding='utf-8'))['models']
        if model not in specs:
            raise ValueError('Modelo no registrado.')
        spec = specs[model]
    output.mkdir(parents=True)
    started = time.perf_counter()
    report = {'experiment_version': VERSION, 'status': 'running',
              'created_at': datetime.now(timezone.utc).isoformat(), 'model': model,
              'model_spec': spec, 'device': 'cpu' if model == 'lexical' else device,
              'dataset': meta, 'dataset_manifest_sha256': sha256(Path(dataset)/'dataset.json'),
              'catalog_aliases': len(aliases), 'catalog_concepts': len({a['concept_id'] for a in aliases}),
              'cases': len(cases), 'top_k': top_k, 'max_length': max_length,
              'batch_size': batch_size, 'python': platform.python_version(), 'platform': platform.platform(),
              'implementation_sha256': sha256(__file__),
              'clinical_validation': False, 'mapping_endpoint_implemented': False,
              'interpretation': 'Prueba documental CIE-10; no mide mapeo a SNOMED.'
                  if meta['kind'] == 'cie10_documentary_proxy' else 'Recuperación de candidatos; no validación clínica.'}
    write_json(output/'run.json', report)
    engine = None
    try:
        if model == 'lexical':
            engine = LexicalRetriever(aliases)
            rankings = engine.search([c['query'] for c in cases], top_k)
        else:
            engine = TransformerRetriever(spec, device, cache_dir, max_length, batch_size)
            rankings = engine.search(aliases, cases, top_k)
            report['resources'] = engine.details
        try:
            import resource
            report['process_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == 'Darwin' else 1024)
        except ImportError:
            report['process_peak_rss_bytes'] = None
        results = [{'case_id': case['id'], 'query': case['query'],
                    'expected_ids': case.get('expected_ids', []), 'candidates': ranking}
                   for case, ranking in zip(cases, rankings, strict=True)]
        cutoffs = tuple(k for k in (1, 5, 10, 20, 50) if k <= top_k)
        report['metrics'] = metrics(results, cases, cutoffs)
        report['seconds'] = time.perf_counter()-started
        report['packages'] = {name: importlib.metadata.version(name) for name in
                              ('torch', 'transformers', 'numpy', 'huggingface-hub')
                              if importlib.util.find_spec(name.replace('-', '_')) is not None}
        report['status'] = 'completed'
        write_jsonl(output/'rankings.jsonl', results)
        report['rankings_sha256'] = sha256(output/'rankings.jsonl')
        lines = ['# Resultado de recuperación', '', report['interpretation'], '',
                 f"Modelo: {model}. Conceptos: {report['catalog_concepts']}. Casos: {len(cases)}.", '',
                 '| Consulta | Esperado documental | Primer candidato |', '|---|---|---|']
        for row in results:
            first = row['candidates'][0] if row['candidates'] else None
            values = [row['query'], ', '.join(row['expected_ids']),
                      (first['concept_id']+' — '+first['term']) if first else 'Sin coincidencias']
            lines.append('| ' + ' | '.join(v.replace('|', '\\|').replace('\n', ' ') for v in values) + ' |')
        (output/'results.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        if isinstance(engine, TransformerRetriever):
            engine.close()
        write_json(output/'run.json', report)
    return report
