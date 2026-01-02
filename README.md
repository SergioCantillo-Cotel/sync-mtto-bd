# 🔄 Microservicio de Sincronización de Mantenimientos

Microservicio para sincronizar mantenimientos desde el CRM de Cotel, utilizando una API de base de datos (PostgREST) para la persistencia.

## 📋 Descripción

Este servicio forma parte de la arquitectura de microservicios de CRAC Monitoring. Su responsabilidad es:

1.  **Obtener seriales** de dispositivos desde una API de base de datos.
2.  **Consultar mantenimientos** en el CRM de Cotel usando esos seriales.
3.  **Comparar** con los registros existentes en la base de datos (vía API), usando una clave compuesta para evitar duplicados.
4.  **Insertar** únicamente los registros nuevos a través de la API.
5.  **Reportar** estadísticas completas y coherentes del proceso.

## 🏗️ Arquitectura

El servicio orquesta las llamadas entre la API de la base de datos y la API del CRM.

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUJO DE SINCRONIZACIÓN                      │
└─────────────────────────────────────────────────────────────────┘

1. API de Base de Datos (PostgREST)
   ├─ GET /dispositivos?select=serial_number_device... 
   ├─ Filtrar por device_type
   └─ Resultado: Lista de seriales
        │
        ▼
2. CRM Cotel API
   ├─ POST /crm/Api/V8/custom/IA/equipos-info
   ├─ Body: { "seriales": [...] }
   └─ Resultado: Lista de mantenimientos desde el CRM
        │
        ▼
3. Comparación (en el microservicio)
   ├─ GET /mantenimientos?select=ods_name,report_id,maintenance_remarks
   ├─ Crear "llaves únicas" con (ID ODS, ID Reporte, Observaciones)
   ├─ Filtrar del CRM: solo los que NO existen
   └─ Resultado: Lista de mantenimientos nuevos
        │
        ▼
4. API de Base de Datos (PostgREST) 
   ├─ POST /mantenimientos
   ├─ Body: [ { ...mantenimiento_nuevo... } ] 
   ├─ Logging detallado
   └─ Resultado: Estadísticas completas de inserción
```

## 📦 Estructura del Proyecto

```
sync-mttos-service-dock/ 
├── app/
    ├── config/
    │   └── settings.py              # Configuración con Pydantic Settings
    ├── services/
    │   ├── crm_client.py            # Cliente para consultar CRM
    │   ├── database_api_client.py   # Cliente para API de la BD (PostgREST)
    │   └── sync_service.py          # Orquestador del proceso completo
    ├── models/
    │   └── schemas.py               # Modelos Pydantic (request/response)
    ├── logs/
    │   └── sync_mantenimientos.log  # Logs del servicio
    ├── main.py                      # Aplicación FastAPI
    ├── requirements.txt             # Dependencias Python
    └── .env                         # Variables de entorno (no commitear)
```

## 🚀 Instalación

### Prerequisitos

- Python 3.11+
- Acceso a la API de la base de datos (PostgREST) con un token válido.
- Acceso al CRM de Cotel (client_id y client_secret).

### Pasos

```bash
# 1. Clonar repositorio
git clone <tu-repositorio>
cd sync-mttos-service-dock

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
nano .env  # Editar con tus credenciales

# 5. Ejecutar el servicio
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

El servicio estará disponible en: `http://localhost:8001`

## ⚙️ Configuración

### Variables de Entorno Principales

```bash
# SERVICIO
SERVICE_NAME=Sync Mantenimientos Service
HOST=0.0.0.0
PORT=8001
LOG_LEVEL=INFO

# CRM Cotel
CRM_BASE_URL=https://crmcotel.com.co
CRM_CLIENT_ID=tu-client-id
CRM_CLIENT_SECRET=tu-client-secret

# API de Base de Datos (PostgREST)
DB_API_BASE_URL=https://tu-api-postgrest.com
DB_API_TOKEN=tu-jwt-token-largo
DB_API_SCHEMA=monitoreo_equipos

# Sincronización
BATCH_SIZE=1000                      # Tamaño de lote para inserciones
```

## 📡 API Endpoints

### 1. Root - Información del Servicio

```http
GET /
```

