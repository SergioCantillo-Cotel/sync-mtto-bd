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
            "Prefer": "return=representation"
        }
        self.client: httpx.AsyncClient | None = None

    async def startup(self):
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,   # descartar conexiones inactivas >30s
            ),
        )

    async def shutdown(self):
        await self.client.aclose()

    async def is_healthy(self) -> bool:
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
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        stats = {}
        try:
            response = await self.client.get(f"{self.base_url}/mantenimientos", headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['total'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            response = await self.client.get(f"{self.base_url}/mantenimientos?select=serial")
            response.raise_for_status()
            seriales_unicos = {item['serial'] for item in response.json() if item.get('serial')}
            stats['dispositivos_unicos'] = len(seriales_unicos)

            response = await self.client.get(f"{self.base_url}/mantenimientos?select=datetime_maintenance_end&datetime_maintenance_end=not.is.null&order=datetime_maintenance_end.asc&limit=1")
            response.raise_for_status()
            first_mto = response.json()
            stats['primer_mantenimiento'] = first_mto[0]['datetime_maintenance_end'] if first_mto else None

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
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        try:
            params = {
                "select": "device_type",
                "device_type": "not.is.null"
            }
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
            response.raise_for_status()
            
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
        params = {
            "select": "serial_number_device",
            "serial_number_device": "not.is.null",
            "serial_number_device": "not.eq."
        }
        if device_types:
            quoted_types = ",".join(f'"{dt}"' for dt in device_types)
            params["device_type"] = f"in.({quoted_types})"

        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
        response.raise_for_status()
        
        seriales = {
            item['serial_number_device'] 
            for item in response.json() 
            if item.get('serial_number_device')
        }
        return sorted(list(seriales))

    async def get_mantenimientos_existentes(self, seriales: Optional[List[str]] = None) -> Dict[str, Set]:
        """
        Retorna DOS estructuras para deduplicación en capas:

        1. 'ids': Set de maintenance_id que ya existen en la BD.
           → Es la llave REAL (PK). Evita el error 409 de clave duplicada.

        2. 'composite_keys': Set de tuplas (ods_name, report_id, maintenance_remarks).
           → Llave de negocio. Detecta registros que el CRM puede haber re-emitido
             con un id_reporte diferente pero con el mismo contenido.

        OPTIMIZACIÓN: Si se pasan 'seriales', la consulta se filtra solo por esos
        seriales en lugar de descargar toda la tabla. Esto evita timeouts en GCP
        cuando la tabla tiene miles de registros creciendo con el tiempo.

        La paginación interna garantiza que aunque el resultado filtrado sea grande,
        siempre se obtiene completo sin depender de un solo request enorme.
        """
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")

        PAGE_SIZE = 1000  # Registros por página — ajustable según límites de PostgREST
        ids: Set[str] = set()
        composite_keys: Set[tuple] = set()
        offset = 0

        try:
            while True:
                params: Dict[str, Any] = {
                    "select": "maintenance_id,ods_name,report_id,maintenance_remarks",
                    "order": "maintenance_id",   # orden estable para paginación confiable
                    "limit": PAGE_SIZE,
                    "offset": offset,
                }

                # FILTRO CLAVE: solo traemos los registros de los seriales que
                # vamos a procesar, no toda la tabla.
                if seriales:
                    quoted = ",".join(f'"{s}"' for s in seriales)
                    params["serial"] = f"in.({quoted})"

                response = await self.client.get(
                    f"{self.base_url}/mantenimientos",
                    params=params
                )
                response.raise_for_status()
                pagina = response.json()

                if not pagina:
                    # No hay más páginas
                    break

                for item in pagina:
                    # Capa 1: PK real
                    if item.get('maintenance_id'):
                        ids.add(str(item['maintenance_id']))

                    # Capa 2: llave de negocio compuesta
                    if item.get('ods_name') and item.get('report_id') and item.get('maintenance_remarks'):
                        composite_keys.add((
                            item['ods_name'],
                            item['report_id'],
                            item['maintenance_remarks']
                        ))

                if len(pagina) < PAGE_SIZE:
                    # Última página (incompleta) — no hay más datos
                    break

                offset += PAGE_SIZE

            logger.info(f"[DEDUP] IDs existentes en BD (filtrado por seriales): {len(ids)}")
            logger.info(f"[DEDUP] Llaves compuestas existentes en BD: {len(composite_keys)}")
            return {"ids": ids, "composite_keys": composite_keys}

        except httpx.HTTPStatusError as e:
            logger.error(f"Error al obtener mantenimientos existentes: {e.response.text}")
            raise
        except httpx.TimeoutException as e:
            logger.error(f"Timeout al obtener mantenimientos existentes (offset={offset}): {e}")
            raise
        except httpx.RequestError as e:
            # RemoteProtocolError, ConnectError, ReadError, etc.
            # Ocurre cuando el servidor cierra una conexión keep-alive inactiva
            # y httpx intenta reutilizarla. Se reintenta UNA vez con conexión fresca.
            logger.warning(f"[CONN] Error de conexión en mantenimientos (offset={offset}): {type(e).__name__}: {e}")
            logger.warning("[CONN] Reintentando con conexión fresca...")
            try:
                # Forzar reconexión cerrando y recreando el cliente
                await self.client.aclose()
                self.client = httpx.AsyncClient(
                    headers=self.client.headers,
                    timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=5,
                        max_connections=10,
                        keepalive_expiry=30.0,
                    ),
                )
                # Reintentar solo la página que falló (offset ya apunta al último intento)
                params_retry: Dict[str, Any] = {
                    "select": "maintenance_id,ods_name,report_id,maintenance_remarks",
                    "order": "maintenance_id",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                }
                if seriales:
                    quoted = ",".join(f'"{s}"' for s in seriales)
                    params_retry["serial"] = f"in.({quoted})"
                response = await self.client.get(
                    f"{self.base_url}/mantenimientos",
                    params=params_retry
                )
                response.raise_for_status()
                pagina = response.json()
                for item in pagina:
                    if item.get('maintenance_id'):
                        ids.add(str(item['maintenance_id']))
                    if item.get('ods_name') and item.get('report_id') and item.get('maintenance_remarks'):
                        composite_keys.add((
                            item['ods_name'],
                            item['report_id'],
                            item['maintenance_remarks']
                        ))
                logger.info(f"[CONN] Reintento exitoso. Total IDs hasta ahora: {len(ids)}")
                return {"ids": ids, "composite_keys": composite_keys}
            except Exception as retry_exc:
                logger.error(f"[CONN] Reintento también falló: {retry_exc}")
                raise

    async def insertar_mantenimientos(self, mantenimientos: List[Dict[str, Any]]) -> int:
        """
        [REFACTORIZADO] Inserta mantenimientos usando ON CONFLICT DO NOTHING
        como red de seguridad final contra el error 409.

        PostgREST interpreta 'resolution=ignore-duplicates' como:
            INSERT INTO mantenimientos (...) VALUES (...) ON CONFLICT DO NOTHING

        Esto protege contra cualquier duplicado que haya escapado la
        deduplicación en Python (ej: condición de carrera, datos inconsistentes).
        """
        if not mantenimientos:
            return 0
        
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")

        # Header especial: le dice a PostgREST que ignore duplicados en lugar de fallar
        insert_headers = {
            **self.headers,
            "Prefer": "return=representation,resolution=ignore-duplicates,count=exact"
        }

        response = await self.client.post(
            f"{self.base_url}/mantenimientos",
            json=mantenimientos,
            headers=insert_headers
        )
        response.raise_for_status()

        # Con 'count=exact', PostgREST devuelve en Content-Range cuántos se insertaron realmente
        if response.status_code == 201:
            content_range = response.headers.get("Content-Range", "")
            try:
                # Formato: "0-N/total" o "*/0" si no hubo inserciones
                total_inserted = int(content_range.split('/')[-1]) if '/' in content_range else len(response.json())
            except (ValueError, IndexError):
                total_inserted = len(response.json())
            return total_inserted
        # 200 con ignore-duplicates: todos eran duplicados, 0 insertados
        return 0

    async def truncate_mantenimientos(self) -> None:
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        logger.warning("[AVISO] Eliminando TODOS los registros de la tabla 'mantenimientos' via DELETE.")
        try:
            response = await self.client.delete(f"{self.base_url}/mantenimientos")
            response.raise_for_status()
            logger.info("Todos los registros de 'mantenimientos' eliminados exitosamente.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error al eliminar registros: {e.response.text}")
            raise

    # --- Métodos para el endpoint de Diagnóstico ---

    async def get_diagnostico_stats(self, device_type: str) -> Dict[str, int]:
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        stats = {}
        try:
            response = await self.client.get(f"{self.base_url}/dispositivos", params={"device_type": f"eq.{device_type}"}, headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['total'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            params_con_serial = {"device_type": f"eq.{device_type}", "serial_number_device": "not.is.null", "serial_number_device": "not.eq."}
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params_con_serial, headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['con_serial'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

            params_sin_serial = {"device_type": f"eq.{device_type}", "or": "(serial_number_device.is.null,serial_number_device.eq.)"}
            response = await self.client.get(f"{self.base_url}/dispositivos", params=params_sin_serial, headers={"Prefer": "count=exact"})
            response.raise_for_status()
            stats['sin_serial'] = int(response.headers.get("Content-Range", "0-0/0").split('/')[-1])

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
        if not self.client:
            raise RuntimeError("El cliente HTTP no ha sido inicializado.")
        
        params = {
            "device_type": f"eq.{device_type}",
            "serial_number_device": "not.is.null",
            "serial_number_device": "not.eq.",
            "select": "serial_number_device,device_name"
        }
        response = await self.client.get(f"{self.base_url}/dispositivos", params=params)
        response.raise_for_status()
        dispositivos = response.json()

        seriales_agrupados = defaultdict(list)
        for disp in dispositivos:
            seriales_agrupados[disp['serial_number_device']].append(disp['device_name'])

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
    logger.debug("Creando o reutilizando instancia de DatabaseApiClient.")
    settings = get_settings()
    if not all([settings.DB_API_BASE_URL, settings.DB_API_TOKEN, settings.DB_API_SCHEMA]):
        raise ValueError("La configuración de la API de la base de datos (URL, Token, Schema) no está completa.")
    
    return DatabaseApiClient(
        base_url=settings.DB_API_BASE_URL,
        token=settings.DB_API_TOKEN,
        schema=settings.DB_API_SCHEMA
    )