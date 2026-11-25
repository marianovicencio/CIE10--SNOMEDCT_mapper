"""Download the pinned official Gemma GGUF in verified HTTP byte ranges."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
import sys
from urllib.request import Request, urlopen

FOLDER = Path(__file__).resolve().parent
MODELS = {'4b': ('f06e91e18fc74295d0c781bf91622508c75655e2c18ed869d52447ffe1e667e1', 2499012288)}
PART_SIZE = 8 * 1024 * 1024


def main():
    VARIANT = sys.argv[1] if len(sys.argv) > 1 else '4b'
    SHA256, SIZE = MODELS[VARIANT]
    URL = 'https://registry.ollama.ai/v2/library/gemma3/blobs/sha256:' + SHA256
    folder = FOLDER / 'model-data'
    folder.mkdir(exist_ok=True)
    temporary = folder / ('gemma3-' + VARIANT + '.gguf.partial')
    destination = folder / ('gemma3-' + VARIANT + '.gguf')
    state_path = FOLDER / ('model-download-' + VARIANT + '-progress.json')
    state = {'model': 'gemma3:' + VARIANT, 'sha256': SHA256, 'url': URL,
             'bytes_total': SIZE, 'status': 'downloading', 'completed_parts': {}}
    if state_path.exists():
        previous = json.loads(state_path.read_text())
        if previous.get('sha256') == SHA256 and temporary.exists() and temporary.stat().st_size == SIZE:
            state = previous
            state['status'] = 'downloading'
    if destination.exists():
        if hash_file(destination) != SHA256:
            raise ValueError('El modelo existente tiene otra huella.')
        print('Model already verified')
        return
    with temporary.open('ab') as stream:
        stream.truncate(SIZE)
    lock = threading.Lock()

    def write_state():
        state['bytes_complete'] = sum(p['size'] for p in state['completed_parts'].values())
        path = state_path.with_suffix('.tmp')
        path.write_text(json.dumps(state, indent=2))
        path.replace(state_path)

    def download(index):
        start = index * PART_SIZE
        end = min(SIZE - 1, start + PART_SIZE - 1)
        previous = state['completed_parts'].get(str(index))
        if previous:
            with temporary.open('rb') as stream:
                stream.seek(start)
                chunk = stream.read(end - start + 1)
            if hashlib.sha256(chunk).hexdigest() == previous['sha256']:
                return index, previous
        for attempt in range(3):
            try:
                request = Request(URL, headers={'Range': f'bytes={start}-{end}'})
                with urlopen(request, timeout=120) as response:
                    expected = f'bytes {start}-{end}/{SIZE}'
                    if response.status != 206 or response.headers.get('Content-Range') != expected:
                        raise ValueError('El servidor no respetó el rango de descarga.')
                    chunk = response.read(end - start + 2)
                if len(chunk) != end - start + 1:
                    raise ValueError('El rango descargado quedó incompleto.')
                with temporary.open('r+b') as stream:
                    stream.seek(start)
                    stream.write(chunk)
                return index, {'size': len(chunk), 'sha256': hashlib.sha256(chunk).hexdigest()}
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)

    write_state()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(download, i) for i in range((SIZE + PART_SIZE - 1) // PART_SIZE)]
            for future in as_completed(futures):
                index, result = future.result()
                with lock:
                    state['completed_parts'][str(index)] = result
                    write_state()
    except Exception as error:
        state['status'] = 'download_failed'
        state['error_type'] = type(error).__name__
        write_state()
        raise
    state['status'] = 'verifying_sha256'
    write_state()
    if hash_file(temporary) != SHA256:
        state['status'] = 'sha256_failed'
        write_state()
        raise ValueError('La huella no coincide con el modelo oficial.')
    temporary.replace(destination)
    state['status'] = 'verified'
    write_state()
    print('Official Gemma model downloaded and SHA-256 verified', flush=True)


def hash_file(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


if __name__ == '__main__':
    main()