**Respuesta:**
```json
{
  "service": "Sync Mantenimientos Service",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "health": "/health",
  "config": {
    "default_sync_behavior": "Sincronizar todos los tipos de dispositivos si no se especifica en el request.",
    "source_table": "monitoreo_equipos.dispositivos"
  }
}
```

---

### 2. Health Check

```http
GET /health
```

Verifica el estado del servicio, conexión a BD y configuración del CRM.

**Respuesta:**
```json
{
  "status": "healthy",
  "service": "Sync Mantenimientos Service",
  "version": "1.0.0",
  "timestamp": "2025-12-23T10:30:00.123456",
  "database_connected": true,
  "crm_configured": true
}
```

---

### 3. Tipos de Dispositivos Disponibles

```http
GET /dispositivos/types
```

Lista todos los tipos de dispositivos en la tabla `dispositivos` con sus cantidades.

**Respuesta:**
```json
{
  "total_types": 5,
  "device_types": [
    {
      "device_type": "Cooling Device",
      "cantidad": 14
    },
    {
      "device_type": "Heating Device",
      "cantidad": 3
    },
    {
      "device_type": "UPS",
      "cantidad": 8
    }
  ]
}
```

---

### 4. Diagnóstico de Seriales

```http
GET /dispositivos/diagnostico?device_type=Cooling Device
```

**NUEVO:** Endpoint de diagnóstico que muestra información detallada sobre los seriales de dispositivos y por qué algunos no se consultan en el CRM.

**Query Parameters:**
- `device_type` (string, opcional): Tipo de dispositivo a diagnosticar. Default: "Cooling Device"

**Respuesta:**
```json
{
  "device_type": "Cooling Device",
  "resumen": {
    "total_dispositivos": 14,
    "con_serial": 12,
    "sin_serial": 2,
    "seriales_unicos": 10,
    "seriales_duplicados_count": 2,
    "se_consultan_en_crm": 10
  },
  "explicacion": {
    "por_que_diferencia": "De 14 dispositivos tipo 'Cooling Device', solo se consultan 10 en el CRM porque:",
    "razon_1": "2 dispositivos NO tienen serial (NULL o vacío)",
    "razon_2": "2 seriales están duplicados (mismo serial en múltiples dispositivos)",
    "resultado": "Se consultan 10 seriales únicos en el CRM"
  },
  "detalles": {
    "dispositivos_sin_serial": [
      {
        "device_id": 15,
        "device_name": "CRAC-15",
        "serial_number_device": "NULL"
      }
    ],
    "seriales_duplicados": [
      {
        "serial": "SN001",
        "cantidad_dispositivos": 2,
        "dispositivos": "CRAC-01, CRAC-01-Backup"
      }
    ],
    "seriales_que_se_consultan": [
      "SN001", "SN002", "SN003", "..."
    ],
    "total_seriales_consultados": 10
  }
}
```

---

### 5. Sincronizar Mantenimientos ⭐

```http
POST /sync/mantenimientos
Content-Type: application/json
```

Ejecuta el proceso completo de sincronización.

**Body:**
```json
{
  "truncate_first": false,
  "seriales": ["SN001", "SN002"],  // Opcional
  "device_type": ["Cooling Device"]   // Opcional
}
```

**Parámetros:**
- `truncate_first` (bool, opcional): Si es `true`, limpia la tabla antes de insertar. Default: `false`
- `seriales` (list, opcional): Lista específica de seriales a consultar. Si no se proporciona, se obtienen desde la tabla `dispositivos`
- `device_type` (string, opcional): Filtra los dispositivos por tipo. Si es nulo, se procesan todos.

**Ejemplos de uso:**

```bash
# Sincronización automática (usa dispositivos de tipo "Cooling Device")
curl -X POST http://localhost:8001/sync/mantenimientos \
  -H "Content-Type: application/json" \
  -d '{"truncate_first": false}'

# Con tipo específico de dispositivo
curl -X POST http://localhost:8001/sync/mantenimientos \
  -H "Content-Type: application/json" \
  -d '{
    "truncate_first": false,
    "device_type": "Heating Device"
  }'

# Con seriales específicos (manual)
curl -X POST http://localhost:8001/sync/mantenimientos \
  -H "Content-Type: application/json" \
  -d '{
    "truncate_first": false,
    "seriales": ["SN001", "SN002", "SN003"]
  }'

# Limpiar tabla y recargar todo
curl -X POST http://localhost:8001/sync/mantenimientos \
  -H "Content-Type: application/json" \
  -d '{"truncate_first": true}'
```

