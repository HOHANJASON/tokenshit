# NexToken AI Local Backend

NexToken AI es una plataforma de gestion de APIs de IA desarrollada con FastAPI. Su objetivo es ofrecer una pasarela compatible con OpenAI, con panel de administracion, consola de clientes, gestion de proveedores, rutas de modelos, claves API, saldo, cobro por uso, limites de velocidad y registros operativos.

El proyecto toma como referencia el flujo funcional de New API, pero mantiene una identidad propia de NexToken con tema negro y dorado.

## Estado actual

Este repositorio contiene la linea principal de desarrollo:

```text
local-backend/
```

El proyecto `legacy-new-api/` se usa unicamente como referencia historica y no debe modificarse salvo que se indique explicitamente.

## Funciones implementadas

- Backend FastAPI.
- Sitio publico para clientes.
- Panel de administracion.
- Consola de clientes.
- API compatible con OpenAI:
  - `GET /v1/models`
  - `POST /v1/chat/completions`
  - `POST /v1/images/generations`
- Respuestas de chat normales y en streaming.
- Gestion de proveedores y canales upstream.
- Configuracion de modelos y precios.
- Rutas multiples por modelo.
- Priorizacion, peso, fallback y enfriamiento por errores de ruta.
- Claves API de cliente.
- Limites RPM/TPM por clave.
- Saldo de cliente.
- Reserva previa de saldo y liquidacion posterior segun uso real.
- Registro de uso y errores.
- Catalogo de 31 modelos:
  - 28 modelos de chat.
  - 3 modelos de imagen.
- Endpoint publico de precios:
  - `/api/pricing`
- Endpoint de catalogo:
  - `/api/catalog`
- Migraciones con Alembic.
- Modo local con SQLite.
- Modo Docker con PostgreSQL y Redis.
- Integracion base para inicio de sesion y vinculacion con Gmail.
- Tema de administracion negro/dorado inspirado en New API.

## Requisitos

- Windows con PowerShell.
- Python 3.12 o compatible.
- Docker Desktop, opcional pero recomendado para modo de produccion local.

Dependencias principales:

- FastAPI
- Uvicorn
- SQLAlchemy
- Alembic
- PostgreSQL driver `psycopg`
- Redis
- HTTPX
- PyJWT
- Cryptography

## Inicio rapido en Windows

Desde la carpeta `local-backend/`, ejecutar:

```powershell
.\Start-NexToken.bat
```

El script:

1. Crea `.env` si no existe.
2. Genera credenciales locales de administrador.
3. Ejecuta migraciones de base de datos.
4. Inicia el servidor en `127.0.0.1:3100`.

URLs locales:

- Sitio publico: `http://127.0.0.1:3100/`
- Panel de administracion: `http://127.0.0.1:3100/admin`
- Consola de cliente: `http://127.0.0.1:3100/customer`
- API compatible con OpenAI: `http://127.0.0.1:3100/v1`

Para detener el servicio:

```powershell
.\Stop-NexToken.bat
```

## Variables de entorno

Copiar `.env.example` a `.env` y ajustar los valores necesarios.

Variables principales:

```env
APP_PORT=3100
TZ=Asia/Taipei
NEXTOKEN_RUNTIME=docker
DATABASE_URL=postgresql+psycopg://nextoken:REPLACE_WITH_DATABASE_PASSWORD@postgres:5432/nextoken
REDIS_URL=redis://:REPLACE_WITH_REDIS_PASSWORD@redis:6379/0
REDIS_REQUIRED=true
ROUTE_FAILURE_THRESHOLD=3
ROUTE_COOLDOWN_SECONDS=60
POSTGRES_DB=nextoken
POSTGRES_USER=nextoken
POSTGRES_PASSWORD=REPLACE_WITH_DATABASE_PASSWORD
REDIS_PASSWORD=REPLACE_WITH_REDIS_PASSWORD
ADMIN_USERNAME=admin
ADMIN_PASSWORD=REPLACE_WITH_A_LONG_RANDOM_PASSWORD
APP_SECRET=REPLACE_WITH_AT_LEAST_32_RANDOM_BYTES
ALLOWED_ORIGINS=http://127.0.0.1:3100,http://localhost:3100
GOOGLE_CLIENT_ID=
```

Notas:

- No subir `.env` a GitHub.
- No cambiar `APP_SECRET` en un entorno con datos existentes sin un plan de migracion, porque las claves API de proveedores cifradas podrian dejar de poder descifrarse.
- En modo local, se puede usar SQLite.
- En modo Docker, se usan PostgreSQL y Redis.

## Modo Docker

Configurar en `.env`:

```env
NEXTOKEN_RUNTIME=docker
```

Luego ejecutar:

```powershell
.\Start-NexToken.bat
```

El `docker-compose.yml` levanta:

- Aplicacion NexToken.
- PostgreSQL.
- Redis.

## Migraciones

Ejecutar manualmente:

