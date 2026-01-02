from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn, logging, os 
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from .config.settings import get_settings
from .models.schemas import SyncRequest, SyncResponse, HealthResponse, StatusResponse
from .services.sync_service import get_sync_service, get_database_api_client
from .services.crm_client import get_crm_client

# Configuración
settings = get_settings()

# Asegurarse de que el directorio de logs exista
log_dir = os.path.dirname(settings.LOG_FILE)
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Configurar logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_FILE, encoding='utf-8') # La ruta ahora es segura
    ]
)

logger = logging.getLogger(__name__)

def get_now_gmt5_iso() -> str:
    """
    Obtiene la fecha y hora actual en zona horaria GMT-5 y la devuelve
    como un string en formato ISO, pero sin el offset de zona horaria.
    """
    gmt5_tz = timezone(timedelta(hours=-5))
    now_gmt5 = datetime.now(gmt5_tz)
    return now_gmt5.strftime('%Y-%m-%dT%H:%M:%S.%f')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager para la aplicación
    """
    # Startup
    logger.info("=" * 80)
    logger.info(f"[INICIO] {settings.SERVICE_NAME} v{settings.SERVICE_VERSION}")
    logger.info("=" * 80)
    logger.info(f"Host: {settings.HOST}:{settings.PORT}")
    logger.info(f"Debug: {settings.DEBUG}")
    logger.info(f"Log Level: {settings.LOG_LEVEL}")
    logger.info("")
    logger.info("CRM Configuration:")
    logger.info(f"  Base URL: {settings.CRM_BASE_URL}")
    logger.info(f"  Client ID: {settings.CRM_CLIENT_ID[:20]}...")
    logger.info(f"  Token URL: {settings.CRM_BASE_URL}/crm/Api/access_token")
    logger.info(f"  Equipos URL: {settings.CRM_BASE_URL}/crm/Api/V8/custom/IA/equipos-info")
    logger.info("")
    logger.info("Database API Configuration:")
    logger.info(f"  API URL: {settings.DB_API_BASE_URL}")
    logger.info(f"  Schema: {settings.DB_API_SCHEMA}")
    logger.info(f"  Tabla origen: dispositivos")
    logger.info(f"  Tabla destino: mantenimientos")
    logger.info("")
    logger.info("Devices Configuration:")
    logger.info(f"  Campo serial: serial_number_device")
    logger.info("")
    logger.info("Sync Configuration:")
    logger.info(f"  Batch Size: {settings.BATCH_SIZE}")
    logger.info(f"  Max Retries: {settings.MAX_RETRIES}")
    logger.info("")

    # Inicializar clientes
    db_client = get_database_api_client()
    await db_client.startup()
    logger.info("[STARTUP] Cliente de API de base de datos inicializado.")
    
    yield
    
    # Shutdown
    db_client = get_database_api_client()
    await db_client.shutdown()
    logger.info("[SHUTDOWN] Cliente de API de base de datos cerrado.")
    logger.info("Servicio detenido.")


# Crear aplicación
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    description="Microservicio de sincronización de mantenimientos en dispositivos desde el CRM Cotel a BD PostgreSQL para alimentar UAI Energy.",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """
    Endpoint raíz
    """
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "config": {
            "default_sync_behavior": "Sincronizar todos los tipos de dispositivos si no se especifica en el request.",
            "source_table": "monitoreo_equipos.dispositivos",
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check del servicio
    """
    # Verificar conexión a la API de la BD
    db_api_healthy = False
    try:
        db_client = get_database_api_client()
        db_api_healthy = await db_client.is_healthy()
    except Exception as e:
        logger.error(f"Health check DB API error: {e}")
    
    # Verificar configuración del CRM
    crm_configured = bool(settings.CRM_CLIENT_ID and settings.CRM_CLIENT_SECRET)
    
    return HealthResponse(
        status="healthy" if (db_api_healthy and crm_configured) else "degraded",
        service=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
        timestamp=get_now_gmt5_iso(),
        database_connected=db_api_healthy,
        crm_configured=crm_configured
    )


@app.get("/sync/status", response_model=StatusResponse)
async def get_sync_status():
    """
    Obtiene el estado actual de la sincronización
    """
    try:
        db_client = get_database_api_client()
        stats = await db_client.get_stats()
        
        return StatusResponse(
            service=settings.SERVICE_NAME,
            version=settings.SERVICE_VERSION,
            timestamp=get_now_gmt5_iso(),
            database_stats=stats
        )
        
    except Exception as e:
        logger.error(f"Error obteniendo status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dispositivos/types")
