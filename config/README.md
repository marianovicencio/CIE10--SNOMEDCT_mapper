# Configuración documental y modelos

- `sources.json`: nombres, huellas y regiones de los tres PDF CIE-10 2018 esperados.
- `index-compatibility.json`: excepción de compatibilidad para la reorganización auditada del codificador y constructor. Fija ambas parejas de huellas; no autoriza cambios de algoritmos ni modifica los datos del índice.
- `retrieval_models.json`: identificadores y revisiones de modelos. La plataforma utiliza `sapbert_spanish`, con su revisión fijada.
- `vol2_documentary_review.json`: registro de revisión documental. Sus huellas invalidan el estado revisado si cambia la extracción; no certifica decisiones clínicas.

Las tablas `cie10/processing/volume1/reviewed_*.json` y `cie10/processing/volume3/volume3_remission_review.json` son recursos operativos del parser. Reconocen fragmentos y referencias de la edición exacta para aplicar correcciones documentales trazables. No contienen el catálogo RF2 ni sustituyen los tres volúmenes originales.

Las configuraciones de índices y capacidades se generan localmente mediante `scripts/configuration/configure_runtime.py` en `infra/retrieval/active*.json`. Están excluidas de Git porque dependen de las huellas de los datos de cada instalación.
