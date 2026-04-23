# Grand Tower del Valle - v1 local

Aplicación local en Python + Streamlit + SQLite para cargar, clasificar, extraer y dar seguimiento a PDFs de reportes, hallazgos y estimaciones de elevadores del complejo Grand Tower del Valle.

## Seguridad y despliegue

Este proyecto quedó preparado para:
- desarrollo local con `.streamlit/secrets.toml`
- despliegue en Streamlit Community Cloud usando `st.secrets`
- subir el código a GitHub sin secretos versionados

Archivos sensibles que no deben subirse:
- `.streamlit/secrets.toml`

Archivo versionado de ejemplo:
- `.streamlit/secrets.toml.example`

`.env` ya no es el mecanismo de configuración de secretos de esta app.

## Estructura

```text
.
|-- app.py
|-- requirements.txt
|-- README.md
|-- SEED.md
|-- ASSUMPTIONS.md
|-- .streamlit/
|   `-- secrets.toml.example
|-- data/
|-- scripts/
`-- gtv/
```

## Requisitos

- Windows 11
- Python 3.11 o superior
- Cuenta Gmail con App Password para SMTP

## Instalación local

1. Crear entorno virtual:

```powershell
py -3 -m venv .venv
```

2. Activarlo:

```powershell
.\.venv\Scripts\Activate.ps1
```

3. Instalar dependencias:

```powershell
python -m pip install -r requirements.txt
```

4. Crear el archivo local de secretos:

```powershell
New-Item -ItemType Directory -Force .streamlit | Out-Null
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

5. Editar `.streamlit/secrets.toml` con:
- los 2 usuarios semilla
- la cuenta Gmail emisora
- el App Password de Gmail

6. Inicializar base:

```powershell
python .\scripts\init_db.py
```

7. Ejecutar la app:

```powershell
streamlit run .\app.py
```

## Streamlit Community Cloud

1. Sube el repo a GitHub sin `.streamlit/secrets.toml`.
2. En Streamlit Community Cloud, abre la app.
3. Ve a `Settings > Secrets`.
4. Pega el contenido equivalente al ejemplo `.streamlit/secrets.toml.example`.
5. Redeploy.

## Google Cloud

Para Google Cloud, este proyecto queda preparado para desplegarse en `Compute Engine`.

Archivos agregados para ese flujo:

- `scripts/publish_github_and_gce.ps1`
- `scripts/install_on_gce.sh`

Flujo esperado:

1. Mantener `.streamlit/secrets.toml` solo en local.
2. Ejecutar el script PowerShell de publicacion.
3. El script:
   - inicializa/push del repo a GitHub
   - actualiza una copia del secreto en Secret Manager
   - crea o reutiliza una VM
   - sube el codigo sin secretos ni `data/`
   - instala dependencias
   - inicializa SQLite
   - arranca Streamlit como servicio `systemd`

Requisitos locales para ese flujo:

- `git`
- `gh`
- `gcloud`
- autenticacion previa en GitHub CLI y Google Cloud CLI

## Uso rápido

1. Configura `.streamlit/secrets.toml`.
2. Inicializa la base.
3. Inicia Streamlit.
4. Entra con un correo semilla activo o solicita acceso por primera vez.
5. Carga PDFs desde `Carga de archivos`.
6. Resuelve incidencias en `Incidencias`.
7. Revisa vinculación pendiente.
8. Consulta casos, conciliación y auditoría.

## Validación de secretos

Si falta una clave requerida, la app muestra un error seguro:
- indica qué clave falta
- no revela valores sensibles
- explica dónde cargar secretos localmente o en Streamlit Community Cloud

## Datos en disco

La app crea y usa estas carpetas dentro de `data/`:

- `reportes/`
- `hallazgos/`
- `estimaciones/`
- `no_reconocidos/`
- `duplicados/`
- `exportes/`
- `por_procesar/`

## Notas

- Esta v1 no usa OCR.
- La extracción está pensada para PDFs con texto digital.
- SQLite sigue siendo el motor de base de datos para local y deploy.
