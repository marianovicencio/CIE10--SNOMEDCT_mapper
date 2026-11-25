"""Fetch only public, pinned standard-transformers model files; no custom code."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from huggingface_hub import snapshot_download
from cie10.retrieval.retrieval_core import sha256, write_json
REPO='BAAI/bge-reranker-v2-m3'
REVISION='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
FILES=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','README.md']
if __name__=='__main__':
 print(json.dumps({'phase':'downloading_pinned_reranker','repository':REPO,'revision':REVISION}),flush=True)
 folder=Path(snapshot_download(REPO,revision=REVISION,cache_dir=str(ROOT/'infra/retrieval/model-cache'),allow_patterns=FILES,token=False,max_workers=2))
 config=json.loads((folder/'config.json').read_text())
 if config.get('auto_map') or config.get('model_type')!='xlm-roberta':raise ValueError('Unexpected model architecture or custom code')
 expected='d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286'
 if sha256(folder/'model.safetensors')!=expected:raise ValueError('Published weight hash mismatch')
 meta={'status':'completed','repository':REPO,'revision':REVISION,'snapshot_path':str(folder),'license_as_published':'apache-2.0','trust_remote_code':False,'weights_format':'safetensors','files':{name:{'sha256':sha256(folder/name),'bytes':(folder/name).stat().st_size} for name in FILES}}
 out=ROOT/'infra/retrieval/model-cache/download-manifests/bge-reranker-v2-m3.json';write_json(out,meta)
 print(json.dumps({'phase':'download_verified','bytes':sum(x['bytes'] for x in meta['files'].values())}),flush=True)