async def get_device_types():
    """
    Obtiene lista de tipos de dispositivos disponibles en la tabla dispositivos
    Útil para saber qué valores usar en device_type
    """
    try:
        db_client = get_database_api_client()
        results = await db_client.get_device_types()
        
        device_types = [
            {
                "device_type": row["device_type"],
                "cantidad": row["count"]
            }
            for row in results
        ]
        
        return {
            "total_types": len(device_types),
            "device_types": device_types,
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo tipos de dispositivos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dispositivos/diagnostico")
async def diagnostico_seriales(device_type: str = "Cooling Device"):
    """
    NUEVO: Diagnóstico detallado de seriales de dispositivos
    
    Muestra por qué algunos dispositivos no se consultan en el CRM:
    - Total de dispositivos del tipo
    - Cuántos tienen serial
    - Cuántos NO tienen serial (NULL o vacío)
    - Seriales únicos (sin duplicados)
    - Lista de dispositivos sin serial
    - Lista de seriales duplicados
    
    Query params:
        - device_type: Tipo de dispositivo (default: "Cooling Device")
    """
    try:
        db_client = get_database_api_client()
        
        # Obtener todos los datos necesarios con el nuevo cliente
        stats = await db_client.get_diagnostico_stats(device_type)
        sin_serial = await db_client.get_diagnostico_sin_serial(device_type)
        duplicados = await db_client.get_diagnostico_duplicados(device_type) # Este método ya recibe un solo tipo
        seriales_consultados = await db_client.get_seriales_por_tipos([device_type])
        
        # Preparar respuesta
        dispositivos_sin_serial = [
            {
                "device_id": row.get("device_id"),
                "device_name": row.get("device_name"),
                "serial_number_device": row.get("serial_number_device") or "NULL"
            }
            for row in sin_serial
        ]
        
        seriales_duplicados = [
            {
                "serial": row.get("serial_number_device"),
                "cantidad_dispositivos": row.get("cantidad"),
                "dispositivos": row.get("dispositivos")
            }
            for row in duplicados
        ]
        
        # Calcular diferencia
        total = stats.get("total", 0)
        con_serial = stats.get("con_serial", 0)
        sin_serial_count = stats.get("sin_serial", 0)
        seriales_unicos = stats.get("seriales_unicos", 0)
        duplicados_count = con_serial - seriales_unicos if con_serial > seriales_unicos else 0
        
        return {
            "device_type": device_type,
            "resumen": {
                "total_dispositivos": total,
                "con_serial": con_serial,
                "sin_serial": sin_serial_count,
                "seriales_unicos": seriales_unicos,
                "seriales_duplicados_count": duplicados_count,
                "se_consultan_en_crm": seriales_unicos
            },
            "explicacion": {
                "por_que_diferencia": f"De {total} dispositivos tipo '{device_type}', solo se consultan {seriales_unicos} en el CRM porque:",
                "razon_1": f"{sin_serial_count} dispositivos NO tienen serial (NULL o vacío)" if sin_serial_count > 0 else None,
                "razon_2": f"{duplicados_count} seriales están duplicados (mismo serial en múltiples dispositivos)" if duplicados_count > 0 else None,
                "resultado": f"Se consultan {seriales_unicos} seriales únicos en el CRM"
            },
            "detalles": {
                "dispositivos_sin_serial": dispositivos_sin_serial,
                "seriales_duplicados": seriales_duplicados,
                "seriales_que_se_consultan": seriales_consultados[:10] + ["..."] if len(seriales_consultados) > 10 else seriales_consultados,
                "total_seriales_consultados": len(seriales_consultados)
            }
        }
        
    except Exception as e:
        logger.error(f"Error en diagnóstico de seriales: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync/mantenimientos", response_model=SyncResponse)
async def sync_mantenimientos(request: SyncRequest):
    """
    Ejecuta la sincronización de mantenimientos
    
    Body:
        - truncate_first (bool): Si es True, limpia la tabla antes de insertar
        - seriales (list, opcional): Lista de seriales a consultar. 
          Si no se proporciona, se obtienen desde la tabla de dispositivos.
        - device_types (list, opcional): Lista de tipos de dispositivo a filtrar (ej: ["Cooling Device", "Heating Device"]).
          Si no se proporciona, se sincronizan TODOS los dispositivos con serial.
    
    Flujo:
        1. Obtiene seriales desde la tabla de dispositivos, aplicando el filtro de `device_types` si se proporciona.
        2. Consulta el CRM con los seriales obtenidos.
        3. Compara con la BD para encontrar registros nuevos.
        4. Inserta los registros nuevos.
    
    Ejemplos de uso:
        - Sincronización de TODOS los dispositivos:
          POST {"truncate_first": false}
        
        - Con tipos específicos:
          POST {"truncate_first": false, "device_types": ["Cooling Device", "Other Device"]}
        
        - Con seriales manuales:
          POST {"truncate_first": false, "seriales": ["SN001", "SN002"]}
    
    Returns:
        Resultado de la sincronización con estadísticas
    """
    logger.info("")
    logger.info("[SOLICITUD] Nueva solicitud de sincronizacion recibida")
    logger.info(f"   Truncate first: {request.truncate_first}")
    logger.info(f"   Device types: {request.device_types or 'TODOS'}")
    logger.info(f"   Seriales proporcionados: {len(request.seriales) if request.seriales else 0}")
    if request.seriales:
        logger.info(f"   Primeros seriales: {request.seriales[:5]}")
    
    try:
        sync_service = get_sync_service()
        resultado = await sync_service.sync_mantenimientos(
            truncate_first=request.truncate_first,
            seriales=request.seriales,
            device_types=request.device_types
        )
        
        return SyncResponse(**resultado)
        
    except Exception as e:
        logger.error(f"[ERROR] Error en sincronizacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/test/crm-connection")
async def test_crm_connection():
    """
    Prueba la conexión con el CRM
    """
    try:
        crm_client = get_crm_client()
        result = crm_client.test_connection()
        return result
    except Exception as e:
        logger.error(f"Error probando CRM: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower()
    )