# Snowstorm

Snowstorm es el servidor terminológico; los contenidos se importan desde los paquetes RF2 obtenidos por el responsable de la instalación. Los archivos de la terminología y los volúmenes de Elasticsearch quedan fuera del repositorio.

Los archivos Compose fijan las imágenes y enlazan el puerto de Snowstorm solo a `127.0.0.1:8081`. `compose.rf2.yaml` ajusta memoria y permite habilitar la escritura durante la importación. El modo de consulta utiliza `MAGISTER_SNOWSTORM_READONLY=true`.

El perfil actual compone la edición española `20261110` con la dependencia internacional `20261001`. Usar un paquete internacional de otra fecha requiere revisar la dependencia publicada y los enlaces de versión del código.

Consulta los comandos completos en la [guía de instalación](../../docs/installation.md#snomed-ct-y-snowstorm). El repositorio no incluye permisos ni acceso a distribuciones SNOMED CT.
