#!/usr/bin/env python3
"""Import an authorised local snapshot, build once, retrieve many times."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from cie10.mapping_context import ContextError
from cie10.snomed_catalog import import_rf2
from cie10.hybrid_retrieval import build_index,run_hybrid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    imp=commands.add_parser('import-rf2')
    imp.add_argument('--concepts',type=Path,required=True)
    imp.add_argument('--descriptions',type=Path,nargs='+',required=True)
    imp.add_argument('--version',required=True)
    imp.add_argument('--output',type=Path,required=True)
    build=commands.add_parser('build')
    build.add_argument('--catalog',type=Path,required=True)
    build.add_argument('--output',type=Path,required=True)
    build.add_argument('--catalog-max-tokens',type=int,default=256)
    build.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    build.add_argument('--allow-fixture',action='store_true')
    run=commands.add_parser('run')
    run.add_argument('--queries',type=Path,required=True)
    run.add_argument('--index',type=Path,required=True)
    run.add_argument('--output',type=Path,required=True)
    run.add_argument('--pool-k',type=int,default=50)
    run.add_argument('--top-k',type=int,default=10)
    run.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    run.add_argument('--allow-fixture',action='store_true')
    run.add_argument('--fhir-url')
    args=p.parse_args()
    if args.command=='import-rf2':result=import_rf2(args.concepts,args.descriptions,args.version,args.output)
    elif args.command=='build':
        spec=json.loads((ROOT/'config/retrieval_models.json').read_text())['models']['sapbert_spanish']
        result=build_index(args.catalog,args.output,spec,args.device,args.catalog_max_tokens,allow_fixture=args.allow_fixture)
    else:result=run_hybrid(args.queries,args.index,args.output,args.pool_k,args.top_k,args.device,args.allow_fixture,args.fhir_url)
    print(json.dumps({k:v for k,v in result.items() if k in ('status','code','counts','aliases','concepts','blocker','snomed_search_executed')},ensure_ascii=False))
    return 2 if result.get('status')=='blocked' else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except ContextError as e:
        print(str(e),file=sys.stderr)
        raise SystemExit(2)
