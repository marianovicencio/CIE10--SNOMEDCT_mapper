"""Ephemeral JSON bridge for the clinical review screen; no inference model."""

from contextlib import redirect_stdout
import fcntl
import json
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cie10.candidate_review_service import validate_request, review_candidates


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        request = validate_request(json.loads(sys.stdin.read(20001)))
        with open("/tmp/magister-candidate-review.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with redirect_stdout(sys.stderr):
                response = review_candidates(request, ROOT)
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except Exception:
        # No exception text or request is logged: it can contain clinical input.
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "message": "No se pudo completar el contraste contextual. Puedes volver a intentarlo.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
