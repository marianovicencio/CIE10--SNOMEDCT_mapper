import argparse
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .audit import audit
from .common import MANIFEST, ROOT, read_json, read_jsonl, sha256, write_json
from .extract import extract_volume
from .parse import parse_all


def import_sources(source_dir, manifest):
    source_dir = Path(source_dir).expanduser().resolve()
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for config in manifest["volumes"].values():
        source = source_dir / config["filename"]
        if not source.is_file() or sha256(source) != config["sha256"]:
            raise ValueError(f"PDF ausente o huella distinta a la fuente verificada: {source}")
    # Validate all three originals before any copy. Never replace a differing source.
    for config in manifest["volumes"].values():
        destination = raw / config["filename"]
        if destination.exists() and sha256(destination) != config["sha256"]:
            raise ValueError(f"Ya existe una fuente diferente: {destination}")
    for config in manifest["volumes"].values():
        destination = raw / config["filename"]
        if not destination.exists():
            temporary = destination.with_suffix(".pdf.tmp")
            shutil.copyfile(source_dir / config["filename"], temporary)
            if sha256(temporary) != config["sha256"]:
                raise ValueError(f"Falló la verificación de copia: {temporary}")
            temporary.replace(destination)
        print(f"Fuente verificada: {destination.name}", flush=True)
    write_json(raw / "manifest.json", manifest)


def run_extraction(args, manifest):
    volumes = args.volumes if hasattr(args, "volumes") else [1, 2, 3]
    if args.workers == 1:
        for volume in volumes:
            extract_volume(volume, manifest["volumes"][str(volume)], args.mode, args.force)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(extract_volume, v, manifest["volumes"][str(v)], args.mode, args.force) for v in volumes]
            for future in futures:
                future.result()


def main():
    parser = argparse.ArgumentParser(description="Preparación reproducible de los tres tomos CIE-10 OPS/OMS 2018")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-sources", help="Copiar y verificar los tres PDF locales")
    importer.add_argument("--source-dir", required=True)
    for name in ("extract", "parse", "audit", "run", "lookup"):
        command = commands.add_parser(name)
        command.add_argument("--mode", choices=["pilot", "full"], default="pilot")
        if name in ("extract", "run"):
            command.add_argument("--workers", type=int, choices=[1, 2, 3], default=1)
            command.add_argument("--force", action="store_true", help="Recalcular páginas generadas; nunca modifica los PDF")
        if name in ("extract", "parse"):
            command.add_argument("--volumes", nargs="+", type=int, choices=[1, 2, 3], default=[1, 2, 3])
        if name == "lookup":
            command.add_argument("code", help="Código exacto del tomo 1, por ejemplo J18.9")
    renderer = commands.add_parser("render", help="Renderizar una página original para revisión visual")
    renderer.add_argument("--volume", type=int, choices=[1, 2, 3], required=True)
    renderer.add_argument("--page", type=int, required=True, help="Página física del PDF, empezando en 1")
    compiler=commands.add_parser('build-context',help='Compilar la consulta documental de los tres tomos')
    compiler.add_argument('--mode',choices=['pilot','full'],default='full')
    context=commands.add_parser('context',help='Consultar los tres tomos por código')
    context.add_argument('code')
    context.add_argument('--scope',choices=['all','mortality','morbidity'],default='all')
    context.add_argument('--limit',type=int,default=50)
    context.add_argument('--offset',type=int,default=0)
    context.add_argument('--view',choices=['readable','evidence'],default='readable')
    server=commands.add_parser('serve',help='Iniciar la API documental local de solo lectura')
    server.add_argument('--host',default='127.0.0.1')
    server.add_argument('--port',type=int,default=8000)
    consumer=commands.add_parser('mapping-context',help='Recuperar todo el contexto documental para el contrato de mapeo')
    consumer.add_argument('code')
    consumer.add_argument('--scope',choices=['all','mortality','morbidity'],default='all')
    consumer.add_argument('--diagnostic-text')
    consumer.add_argument('--api-url',default='http://127.0.0.1:8000')
    consumer.add_argument('--page-size',type=int,default=200)
    consumer.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    manifest = read_json(MANIFEST)
    try:
        if args.command == "import-sources":
            import_sources(args.source_dir, manifest)
        elif args.command=='build-context':
            from .context_api import build_database
            print(json.dumps(build_database(args.mode),ensure_ascii=False))
        elif args.command=='context':
            from .context_api import ContextStore
            print(json.dumps(ContextStore().context(args.code,args.scope,args.limit,args.offset,args.view),ensure_ascii=False,indent=2))
        elif args.command=='mapping-context':
            from .mapping_context import MappingContextClient
            request={'code':args.code,'scope':args.scope}
            if args.diagnostic_text is not None:request['diagnostic_text']=args.diagnostic_text
            pack=MappingContextClient(args.api_url,page_size=args.page_size).prepare(request)
            if args.output.exists():raise ValueError('La carpeta de salida ya existe; usa otra para conservar el paquete anterior.')
            for name,payload in pack.items():write_json(args.output/(name+'.json'),payload)
            print(json.dumps({'status':'context_prepared','output':str(args.output),'retrieval':pack['context']['retrieval']},ensure_ascii=False))
        elif args.command=='serve':
            from .context_api import serve
            serve(host=args.host,port=args.port)
        elif args.command in ("extract", "run"):
            run_extraction(args, manifest)
            if args.command == "run":
                parse_all(args.mode, manifest)
                return 0 if audit(args.mode)["structural_checks_passed"] else 2
        elif args.command == "parse":
            parse_all(args.mode, manifest, args.volumes)
        elif args.command == "audit":
            return 0 if audit(args.mode)["structural_checks_passed"] else 2
        elif args.command == "lookup":
            records = [r for r in read_jsonl(ROOT / "data" / "processed" / args.mode / "vol1_tabular.jsonl") if r.get("code") == args.code.upper()]
            if not records:
                print("No se encontró un encabezado para ese código en esta extracción.", file=sys.stderr)
                return 1
            print(json.dumps(records, ensure_ascii=False, indent=2))
        elif args.command == "render":
            import pdfplumber
            config = manifest["volumes"][str(args.volume)]
            if not 1 <= args.page <= config["pages"]:
                raise ValueError("Página fuera del documento")
            source = ROOT / "data" / "raw" / config["filename"]
            if sha256(source) != config["sha256"]:
                raise ValueError("Huella del PDF distinta del manifiesto")
            out = ROOT / "data" / "reports" / "qa" / f"vol{args.volume}_page_{args.page:04d}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            with pdfplumber.open(source) as pdf:
                pdf.pages[args.page - 1].to_image(resolution=150).save(out)
            print(out)
    except (ValueError, FileNotFoundError,KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
