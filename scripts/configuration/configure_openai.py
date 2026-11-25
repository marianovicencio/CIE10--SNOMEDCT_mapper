"""Run interactively in WSL. Never pass credentials through command arguments."""
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from cie10.explanations.openai_explanation import DEFAULT_MODEL, normalize_api_key, OpenAIError


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Ejecuta este asistente directamente en una terminal WSL; no admite claves por argumentos o entrada redirigida.')
    print('La clave se guardará solo en .secrets/openai.json del servidor WSL, con permisos privados y excluida del repositorio.')
    try:
        key=normalize_api_key(getpass.getpass('Pega tu API key (no se mostrará): '))
    except OpenAIError as error:
        raise SystemExit(str(error)+' No se guardó ningún cambio.') from None
    folder=ROOT/'.secrets'
    if folder.is_symlink():raise SystemExit('El directorio privado no puede ser un enlace.')
    folder.mkdir(mode=0o700,exist_ok=True)
    folder.chmod(0o700)
    fd,name=tempfile.mkstemp(prefix='openai-',dir=folder)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump({'api_key':key,'model':DEFAULT_MODEL},stream)
        os.chmod(name,0o600)
        os.replace(name,folder/'openai.json')
    finally:
        if os.path.exists(name):os.unlink(name)
    print('Configuración privada guardada. Modelo: '+DEFAULT_MODEL+'. No se hizo ninguna llamada de pago.')


if __name__=='__main__':main()
