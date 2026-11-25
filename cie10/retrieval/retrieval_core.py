"""Shared file helpers, lexical normalization and the pinned SAPBERT encoder.

Neural libraries are imported only when creating an encoder. Retrieval and
preprocessing share these primitives without importing research experiments.
"""
import gc
import hashlib
import json
from pathlib import Path
import re
import unicodedata

PIN = re.compile(r'^[0-9a-f]{40}$')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def normalize(text):
    # This is lexical token normalization, never a modification of the evidence.
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+', text))


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


    def close(self):
        del self.model
        gc.collect()
        if self.device == 'cuda':
            self.torch.cuda.empty_cache()
