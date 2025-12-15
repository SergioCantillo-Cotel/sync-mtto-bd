from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import logging
from datetime import datetime
from typing import Dict, Any

from config.settings import get_settings
from models.schemas import SyncRequest, SyncResponse, HealthResponse, StatusResponse
from services.sync_service import get_sync_service
from services.postgres_client import get_postgres_client
from services.crm_client import get_crm_client

# Configuración
settings = get_settings()

# Configurar logging sin emojis para Windows
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_FILE, encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)


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
    logger.info("Database Configuration:")
    logger.info(f"  Host: {settings.DB_HOST}:{settings.DB_PORT}")
    logger.info(f"  Database: {settings.DB_NAME}")
    logger.info(f"  User: {settings.DB_USER}")
    logger.info(f"  Schema: monitoreo_equipos")
    logger.info(f"  Tabla origen: dispositivos")
    logger.info(f"  Tabla destino: mantenimientos")
    logger.info("")
    logger.info("Dispositivos Configuration:")
    logger.info(f"  Filtro por defecto: device_type = '{settings.DEVICE_TYPE_FILTER}'")
    logger.info(f"  Campo serial: serial_number_device")
    logger.info("")
    logger.info("Sync Configuration:")
    logger.info(f"  Batch Size: {settings.BATCH_SIZE}")
    logger.info(f"  Max Retries: {settings.MAX_RETRIES}")
    logger.info("")
    logger.info("[IMPORTANTE] FLUJO DE SINCRONIZACION:")
    logger.info(f"   1. Obtener seriales desde monitoreo_equipos.dispositivos")
    logger.info(f"   2. Filtrar por device_type = '{settings.DEVICE_TYPE_FILTER}'")
    logger.info(f"   3. Consultar CRM con POST /equipos-info")
    logger.info(f"   4. Comparar con BD e insertar solo nuevos")
    logger.info("=" * 80)
    logger.info("")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")


