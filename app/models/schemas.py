from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class SyncRequest(BaseModel):
    """
    Request para sincronización de mantenimientos
    """
    truncate_first: bool = Field(
        default=False,
        description="Si es True, limpia la tabla antes de insertar"
    )
    seriales: Optional[List[str]] = Field(
        default=None,
        description="Lista opcional de seriales a consultar. Si no se proporciona, se obtienen desde tabla dispositivos"
    )
    device_type: Optional[str] = Field(
        default=None,
        description="Tipo de dispositivo a filtrar en tabla dispositivos (ej: 'Cooling Device'). Si no se especifica, usa el valor por defecto del .env"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "description": "Sincronización automática con Cooling Devices",
                    "value": {
                        "truncate_first": False
                    }
                },
                {
                    "description": "Sincronización con seriales específicos",
                    "value": {
                        "truncate_first": False,
                        "seriales": ["SN001", "SN002", "SN003"]
                    }
                },
                {
                    "description": "Sincronización con tipo de dispositivo específico",
                    "value": {
                        "truncate_first": False,
                        "device_type": "Cooling Device"
                    }
                }
            ]
        }


class SyncResponse(BaseModel):
    """
    Response de sincronización
    """
    success: bool
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    dispositivos: Dict[str, Any] = Field(default_factory=dict)
    seriales: Dict[str, Any] = Field(default_factory=dict)
    crm: Dict[str, Any] = Field(default_factory=dict)
    database: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """
    Response de health check
    """
    status: str
    service: str
    version: str
    timestamp: str
    database_connected: bool
    crm_configured: bool


class StatusResponse(BaseModel):
    """
    Response de status
    """
    service: str
    version: str
    timestamp: str
    database_stats: Optional[Dict[str, Any]] = None