# -*- coding: utf-8 -*-
"""
Archivo de constantes de configuración para el servicio.

Contiene valores de configuración que no son secretos y que no cambian
frecuentemente entre entornos (desarrollo, producción).
"""

# CONFIGURACIÓN DEL SERVICIO
SERVICE_NAME = "Sync Mantenimientos Service"
SERVICE_VERSION = "1.0.0"
HOST = "0.0.0.0"
PORT = 8080
DEBUG = True

# LOGGING
LOG_LEVEL = "INFO"

# CONFIGURACIÓN DEL CRM
CRM_BASE_URL = "https://crmcotel.com.co"
CRM_CLIENT_ID = "cd031831-d1f0-0a8b-b0a0-69123cd994f5"
CRM_TIMEOUT = 30
CRM_SERVICES_ENDPOINT = "/crm/Api/V8/custom/IA/equipos-info"

# CONFIGURACIÓN DE LA API DE BASE DE DATOS (POSTGREST)
DB_API_BASE_URL = "https://api-bd-eficiencia-energetica-853514779938.us-central1.run.app"
DB_API_SCHEMA = "monitoreo_equipos"

# CONFIGURACIÓN DE SINCRONIZACIÓN
BATCH_SIZE = 10000
MAX_RETRIES = 3
RETRY_DELAY = 5
