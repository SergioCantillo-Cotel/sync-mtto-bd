# 🔄 Microservicio de Sincronización de Mantenimientos

Microservicio independiente para sincronizar mantenimientos desde el CRM de Cotel hacia PostgreSQL.

## 📋 Descripción

Este servicio forma parte de la arquitectura de microservicios de CRAC Monitoring. Su única responsabilidad es:

1. **Consultar** mantenimientos desde el API del CRM
2. **Insertar/Actualizar** los datos en PostgreSQL
3. **Reportar** el estado del proceso

## 🏗️ Arquitectura

```
┌─────────────────┐
│   CRM Cotel     │
│   (API REST)    │
└────────┬────────┘
         │
         │ GET /api/v8/services/getall
         │
         ▼
┌─────────────────────────────────┐
│  Sync Mantenimientos Service    │
│                                  │
│  ┌──────────────────────────┐   │
│  │    FastAPI Application   │   │
│  │  - POST /sync/mttos      │   │
│  │  - GET  /health          │   │
│  │  - GET  /sync/status     │   │
│  └──────────────────────────┘   │
│                                  │
│  ┌──────────────────────────┐   │
│  │    Business Logic        │   │
│  │  - CRM Client            │   │
│  │  - Postgres Client       │   │
│  │  - Sync Service          │   │
│  └──────────────────────────┘   │
└──────────────┬──────────────────┘
               │
               │ INSERT/UPDATE
               │
               ▼
      ┌────────────────┐
      │  PostgreSQL    │
      │  (mantenimientos)  │
      └────────────────┘
```

## 📦 Estructura del Proyecto

```
sync-mantenimientos-service/
├── config/
│   └── settings.py          # Configuración (Pydantic Settings)
├── services/
│   ├── crm_client.py        # Cliente para consultar CRM
│   ├── postgres_client.py   # Cliente para insertar en PostgreSQL
│   └── sync_service.py      # Orquestador del proceso
├── models/
│   └── schemas.py           # Modelos Pydantic (request/response)
├── logs/
│   └── sync_mantenimientos.log  # Logs del servicio
├── main.py                  # Aplicación FastAPI
├── requirements.txt         # Dependencias Python
├── .env.example             # Ejemplo de configuración
├── Dockerfile               # Containerización
├── docker-compose.yml       # Orquestación Docker
└── README.md                # Esta documentación
```

## 🚀 Inicio Rápido

### Opción 1: Ejecución Local

```bash
# 1. Clonar/Copiar el proyecto
cd sync-mantenimientos-service

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
nano .env  # Editar con tus credenciales

# 5. Ejecutar el servicio
python main.py
```

El servicio estará disponible en: `http://localhost:8001`

### Opción 2: Docker

```bash
# 1. Construir imagen
docker build -t sync-mantenimientos:latest .

# 2. Ejecutar contenedor
docker run -d \
  --name sync-mantenimientos \
  -p 8001:8001 \
  --env-file .env \
  sync-mantenimientos:latest

# 3. Ver logs
docker logs -f sync-mantenimientos
```

### Opción 3: Docker Compose (Recomendado)

```bash
# 1. Configurar .env
cp .env.example .env
nano .env

# 2. Iniciar servicio
docker-compose up -d

# 3. Ver logs en tiempo real
docker-compose logs -f

# 4. Detener servicio
docker-compose down
```

## ⚙️ Configuración

### Variables de Entorno

Edita el archivo `.env` con tus valores:

```bash
# Servicio
SERVICE_NAME=Sync Mantenimientos Service
PORT=8001
DEBUG=true
LOG_LEVEL=INFO

# CRM
CRM_BASE_URL=https://crmcotel.com.co
CRM_CLIENT_ID=tu-client-id
CRM_CLIENT_SECRET=tu-client-secret

# PostgreSQL
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=eficiencia_energetica
DB_USER=tu_usuario
DB_PASSWORD=tu_password

# Sincronización
BATCH_SIZE=100
MAX_RETRIES=3
```

