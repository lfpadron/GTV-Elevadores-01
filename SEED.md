# Seed y Secrets

## Bootstrap de usuarios semilla

La app crea o actualiza de forma idempotente 2 usuarios semilla usando los datos definidos en Streamlit secrets.

Si el usuario semilla:
- ya existe: se actualiza sin duplicarse
- no existe: se crea

## Estructura esperada

```toml
[seed_users.admin1]
full_name = "Administrador Semilla 1"
preferred_name = "Admin 1"
email = "admin1@example.com"

[seed_users.admin2]
full_name = "Administrador Semilla 2"
preferred_name = "Admin 2"
email = "admin2@example.com"

[gmail]
sender_email = "tu_correo_gmail@gmail.com"
app_password = "tu_app_password"
smtp_server = "smtp.gmail.com"
smtp_port = 587
use_tls = true
```

## Local

Usa:
- `.streamlit/secrets.toml`

Partiendo de:
- `.streamlit/secrets.toml.example`

## Streamlit Community Cloud

Usa:
- `st.secrets` configurado desde el panel `Secrets`

## Claves requeridas

- `seed_users.admin1.full_name`
- `seed_users.admin1.preferred_name`
- `seed_users.admin1.email`
- `seed_users.admin2.full_name`
- `seed_users.admin2.preferred_name`
- `seed_users.admin2.email`
- `gmail.sender_email`
- `gmail.app_password`

## Claves opcionales con default

- `app.title`
- `app.db_path`
- `app.base_url`
- `app.session_timeout_minutes`
- `gmail.smtp_server`
- `gmail.smtp_port`
- `gmail.use_tls`