# Crear aplicación
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    description="Microservicio de sincronizacion de mantenimientos desde CRM Cotel a PostgreSQL. Obtiene seriales desde tabla dispositivos.",
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
            "device_type_filter": settings.DEVICE_TYPE_FILTER,
            "source_table": "monitoreo_equipos.dispositivos",
            "target_table": "monitoreo_equipos.mantenimientos"
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check del servicio
    """
    # Verificar conexión a PostgreSQL
    db_connected = False
    try:
        postgres_client = get_postgres_client()
        postgres_client.connect()
        postgres_client.cursor.execute("SELECT 1;")
        postgres_client.disconnect()
        db_connected = True
    except Exception as e:
        logger.error(f"Health check DB error: {e}")
    
    # Verificar configuración del CRM
    crm_configured = bool(settings.CRM_CLIENT_ID and settings.CRM_CLIENT_SECRET)
    
    return HealthResponse(
        status="healthy" if (db_connected and crm_configured) else "degraded",
        service=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
        timestamp=datetime.now().isoformat(),
        database_connected=db_connected,
        crm_configured=crm_configured
    )


@app.get("/sync/status", response_model=StatusResponse)
async def get_sync_status():
    """
    Obtiene el estado actual de la sincronización
    """
    try:
        postgres_client = get_postgres_client()
        postgres_client.connect()
        
        stats = postgres_client.get_stats()
        
        postgres_client.disconnect()
        
        return StatusResponse(
            service=settings.SERVICE_NAME,
            version=settings.SERVICE_VERSION,
            timestamp=datetime.now().isoformat(),
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
        postgres_client = get_postgres_client()
        postgres_client.connect()
        
        query = """
        SELECT DISTINCT device_type, COUNT(*) as cantidad
        FROM monitoreo_equipos.dispositivos 
        WHERE device_type IS NOT NULL
        GROUP BY device_type
        ORDER BY cantidad DESC;
        """
        
        postgres_client.cursor.execute(query)
        results = postgres_client.cursor.fetchall()
        
        postgres_client.disconnect()
        
        device_types = [
            {
                "device_type": row[0],
                "cantidad": row[1]
            }
            for row in results
        ]
        
        return {
            "total_types": len(device_types),
            "device_types": device_types,
            "default_filter": settings.DEVICE_TYPE_FILTER
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
        postgres_client = get_postgres_client()
        postgres_client.connect()
        
        # Query 1: Estadísticas generales
        stats_query = """
        SELECT 
            COUNT(*) as total,
            COUNT(serial_number_device) as con_serial,
            COUNT(*) - COUNT(serial_number_device) as sin_serial,
            COUNT(DISTINCT serial_number_device) as seriales_unicos
        FROM monitoreo_equipos.dispositivos 
        WHERE device_type = %s;
        """
        
        postgres_client.cursor.execute(stats_query, (device_type,))
        stats = postgres_client.cursor.fetchone()
        
        # Query 2: Dispositivos sin serial
        sin_serial_query = """
        SELECT 
            device_id,
            device_name,
            serial_number_device
        FROM monitoreo_equipos.dispositivos 
        WHERE device_type = %s
        AND (serial_number_device IS NULL OR serial_number_device = '')
        ORDER BY device_name;
        """
        
        postgres_client.cursor.execute(sin_serial_query, (device_type,))
        sin_serial = postgres_client.cursor.fetchall()
        
        # Query 3: Seriales duplicados
        duplicados_query = """
        SELECT 
            serial_number_device,
            COUNT(*) as cantidad,
            STRING_AGG(device_name, ', ') as dispositivos
        FROM monitoreo_equipos.dispositivos 
        WHERE device_type = %s
        AND serial_number_device IS NOT NULL
        AND serial_number_device != ''
        GROUP BY serial_number_device
        HAVING COUNT(*) > 1
        ORDER BY cantidad DESC;
        """
        
        postgres_client.cursor.execute(duplicados_query, (device_type,))
        duplicados = postgres_client.cursor.fetchall()
        
        # Query 4: Lista de seriales que SE CONSULTAN
        seriales_query = """
        SELECT DISTINCT serial_number_device 
        FROM monitoreo_equipos.dispositivos 
        WHERE device_type = %s
        AND serial_number_device IS NOT NULL 
        AND serial_number_device != ''
        ORDER BY serial_number_device;
        """
        
        postgres_client.cursor.execute(seriales_query, (device_type,))
        seriales_consultados = [row[0] for row in postgres_client.cursor.fetchall()]
        
        postgres_client.disconnect()
        
        # Preparar respuesta
        dispositivos_sin_serial = [
            {
                "device_id": row[0],
                "device_name": row[1],
                "serial_number_device": row[2] if row[2] else "NULL"
            }
            for row in sin_serial
        ]
        
        seriales_duplicados = [
            {
                "serial": row[0],
                "cantidad_dispositivos": row[1],
                "dispositivos": row[2]
            }
            for row in duplicados
        ]
        
        # Calcular diferencia
        total = stats[0]
        con_serial = stats[1]
        sin_serial_count = stats[2]
        seriales_unicos = stats[3]
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
          Si no se proporciona, se obtienen desde tabla dispositivos.
        - device_type (str, opcional): Tipo de dispositivo a filtrar (ej: "Cooling Device").
          Si no se proporciona, usa el valor por defecto del .env
    
    Flujo:
        1. Conecta a PostgreSQL
        2. Obtiene seriales desde tabla dispositivos (filtrado por device_type)
        3. Consulta CRM con POST /equipos-info
        4. Consulta BD para ver qué ya existe
        5. Compara y filtra solo los nuevos
        6. Inserta solo registros nuevos
    
    Ejemplos de uso:
        - Sincronización automática (Cooling Device):
          POST {"truncate_first": false}
        
        - Con tipo específico:
          POST {"truncate_first": false, "device_type": "Heating Device"}
        
        - Con seriales manuales:
          POST {"truncate_first": false, "seriales": ["SN001", "SN002"]}
    
    Returns:
        Resultado de la sincronización con estadísticas
    """
    logger.info("")
    logger.info("[SOLICITUD] Nueva solicitud de sincronizacion recibida")
    logger.info(f"   Truncate first: {request.truncate_first}")
    logger.info(f"   Device type: {request.device_type or settings.DEVICE_TYPE_FILTER}")
    logger.info(f"   Seriales proporcionados: {len(request.seriales) if request.seriales else 0}")
    if request.seriales:
        logger.info(f"   Primeros seriales: {request.seriales[:5]}")
    
    try:
        sync_service = get_sync_service()
        resultado = sync_service.sync_mantenimientos(
            truncate_first=request.truncate_first,
            seriales=request.seriales,
            device_type=request.device_type
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