## 📡 API Endpoints

### 1. Root
```http
GET /
```

Información básica del servicio.

**Respuesta:**
```json
{
  "service": "Sync Mantenimientos Service",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "health": "/health",
  "sync_endpoint": "/sync/mantenimientos"
}
```

---

### 2. Health Check
```http
GET /health
```

Verifica el estado del servicio.

**Respuesta:**
```json
{
  "status": "healthy",
  "service": "Sync Mantenimientos Service",
  "version": "1.0.0",
  "timestamp": "2025-01-05T10:30:00",
  "database_connected": true,
  "crm_configured": true
}
```

---

### 3. Sincronizar Mantenimientos ⭐

```http
POST /sync/mantenimientos
Content-Type: application/json

{
  "truncate_first": false
}
```

**Parámetros:**
- `truncate_first` (bool, opcional): Si es `true`, limpia la tabla antes de insertar. Default: `false`

**Respuesta Exitosa (200):**
```json
{
  "success": true,
  "start_time": "2025-01-05T10:30:00",
  "end_time": "2025-01-05T10:35:00",
  "duration_seconds": 300.5,
  "crm": {
    "total_consultado": 1500,
    "timestamp": "2025-01-05T10:31:00"
  },
  "database": {
    "total": 1500,
    "insertados": 100,
    "actualizados": 1400,
    "errores": 0,
    "exitosos": 1500,
    "stats": {
      "total_registros": 5000,
      "dispositivos_unicos": 250,
      "clientes_unicos": 50,
      "primer_mantenimiento": "2023-01-01T00:00:00",
      "ultimo_mantenimiento": "2025-01-05T10:00:00"
    }
  },
  "errors": [],
  "message": "Sincronización completada exitosamente"
}
```

**Respuesta con Errores (500):**
```json
{
  "success": false,
  "start_time": "2025-01-05T10:30:00",
  "end_time": "2025-01-05T10:30:30",
  "duration_seconds": 30.0,
  "errors": [
    "Error de conexión al CRM",
    "Error de autenticación"
  ],
  "message": "Sincronización completada con errores"
}
```

---

### 4. Estado de Sincronización

```http
GET /sync/status
```

Obtiene estadísticas actuales de la tabla de mantenimientos.

**Respuesta:**
```json
{
  "status": "success",
  "timestamp": "2025-01-05T10:30:00",
  "statistics": {
    "total_registros": 5000,
    "dispositivos_unicos": 250,
    "clientes_unicos": 50,
    "primer_mantenimiento": "2023-01-01T00:00:00",
    "ultimo_mantenimiento": "2025-01-05T10:00:00"
  }
}
```

---

## 🔍 Ejemplos de Uso

### cURL

```bash
# Health check
curl http://localhost:8001/health

# Sincronización (modo UPSERT)
curl -X POST http://localhost:8001/sync/mantenimientos \
  -H "Content-Type: application/json" \
  -d '{"truncate_first": false}'

# Sincronización (limpiando tabla primero)
curl -X POST http://localhost:8001/sync/mantenimientos \
  -H "Content-Type: application/json" \
  -d '{"truncate_first": true}'

# Ver estado
curl http://localhost:8001/sync/status
```

### Python

```python
import requests

# Sincronización
response = requests.post(
    "http://localhost:8001/sync/mantenimientos",
    json={"truncate_first": False}
)

result = response.json()

if result["success"]:
    print(f"✅ Sincronización exitosa")
    print(f"Consultados: {result['crm']['total_consultado']}")
    print(f"Insertados: {result['database']['insertados']}")
    print(f"Actualizados: {result['database']['actualizados']}")
else:
    print(f"❌ Sincronización fallida")
    print(f"Errores: {result['errors']}")
```

### JavaScript