```powershell
.\.venv\Scripts\python.exe scripts\migrate.py
```

Ver la migracion actual:

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

Crear una nueva migracion:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "descripcion del cambio"
```

Migraciones actuales:

- `0001_initial.py`
- `0002_routing_and_limits.py`
- `0003_model_capabilities.py`
- `0004_gmail_identity.py`

## Ejemplo de uso con OpenAI SDK

Python:

```python
from openai import OpenAI

client = OpenAI(
    api_key="nxt_live_xxxxxxxxx",
    base_url="http://127.0.0.1:3100/v1",
)

response = client.chat.completions.create(
    model="gpt-5.5",
    messages=[
        {"role": "user", "content": "Hola"}
    ],
)

print(response.choices[0].message.content)
```

cURL:

```bash
curl http://127.0.0.1:3100/v1/chat/completions \
  -H "Authorization: Bearer nxt_live_xxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.5",
    "messages": [{"role": "user", "content": "Hola"}]
  }'
```

## Gmail

La base para Gmail ya esta implementada.

Endpoints:

- `GET /api/auth/google/config`
- `POST /api/customer/google/login`
- `POST /api/customer/google/bind`

Para activar Gmail:

1. Crear un OAuth Client ID en Google Cloud.
2. Configurar el dominio o localhost autorizado.
3. Colocar el valor en `.env`:

```env
GOOGLE_CLIENT_ID=tu_google_client_id
```

4. Reiniciar NexToken.

Actualmente solo se permite vincular cuentas `@gmail.com`. Si se necesita Google Workspace, se debe ajustar la validacion del dominio.

## Seguridad

No subir a GitHub:

- `.env`
- `data/`
- `.venv/`
- bases de datos SQLite locales
- claves de proveedores
- claves API reales
- credenciales de pago

Buenas practicas pendientes para produccion:

- Usar HTTPS.
- Usar una base de datos PostgreSQL administrada.
- Usar Redis persistente.
- Rotar claves y secretos.
- Configurar CORS con dominios reales.
- Anadir auditoria de administradores.
- Anadir 2FA para administradores.
- Anadir monitoreo y alertas.

## Funciones pendientes

### Administracion y usuarios

- Administradores en base de datos.
- Multiples administradores.
- Roles y permisos.
- Cambio de contrasena desde UI.
- Auditoria de acciones administrativas.
- Gestion completa de usuarios.

### Paridad con New API

Pendiente de implementar completamente:

- Playground.
- Pagina de chat.
- Logs de imagen.
- Logs de tareas.
- Gestion de billetera.
- Configuracion personal.
- Suscripciones.
- Despliegue de modelos.
- Codigos de recarga o cupones.
- Configuracion del sistema.
- Agrupacion y precios por grupo.
- Anuncios.
- FAQ y configuracion del dashboard.
- Operaciones masivas, filtros, ordenamiento y configuracion de columnas.

### Pagos y pedidos

Pendiente:

- Tabla de pedidos.
- Estados de pago.
- LINE Pay.
- Tarjeta de credito.
- USDT.
- Transferencia bancaria con revision manual.
- Reembolsos.
- Webhooks de pago con verificacion de firma.
- Recibos o facturas.

### Modelos reales

El catalogo de 31 modelos existe, pero falta validacion comercial completa con proveedores reales.

Pendiente:

- Claves reales de proveedores.
- Confirmar permisos de uso comercial y reventa.
- Adaptadores nativos para Anthropic, Gemini y proveedores de imagen.
- Pruebas de extremo a extremo por modelo.
- Sincronizacion de precios y capacidades.
- Manejo de diferencias de endpoint por proveedor.

### Riesgo, abuso y operacion

Pendiente:

- Restriccion por IP.
- Restriccion de modelos por API Key.
- Fecha de expiracion de API Key.
- Deteccion de trafico anomalo.
- Listas negras y listas blancas.
- Suspension de cuentas.
- Revision de abuso.
- Exportacion CSV.
- Estadisticas por usuario, modelo, costo e ingreso.

## Pruebas

Existe un smoke test con proveedor mock:

```powershell
.\.venv\Scripts\python.exe tests\smoke_test.py
```

Pendiente:

- CI con GitHub Actions.
- Pruebas unitarias completas.
- Pruebas de migracion fresh DB y existing DB.
- Pruebas automatizadas de UI.
- Pruebas con proveedores reales en sandbox.

## Estado de Git

Ultimos hitos:

- Base inicial del backend.
- Migraciones y servicios de datos.
- Rutas resilientes, streaming y limites.
- Catalogo de 31 modelos e imagenes.
- Exposicion de rutas, precios y limites en el panel admin.
- Roadmap de paridad con New API y consola negro/dorado.
- Vinculacion con Gmail.
- Correccion de superposicion del footer del sidebar.

## Licencia

Pendiente de definir.

Antes de publicar en GitHub, anadir un archivo `LICENSE` si el repositorio sera publico.
