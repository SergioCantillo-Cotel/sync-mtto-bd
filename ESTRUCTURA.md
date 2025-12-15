# 📂 Estructura del Microservicio

## 📁 Árbol de Archivos

```
sync-mantenimientos-service/
│
├── 📁 config/
│   ├── __init__.py
│   └── settings.py                  # Configuración (Pydantic Settings)
│
├── 📁 services/
│   ├── __init__.py
│   ├── crm_client.py               # Cliente CRM (consultas)
│   ├── postgres_client.py          # Cliente PostgreSQL (inserción)
│   └── sync_service.py             # Orquestador principal
│
├── 📁 models/
│   ├── __init__.py
│   └── schemas.py                  # Modelos Pydantic
│
├── 📁 logs/
│   └── sync_mantenimientos.log     # Logs del servicio (generado)
│
├── 📄 main.py                      # Aplicación FastAPI
├── 📄 requirements.txt             # Dependencias Python
├── 📄 .env.example                 # Ejemplo de configuración
├── 📄 .env                         # Configuración real (crear)
├── 📄 .gitignore                   # Archivos a ignorar
├── 📄 Dockerfile                   # Containerización
├── 📄 docker-compose.yml           # Orquestación Docker
├── 🔧 start.sh                     # Script de inicio rápido
├── 🧪 test_service.py              # Suite de pruebas
├── 📖 README.md                    # Documentación principal
└── 📖 ESTRUCTURA.md                # Este archivo
```

## 📝 Descripción de Archivos

### Configuración

**config/settings.py**
- Variables de entorno con Pydantic
- Configuración de CRM, PostgreSQL, Sync
- Validación automática de tipos
- Propiedades computadas (database_url, etc.)

### Servicios

**services/crm_client.py**
- `CRMClient`: Cliente para API del CRM
- `_get_token()`: Autenticación
- `get_mantenimientos()`: Consulta completa
- `get_mantenimientos_by_seriales()`: Consulta filtrada
- Logging detallado de todo el proceso

**services/postgres_client.py**
- `PostgresClient`: Cliente para PostgreSQL
- `connect()`: Establecer conexión
- `ensure_table_exists()`: Crear tabla si no existe
- `truncate_table()`: Limpiar tabla
- `insert_mantenimientos_batch()`: Inserción en lotes con UPSERT
- `get_stats()`: Estadísticas de la tabla

**services/sync_service.py**
- `SyncService`: Orquestador del proceso completo
- `sync_mantenimientos()`: Flujo principal
  1. Conectar PostgreSQL
  2. Verificar tabla
  3. Truncate opcional
  4. Consultar CRM
  5. Insertar en BD
  6. Generar estadísticas
- Manejo de errores completo
- Logging de cada paso

### Modelos

**models/schemas.py**
- `SyncRequest`: Request body para sincronización
- `SyncResponse`: Response con estadísticas completas
- `CRMStats`: Estadísticas del CRM
- `DatabaseStats`: Estadísticas de la BD
- `HealthResponse`: Response del health check

### Aplicación

**main.py**
- `FastAPI` application
- Endpoints:
  - `GET /`: Root
  - `GET /health`: Health check
  - `POST /sync/mantenimientos`: Sincronización ⭐
  - `GET /sync/status`: Estado actual
- CORS middleware
- Logging configurado
- Eventos de startup/shutdown

### Configuración

**.env.example**
- Template de configuración
- Variables documentadas
- Valores por defecto seguros

**requirements.txt**
- fastapi==0.115.0
- uvicorn[standard]==0.32.0
- pydantic==2.10.0
- pydantic-settings==2.6.1
- requests==2.32.3
- psycopg2-binary==2.9.10
- python-dotenv==1.0.1

### Docker

**Dockerfile**
- Base: python:3.11-slim
- Multi-stage build
- Health check incluido
- Usuario no-root
- Logs persistentes

**docker-compose.yml**
- Definición del servicio
- Networks configuradas
- Volumes para logs
- Health check
- Restart policy

### Scripts

**start.sh**
- Verificación de dependencias
- Creación de venv
- Instalación de paquetes
- Inicio del servicio
- Script interactivo

**test_service.py**
- Suite de pruebas completa
- Test de todos los endpoints
- Validación de respuestas
- Resumen final
- Modo interactivo

## 🔄 Flujo de Datos