**Respuesta Exitosa (200):**
```json
{
  "success": true,
  "start_time": "2025-12-23T10:19:20.682825",
  "end_time": "2025-12-23T10:19:32.275299",
  "duration_seconds": 11.59,
  "seriales": {
    "source": "BD (dispositivos - ['Cooling Device'])",
    "total": 467,
    "list": ["SERIAL1", "SERIAL2", "..."]
  },
  "crm": {
    "seriales_consultados": 467,
    "seriales_con_resultado": 460,
    "seriales_sin_resultado": 7,
    "list_seriales_sin_resultado": ["SERIAL_A", "SERIAL_B", "..."],
    "mantenimientos_obtenidos": 4675,
    "timestamp": "2025-12-23T10:19:25.123456"
  },
  "comparacion": {
    "registros_obtenidos_crm": 4675,
    "registros_descartados_sin_campos_clave": 61,
    "registros_validos_crm": 4614,
    "duplicados_en_crm": 5,
    "existentes_en_bd": 0,
    "nuevos_a_insertar": 4609
  },
  "database": {
    "total_intentado": 4609,
    "exitosos": 4609,
    "errores": 0,
    "stats": {
      "total_registros": 4609,
      "dispositivos_unicos": 450,
      "clientes_unicos": 80,
      "primer_mantenimiento": "2024-01-15T14:00:00",
      "ultimo_mantenimiento": "2025-12-23T09:00:00",
      "error": null
    }
  },
  "errors": []
}
```
---

### 6. Estado de Sincronización

```http
GET /sync/status
```

Obtiene estadísticas actuales de la tabla de mantenimientos.

**Respuesta:**
```json
{
  "service": "Sync Mantenimientos Service",
  "version": "1.0.0",
  "timestamp": "2025-12-23T10:59:00.732668",
  "database_stats": {
    "total": 4610,
    "dispositivos_unicos": 217,
    "clientes_unicos": 24,
    "primer_mantenimiento": "2018-02-13T20:33:06",
    "ultimo_mantenimiento": "2025-12-22T14:56:47",
    "error": null
  }
}
```

---

### 7. Test de Conexión CRM

```http
POST /test/crm-connection
```

Prueba la conexión y autenticación con el CRM.

**Respuesta:**
```json
{
  "base_url": "https://crmcotel.com.co",
  "token_url": "https://crmcotel.com.co/crm/Api/access_token",
  "equipos_url": "https://crmcotel.com.co/crm/Api/V8/custom/IA/equipos-info",
  "auth_success": true,
  "auth_error": null,
  "token_preview": "...xyz123abc"
}
```

## 🗄️ Esquema de Base de Datos

### 📊 Mapeo de Campos CRM → BD

| Campo CRM | Campo BD | Tipo |
|-----------|----------|------|
| `nombre_ods` | `ods_name` | VARCHAR |
| `tipo_mantenimiento` | `maintenance_type` | VARCHAR |
| `id_equipos` | `device_id` | VARCHAR |
| `nombre_equipo` | `device_name` | VARCHAR |
| `marca` | `device_brand` | VARCHAR |
| `modelo` | `device_model` | VARCHAR |
| `linea` | `device_type` | VARCHAR |
| `fecha_creacion` | `datetime_ods_create` | TIMESTAMP |
| `serial` | `serial` | VARCHAR |
| `reporte` | `report_id` | VARCHAR |
| `hora_salida` | `datetime_maintenance_end` | TIMESTAMP |
| `observaciones_reporte` | `maintenance_remarks` | TEXT |
| `status` / `estado_reporte` | `report_status` | VARCHAR |
| `nit` | `nit` | VARCHAR |
| `cliente` | `customer_name` | VARCHAR |
| *(generado)* | `maintenance_id` | UUID |

---

## 📝 Ejemplos de Uso Completos

### Ejemplo 1: Sincronización Automática Básica

