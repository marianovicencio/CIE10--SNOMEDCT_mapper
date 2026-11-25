# Guía de lectura del código

## Carpetas por responsabilidad

```text
cie10/
├── processing/         Extracción, reconstrucción y auditoría documental.
│   ├── volume1/       Lista tabular, listas, llaves, alcance y herencia.
│   ├── volume2/       Manual, reglas, ejemplos, unidades y anexos.
│   └── volume3/       Índice, tablas, continuaciones y remisiones.
├── api/                Compilación, servicio HTTP y consumo del contexto CIE-10.
├── retrieval/          Consultas, SAPBERT, BM25, RRF, índices y reranker.
├── terminology/        Catálogos RF2, verificación FHIR y alineación SNOMED CT.
├── comparison/         Contraste documental de los candidatos y sus dimensiones.
├── explanations/       Prompts, generación local/BYOK, citas y validación.
├── reasoning/          Afirmaciones, alcance y restricciones de los tres tomos.
└── common.py           Raíz del proyecto y utilidades documentales compartidas.

scripts/
├── preparation/        Importación RF2, catálogo, índice y preparación de consultas.
├── models/             Descarga de SAPBERT y del reranker.
├── configuration/      Configuración local y de la API externa.
├── web/                Entrada JSON desde el servidor Nuxt.
└── checks/             Ejecución de las pruebas de razonamiento.

tests/                  Grupos equivalentes a los módulos, con configuración aparte.
frontend/               Interfaz Nuxt + Nuxt UI y rutas de servidor.
config/                 Fuentes, revisiones, modelos y compatibilidad del índice.
infra/                  Snowstorm y ejecutor del modelo generativo local.
docs/                   Instalación y guía de lectura.
```

`cie10/__main__.py` conserva el comando `python -m cie10`; `common.py` mantiene las utilidades y la raíz compartida. Los archivos `__init__.py` definen los paquetes y permiten descubrir las pruebas en subcarpetas. No son procesos adicionales.

## Scripts de operación

| Grupo | Archivos | Cuándo se utiliza |
| --- | --- | --- |
| `scripts/preparation/` | `import_snomed.py`, `prepare_full_snomed_catalog.py`, `build_full_snomed_index.py`, `prepare_retrieval_queries.py` | Preparar o reconstruir las fuentes y el índice. |
| `scripts/models/` | `download_retriever_models.py`, `download_local_reranker.py` | Descargar las revisiones fijadas de los modelos de recuperación. |
| `scripts/configuration/` | `configure_runtime.py`, `configure_openai.py` | Configurar los datos preparados y la clave privada de la API externa. |
| `scripts/web/` | `web_retrieval.py`, `web_candidate_review.py`, `web_explanation.py` | Atender las solicitudes de Nuxt mediante entrada y salida JSON. |
| `scripts/checks/` | `check_reasoning.py` | Ejecutar los controles de comparación, fuentes y explicaciones. |

## Recorrido de una consulta

1. `frontend/app/composables/useConsultation.ts` coordina el código, el diagnóstico opcional, la búsqueda, la selección del candidato y las explicaciones en memoria.
2. `frontend/server/api/candidatos.post.ts` valida la solicitud e inicia `scripts/web/web_retrieval.py`. No genera equivalencias.
3. `cie10/api/mapping_context.py` recupera todas las páginas necesarias de la API documental y mantiene la evidencia de entrada separada de las fuentes.
4. `cie10/retrieval/retrieval_queries.py` y `retrieval_title_fragments.py` preparan variantes trazables, con comprobación de longitud antes de codificar.
5. `cie10/retrieval/full_retrieval_runtime.py` lee el índice en bloques. `full_retrieval.py` implementa BM25, recuperación vectorial y fusión RRF. `retrieval_core.py` contiene el codificador SAPBERT y las funciones compartidas de normalización y huellas.
6. `cie10/terminology/snowstorm_verification.py` verifica la edición y actividad del concepto mediante FHIR. `terminology_alignment.py` resuelve componentes con descripciones publicadas y relaciones direccionales.
7. `scripts/web/web_candidate_review.py`, `candidate_review_service.py` y `candidate_context.py` contrastan los candidatos con el contexto documental.
8. `cie10/comparison/candidate_comparison.py` compone dimensiones y mensajes automáticos. `ComparisonDimension.vue` y `CandidateContextReview.vue` presentan valores, lectura y fuentes.
9. `scripts/web/web_explanation.py` inicia `cie10/explanations/explanation_service.py` al solicitar una explicación. El modelo no interviene en cada consulta ni genera todos los candidatos a la vez.

## Documentos CIE-10