```
Usuario
  │
  │ POST /sync/mantenimientos
  │
  ▼
FastAPI (main.py)
  │
  │ Llama a sync_service.sync_mantenimientos()
  │
  ▼
SyncService (sync_service.py)
  │
  ├─► PostgresClient
  │   ├─ connect()
  │   ├─ ensure_table_exists()
  │   └─ truncate_table() [opcional]
  │
  ├─► CRMClient
  │   ├─ _get_token()
  │   └─ get_mantenimientos()
  │       └─ GET https://crmcotel.com.co/api/v8/services/getall
  │
  └─► PostgresClient
      └─ insert_mantenimientos_batch()
          └─ UPSERT en tabla mantenimientos
```

## 📊 Esquema de Base de Datos

```sql
mantenimientos
├── id (SERIAL PRIMARY KEY)
├── service_id (VARCHAR UNIQUE) ← Clave para UPSERT
├── device_serial
├── device_brand
├── device_model
├── customer_name
├── customer_id
├── datetime_maintenance_start
├── datetime_maintenance_end
├── service_type
├── technician_name
├── status
├── notes
├── raw_data (JSONB)
├── created_at
└── updated_at

Índices:
- idx_device_serial
- idx_customer_id
- idx_maintenance_end
- idx_service_id
```

## 🔐 Variables de Entorno

### Servicio
```bash
SERVICE_NAME=Sync Mantenimientos Service
SERVICE_VERSION=1.0.0
HOST=0.0.0.0
PORT=8001
DEBUG=true
LOG_LEVEL=INFO
LOG_FILE=logs/sync_mantenimientos.log
```

### CRM
```bash
CRM_BASE_URL=https://crmcotel.com.co
CRM_CLIENT_ID=your-client-id
CRM_CLIENT_SECRET=your-client-secret
CRM_TIMEOUT=30
```

### PostgreSQL
```bash
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=eficiencia_energetica
DB_USER=api_crud_monitoreo_equipos
DB_PASSWORD=your-password
```

### Sincronización
```bash
BATCH_SIZE=100
MAX_RETRIES=3
RETRY_DELAY=5
```

## 🎯 Endpoints

### 1. Root
```
GET /
```
Información básica del servicio

### 2. Health Check
```
GET /health
```
Verifica estado del servicio, DB y CRM

### 3. Sincronización ⭐
```
POST /sync/mantenimientos
Content-Type: application/json

{
  "truncate_first": false
}
```
Proceso completo de sincronización

### 4. Estado
```
GET /sync/status
```
Estadísticas actuales de la tabla

## 🧪 Testing

```bash
# Ejecutar suite de pruebas
python test_service.py

# O con permisos
./test_service.py
```

Tests incluidos:
1. ✅ Endpoint raíz
2. ✅ Health check
3. ✅ Estado de sincronización
4. ✅ Sincronización completa (opcional)

## 📝 Logging

Logging en 2 destinos:
1. **Consola** (stdout) - Tiempo real
2. **Archivo** (logs/sync_mantenimientos.log) - Persistente

Niveles:
- DEBUG: Detalles técnicos
- INFO: Progreso del proceso ← Default
- WARNING: Situaciones anómalas
- ERROR: Errores críticos

## 🚀 Despliegue

### Local
```bash
./start.sh
```

### Docker
```bash
docker-compose up -d
```

### Producción
- Cambiar DEBUG=false
- Usar LOG_LEVEL=WARNING
- Configurar restart policy
- Monitorear logs
- Health checks configurados

## 📈 Métricas

El servicio reporta:
- Total de registros procesados
- Insertados vs actualizados
- Errores de inserción
- Duración del proceso
- Estadísticas de la tabla
- Dispositivos únicos
- Clientes únicos
- Rango de fechas

## 🔄 Mantenimiento

### Logs
```bash
# Ver logs en tiempo real
tail -f logs/sync_mantenimientos.log

# Limpiar logs antiguos
> logs/sync_mantenimientos.log
```

### Base de Datos
```bash
# Ver estadísticas
curl http://localhost:8001/sync/status

# Conectar a PostgreSQL
psql -h 127.0.0.1 -U api_crud_monitoreo_equipos -d eficiencia_energetica

# Ver tabla
SELECT COUNT(*) FROM mantenimientos;
```

## 📦 Dependencias

- **FastAPI**: Framework web
- **Uvicorn**: ASGI server
- **Pydantic**: Validación de datos
- **Requests**: HTTP client
- **Psycopg2**: PostgreSQL driver
- **Python-dotenv**: Variables de entorno

## 🎯 Próximos Pasos

1. ✅ Microservicio de sincronización (este)
2. ⏳ Separar Predictions API
3. ⏳ Separar Devices API
4. ⏳ Separar Analytics API
5. ⏳ API Gateway
6. ⏳ Service mesh

---

**Versión**: 1.0.0
**Puerto**: 8001
**Estado**: ✅ Producción
