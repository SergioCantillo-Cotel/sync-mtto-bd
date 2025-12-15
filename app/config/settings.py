from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """
    Configuración del Microservicio de Sincronización de Mantenimientos
    """
    
    # ============================================================
    # API CONFIG
    # ============================================================
    SERVICE_NAME: str = Field(default="Sync Mantenimientos Service", description="Nombre del servicio")
    SERVICE_VERSION: str = Field(default="1.0.0", description="Versión del servicio")
    HOST: str = Field(default="0.0.0.0", description="Host del servicio")
    PORT: int = Field(default=8001, description="Puerto del servicio")
    DEBUG: bool = Field(default=True, description="Modo debug")
    
    # ============================================================
    # CRM API - CRM COTEL
    # ============================================================
    CRM_BASE_URL: str = Field(default="https://crmcotel.com.co", description="URL base del CRM")
    CRM_CLIENT_ID: str = Field(default="", description="Client ID del CRM")
    CRM_CLIENT_SECRET: str = Field(default="", description="Client Secret del CRM")
    CRM_TIMEOUT: int = Field(default=30, description="Timeout para requests al CRM (segundos)")
    
    # Endpoints del CRM Cotel (no cambiar)
    CRM_SERVICES_ENDPOINT: str = Field(
        default="/crm/Api/V8/custom/IA/equipos-info", 
        description="Endpoint de equipos/mantenimientos del CRM"
    )
    
    # ============================================================
    # POSTGRESQL
    # ============================================================
    DB_HOST: str = Field(default="127.0.0.1", description="Host de PostgreSQL")
    DB_PORT: int = Field(default=5432, description="Puerto de PostgreSQL")
    DB_NAME: str = Field(default="eficiencia_energetica", description="Nombre de la base de datos")
    DB_USER: str = Field(default="api_crud_monitoreo_equipos", description="Usuario de la base de datos")
    DB_PASSWORD: str = Field(default="", description="Contraseña de la base de datos")
    
    # ============================================================
    # DISPOSITIVOS CONFIG
    # ============================================================
    DEVICE_TYPE_FILTER: str = Field(
        default="Cooling Device", 
        description="Tipo de dispositivo a filtrar de la tabla dispositivos"
    )
    
    # ============================================================
    # SYNC CONFIG
    # ============================================================
    BATCH_SIZE: int = Field(default=100, description="Tamaño de lote para inserciones")
    MAX_RETRIES: int = Field(default=3, description="Máximo número de reintentos")
    RETRY_DELAY: int = Field(default=5, description="Delay entre reintentos (segundos)")
    
    # ============================================================
    # LOGGING
    # ============================================================
    LOG_LEVEL: str = Field(default="INFO", description="Nivel de logging")
    LOG_FILE: str = Field(default="logs/sync_mantenimientos.log", description="Archivo de logs")
    
    # ============================================================
    # CONFIGURACIÓN DEL MODELO
    # ============================================================
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore'
    )
    
    # ============================================================
    # PROPIEDADES COMPUTADAS
    # ============================================================
    
    @property
    def database_url(self) -> str:
        """Construye URL de conexión a PostgreSQL"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
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