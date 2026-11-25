from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cie10.full_retrieval import build_index
if __name__=='__main__':
    spec=json.loads((ROOT/'config/retrieval_models.json').read_text())['models']['sapbert_spanish']
    result=build_index(ROOT/'data/catalogs/snomed/full-es-20261110-v1',ROOT/'data/indexes/snomed/full-es-20261110-v1',spec,batch_size=32)
    print(json.dumps({k:result[k] for k in ('status','aliases','concepts','semantic_aliases','lexical_only_aliases','seconds_this_run')}))