```javascript
// Sincronización
fetch('http://localhost:8001/sync/mantenimientos', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    truncate_first: false
  })
})
.then(response => response.json())
.then(data => {
  if (data.success) {
    console.log('✅ Sincronización exitosa');
    console.log(`Duración: ${data.duration_seconds}s`);
  } else {
    console.error('❌ Sincronización fallida');
  }
});
```

---

## 📊 Proceso de Sincronización

El endpoint `POST /sync/mantenimientos` ejecuta los siguientes pasos:

1. **Conectar a PostgreSQL** 🔌
   - Establece conexión con la base de datos
   - Verifica credenciales

2. **Verificar Tabla** 🔍
   - Crea tabla `mantenimientos` si no existe
   - Crea índices necesarios

3. **Truncate (Opcional)** 🗑️
   - Si `truncate_first=true`, limpia la tabla
   - Si `false`, hace UPSERT (inserta o actualiza)

4. **Consultar CRM** 🌐
   - Autenticación con client_id/client_secret
   - GET `/api/v8/services/getall`
   - Retorna lista de mantenimientos

5. **Insertar en PostgreSQL** 💾
   - Procesamiento en lotes (batch_size=100)
   - UPSERT por `service_id` (no duplicados)
   - Logging detallado del progreso

6. **Estadísticas** 📈
   - Cuenta registros totales
   - Dispositivos únicos
   - Clientes únicos
   - Rango de fechas

7. **Desconectar** 🔌
   - Cierra conexión limpiamente

Todo el proceso se loguea en:
- **Consola** (stdout)
- **Archivo** (`logs/sync_mantenimientos.log`)

---

## 📝 Logs

### Niveles de Log

- `DEBUG`: Detalles técnicos y queries
- `INFO`: Progreso del proceso (default)
- `WARNING`: Situaciones anómalas pero no críticas
- `ERROR`: Errores que requieren atención

### Ejemplo de Logs

```
2025-01-05 10:30:00 - INFO - ══════════════════════════════════════════════════════
2025-01-05 10:30:00 - INFO - 🔄 SOLICITUD DE SINCRONIZACIÓN RECIBIDA
2025-01-05 10:30:00 - INFO - ══════════════════════════════════════════════════════
2025-01-05 10:30:01 - INFO - PASO 1/5: Conectando a PostgreSQL...
2025-01-05 10:30:01 - INFO - ✅ Conexión exitosa a PostgreSQL
2025-01-05 10:30:02 - INFO - PASO 2/5: Verificando estructura de base de datos...
2025-01-05 10:30:02 - INFO - ✅ Tabla 'mantenimientos' verificada/creada
2025-01-05 10:30:03 - INFO - PASO 3/5: Omitiendo truncate (modo UPSERT)...
2025-01-05 10:30:04 - INFO - PASO 4/5: Consultando mantenimientos desde CRM...
2025-01-05 10:30:05 - INFO - 🔑 Obteniendo token del CRM...
2025-01-05 10:30:06 - INFO - ✅ Token obtenido exitosamente
2025-01-05 10:30:07 - INFO - 🌐 GET https://crmcotel.com.co/api/v8/services/getall
2025-01-05 10:30:30 - INFO - ✅ 1500 mantenimientos consultados del CRM
2025-01-05 10:30:31 - INFO - PASO 5/5: Insertando en PostgreSQL...
2025-01-05 10:30:31 - INFO - 📦 Procesando lote 1/15 (100 registros)...
2025-01-05 10:30:35 - INFO - ✅ Lote 1 completado
...
2025-01-05 10:35:00 - INFO - ══════════════════════════════════════════════════════
2025-01-05 10:35:00 - INFO - ✅ SINCRONIZACIÓN COMPLETADA EXITOSAMENTE
2025-01-05 10:35:00 - INFO - Duración: 300.5 segundos
2025-01-05 10:35:00 - INFO - ══════════════════════════════════════════════════════
```

---

## 🗄️ Esquema de Base de Datos

### Tabla: `mantenimientos`

