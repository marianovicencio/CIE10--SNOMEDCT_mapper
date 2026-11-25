# Instalación local

Esta guía prepara una instalación propia. Clonar el repositorio permite leer el código y abrir las páginas informativas; consultar códigos requiere preparar los catálogos y servicios. Los datos y modelos no se descargan al instalar el frontend.

## Requisitos

- Linux / Ubuntu WSL. El código de procesos y bloqueos utiliza funciones de Linux.
- Python 3.14 y Node.js 24, según los manifiestos incluidos.
- Docker con Compose, y `curl` para la importación RF2.
- GPU NVIDIA y CUDA compatibles con el entorno de recuperación actual. La generación local usa también CUDA; seleccionar la API externa solo reemplaza esa etapa de explicación.
- Espacio para PDF, RF2, datos de Elasticsearch, catálogo, vectores y modelos.

Todos los comandos parten de la raíz del clon. Las versiones del código están fijadas a CIE-10 español 2018 y SNOMED CT español 2026-11-10.

## Código y entornos

```bash
git clone https://github.com/marianovicencio/CIE10--SNOMEDCT_mapper.git
cd CIE10--SNOMEDCT_mapper

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock

python3 -m venv infra/retrieval/.venv
infra/retrieval/.venv/bin/python -m pip install -r infra/retrieval/requirements.lock

cd frontend
npm ci
cd ..
```

Si tu Python de Ubuntu no incluye `ensurepip`, instala el soporte de entornos virtuales de tu distribución. Como alternativa, un `pip` del sistema que admita `--python` puede instalar en un entorno creado con `python3 -m venv --without-pip .venv`.

El lock de recuperación conserva las versiones del entorno de referencia. Si cambias versiones de PyTorch, Transformers o del codificador, construye un índice nuevo; el servidor comprueba esa identidad al consultar.

## CIE-10: documentos e índice documental

Obtén los tres PDF de la edición española OPS/OMS 2018 por su canal oficial. `config/sources.json` contiene los nombres y SHA-256 esperados; no basta renombrar un PDF de otra edición.

```bash
.venv/bin/python -m cie10 import-sources --source-dir /ruta/a/los/tres/pdf
.venv/bin/python -m cie10 run --mode full --workers 2
.venv/bin/python -m cie10 build-context --mode full
```

La extracción guarda páginas en `data/interim/`, registros JSONL en `data/processed/` y la compilación en `data/compiled/full/context.sqlite`. Se puede reanudar. Los reportes se generan en `data/reports/`; un resultado de auditoría con salida `2` requiere revisar el reporte y no representa una validación clínica.

Las tablas de revisión incluidas en el código están vinculadas a esa edición y a secuencias de fragmentos concretas. Cambiar las fuentes puede invalidarlas.

## SNOMED CT y Snowstorm

Obtén los paquetes RF2 mediante tu acceso autorizado y conserva los ZIP, sin necesidad de descomprimirlos:

```text
snomed/SnomedCT_InternationalRF2_PRODUCTION_20261001T120000Z.zip
snomed/SnomedCT_SpanishRelease-es_PRODUCTION_20261110T120000Z.zip
```

La fecha internacional es la dependencia de esta edición española; no se selecciona simplemente el ZIP más reciente.

Inicia una instancia nueva en modo de importación:

```bash
MAGISTER_SNOWSTORM_READONLY=false docker compose -p cie10-snomed \
  -f infra/snowstorm/compose.yaml -f infra/snowstorm/compose.rf2.yaml up -d

# Comprobar que el servidor responde antes de importar:
curl --fail http://127.0.0.1:8081/fhir/metadata

.venv/bin/python scripts/import_snomed.py
```

El importador comprueba que la rama base esté vacía. Importa primero la dependencia internacional, crea la rama española y verifica sus versiones. No se debe volver a ejecutar sobre un servidor ya importado. Su estado se guarda en `data/runtime/snomed-import.json`.

Después vuelve al modo de consulta, conservando los volúmenes:

```bash
MAGISTER_SNOWSTORM_READONLY=true docker compose -p cie10-snomed \
  -f infra/snowstorm/compose.yaml -f infra/snowstorm/compose.rf2.yaml up -d
```

El puerto expuesto es `127.0.0.1:8081`; la API FHIR queda en `/fhir`. Los archivos Compose no configuran una instalación terminológica pública con autenticación.

