"""HTTP consumer of documentary CIE-10 context; no terminology mapping.

Fetch the entire selected result set, retain an audit representation, and
prepare a reading representation with one catalogue of citation locations.
"""
from copy import deepcopy
import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

from .context_readable import Reader, readable_context, without_provenance

CONSUMER_VERSION = '0.1.0'
CODE = re.compile(r'^[A-Z][0-9]{2}(?:\.[0-9]{1,2})?$')
HASH = re.compile(r'^[0-9a-f]{64}$')


class ContextError(ValueError):
    """Incomplete or inconsistent documentary input must not reach a model."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def validate_mapping_input(value):
    if not isinstance(value, dict):
        raise ContextError('La entrada debe ser un objeto JSON.')
    unknown = set(value) - {'code', 'diagnostic_text', 'scope', 'top_k', 'target_version'}
    if unknown:
        raise ContextError('Campos no permitidos: ' + ', '.join(sorted(unknown)))
    if not isinstance(value.get('code'), str) or not CODE.fullmatch(value['code']):
        raise ContextError('Se requiere un código CIE-10 canónico; no un rango o familia.')
    result = {'code': value['code'], 'scope': value.get('scope', 'all'),
              'top_k': value.get('top_k', 10)}
    if result['scope'] not in ('all', 'mortality', 'morbidity'):
        raise ContextError('scope debe ser all, mortality o morbidity.')
    if type(result['top_k']) is not int or not 1 <= result['top_k'] <= 20:
        raise ContextError('top_k debe ser un entero entre 1 y 20.')
    if 'diagnostic_text' in value:
        text = value['diagnostic_text']
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ContextError('diagnostic_text debe contener entre 1 y 4000 caracteres.')
        result['diagnostic_text'] = text  # Preserve original Unicode offsets.
    if 'target_version' in value:
        version = value['target_version']
        if not isinstance(version, str) or not re.fullmatch(
                r'http://snomed\.info/sct/[0-9]{6,18}/version/[0-9]{8}', version):
            raise ContextError('target_version debe identificar una edición SNOMED fechada.')
        result['target_version'] = version
    return result


class HTTPTransport:
    def __init__(self, base_url='http://127.0.0.1:8000', timeout=30):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ContextError('Dirección de API inválida.')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def __call__(self, path):
        if not path.startswith('/v1/') or path.startswith('//'):
            raise ContextError('Ruta documental inválida.')
        request = Request(self.base_url + path, headers={'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ContextError(f'No se pudo recuperar {path}: {error}') from error


def rebase(page):
    """Page-local s1 identifiers must never collide across HTTP responses."""
    page = deepcopy(page)
    locations = page.pop('source_locations')
    aliases = {key: 's-' + digest(location) for key, location in locations.items()}

    def visit(value):
        if isinstance(value, dict):
            if 'source_ref' in value:
                if value['source_ref'] not in aliases:
                    raise ContextError('Una referencia de procedencia no tiene ubicación.')
                value['source_ref'] = aliases[value['source_ref']]
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    page = visit(page)
    page['source_locations'] = {aliases[key]: loc for key, loc in locations.items()}
    return page


def merge_records(destination, source):
    for identifier, record in source.items():
        if identifier in destination and destination[identifier] != record:
            raise ContextError('El registro cambió durante la recuperación: ' + identifier)
        destination[identifier] = record


def unique(items):
    seen = set()
    result = []
    for item in items:
        key = canonical(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


class MappingContextClient:
    def __init__(self, base_url='http://127.0.0.1:8000', transport=None, page_size=200):
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise ContextError('page_size debe estar entre 1 y 200.')
        self.transport = transport or HTTPTransport(base_url)
        self.base_url = base_url.rstrip('/')
        self.page_size = page_size

    def fetch_evidence(self, code, scope='all'):
        validate_mapping_input({'code': code, 'scope': scope})
        merged = None
        requests = []
        retrieved = set()
        offset = 0
        while True:
            path = '/v1/codes/' + quote(code, safe='') + '?' + urlencode(
                {'view': 'evidence', 'scope': scope, 'limit': self.page_size, 'offset': offset})
            page = self.transport(path)
            snapshot = page.get('source_snapshot_sha256', '')
            if not HASH.fullmatch(snapshot):
                raise ContextError('La API no expone una huella del catálogo; se requiere API 0.8 o superior.')
            if page.get('code') != code or not isinstance(page.get('records'), dict):
                raise ContextError('Respuesta de código o registros inesperada.')
            pagination = page['pagination']
            total = pagination['total_records']
            if type(total) is not int or total < 0 or pagination.get('offset') != offset or pagination.get('limit') != self.page_size or pagination.get('scope') != scope:
                raise ContextError('Paginación inconsistente.')
            page_ids = {link['record_id'] for link in page['context_links']}
            if len(page_ids) != min(self.page_size, max(0, total - offset)) or not page_ids.issubset(page['records']) or page_ids & retrieved:
                raise ContextError('Faltan registros o una página repite resultados seleccionados.')
            expected_next = offset + self.page_size if offset + self.page_size < total else None
            if pagination.get('next_offset') != expected_next:
                raise ContextError('La secuencia de páginas está cortada o forma un ciclo.')
            page = rebase(page)
            requests.append({'path': path, 'offset': offset, 'selected_records': len(page_ids)})
            retrieved.update(page_ids)
            if merged is None:
                merged = page
            else:
                for key in ('api_version', 'edition', 'source_snapshot_sha256', 'source_manifest', 'classification', 'effective_tabular_notes', 'general_convention_refs'):
                    if page[key] != merged[key]:
                        raise ContextError('El catálogo o la proyección cambiaron entre páginas: ' + key)
                if total != merged['pagination']['total_records']:
                    raise ContextError('El total de resultados cambió entre páginas.')
                merge_records(merged['documents'], page['documents'])
                merge_records(merged['records'], page['records'])
                merge_records(merged['source_locations'], page['source_locations'])
                for key in ('context_links', 'manual_reference_links', 'supporting_manual_unit_refs'):
                    merged[key] = unique(merged[key] + page[key])
            if expected_next is None:
                break
            offset = expected_next
        # The API returns convention references separately from the selected
        # result set. Fetch their bodies too; zero paginated records is valid.
        for identifier in merged['general_convention_refs']:
            if identifier in merged['records']:
                continue
            path = '/v1/records/' + quote(identifier, safe='')
            item = self.transport(path)
            if item.get('source_snapshot_sha256') != merged['source_snapshot_sha256']:
                raise ContextError('El catálogo cambió al recuperar una convención.')
            if item.get('record', {}).get('id') != identifier:
                raise ContextError('La convención recuperada tiene otro identificador.')
            item = rebase(item)
            for key, document in item['documents'].items():
                if key in merged['documents'] and document != merged['documents'][key]:
                    raise ContextError('La identidad del documento cambió.')
                merged['documents'][key] = document
            merge_records(merged['records'], {identifier: item['record']})
            merge_records(merged['source_locations'], item['source_locations'])
        merged['pagination'] = {**merged['pagination'], 'offset': 0,
                                'next_offset': None, 'complete': True}
        merged['quality']['pending_or_ambiguous_record_refs'] = [
            r['id'] for r in merged['records'].values() if r.get('review_status') != 'source_verified']
        merged['retrieval'] = {
            'all_selected_pages_retrieved': True, 'selected_records': len(retrieved),
            'total_selected_records': total, 'page_count': len(requests),
            'page_requests': requests, 'general_conventions_retrieved': len(merged['general_convention_refs']),
            'completeness_meaning': 'selected_results_and_returned_dependencies_not_clinical_exhaustiveness'}
        return merged

    def prepare(self, request):
        request = validate_mapping_input(request)
        evidence = self.fetch_evidence(request['code'], request['scope'])
        return {'audit': evidence, 'context': compact_mapping_context(evidence, request, self.base_url)}


def compact_mapping_context(evidence, request, base_url):
    # Render only once after merging: repeated headings, parent clauses and
    # table captions no longer multiply with the number of HTTP pages.
    reading = readable_context(evidence)
    reader = Reader(evidence)
    convention_ids = set(evidence['general_convention_refs'])
    convention_urls = {'/v1/records/' + quote(i, safe='') for i in convention_ids}
    reading['shared_context'] = [item for item in reading['shared_context']
        if item.get('reference', {}).get('detail_url') not in convention_urls]
    reading['general_conventions'] = [
        {'kind': evidence['records'][i]['kind'], 'scope': evidence['records'][i].get('scope', 'classification_usage'),
         'text': reader.text(evidence['records'][i].get('text', ''), evidence['records'][i]),
         'reference': reader.reference(evidence['records'][i])}
        for i in evidence['general_convention_refs']]
    # Dependencies can enter the merged record map on different HTTP pages.
    # Their presentation order must not depend on the requested page size.
    reading['shared_context'].sort(key=lambda item: item.get('reference', {}).get('detail_url', ''))
    catalogue = {}
    external_navigation = set()

    def citation(reference):
        identifier = unquote(reference['detail_url'].split('/v1/records/', 1)[1])
        record = evidence['records'].get(identifier)
        if record is None:
            raise ContextError('Una cita remite a un registro no recuperado.')
        key = 'e:' + identifier
        sources = record.get('sources') or [record.get('source', {})]
        locations = [evidence['source_locations'].get(s.get('source_ref'), s) for s in sources]
        docs = unique([evidence['documents'][loc['document_ref']] for loc in locations if loc.get('document_ref')])
        catalogue[key] = {
            'record_id': identifier, 'volume': docs[0]['volume'] if docs else None,
            'pdf_pages': sorted({loc['pdf_page'] for loc in locations if loc.get('pdf_page')}),
            'printed_pages': list(dict.fromkeys(str(loc['printed_page']) for loc in locations if loc.get('printed_page'))),
            'source_sha256': docs[0]['sha256'] if docs else None,
            'detail_url': base_url + reference['detail_url']}
        if reference.get('reading_url'):
            catalogue[key]['reading_url'] = base_url + reference['reading_url']
        return key

    def visit(value):
        if isinstance(value, dict):
            if 'detail_url' in value and '/v1/records/' in value['detail_url']:
                identifier = unquote(value['detail_url'].split('/v1/records/', 1)[1])
                if identifier not in evidence['records']:
                    # A link to another section is not its content. Preserve
                    # navigation without fabricating evidence from an URL.
                    external_navigation.add(identifier)
                    item = {k: visit(v) for k, v in value.items()}
                    item['detail_url'] = base_url + value['detail_url']
                    if value.get('reading_url'):
                        item['reading_url'] = base_url + value['reading_url']
                    item['content_retrieved'] = False
                    return item
                # A location label alone is not fed repeatedly to the model.
                ref = citation(value)
                return {**{k: visit(v) for k, v in value.items() if k not in ('source', 'detail_url', 'reading_url')}, 'evidence_ref': ref}
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    reading = visit(reading)
    for key in ('pagination', 'evidence_url', 'retrieved_context_records', 'view'):
        reading.pop(key, None)
    # Preserve structured annotations that a reading projection intentionally
    # omits. Geometry/raw physical lines remain in the audit pack, not prompts.
    annotations = []
    names = ('code_structure', 'coding_relations', 'semantic_review_issues',
             'structure_issues', 'scope', 'scope_notes', 'clinical_input_requirements',
             'code_reference_details', 'definition_groups', 'term_groups',
             'referenced_table', 'subdivision_table', 'warnings')
    tabular_ids = unique([o['origin_record_id'] for o in evidence['effective_tabular_notes']])
    for identifier in tabular_ids:
        record = evidence['records'][identifier]
        content = {name: without_provenance(record[name]) for name in names if record.get(name)}
        if content:
            annotations.append({'evidence_ref': citation(reader.reference(record)),
                                'origin_code': record.get('code'), **content})
    inherited_scopes = [{k: origin[k] for k in ('origin_record_id', 'origin_code', 'inherited', 'scope')}
                       for origin in evidence['effective_tabular_notes']]
    result = {
        'consumer_version': CONSUMER_VERSION,
        'input': request,
        'input_mode': 'code_with_diagnostic_text' if 'diagnostic_text' in request else 'code_only',
        'source_snapshot_sha256': evidence['source_snapshot_sha256'],
        'retrieval': evidence['retrieval'],
        'documentary_context': reading,
        'tabular_origin_scopes': inherited_scopes,
        'tabular_annotations': annotations,
        'evidence': catalogue,
        'quality': {'clinical_validation': 'not_performed', 'automatic_recoding': False,
                    'patient_applicability': 'not_evaluated',
                    'snomed_mapping': 'not_performed'},
    }
    result['retrieval'] = {**result['retrieval'], 'external_navigation_content_not_retrieved': sorted(external_navigation)}
    if 'diagnostic_text' in request:
        text = request['diagnostic_text']
        result['input_evidence'] = {'i:diagnostic_text': {'field': 'diagnostic_text',
            'text': text, 'start': 0, 'end': len(text), 'offset_unit': 'unicode_code_points'}}
    result['context_sha256'] = digest(result)
    return result
