# Fuentes y dependencias

La licencia [Apache 2.0](../LICENSE) del repositorio no reemplaza las condiciones de los documentos, terminologías, modelos ni dependencias de software.

| Recurso | Uso | Distribución en este repositorio |
| --- | --- | --- |
| OPS/OMS CIE-10, edición española 2018 | Documentos de origen de la API; huellas en `config/sources.json`. | No se incluyen los PDF completos ni el corpus compilado. Se conservan anotaciones y correcciones necesarias para el parser. |
| SNOMED CT RF2 | Conceptos, descripciones y relaciones de la edición configurada. | No se incluyen archivos RF2, catálogos derivados ni índices. Cada instalación debe obtener acceso por el canal aplicable. |
| Snowstorm / Elasticsearch | Servidor terminológico y almacenamiento. | Se incluyen los archivos Compose y versiones de imágenes; no los volúmenes de datos ni las imágenes. |
| SAPBERT español | Recuperación semántica de candidatos. | Se incluye la especificación de revisión, no los pesos. |
| BGE reranker | Reordenación opcional del conjunto recuperado. | Se incluye el descargador verificado, no los pesos. |
| Gemma 3 / llama.cpp | Explicaciones locales bajo demanda. | Se incluyen el descargador y las referencias de versión; no pesos ni ejecutables. |
| Nuxt / Nuxt UI / paquetes Python | Interfaz, procesamiento y recuperación. | Se incluyen manifiestos de dependencias y código propio. |

Fuentes de referencia: [OMS](https://www.who.int/standards/classifications/classification-of-diseases), [SNOMED International](https://www.snomed.org/), [Snowstorm](https://github.com/IHTSDO/snowstorm), [SAPBERT español](https://huggingface.co/BSC-NLP4BIA/SapBERT-from-roberta-base-biomedical-clinical-es), [Gemma 3](https://huggingface.co/google/gemma-3-4b-it) y [llama.cpp](https://github.com/ggml-org/llama.cpp).

La aplicación procesa el diagnóstico y las explicaciones en memoria. El uso de una API externa envía el contexto seleccionado al proveedor con autorización del usuario; debe considerarse al decidir qué información se introduce en una instalación.