```python
import requests

# Sincronización usando dispositivos "Cooling Device"
response = requests.post(
    "http://localhost:8001/sync/mantenimientos",
    json={"truncate_first": False}
)

result = response.json()

if result["success"]:
    print(f"✅ Sincronización exitosa")
    print(f"Duración: {result['duration_seconds']}s")
    print(f"\nSeriales consultados: {result['seriales']['total']}")
    print(f"Mantenimientos del CRM: {result['crm']['mantenimientos_obtenidos']}")
    print(f"Ya existían en BD: {result['database']['duplicados']}")
    print(f"Nuevos insertados: {result['database']['insertados']}")
    print(f"\nTotal en BD ahora: {result['database']['stats']['total_registros']}")
else:
    print(f"❌ Error: {result['errors']}")
```

### Ejemplo 2: Sincronización con Tipo Específico

```python
import requests

# Consultar mantenimientos de "Heating Device" en lugar de "Cooling Device"
response = requests.post(
    "http://localhost:8001/sync/mantenimientos",
    json={
        "truncate_first": False,
        "device_type": "Heating Device"
    }
)

result = response.json()
print(f"Dispositivos consultados: {result['dispositivos']['device_type_filter']}")
print(f"Seriales: {result['seriales']['total']}")
```

### Ejemplo 3: Sincronización con Seriales Manuales

```python
import requests

# Consultar solo seriales específicos
seriales_especificos = ["SN001", "SN002", "SN003"]

response = requests.post(
    "http://localhost:8001/sync/mantenimientos",
    json={
        "truncate_first": False,
        "seriales": seriales_especificos
    }
)

result = response.json()
print(f"Fuente de seriales: {result['seriales']['source']}")
print(f"Total consultado: {result['seriales']['total']}")
```

### Ejemplo 4: Diagnóstico Antes de Sincronizar

```python
import requests

# 1. Primero diagnosticar
diag_response = requests.get(
    "http://localhost:8001/dispositivos/diagnostico",
    params={"device_type": "Cooling Device"}
)

diag = diag_response.json()

print("=== DIAGNÓSTICO ===")
print(f"Total dispositivos: {diag['resumen']['total_dispositivos']}")
print(f"Con serial: {diag['resumen']['con_serial']}")
print(f"Sin serial: {diag['resumen']['sin_serial']}")
print(f"Seriales únicos: {diag['resumen']['seriales_unicos']}")
print(f"Se consultarán en CRM: {diag['resumen']['se_consultan_en_crm']}")

if diag['resumen']['sin_serial'] > 0:
    print("\n⚠️ Dispositivos sin serial:")
    for disp in diag['detalles']['dispositivos_sin_serial']:
        print(f"  - {disp['device_name']} (ID: {disp['device_id']})")

# 2. Luego sincronizar
sync_response = requests.post(
    "http://localhost:8001/sync/mantenimientos",
    json={"truncate_first": False}
)

sync = sync_response.json()
print(f"\n=== SINCRONIZACIÓN ===")
print(f"Nuevos insertados: {sync['database']['insertados']}")
```

### Ejemplo 5: Verificar Estado Antes y Después

```python
import requests

# ANTES
status_antes = requests.get("http://localhost:8001/sync/status").json()
print("=== ANTES ===")
print(f"Total registros: {status_antes['database_stats']['total_registros']}")

# SINCRONIZAR
sync = requests.post(
    "http://localhost:8001/sync/mantenimientos",
    json={"truncate_first": False}
).json()

print(f"\n=== SINCRONIZACIÓN ===")
print(f"Nuevos insertados: {sync['database']['insertados']}")

# DESPUÉS
status_despues = requests.get("http://localhost:8001/sync/status").json()
print(f"\n=== DESPUÉS ===")
print(f"Total registros: {status_despues['database_stats']['total_registros']}")
print(f"Incremento: {status_despues['database_stats']['total_registros'] - status_antes['database_stats']['total_registros']}")
```

---

## 🔧 Troubleshooting

### Error: "No hay seriales de tipo 'X' para consultar"

**Causa:** No hay dispositivos con ese `device_type` o no tienen `serial_number_device`

**Solución:**
```bash
# Ver tipos disponibles
curl http://localhost:8001/dispositivos/types

# Diagnosticar el tipo específico
curl "http://localhost:8001/dispositivos/diagnostico?device_type=Cooling+Device"
```

### Error: "Error de autenticación con CRM"

**Causa:** Credenciales incorrectas o CRM no disponible

**Solución:**
```bash
# Probar conexión
curl -X POST http://localhost:8001/test/crm-connection

# Verificar .env
cat .env | grep CRM_CLIENT
```