- `processing/extract.py`: texto visible, tipografía, geometría y normalización de páginas.
- `processing/parse.py`: puntos de entrada para reconstruir los tres volúmenes.
- `processing/volume1/tabular_*`: listas, llaves, herencia, semántica, relaciones y correcciones documentales del volumen 1.
- `processing/volume2/manual_*`: estructura, unidades, ámbitos, tablas y reglas del volumen 2.
- `processing/volume3/`: rutas, continuaciones, tablas, remisiones y revisión documental del volumen 3.
- `api/context_api.py`: compilación SQLite y servicio HTTP de consulta por código.
- `api/context_readable.py`: proyección legible; conserva el acceso a la evidencia original.
- `processing/audit.py`: controles estructurales y reportes generados localmente.

Los JSON de revisión que acompañan al código son recursos de normalización, vinculados a fragmentos y huellas de la edición. Deben revisarse al cambiar la fuente; no son reglas clínicas universales.

## Explicaciones

Los módulos siguientes están en `cie10/explanations/`; las restricciones compartidas están en `cie10/reasoning/`.

| Archivo | Función |
| --- | --- |
| `explanation_service.py` | Reúne evidencia, aplica restricciones y llama al proveedor elegido. |
| `explanation_prompt.py` | Instrucciones y presentación de los datos al modelo. |
| `explanation_contract.py` | Esquema de respuesta y fuentes de base obligatorias. |
| `candidate_explanation.py` | Generación, reintentos y coordinación de validaciones. |
| `explanation_focus.py`, `explanation_budget.py` | Selección de fuentes completas y ajuste al presupuesto de tokens. |
| `explanation_recovery.py` | Contexto reducido del último intento local. |
| `explanation_validation.py`, `explanation_attribution.py` | Estructura, citas y atribución por afirmación. |
| `openai_explanation.py` | Transporte externo y lectura privada de la configuración. |
| `reasoning/` | Afirmaciones, negación, contexto y prioridad de restricciones. |

Las reglas automáticas y los textos de comparación pueden describir, diferir o restringir. No convierten una similitud, un sitio compartido o una relación jerárquica en una aprobación clínica.

## Interfaz y rutas

`frontend/app/pages/` conserva las páginas de consulta, propósito, desafíos, preprocesamiento, flujo, recuperación y modelos. Los estilos compartidos están en `app/assets/css/`. El tutorial vive en `GuidedTour.vue`.

Las rutas principales son `POST /api/candidatos`, `POST /api/revision-contextual` y `POST /api/explicacion`. Los JSON técnicos se sirven desde `server/api/raw/`. La API documental separada utiliza `GET /v1/codes/{codigo}` con `scope`, `view`, `limit` y `offset`.

## Datos y configuración local

`data/`, `snomed/`, los modelos y las credenciales se excluyen de Git. `scripts/configuration/configure_runtime.py` enlaza las huellas del índice y de la compilación documental de cada instalación. No reutiliza informes antiguos ni atribuye validación clínica a esa configuración.

Al cambiar el algoritmo del codificador o del constructor hay que reconstruir el índice. `retrieval_configuration.py` exige huellas exactas. La única excepción es la reorganización de código documentada en `config/index-compatibility.json`: conserva las funciones de codificación y ranking, y fija tanto las huellas antiguas como las nuevas. No modifica el manifiesto original ni omite la integridad de vectores, catálogo, paquetes o edición. Las capacidades opcionales también comprueban su revisión del código.

## Qué se conserva y qué queda fuera

La ejecución web utiliza los puentes `web_*.py` y los módulos del recorrido anterior. Los demás scripts preparan datos, descargan modelos, importan SNOMED CT, configuran la instalación o ejecutan controles. No se ejecutan todos al consultar un código.

El repositorio conserva la preparación reproducible de los tres volúmenes y las pruebas del comportamiento actual. Se retiraron el índice piloto, la búsqueda independiente de frases y las herramientas de experimentos históricos. Las explicaciones no tienen una respuesta prefabricada de sustitución: los reintentos vuelven a consultar al modelo y un intento inválido permanece identificado como tal.

## Organización y ejecución de pruebas

`tests/` refleja los grupos de `cie10/`: `api/`, `comparison/`, `explanations/`, `reasoning/`, `retrieval/`, `terminology/` y `processing/volume1`, `volume2`, `volume3`. `configuration/` comprueba la activación de una instalación. Las importaciones de fixtures son relativas a cada grupo.

Desde la raíz del proyecto:

```bash
# Toda la suite, incluida la búsqueda recursiva en paquetes:
.venv/bin/python -m unittest discover -s tests

# Controles de razonamiento sin modelos ni llamadas de pago:
.venv/bin/python scripts/checks/check_reasoning.py

# Un módulo concreto de recuperación, usando su entorno con NumPy:
infra/retrieval/.venv/bin/python -m unittest tests.retrieval.test_full_retrieval
```

Los comandos de instalación se encuentran actualizados en [installation.md](installation.md). Las URLs públicas de las APIs y `python -m cie10` conservan su contrato; cambian las rutas internas de los scripts.
