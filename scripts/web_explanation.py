"""One local explanation request via stdin. No prompts, responses or logs on disk."""
import fcntl
import json
from pathlib import Path
import re
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cie10.candidate_explanation import ExplanationError
from cie10.explanation_service import run_explanation


def terminate(*_):
    raise SystemExit(143)


def main():
    request = json.load(sys.stdin)
    expected = {'code', 'concept_id', 'diagnostic_text', 'source_snapshot_sha256', 'target_version', 'provider', 'external_consent'}
    if not isinstance(request, dict) or set(request) - expected:
        raise ExplanationError('Solicitud de explicación inválida.')
    for key, pattern in (
        ('code', r'[A-Z][0-9]{2}(?:\.[0-9]{1,2})?'),
        ('concept_id', r'[0-9]{6,18}'),
        ('source_snapshot_sha256', r'[a-f0-9]{64}')
    ):
        if not isinstance(request.get(key), str) or not re.fullmatch(pattern, request[key]):
            raise ExplanationError('Solicitud de explicación inválida.')
    if request.get('provider','local') not in ('local','openai'):
        raise ExplanationError('Proveedor de explicación no válido.')
    if request.get('provider')=='openai' and request.get('external_consent') is not True:
        raise ExplanationError('Falta confirmar el envío de la evidencia a OpenAI.')
    diagnostic = request.get('diagnostic_text', '')
    if not isinstance(diagnostic, str) or len(diagnostic) > 4000:
        raise ExplanationError('Diagnóstico inválido.')
    if not isinstance(request.get('target_version'), str):
        raise ExplanationError('Falta la edición SNOMED.')
    # The empty lock file contains no request or generated content.
    with (Path(tempfile.gettempdir()) / 'magister-explanation-11435.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ExplanationError('Ya hay una explicación en curso. Intenta nuevamente cuando termine.') from error
        return run_explanation(request)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminate)
    try:
        result = main()
    except ExplanationError as error:
        result = {'status': 'explanation_unavailable', 'analysis': None, 'message': str(error)}
    except Exception:
        result = {'status': 'explanation_unavailable', 'analysis': None,
                  'message': 'No se pudo preparar la explicación. Comprueba los servicios locales.'}
    print(json.dumps(result, ensure_ascii=False))