### Error: "Error de conexión a base de datos"

### Los nuevos mantenimientos no se insertan

**Causa:** Ya existen en BD (duplicados detectados)

**Diagnóstico:**
```bash
# Ver estadísticas
curl http://localhost:8001/sync/status

# Ver logs detallados
tail -f logs/sync_mantenimientos.log | grep "DUPLICADO"
```

---

## 📊 Logs

### Niveles de Log

- `DEBUG`: Detalles técnicos, queries SQL, requests HTTP
- `INFO`: Progreso del proceso, confirmaciones (default)
- `WARNING`: Situaciones anómalas pero no críticas
- `ERROR`: Errores que requieren atención

### Ejemplo de Logs de Sincronización Exitosa

```
2025-12-15 10:30:00 - INFO - ════════════════════════════════════════
2025-12-15 10:30:00 - INFO - SINCRONIZACION DE MANTENIMIENTOS
2025-12-15 10:30:00 - INFO - ════════════════════════════════════════
2025-12-15 10:30:01 - INFO - PASO 1/7: Conectando a PostgreSQL...
2025-12-15 10:30:01 - INFO - [OK] Conexión exitosa a PostgreSQL
2025-12-15 10:30:02 - INFO - PASO 2/7: Verificando tabla de destino...
2025-12-15 10:30:02 - INFO - [OK] Tabla verificada
2025-12-15 10:30:03 - INFO - PASO 3/7: Omitiendo truncate...
2025-12-15 10:30:04 - INFO - PASO 4/7: Obteniendo lista de seriales...
2025-12-15 10:30:04 - INFO - [OK] 10 seriales únicos encontrados
2025-12-15 10:30:05 - INFO - PASO 5/7: Consultando mantenimientos desde CRM...
2025-12-15 10:30:30 - INFO - [OK] 150 mantenimientos obtenidos del CRM
2025-12-15 10:30:31 - INFO - PASO 6/7: Consultando registros existentes en BD...
2025-12-15 10:30:31 - INFO - [OK] 1200 registros existentes en BD
2025-12-15 10:30:32 - INFO - PASO 7/7: Insertando solo registros nuevos...
2025-12-15 10:30:32 - INFO - [FILTRADO] Resumen de comparación:
2025-12-15 10:30:32 - INFO -    * Total del CRM: 150
2025-12-15 10:30:32 - INFO -    * Ya existen en BD: 125
2025-12-15 10:30:32 - INFO -    * NUEVOS a insertar: 25
2025-12-15 10:30:35 - INFO - [OK] 25 registros insertados exitosamente
2025-12-15 10:30:35 - INFO - ════════════════════════════════════════
2025-12-15 10:30:35 - INFO - RESUMEN FINAL
2025-12-15 10:30:35 - INFO - Estado: [OK] EXITOSO
2025-12-15 10:30:35 - INFO - Duración: 35.2 segundos
2025-12-15 10:30:35 - INFO - ════════════════════════════════════════
```

---

## 🚀 Próximos Pasos

Este servicio es el primero de la arquitectura de microservicios:

1. ✅ **Sync Mantenimientos Service** (este servicio)
2. ⏳ **Predictions API** - Predicciones de riesgo

---

## 📚 Documentación API Interactiva

- **Swagger UI**: http://localhost:8001/docs
---

## 🤝 Contribución

1. Fork el repositorio
2. Crea una rama: `git checkout -b feature/nueva-funcionalidad`
3. Commit cambios: `git commit -am 'Agregar nueva funcionalidad'`
4. Push: `git push origin feature/nueva-funcionalidad`
5. Crear Pull Request

---

## Dockerización

```bash
# Construir imagen y ejecutar
docker build -t sync-mtto-srv .
docker images
docker run -d -p 8001:8001 --name sync-mtto-srv-cont sync-mtto-srv
docker logs -f sync-mtto-srv-cont

# Detener y eliminar
docker stop sync-mtto-srv-cont
docker rm sync-mtto-srv-cont

# Borrar imagen
docker rmi sync-mtto-srv:latest
```
---

## 📄 Licencia

Propiedad de Cotel Investments S.A.S.

---

**Versión**: 1.0.0  
**Última actualización**: 2025-12-23  
**Puerto**: 8001  
**Estado**: ✅ Producción