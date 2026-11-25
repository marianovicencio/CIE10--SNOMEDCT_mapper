"""Local cross-encoder experiment: permute a frozen shortlist, never select a diagnosis."""
import gc,hashlib,json,math,re
from pathlib import Path
from .full_retrieval_runtime import streamed_sha256
from .mapping_context import ContextError

REPOSITORY='BAAI/bge-reranker-v2-m3'
REVISION='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
POLICY='context_only_same_five_scope_guard_v1'
SCOPE_MARKERS=re.compile(r'\b(?:no\s+(?:hay|tiene|presenta|padece)|niega|se descarta|no se descarta|(?:su|mi|la|el)\s+(?:madre|padre|herman[ao]|hij[ao]|acompanante|familiar))\b')

def query_text(title,diagnostic):
    if not isinstance(title,str) or not title.strip():raise ContextError('Falta el título oficial.')
    if not isinstance(diagnostic,str):raise ContextError('El diagnóstico debe ser texto.')
    return 'CIE-10: '+title+'\nDiagnóstico: '+diagnostic


def scope_status(diagnostic):
    from .explanation_constraints import normalize
    if not diagnostic:return 'code_only_unchanged'
    if SCOPE_MARKERS.search(normalize(diagnostic)):return 'scope_marker_keep_baseline'
    return 'eligible_for_scoring'


def apply_scores(candidates,scores):
    ids=[c['concept_id'] for c in candidates]
    if len(ids)!=5 or len(set(ids))!=5:raise ContextError('Se requieren cinco candidatos distintos.')
    if set(scores)!=set(ids) or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in scores.values()):raise ContextError('Puntuaciones incompletas o no finitas.')
    ordered=sorted(enumerate(candidates),key=lambda pair:(-scores[pair[1]['concept_id']],pair[0]))
    return [{**c,'baseline_rank':i+1,'reranker_score':float(scores[c['concept_id']]),'reranked_position':rank} for rank,(i,c) in enumerate(ordered,1)]


class LocalCrossEncoder:
    def __init__(self,root,device='cuda',max_tokens=512,batch_size=2):
        import torch
        from transformers import AutoTokenizer,AutoModelForSequenceClassification
        if device!='cuda' or not torch.cuda.is_available():raise ContextError('El experimento requiere CUDA; no cambia a CPU silenciosamente.')
        if not 4<=max_tokens<=512 or not 1<=batch_size<=4:raise ContextError('Configuración del reordenador inválida.')
        root=Path(root);manifest=root/'infra/retrieval/model-cache/download-manifests/bge-reranker-v2-m3.json'
        info=json.loads(manifest.read_text())
        if info['status']!='completed' or info['repository']!=REPOSITORY or info['revision']!=REVISION or info['trust_remote_code'] is not False:raise ContextError('Revisión del reordenador no verificada.')
        snapshot=Path(info['snapshot_path']).resolve()
        if not snapshot.is_relative_to((root/'infra/retrieval/model-cache').resolve()):raise ContextError('Modelo fuera de la caché del proyecto.')
        for name,entry in info['files'].items():
            if streamed_sha256(snapshot/name)!=entry['sha256']:raise ContextError('Cambió un archivo del reordenador.')
        self.torch=torch;self.device=device;self.max_tokens=max_tokens;self.batch_size=batch_size
        torch.set_num_threads(4);torch.manual_seed(0);torch.backends.cuda.matmul.allow_tf32=False
        self.tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False)
        self.model=AutoModelForSequenceClassification.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False,use_safetensors=True,dtype=torch.float16).eval().to(device)
        if self.model.config.num_labels!=1:raise ContextError('El modelo no devuelve un escalar por pareja.')
        torch.cuda.reset_peak_memory_stats()
        self.metadata={'repository':REPOSITORY,'revision':REVISION,'dtype':'float16','max_tokens':max_tokens,'batch_size':batch_size,'model_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'score_is_probability':False,'clinical_validation':False}

    def score(self,query,passages):
        texts=[(query,p) for p in passages]
        lengths=[len(self.tokenizer(a,b,add_special_tokens=True,truncation=False)['input_ids']) for a,b in texts]
        if any(n>self.max_tokens for n in lengths):raise ContextError('Una pareja excede el límite; no se recorta.')
        scores=[]
        for offset in range(0,len(texts),self.batch_size):
            batch=texts[offset:offset+self.batch_size]
            tokens=self.tokenizer([a for a,b in batch],[b for a,b in batch],padding=True,truncation=False,return_tensors='pt').to(self.device)
            with self.torch.inference_mode():values=self.model(**tokens,return_dict=True).logits.view(-1).float()
            scores.extend(values.cpu().tolist())
        if len(scores)!=len(passages) or any(not math.isfinite(v) for v in scores):raise ContextError('Salida no finita o incompleta.')
        return scores,lengths

    def close(self):
        del self.model;gc.collect();self.torch.cuda.empty_cache()
