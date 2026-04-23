# Supuestos tecnicos no criticos

## Estado consolidado sugerido del caso

La v1 calcula el estado sugerido con esta regla inicial:

- sin documentos: `pendiente_documentacion`
- hay hallazgos pero no estimaciones: `pendiente_revision`
- hay estimaciones con recepcion incompleta: `pendiente_recepcion`
- hay estimaciones con pago incompleto: `pendiente_compra`
- existen documentos abiertos/no completados: `en_gestion`
- todo cerrado/completado: `cerrado`

El estado manual sigue siendo el valido cuando el usuario lo define.

## Creacion automatica de caso origen

Para no dejar documentos reconocidos sin agrupacion inicial, la v1 crea automaticamente un caso origen cuando:

- el documento tiene equipo identificable
- el documento no tiene sugerencias de vinculacion hacia un caso existente

Los documentos posteriores solo se sugieren; no se vinculan automaticamente.

## Resumen inteligente editable

La v1 genera `summary_ai_original` con una heuristica local basada en:

- primera oracion util del texto extraido
- descripcion corta fija de 160 caracteres

No usa modelos externos ni servicios de IA en esta version.

## Duplicados descartados

Cuando un duplicado se descarta, la v1 lo marca logicamente como `descartado` en base de datos.
El archivo no se elimina fisicamente en esta primera version para conservar trazabilidad local.

## Aviso de timeout

El aviso de timeout se evalua en cada rerun/interaccion de Streamlit.
En esta v1 no se implementa un heartbeat activo del navegador.

## Extraccion de partidas de estimacion

La extraccion de partidas usa heuristicas de lineas con columnas numericas y un fallback minimo cuando detecta concepto general.
Por eso algunas estimaciones pueden requerir correccion manual en incidencias o detalle de caso.

## Carpetas sin fecha

Si un documento no tiene fecha extraible, la v1 lo guarda bajo una ruta `sin_fecha` dentro del bucket correspondiente.

## Fechas de atendimiento y cierre en reportes/hallazgos

Los reportes operativos muestran:

- `fecha de apertura` desde la fecha/hora del documento
- `fecha de atendimiento` desde auditoria de cambio de estado cuando exista
- `fecha de cierre` desde auditoria de cambio a `cerrado` cuando exista

Si no existe auditoria historica del cambio de estado, la v1 usa un fallback conservador:

- si el estado actual ya esta en atencion/atendido/cerrado, puede mostrar la fecha original del documento como referencia operativa
- si no hay evidencia suficiente, el campo queda vacio

## Importe pagado de partidas

La v1 no guarda un monto pagado manual independiente por partida.
Para reportes y bandejas operativas, calcula `importe pagado` asi:

- si hay unidades hijas pagadas, prorratea el subtotal por cantidad pagada
- si la partida esta en `pagada_total`, usa el subtotal completo
- si la partida esta en `pagada_parcial` pero no hay desglose suficiente por unidad, muestra el monto confirmado disponible; si no hay evidencia suficiente, conserva un valor conservador

## Vinculacion de estimaciones desde la bandeja de partidas

La vinculacion desde la vista de estimaciones opera a nivel documento de estimacion.
Aunque la tabla se muestra por partida, al vincular una fila se vincula la estimacion completa al caso seleccionado.

## Código de equipo

La v1 mantiene un `codigo de equipo` interno cuando puede extraerlo o inferirlo.

- si el PDF trae `Código: 10265-MEX-ELE-BLT`, ese valor se conserva
- si una estimacion no trae codigo explicito pero el equipo coincide con un alias conocido del complejo, la v1 infiere el codigo
- si no existe evidencia suficiente, el codigo queda vacio y la app usa el fallback previo por texto/equipo

La normalizacion interna de vinculacion y filtros prioriza este codigo cuando esta disponible.

## Publicacion en Google Cloud

Para publicacion en Google Cloud, esta v1 asume `Compute Engine` en lugar de `Cloud Run`.

Motivo:

- la herramienta persiste `SQLite` y archivos PDF locales dentro de `data/`
- `Cloud Run` es estateless y su filesystem no es un medio duradero adecuado para esta combinacion
- una VM de `Compute Engine` conserva disco persistente local, que encaja mejor con la arquitectura actual sin migrar de motor de datos

La automatizacion de despliegue:

- sube primero el codigo a GitHub sin secretos ni runtime data
- publica los secretos solo fuera del repo
- despliega la app Streamlit en una VM Linux con servicio `systemd`
- deja la base SQLite y los documentos en el disco persistente de la VM
