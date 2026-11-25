"""Read-only FHIR checks; always bind requests to an explicit dated edition."""
import json
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen

from .mapping_context import ContextError,digest
from .snomed_catalog import SYSTEM,SCTID,dated_version


class SnowstormFHIR:
    def __init__(self,base_url,version,transport=None):
        parsed=urlsplit(base_url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ContextError('Dirección FHIR inválida.')
        dated_version(version)
        self.base_url,self.version,self.transport=base_url.rstrip('/'),version,transport

    def get(self,path):
        if self.transport:return self.transport(path)
        try:
            with urlopen(Request(self.base_url+path,headers={'Accept':'application/fhir+json'}),timeout=15) as response:
                return json.load(response)
        except Exception as e:raise ContextError('No se pudo verificar Snowstorm: '+str(e)) from e

    def require_version(self):
        path='/CodeSystem?'+urlencode({'url':SYSTEM,'version':self.version})
        data=self.get(path)
        if data.get('resourceType')!='Bundle':raise ContextError('Respuesta FHIR inesperada al localizar la edición.')
        matches=[e['resource'] for e in data.get('entry',[]) if e.get('resource',{}).get('resourceType')=='CodeSystem'
                 and e['resource'].get('url')==SYSTEM and e['resource'].get('version')==self.version]
        if len(matches)!=1:raise ContextError('La edición exacta no está verificada en Snowstorm.')
        return {'version':self.version,'response_sha256':digest(data),'request_path':path}

    def lookup_active(self,concept_id):
        if not SCTID.fullmatch(concept_id):raise ContextError('Se requiere un identificador de concepto RF2.')
        path='/CodeSystem/$lookup?'+urlencode({'system':SYSTEM,'version':self.version,'code':concept_id,
                                             'displayLanguage':'es','property':'inactive'})
        data=self.get(path)
        if data.get('resourceType')!='Parameters':raise ContextError('El concepto no pudo verificarse mediante lookup.')
        parameters=data.get('parameter',[])
        versions=[p.get('valueString',p.get('valueUri')) for p in parameters if p.get('name')=='version']
        if versions!=[self.version]:raise ContextError('Snowstorm devolvió una edición diferente o sin fecha verificable.')
        displays=[p.get('valueString') for p in parameters if p.get('name')=='display']
        if len(displays)!=1 or not displays[0]:raise ContextError('Lookup no devolvió un término publicado.')
        inactive=[]
        for p in parameters:
            if p.get('name')!='property':continue
            parts=p.get('part',[])
            if any(x.get('name')=='code' and x.get('valueCode')=='inactive' for x in parts):
                values=[x.get('valueBoolean') for x in parts if x.get('name')=='value']
                if len(values)!=1 or type(values[0]) is not bool:raise ContextError('Propiedad inactive inválida.')
                inactive.extend(values)
        if len(inactive)>1 or any(inactive):raise ContextError('El concepto está inactivo o su actividad es ambigua.')
        return {'status':'verified_in_requested_server_version','active':True,'version':self.version,
            'request_path':path,'response_sha256':digest(data),
            'activity_basis':'explicit_inactive_false' if inactive else 'inactive_defaults_false_in_fhir_snomed_r4'}


def published_attributes(verified, resolver):
    """Expose published attributes without inferring new anatomy from the input.

    This is a FHIR lookup projection, not a complete role-group representation.
    Every part is retained for selected properties; no relationship is invented.
    """
    if "_proposal_attributes" not in verified:
        data = resolver.verifier.get(verified["request_path"])
        if digest(data) != verified["response_sha256"]:
            raise ContextError("Cambió la respuesta de origen al leer sus atributos.")
        attributes = []
        for prop in data.get("parameter", []):
            if prop.get("name") != "property":
                continue
            codes = [
                p.get("valueCode")
                for p in prop.get("part", [])
                if p.get("name") == "code"
            ]
            if (
                len(codes) == 1
                and isinstance(codes[0], str)
                and (codes[0].isdigit() or codes[0] == "parent")
            ):
                attributes.append(prop)
        verified["_proposal_attributes"] = attributes
    return verified["_proposal_attributes"]