## SAPBERT y catálogo de recuperación

Descarga el recuperador español fijado y prepara el catálogo completo:

```bash
infra/retrieval/.venv/bin/python scripts/download_retriever_models.py --models sapbert_spanish
.venv/bin/python scripts/prepare_full_snomed_catalog.py
infra/retrieval/.venv/bin/python scripts/build_full_snomed_index.py
.venv/bin/python scripts/configure_runtime.py
```

El importador compone los estados RF2 y comprueba sus dependencias. El constructor produce `aliases.sqlite`, `embeddings.npy` e `index.json` dentro de `data/indexes/snomed/full-es-20261110-v1/`. Las rutas del catálogo se generan para esta instalación: no se debe copiar un manifiesto con rutas de otro equipo sin reconstruir o revisar su enlace.

`configure_runtime.py` verifica la integridad del índice y obtiene la huella de la compilación CIE-10 local. Genera los archivos `infra/retrieval/active*.json` que vinculan la versión, las variantes de consulta y la alineación de componentes. Es una configuración de consistencia técnica, no una aprobación clínica.

El reranker es opcional:

```bash
infra/retrieval/.venv/bin/python scripts/download_local_reranker.py
.venv/bin/python scripts/configure_runtime.py --enable-reranker
```

Solo puede reordenar el mismo conjunto de candidatos cuando la entrada es elegible. Si no está configurado o disponible, la búsqueda conserva su orden de referencia.

## Modelo local opcional

Las consultas y la comparación documental pueden utilizarse sin generar explicaciones. Para habilitar Gemma local:

```bash
.venv/bin/python infra/llm/download_model.py 4b
mkdir -p infra/llm/runtime/llama-b11430-cuda
```

Obtén el archivo indicado en `gpu_runtime.source_url` de `infra/llm/software-lock.json` desde los releases oficiales de `llama.cpp`. Comprueba su SHA-256 contra `gpu_runtime.archive_sha256` **antes** de descomprimirlo. El resultado esperado es:

```text
infra/llm/runtime/llama-b11430-cuda/llama-b11430/llama-server
infra/llm/model-data/gemma3-4b.gguf
```

El servicio encuentra las bibliotecas NVIDIA en `infra/retrieval/.venv`, usa una ventana de 8.192 tokens y carga el modelo bajo demanda. La integración web actual espera este ejecutor CUDA; no utiliza el antiguo servidor CPU ni necesita Ollama ejecutándose.

## API externa opcional

```bash
.venv/bin/python scripts/configure_openai.py
```

El comando solicita la clave con entrada oculta y la guarda en `.secrets/openai.json`, con permisos privados. No se incluye una clave de ejemplo ni se coloca en variables públicas de Nuxt.

Selecciona «API externa configurada» y autoriza el envío en Opciones avanzadas. El conector implementado es OpenAI; BYOK corresponde a la instancia del servidor. Esta versión no ofrece claves separadas por visitante ni un selector de proveedores arbitrarios.

## Iniciar la plataforma

Terminal 1, en la raíz del repositorio:

```bash
.venv/bin/python -m cie10 serve --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
npm run dev
```

Abre `http://localhost:3000`. Para una compilación de producción local, utiliza `npm run build` y `npm run preview` desde `frontend/`. Snowstorm debe continuar iniciado por Docker Compose.

El frontend deduce la raíz del proyecto a partir de su carpeta; `MAGISTER_PROJECT_ROOT` permite configurarla explícitamente. `NUXT_PUBLIC_REPOSITORY_URL` solo cambia el enlace público al repositorio.

Para comprobar la API documental desde Bruno, configura un GET:

```text
http://127.0.0.1:8000/v1/codes/F00?scope=morbidity&view=readable&limit=12
```

Las respuestas documentales pueden paginarse. Las rutas Nuxt de consulta realizan la preparación y verificación necesarias para la interfaz.

## Verificación del código

```bash
python3 -m unittest discover -s tests
python3 scripts/check_reasoning.py
cd frontend
npm run typecheck
npm run build
```

Las pruebas de la API externa utilizan transportes simulados. No necesitan leer una clave real ni realizar llamadas de pago. Las pruebas que requieren los PDF o páginas extraídas se omiten cuando estos archivos no están presentes.
