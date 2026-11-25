#!/usr/bin/env python3
"""Download pinned public encoder assets, verify upstream hashes, resume chunks.

Uses the standard Hugging Face snapshot directory layout. No model code is run.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from urllib.request import Request, urlopen


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def fetch(url, destination, start=None, end=None):
    headers = {'User-Agent': 'cie10-retrieval-research/0.1'}
    if start is not None:
        headers['Range'] = f'bytes={start}-{end}'
        url += '?download=true&part=' + str(start)
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=headers), timeout=120) as response:
                if start is not None:
                    expected = f'bytes {start}-{end}/'
                    if response.status != 206 or not response.headers.get('Content-Range', '').startswith(expected):
                        raise ValueError('El servidor no respetó el intervalo solicitado.')
                with destination.open('wb') as f:
                    while data := response.read(1024*1024):
                        f.write(data)
            if start is not None and destination.stat().st_size != end-start+1:
                raise ValueError('Parte incompleta.')
            return
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt+1)


def download_model(name, spec, cache, workers):
    repo, revision = spec['repository'], spec['revision']
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Se requiere una revisión exacta.')
    api = f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true'
    with urlopen(api, timeout=40) as response:
        meta = json.load(response)
    if meta.get('sha') != revision or meta.get('gated'):
        raise ValueError('El modelo no coincide con la revisión pública prevista.')
    files = {f['rfilename']: f for f in meta['siblings']}
    weight = 'model.safetensors' if 'model.safetensors' in files else 'pytorch_model.bin'
    allowed = {'README.md', 'config.json', 'tokenizer.json', 'tokenizer_config.json',
               'special_tokens_map.json', 'added_tokens.json', 'sentencepiece.bpe.model',
               'merges.txt', 'vocab.json', weight}
    selected = [files[key] for key in sorted(allowed & files.keys())]
    if weight not in files:
        raise ValueError('El checkpoint no tiene un archivo de pesos admitido.')
    folder = cache/('models--'+repo.replace('/', '--'))/'snapshots'/revision
    folder.mkdir(parents=True, exist_ok=True)
    required = sum(f['size'] for f in selected if not (folder/f['rfilename']).is_file())
    if shutil.disk_usage('/mnt/c').free < required*2 + 2*1024**3:
        raise ValueError('Espacio físico insuficiente para descargar y ensamblar los pesos.')
    print(json.dumps({'stage': 'model_download', 'model': name, 'bytes': required}), flush=True)
    verified = []
    for item in selected:
        filename = item['rfilename']
        target = folder/filename
        upstream_sha = item.get('lfs', {}).get('sha256')
        if target.exists():
            if target.stat().st_size != item['size'] or (upstream_sha and digest(target) != upstream_sha):
                raise ValueError('Archivo previo distinto a la fuente: '+filename)
        else:
            url = f'https://huggingface.co/{repo}/resolve/{revision}/{filename}'
            temporary = target.with_name(filename+'.partial')
            if item['size'] < 16*1024**2:
                fetch(url, temporary)
            else:
                parts_dir = folder/'.parts'
                parts_dir.mkdir(exist_ok=True)
                size = 16*1024**2
                intervals = [(start, min(start+size-1, item['size']-1))
                             for start in range(0, item['size'], size)]
                def part(start, end):
                    path = parts_dir/f'{filename}.{start}-{end}'
                    if not path.exists() or path.stat().st_size != end-start+1:
                        fetch(url, path, start, end)
                    return path
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(part, start, end) for start, end in intervals]
                    done = 0
                    for future in as_completed(futures):
                        done += future.result().stat().st_size
                        if done//(128*1024**2) != (done-future.result().stat().st_size)//(128*1024**2):
                            print(json.dumps({'stage': 'download_progress', 'model': name,
                                              'downloaded_bytes': done, 'total_bytes': item['size']}), flush=True)
                with temporary.open('wb') as output:
                    for start, end in intervals:
                        with (parts_dir/f'{filename}.{start}-{end}').open('rb') as part_file:
                            shutil.copyfileobj(part_file, output, 1024*1024)
            if temporary.stat().st_size != item['size']:
                raise ValueError('Tamaño incorrecto: '+filename)
            if upstream_sha and digest(temporary) != upstream_sha:
                raise ValueError('SHA-256 diferente al publicado: '+filename)
            temporary.replace(target)
            if item['size'] >= 16*1024**2:
                for start, end in intervals:
                    path = parts_dir/f'{filename}.{start}-{end}'
                    if not path.resolve().is_relative_to(folder.resolve()):
                        raise ValueError('Ruta de parte fuera de la caché.')
                    path.unlink()
        if not upstream_sha and item.get('blobId'):
            data = target.read_bytes()
            blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if blob != item['blobId']:
                raise ValueError('Git blob distinto al publicado: '+filename)
        verified.append({'file': filename, 'bytes': target.stat().st_size,
                         'sha256': digest(target), 'upstream_lfs_sha256': upstream_sha})
    manifests = cache/'download-manifests'
    manifests.mkdir(exist_ok=True)
    (manifests/(name+'.json')).write_text(json.dumps({'model': name, **spec,
        'snapshot': str(folder), 'files': verified}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'stage': 'model_verified', 'model': name, 'files': len(verified)}), flush=True)


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', default=['sapbert_spanish'])
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=6)
    args = parser.parse_args()
    specs = json.loads((root/'config/retrieval_models.json').read_text())['models']
    cache = root/'infra/retrieval/model-cache'
    for name in args.models:
        download_model(name, specs[name], cache, args.workers)


if __name__ == '__main__':
    main()