```sql
CREATE TABLE mantenimientos (
    id SERIAL PRIMARY KEY,
    service_id VARCHAR(100) UNIQUE,          -- ID único del servicio
    device_serial VARCHAR(100),              -- Serial del dispositivo
    device_brand VARCHAR(100),               -- Marca
    device_model VARCHAR(100),               -- Modelo
    customer_name VARCHAR(200),              -- Nombre del cliente
    customer_id VARCHAR(100),                -- ID del cliente
    datetime_maintenance_start TIMESTAMP,    -- Inicio del mantenimiento
    datetime_maintenance_end TIMESTAMP,      -- Fin del mantenimiento
    service_type VARCHAR(100),               -- Tipo de servicio
    technician_name VARCHAR(200),            -- Nombre del técnico
    status VARCHAR(50),                      -- Estado
    notes TEXT,                              -- Notas
    raw_data JSONB,                          -- Datos crudos del CRM
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices
CREATE INDEX idx_device_serial ON mantenimientos(device_serial);
CREATE INDEX idx_customer_id ON mantenimientos(customer_id);
CREATE INDEX idx_maintenance_end ON mantenimientos(datetime_maintenance_end);
CREATE INDEX idx_service_id ON mantenimientos(service_id);
```

### UPSERT Logic

El servicio usa **UPSERT** por defecto:
- Si `service_id` **no existe**: Inserta nuevo registro
- Si `service_id` **existe**: Actualiza registro existente

Esto evita duplicados y mantiene los datos actualizados.

---

## 🔧 Troubleshooting

### Error: "Error de autenticación con CRM"

**Causa**: Credenciales incorrectas

**Solución**:
```bash
# Verificar variables en .env
echo $CRM_CLIENT_ID
echo $CRM_CLIENT_SECRET

# Probar credenciales manualmente
curl -X POST https://crmcotel.com.co/api/v8/authenticate \
  -H "Content-Type: application/json" \
  -d '{"client_id":"tu-id","client_secret":"tu-secret"}'
```

### Error: "Error de conexión a base de datos"

**Causa**: PostgreSQL no accesible

**Solución**:
```bash
# Verificar que PostgreSQL está corriendo
psql -h 127.0.0.1 -U api_crud_monitoreo_equipos -d eficiencia_energetica

# Si estás en Docker, usar host.docker.internal
DB_HOST=host.docker.internal
```

### Los logs no se muestran

**Causa**: Nivel de log muy alto

**Solución**:
```bash
# Cambiar en .env
LOG_LEVEL=INFO  # o DEBUG para más detalle
```

### El servicio no responde

**Solución**:
```bash
# Ver logs del contenedor
docker logs sync-mantenimientos

# Reiniciar
docker-compose restart

# Health check
curl http://localhost:8001/health
```

---

## 🎯 Próximos Pasos

Este es el primer microservicio de la arquitectura. Los siguientes servicios serán:

1. ✅ **Sync Mantenimientos** (este servicio)
2. ⏳ **Predictions API** - Predicciones de riesgo
3. ⏳ **Devices API** - Gestión de dispositivos
4. ⏳ **Analytics API** - Análisis y reportes
5. ⏳ **Auth API** - Autenticación y autorización

---

## 📚 Documentación Adicional

- **Swagger UI**: `http://localhost:8001/docs`
- **ReDoc**: `http://localhost:8001/redoc`

---

## 👥 Contribución

1. Fork el repositorio
2. Crea una rama: `git checkout -b feature/nueva-funcionalidad`
3. Commit cambios: `git commit -am 'Agregar nueva funcionalidad'`
4. Push a la rama: `git push origin feature/nueva-funcionalidad`
5. Crear Pull Request

---

## 📄 Licencia

Propiedad de CRAC Monitoring Team.

---

**Versión**: 1.0.0  
**Última actualización**: 2025-01-05  
**Puerto**: 8001  
**Estado**: ✅ Producción

