"""Server-side OpenAI transport. No request, answer or credential logging."""
from .explanation_limits import EXTERNAL_MAX_OUTPUT_TOKENS

import copy
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'.secrets/openai.json'
DEFAULT_MODEL='gpt-6.1-terra'


class OpenAIError(ValueError):
    pass



def normalize_api_key(value):
    """Treat credentials as opaque tokens; unwrap only known clipboard wrappers."""
    if not isinstance(value,str):
        raise OpenAIError('Introduce únicamente la clave completa, no un archivo o una lista.')
    edges='\ufeff\u200b\u2060'
    key=value.strip().strip(edges).strip()
    if key.startswith('\x1b[200~') and key.endswith('\x1b[201~'):
        key=key[len('\x1b[200~'):-len('\x1b[201~')].strip()
    key=re.sub(r'^(?:export\s+)?OPENAI_API_KEY\s*=\s*','',key,flags=re.IGNORECASE)
    key=re.sub(r'^(?:Authorization:\s*)?Bearer\s+','',key,flags=re.IGNORECASE)
    pairs={'"':'"',"'":"'",'“':'”','‘':'’','`':'`'}
    for _ in range(3):
        if len(key)>1 and key[0] in pairs and key[-1]==pairs[key[0]]:
            key=key[1:-1].strip().strip(edges).strip()
        else:break
    if not key:
        raise OpenAIError('No se recibió una clave. Pégala en el aviso oculto y pulsa Enter.')
    if '...' in key or '…' in key or '****' in key:
        raise OpenAIError('La entrada parece una clave oculta o recortada. Copia la clave secreta completa, no su nombre ni la vista abreviada.')
    if any(c.isspace() for c in key):
        raise OpenAIError('La entrada contiene espacios o saltos de línea. Pega solo la clave completa en una línea, sin instrucciones ni comentarios.')
    if not key.isascii() or any(ord(c)<33 or ord(c)>126 for c in key):
        raise OpenAIError('El pegado contiene caracteres invisibles o de control. Copia de nuevo la clave completa directamente desde la plataforma.')
    if len(key)<12:
        raise OpenAIError('La entrada es demasiado corta. Copia la clave completa, no el nombre del proyecto o sus últimos caracteres.')
    if len(key)>4096:
        raise OpenAIError('La entrada es demasiado larga. Pega solo la clave, no un comando ni un documento completo.')
    return key


def load_config(path=CONFIG):
    try:
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode)&0o077:
            raise OpenAIError('Configura la clave privada con .venv/bin/python scripts/configure_openai.py.')
        data=json.loads(path.read_text())
        if not isinstance(data,dict):
            raise OpenAIError('La configuración privada de OpenAI no es válida.')
        key=data.get('api_key','')
        model=data.get('model',DEFAULT_MODEL)
        key=normalize_api_key(key)
        if not isinstance(model,str) or not re.fullmatch(r'gpt-[a-zA-Z0-9._-]{1,100}',model):
            raise OpenAIError('El nombre del modelo configurado no es válido.')
        return key,model
    except OpenAIError:
        raise
    except (OSError,ValueError,TypeError):
        raise OpenAIError('No se pudo leer la configuración privada de OpenAI.') from None


def provider_schema(schema):
    """Keep enum item references; mandatory bundles and uniqueness checked locally."""
    result=copy.deepcopy(schema)
    def visit(node):
        if isinstance(node,dict):
            node.pop('uniqueItems',None)
            if node.get('type')=='array':
                node.pop('enum',None)
                alternatives=node.get('anyOf',[])
                if alternatives and all(isinstance(branch.get('items'),list) for branch in alternatives):
                    # OpenAI requires homogeneous arrays. Mandatory anchors are
                    # enforced again by the unchanged local attribution validator.
                    node.pop('anyOf')
            for value in node.values():visit(value)
        elif isinstance(node,list):
            for value in node:visit(value)
    visit(result)
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise HTTPError(req.full_url,code,'Redirect rejected',headers,None)


class OpenAITransport:
    def __init__(self,key,model,opener=None):
        self._key=key
        self.model=model
        self.opener=opener or build_opener(NoRedirect())
        self.usage=[]

    def __call__(self,body):
        prompt=body['prompt']
        if len(prompt)>60000:
            raise OpenAIError('El contexto seleccionado supera el límite de esta prueba; no se envió a OpenAI.')
        payload={'model':self.model,'input':prompt,'store':False,'max_output_tokens':EXTERNAL_MAX_OUTPUT_TOKENS,
                 'reasoning':{'effort':'low'},
                 'text':{'format':{'type':'json_schema','name':'candidate_explanation','strict':True,
                                   'schema':provider_schema(body['json_schema'])}}}
        request=Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),
                        headers={'Authorization':'Bearer '+self._key,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=60) as response:
                data=json.load(response)
        except HTTPError as error:
            error.close()
            messages={401:'La clave de OpenAI no es válida o fue revocada.',403:'La cuenta no tiene permiso para esta solicitud.',
                      404:'El modelo configurado no está disponible para esta cuenta.',
                      429:'OpenAI indicó un límite de uso o saldo insuficiente. Revisa el saldo y los límites de la API.'}
            raise OpenAIError(messages.get(error.code,'OpenAI no pudo completar la solicitud. No se reintentó automáticamente.')) from None
        except (URLError,OSError,ValueError):
            raise OpenAIError('No se pudo completar la conexión con OpenAI. La solicitud pudo consumir créditos; no se reintentó automáticamente.') from None
        if data.get('status')!='completed':
            raise OpenAIError('OpenAI no entregó una respuesta completa. No se utilizó una explicación parcial.')
        parts=[]
        for item in data.get('output',[]):
            if item.get('type')!='message':continue
            for content in item.get('content',[]):
                if content.get('type')=='refusal':
                    raise OpenAIError('OpenAI rechazó generar esta explicación.')
                if content.get('type')=='output_text':parts.append(content.get('text',''))
        if not parts:raise OpenAIError('OpenAI no devolvió una explicación textual válida.')
        usage=data.get('usage') or {}
        self.usage.append({**{key:usage[key] for key in ('input_tokens','output_tokens','total_tokens') if isinstance(usage.get(key),int)},
                           'model':data.get('model',self.model)})
        return {'content':''.join(parts),'stop_type':'eos','truncated':False}
