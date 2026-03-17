from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

# =====================================================================
# Modelos para el endpoint /health
# =====================================================================

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str
    database_connected: bool
    crm_configured: bool

# =====================================================================
# Modelos para el endpoint /sync/status
# =====================================================================

class DatabaseStats(BaseModel):
    """Estadísticas de la tabla de mantenimientos."""
    total_registros: Optional[int] = Field(None, alias="total")
    dispositivos_unicos: Optional[int] = None
    primer_mantenimiento: Optional[str] = None
    ultimo_mantenimiento: Optional[str] = None
    error: Optional[str] = None

    class Config:
        populate_by_name = True

class StatusResponse(BaseModel):
    service: str
    version: str
    timestamp: str
    database_stats: DatabaseStats

# =====================================================================
# Modelos para el endpoint /sync/mantenimientos
# =====================================================================

class SyncRequest(BaseModel):
    truncate_first: bool = False

class SerialesInfo(BaseModel):
    source: Optional[str] = None
    total: int = 0
    list: List[str] = []

class CrmInfo(BaseModel):
    seriales_consultados: int = 0
    seriales_con_resultado: int = 0
    seriales_sin_resultado: int = 0
    list_seriales_sin_resultado: List[str] = []
    mantenimientos_obtenidos: int = 0
    timestamp: Optional[str] = None

class ComparacionInfo(BaseModel):
    """
    [ACTUALIZADO] Incluye métricas de la deduplicación en doble capa.
    """
    registros_obtenidos_crm: int = 0
    registros_descartados_sin_campos_clave: int = 0
    registros_validos_crm: int = 0
    # Métricas de deduplicación nuevas
    descartados_por_id_existente: int = 0       # Capa 1: PK ya existe
    descartados_por_contenido_existente: int = 0 # Capa 2: llave compuesta ya existe
    duplicados_en_crm: int = 0                  # Duplicados dentro del propio lote del CRM
    # Mantenidos para compatibilidad
    existentes_en_bd: int = 0
    nuevos_a_insertar: int = 0

class DatabaseInfo(BaseModel):
    total_intentado: int = 0
    exitosos: int = 0
    errores: int = 0
    stats: Optional[DatabaseStats] = None

class SyncResponse(BaseModel):
    success: bool
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    seriales: SerialesInfo = Field(default_factory=SerialesInfo)
    crm: CrmInfo = Field(default_factory=CrmInfo)
    comparacion: ComparacionInfo = Field(default_factory=ComparacionInfo)
    database: DatabaseInfo = Field(default_factory=DatabaseInfo)
    errors: List[str] = []

    class Config:
        extra = 'ignore'