#!/usr/bin/env python3
"""Fetch complete API context and prepare auditable, literal retrieval variants."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cie10.mapping_context import ContextError, MappingContextClient
from cie10.retrieval_queries import check_token_budget, prepare_queries, render_queries
from cie10.retrieval_core import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('code')
    parser.add_argument('--diagnostic-text')
    parser.add_argument('--scope',choices=['all','morbidity','mortality'],default='all')
    parser.add_argument('--api-url',default='http://127.0.0.1:8000')
    parser.add_argument('--page-size',type=int,default=200)
    parser.add_argument('--max-queries',type=int,default=12)
    parser.add_argument('--tokenizer-model',choices=['sapbert_spanish','sapbert_multilingual','bioelx'])
    parser.add_argument('--max-tokens',type=int,default=64)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ContextError('La carpeta de salida ya existe; usa una nueva.')
    request = {'code':args.code,'scope':args.scope}
    if args.diagnostic_text is not None:
        request['diagnostic_text'] = args.diagnostic_text
    pack = MappingContextClient(args.api_url,page_size=args.page_size).prepare(request)
    plan = prepare_queries(pack,args.max_queries)
    if args.tokenizer_model:
        from transformers import AutoTokenizer
        spec = json.loads((ROOT/'config/retrieval_models.json').read_text())['models'][args.tokenizer_model]
        tokenizer = AutoTokenizer.from_pretrained(spec['repository'],revision=spec['revision'],
            cache_dir=str(ROOT/'infra/retrieval/model-cache'),local_files_only=True,trust_remote_code=False)
        plan = check_token_budget(plan,tokenizer,args.max_tokens,spec)
    args.output.mkdir(parents=True)
    for name, value in {**pack,'queries':plan}.items():
        write_json(args.output/(name+'.json'),value)
    (args.output/'queries.md').write_text(render_queries(plan),encoding='utf-8')
    write_json(args.output/'manifest.json',{'status':'queries_prepared_not_executed',
        'files':{p.name:sha256(p) for p in sorted(args.output.iterdir()) if p.is_file()},
        'source_snapshot_sha256':plan['source_snapshot_sha256'], 'plan_sha256':plan['plan_sha256']})
    print(json.dumps({'status':plan['status'],'code':args.code,'queries':len(plan['queries']),
        'held':len(plan['held_inclusions_or_variants']), 'token_check':plan.get('token_budget_check'),
        'output':str(args.output)},ensure_ascii=False))


if __name__ == '__main__':
    main()
