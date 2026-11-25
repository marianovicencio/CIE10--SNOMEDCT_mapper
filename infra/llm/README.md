# Generación local

La interfaz utiliza Gemma 3 4B a través de `llama.cpp`, cargado bajo demanda por `cie10/explanation_service.py`. El servidor escucha en `127.0.0.1:11435` y se detiene al completar la solicitud. Las explicaciones y diagnósticos no se escriben como historial.

`software-lock.json` registra los pesos y el ejecutor verificados; no contiene los archivos descargados. `download_model.py 4b` descarga el GGUF y comprueba su tamaño y SHA-256.

La integración web actual espera el ejecutor CUDA de `llama.cpp` en `runtime/llama-b11430-cuda/llama-b11430/llama-server`, el GGUF en `model-data/gemma3-4b.gguf` y las bibliotecas NVIDIA de `infra/retrieval/.venv`. Consulta la [guía de instalación](../../docs/installation.md#modelo-local-opcional).

El modelo local dispone de hasta tres intentos. El último reduce el contexto a fuentes completas sobre términos y atributos SNOMED; se identifica en pantalla y no propone una selección automática. Las restricciones documentales se comprueban con la evidencia original.

La API externa se configura aparte mediante `scripts/configure_openai.py`. En esta versión el conector implementado es OpenAI y la clave pertenece a la instancia del servidor, no a cada visitante.
