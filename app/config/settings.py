from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from pathlib import Path
from . import constants

# Construir la ruta al archivo .env en el directorio raíz del proyecto
# Esto hace que la carga sea robusta, sin importar desde dónde se ejecute el script.
env_path = Path(__file__).resolve().parent.parent.parent / '.env'

class Settings(BaseSettings):
    """
    Configuración del Microservicio de Sincronización de Mantenimientos
    """
    
    # ============================================================
    # API CONFIG
    # ============================================================
    SERVICE_NAME: str = Field(default=constants.SERVICE_NAME, description="Nombre del servicio")
    SERVICE_VERSION: str = Field(default=constants.SERVICE_VERSION, description="Versión del servicio")
    HOST: str = Field(default=constants.HOST, description="Host del servicio")
    PORT: int = Field(default=constants.PORT, description="Puerto del servicio")
    DEBUG: bool = Field(default=constants.DEBUG, description="Modo debug")
    
    # ============================================================
    # API SECURITY
    # ============================================================
    SYNC_MAINTENANCE_BEARER_TOKEN: str = Field(..., description="Token maestro para asegurar los endpoints de la API")

    # ============================================================
    # CRM API - CRM COTEL
    # ============================================================
    CRM_BASE_URL: str = Field(default=constants.CRM_BASE_URL, description="URL base del CRM")
    CRM_CLIENT_ID: str = Field(default=constants.CRM_CLIENT_ID, description="Client ID del CRM")
    CRM_CLIENT_SECRET: str = Field(..., description="Client Secret del CRM")
    CRM_TIMEOUT: int = Field(default=constants.CRM_TIMEOUT, description="Timeout para requests al CRM (segundos)")
    
    # Endpoints del CRM Cotel (no cambiar)
    CRM_SERVICES_ENDPOINT: str = Field(
        default=constants.CRM_SERVICES_ENDPOINT, 
        description="Endpoint de equipos/mantenimientos del CRM"
    )
    
    # ============================================================
    # DATABASE API (POSTGREST)
    # ============================================================
    DB_API_BASE_URL: str = Field(default=constants.DB_API_BASE_URL, description="URL base de la API de la base de datos")
    DB_API_TOKEN: str = Field(..., alias="BEARER_TOKEN_API_POSTGREST_CRUD_MONITOREO_EQUIPOS", description="Bearer token para la API de la base de datos")
    DB_API_SCHEMA: str = Field(default=constants.DB_API_SCHEMA, description="Schema profile para la API de la base de datos")
    
    # ============================================================
    # SYNC CONFIG
    # ============================================================
    BATCH_SIZE: int = Field(default=constants.BATCH_SIZE, description="Tamaño de lote para inserciones")
    MAX_RETRIES: int = Field(default=constants.MAX_RETRIES, description="Máximo número de reintentos")
    RETRY_DELAY: int = Field(default=constants.RETRY_DELAY, description="Delay entre reintentos (segundos)")
    
    # ============================================================
    # LOGGING
    # ============================================================
    LOG_LEVEL: str = Field(default=constants.LOG_LEVEL, description="Nivel de logging")
    
    # ============================================================
    # CONFIGURACIÓN DEL MODELO
    # ============================================================
    model_config = SettingsConfigDict(
        env_file=env_path,
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore'
    )
    
    # ============================================================
    # PROPIEDADES COMPUTADAS
    # ============================================================
    
    @property
    def crm_api_url(self) -> str:
        """URL completa del API del CRM"""
        return f"{self.CRM_BASE_URL}/api/v8"
    
    @property
    def crm_auth_url(self) -> str:
        """URL completa de autenticación"""
        return f"{self.CRM_BASE_URL}/crm/Api/access_token"
    
    @property
    def crm_equipos_url(self) -> str:
        """URL completa de equipos"""
        return f"{self.CRM_BASE_URL}{self.CRM_SERVICES_ENDPOINT}"


@lru_cache
def get_settings() -> Settings:
    """
    Retorna instancia singleton de Settings
    """
    return Settings()