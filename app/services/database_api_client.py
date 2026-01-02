import httpx
import logging
from functools import lru_cache
from collections import defaultdict
from typing import List, Dict, Any, Set, Optional

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

class DatabaseApiClient:
    """
    Cliente asíncrono para interactuar con la API de la base de datos (PostgREST).
    """
    def __init__(self, base_url: str, token: str, schema: str):
        self.base_url = base_url.rstrip('/')
        self.schema = schema
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept-Profile": schema,
            "Content-Profile": schema,
            "Prefer": "return=representation" # Devuelve el objeto insertado/actualizado
        }
        self.client: httpx.AsyncClient | None = None

    async def startup(self):
        self.client = httpx.AsyncClient(headers=self.headers, timeout=60.0)

    async def shutdown(self):
        await self.client.aclose()

    async def is_healthy(self) -> bool:
        """
        Verifica si la API de la base de datos está disponible.
        PostgREST responde en la ruta raíz con el esquema de la API.
        """
        try:
            if not self.client:
                raise RuntimeError("El cliente HTTP no ha sido inicializado. Llama a startup() primero.")
            response = await self.client.get(self.base_url)
            response.raise_for_status()
            logger.debug("Conexión con la API de la BD exitosa.")
            return response.status_code == 200
        except httpx.RequestError as e:
            logger.error(f"Error de conexión con la API de la BD: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """
        Refactorizado para usar consultas directas a PostgREST.
        """
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        stats = {}
        try:
            # Total de registros
            response = await self.client.get(f"{self.base_url}/mantenimientos", headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['total'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            # Dispositivos únicos (por serial)
            response = await self.client.get(f"{self.base_url}/mantenimientos?select=serial")
            response.raise_for_status()
            # Procesar en el cliente para obtener valores únicos
            seriales_unicos = {item['serial'] for item in response.json() if item.get('serial')}
            stats['dispositivos_unicos'] = len(seriales_unicos)

            # Clientes únicos (por customer_name)
            response = await self.client.get(f"{self.base_url}/mantenimientos?select=customer_name")
            response.raise_for_status()
            # Procesar en el cliente para obtener valores únicos
            clientes_unicos = {item['customer_name'] for item in response.json() if item.get('customer_name')}
            stats['clientes_unicos'] = len(clientes_unicos)

            # Primer mantenimiento
            response = await self.client.get(f"{self.base_url}/mantenimientos?select=datetime_maintenance_end&datetime_maintenance_end=not.is.null&order=datetime_maintenance_end.asc&limit=1")
            response.raise_for_status()
            first_mto = response.json()
            stats['primer_mantenimiento'] = first_mto[0]['datetime_maintenance_end'] if first_mto else None

            # Último mantenimiento
            response = await self.client.get(f"{self.base_url}/mantenimientos?select=datetime_maintenance_end&datetime_maintenance_end=not.is.null&order=datetime_maintenance_end.desc&limit=1")
            response.raise_for_status()
            last_mto = response.json()
            stats['ultimo_mantenimiento'] = last_mto[0]['datetime_maintenance_end'] if last_mto else None
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Error al obtener estadísticas de mantenimientos: {e.response.text}")
            stats['error'] = f"Error al obtener estadísticas: {e.response.text}"
        except Exception as e:
            logger.error(f"Error inesperado al obtener estadísticas: {e}")
            stats['error'] = f"Error inesperado: {e}"
            
        return stats

    async def get_device_types(self) -> List[Dict[str, Any]]:
        """
        Obtiene los tipos de dispositivos y su cantidad.
        Refactorizado para usar consultas directas a PostgREST.
        """
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        try:
            # Se refactoriza para no usar 'group' que causa conflictos.
            # 1. Se obtienen todos los device_type no nulos.
            # 2. Se agrupa y cuenta en el cliente (Python).
            params = {
                "select": "device_type",
                "device_type": "not.is.null" # Filtro para no traer nulos
            }
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
            response.raise_for_status()
            
            # Agrupar y contar en Python
            device_counts = defaultdict(int)
            for item in response.json():
                device_counts[item['device_type']] += 1
            
            results = [{"device_type": dt, "count": count} for dt, count in device_counts.items()]
            return sorted(results, key=lambda x: x.get('count', 0), reverse=True)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error al obtener tipos de dispositivos: {e.response.text}")
            if e.response.status_code == 404:
                return [{"error": "La tabla 'dispositivos' no fue encontrada."}]
            raise

    async def get_seriales_por_tipos(self, device_types: Optional[List[str]] = None) -> List[str]:
        """
        Obtiene una lista de seriales únicos para una lista de tipos de dispositivo.
        Si device_types es None, obtiene seriales de todos los dispositivos.
        """
        params = {
            "select": "serial_number_device",
            "serial_number_device": "not.is.null",
            "serial_number_device": "not.eq."  # No vacío
        }
        if device_types:
            # Formato para el filtro 'in' de PostgREST: in.("type 1","type 2")
            # Se construye la cadena de valores entrecomillados para evitar el SyntaxError con la barra invertida en la f-string.
            quoted_types = ",".join(f'"{dt}"' for dt in device_types)
            params["device_type"] = f"in.({quoted_types})"

        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
        response.raise_for_status()
        
        # Extraer seriales únicos y no vacíos
        seriales = {
            item['serial_number_device'] 
            for item in response.json() 
            if item.get('serial_number_device')
        }
        return sorted(list(seriales))

    async def get_mantenimientos_existentes(self) -> Set[tuple]:
        """
        Consulta la API para obtener las combinaciones únicas de 
        (ods_name, report_id, maintenance_remarks) que ya existen en la tabla.
        Esta combinación actúa como una clave única para identificar un mantenimiento.
        """
        params = {
            "select": "ods_name,report_id,maintenance_remarks",
            "ods_name": "not.is.null",
            "report_id": "not.is.null",
            "maintenance_remarks": "not.is.null"
        }
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        response = await self.client.get(f"{self.base_url}/mantenimientos", params=params)
        response.raise_for_status()
        
        # Crear un set de tuplas para una búsqueda de existencia O(1)
        return {
            (item['ods_name'], item['report_id'], item['maintenance_remarks']) 
            for item in response.json()
        }

    async def insertar_mantenimientos(self, mantenimientos: List[Dict[str, Any]]) -> int:
        """
        Inserta una lista de mantenimientos en la base de datos.
        """
        if not mantenimientos:
            return 0
        
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        response = await self.client.post(f"{self.base_url}/mantenimientos", json=mantenimientos)
        response.raise_for_status()
        # El status 201 indica creación exitosa
        return len(response.json()) if response.status_code == 201 else 0

    async def truncate_mantenimientos(self) -> None:
        """
        Trunca la tabla de mantenimientos.
         ADVERTENCIA: Esto elimina todos los registros pero no reinicia las secuencias de IDs.
        """
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        logger.warning("[AVISO] Eliminando TODOS los registros de la tabla 'mantenimientos' via DELETE. Esto no reinicia secuencias de IDs.")
        try:
            response = await self.client.delete(f"{self.base_url}/mantenimientos")
            response.raise_for_status()
            logger.info("Todos los registros de 'mantenimientos' eliminados exitosamente via DELETE.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error al eliminar registros de la tabla 'mantenimientos': {e.response.text}")
            raise

    # --- Métodos para el endpoint de Diagnóstico ---

    async def get_diagnostico_stats(self, device_type: str) -> Dict[str, int]:
        """
        Obtiene estadísticas para el diagnóstico.
        Refactorizado para usar consultas directas a PostgREST.
        """
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        stats = {}
        try:
            # Total de dispositivos del tipo
            response = await self.client.get(f"{self.base_url}/dispositivos", params={"device_type": f"eq.{device_type}"}, headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['total'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            # Con serial
            params_con_serial = {"device_type": f"eq.{device_type}", "serial_number_device": "not.is.null", "serial_number_device": "not.eq."}
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params_con_serial, headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['con_serial'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            # Sin serial
            params_sin_serial = {"device_type": f"eq.{device_type}", "or": "(serial_number_device.is.null,serial_number_device.eq.)"}
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params_sin_serial, headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['sin_serial'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            # Seriales únicos
            params_unicos = {"device_type": f"eq.{device_type}", "serial_number_device": "not.is.null", "serial_number_device": "not.eq.", "select": "serial_number_device"}
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params_unicos)
            response.raise_for_status()
            seriales_unicos = {item['serial_number_device'] for item in response.json()}
            stats['seriales_unicos'] = len(seriales_unicos)

        except httpx.HTTPStatusError as e:
            logger.error(f"Error al obtener estadísticas de diagnóstico: {e.response.text}")
            stats['error'] = f"Error al obtener estadísticas de diagnóstico: {e.response.text}"
        except Exception as e:
            logger.error(f"Error inesperado al obtener estadísticas de diagnóstico: {e}")
            stats['error'] = f"Error inesperado: {e}"
        return stats

    async def get_diagnostico_sin_serial(self, device_type: str) -> List[Dict[str, Any]]:
        """
        Obtiene dispositivos sin número de serial.
        """
        params = {
            "select": "device_id,device_name,serial_number_device",
            "device_type": f"eq.{device_type}",
            "or": "(serial_number_device.is.null,serial_number_device.eq.)",
            "order": "device_name"
        }
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
        response.raise_for_status()
        return response.json()

    async def get_diagnostico_duplicados(self, device_type: str) -> List[Dict[str, Any]]:
        """
        Obtiene seriales duplicados.
        Refactorizado para procesar en Python, sin RPC.
        """
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        # 1. Obtener todos los seriales y nombres de dispositivos para el tipo
        params = {
            "device_type": f"eq.{device_type}",
            "serial_number_device": "not.is.null",
            "serial_number_device": "not.eq.",
            "select": "serial_number_device,device_name"
        }
        response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
        response.raise_for_status()
        dispositivos = response.json()

        # 2. Procesar en Python para encontrar duplicados
        seriales_agrupados = defaultdict(list)
        for disp in dispositivos:
            seriales_agrupados[disp['serial_number_device']].append(disp['device_name'])

        # 3. Filtrar y formatear los duplicados
        duplicados = []
        for serial, nombres in seriales_agrupados.items():
            if len(nombres) > 1:
                duplicados.append({
                    "serial_number_device": serial,
                    "cantidad": len(nombres),
                    "dispositivos": ", ".join(nombres)
                })
        
        return sorted(duplicados, key=lambda x: x['cantidad'], reverse=True)


@lru_cache()
def get_database_api_client() -> DatabaseApiClient:
    """
    Factory para obtener una instancia singleton del DatabaseApiClient.
    Usa lru_cache para asegurar que solo se cree una instancia.
    """
    logger.debug("Creando o reutilizando instancia de DatabaseApiClient.")
    settings = get_settings()
    if not all([settings.DB_API_BASE_URL, settings.DB_API_TOKEN, settings.DB_API_SCHEMA]):
        raise ValueError("La configuración de la API de la base de datos (URL, Token, Schema) no está completa.")
    
    return DatabaseApiClient(
        base_url=settings.DB_API_BASE_URL,
        token=settings.DB_API_TOKEN,
        schema=settings.DB_API_SCHEMA
    )