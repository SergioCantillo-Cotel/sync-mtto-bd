from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone, timedelta
import logging
import uuid
import asyncio

from .crm_client import get_crm_client, CRMClient
from .database_api_client import get_database_api_client, DatabaseApiClient
from ..config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def get_now_gmt5_iso() -> str:
    """
    Obtiene la fecha y hora actual en zona horaria GMT-5 y la devuelve
    como un string en formato ISO, pero sin el offset de zona horaria.
    """
    gmt5_tz = timezone(timedelta(hours=-5))
    now_gmt5 = datetime.now(gmt5_tz)
    return now_gmt5.strftime('%Y-%m-%dT%H:%M:%S.%f')

class SyncService:
    """
    Servicio de sincronización de mantenimientos
    
    FLUJO:
    1. Obtener seriales desde la API de la BD (tabla dispositivos)
    2. Consultar CRM con esos seriales
    4. Consultar API de la BD para ver qué mantenimientos ya existen
    4. Comparar y filtrar solo los nuevos
    5. Insertar solo registros nuevos a través de la API de la BD
    """
    
    def __init__(self):
        self.crm_client: CRMClient = get_crm_client()
        self.db_client: DatabaseApiClient = get_database_api_client()
        logger.info("SyncService inicializado")
    
    def _map_crm_to_db(self, mto: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mapea los datos del CRM a los campos de la base de datos.
        Esta lógica se movió desde el antiguo PostgresClient.
        
        Args:
            mto: Diccionario con datos del CRM
            
        Returns:
            Diccionario con campos mapeados para la BD
        """
        # Generar UUID para maintenance_id
        maintenance_id = str(uuid.uuid4())
        
        # Mapeo de campos CRM → BD
        mapped = {
            'maintenance_id': maintenance_id,
            'ods_name': mto.get('nombre_ods'),
            'maintenance_type': mto.get('tipo_mantenimiento'),
            'device_id': mto.get('id_equipos'),
            'device_name': mto.get('nombre_equipo'),
            'device_brand': mto.get('marca'),
            'device_model': mto.get('modelo'),
            'device_type': mto.get('linea'),
            'datetime_ods_create': mto.get('fecha_creacion'),
            'serial': mto.get('serial'),
            'report_id': mto.get('reporte'),
            'datetime_maintenance_end': mto.get('hora_salida'),
            'maintenance_remarks': mto.get('observaciones_reporte'),
            'report_status': mto.get('status') or mto.get('estado_reporte'),
            'nit': mto.get('nit'),
            'customer_name': mto.get('cliente')
        }
        return mapped

    async def _insertar_en_lotes(self, mantenimientos: List[Dict[str, Any]]) -> Dict[str, int]:
        """Inserta mantenimientos en la BD en lotes."""
        insertados = 0
        errores = 0
        batch_size = settings.BATCH_SIZE
        total_batches = (len(mantenimientos) + batch_size - 1) // batch_size
        
        logger.info(f"[INFO] Insertando {len(mantenimientos)} registros en {total_batches} lotes...")

        for i in range(0, len(mantenimientos), batch_size):
            batch = mantenimientos[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            logger.info(f"[LOTE] Procesando lote {batch_num}/{total_batches} ({len(batch)} registros)...")
            try:
                nuevos_insertados = await self.db_client.insertar_mantenimientos(batch)
                insertados += nuevos_insertados
                logger.info(f"   [OK] Lote {batch_num} insertado. {nuevos_insertados} registros guardados.")
            except Exception as e:
                errores += len(batch)
                logger.error(f"   [ERROR] Error insertando lote {batch_num}: {e}")
        
        return {'insertados': insertados, 'errores': errores}

    async def sync_mantenimientos(
        self, 
        truncate_first: bool = False,
        seriales: Optional[List[str]] = None,
        device_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta el proceso completo de sincronización de forma asíncrona.
        
        Args:
            truncate_first: Si es True, limpia la tabla antes de insertar
            seriales: Lista opcional de seriales a consultar.
            device_types: Lista de tipos de dispositivo a filtrar. Si es None, se sincronizan todos.
            
        Returns:
            Diccionario con resultados de la sincronización
        """
        start_time_obj = datetime.now(timezone(timedelta(hours=-5)))
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("         INICIO DE SINCRONIZACION ASINCRONA")
        logger.info("=" * 80)
        logger.info(f"Inicio: {start_time_obj.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Fuente: API de BD (Tabla 'dispositivos')")
        logger.info(f"Destino: API de BD (Tabla 'mantenimientos')")
        logger.info(f"Filtro dispositivos: {device_types or 'TODOS'}")
        logger.info(f"Estrategia: Insertar solo registros nuevos")
        logger.info("")
        
        resultado = {
            'success': False,
            'start_time': get_now_gmt5_iso(),
            'end_time': None,
            'duration_seconds': None,
            'seriales': {
                'source': None,
                'total': 0,
                'list': []
            },
            'crm': {},
            'database': {},
            'comparacion': {},
            'errors': []
        }
        
        try:
            # PASO 1: Verificar salud de la API
            logger.info("PASO 1/6: Verificando conexión con la API de la BD...")
            if not await self.db_client.is_healthy():
                raise Exception("La API de la base de datos no está disponible.")
            logger.info("[OK] La API de la BD está respondiendo.")

            # PASO 2: Truncar si se solicita
            if truncate_first:
                logger.info("")
                logger.info("PASO 2/6: Limpiando tabla (TRUNCATE)...")
                await self.db_client.truncate_mantenimientos()
            else:
                logger.info("")
                logger.info("PASO 2/6: Omitiendo truncate...")
            
            # PASO 3: Obtener lista de seriales
            logger.info("")
            logger.info("PASO 3/6: Obteniendo lista de seriales...")
            
            if seriales is None:
                logger.info(f"Consultando seriales para los tipos: {device_types or 'TODOS'}")
                seriales = await self.db_client.get_seriales_por_tipos(device_types=device_types)
                resultado['seriales']['source'] = f"BD (dispositivos - {device_types or 'TODOS'})"
            else:
                resultado['seriales']['source'] = 'Parámetro del request'
                logger.info(f"[OK] Usando seriales proporcionados en el request: {len(seriales)}")
            
            if not seriales:
                logger.warning("[AVISO] No se obtuvieron seriales para los filtros especificados. No se puede consultar el CRM.")
                resultado['errors'].append(f"No hay seriales para los tipos de dispositivo '{device_types or 'TODOS'}'")
                
                if settings.DEBUG:
                    logger.info("[AYUDA] Verifica que existan dispositivos con ese 'device_type' y 'serial_number_device' no nulo.")
                # No retornar, para que el bloque finally se ejecute correctamente
            
            resultado['seriales']['total'] = len(seriales)
            resultado['seriales']['list'] = seriales[:10]
            
            if not seriales:
                raise Exception("Proceso detenido: no se encontraron seriales para continuar.")

            logger.info(f"[INFO] Se obtuvieron {len(seriales)} seriales únicos y válidos de la base de datos.")
            logger.info(f"[OK] {len(seriales)} seriales a consultar en CRM.")
            
            # PASO 4: Consultar CRM
            logger.info("")
            logger.info("PASO 4/6: Consultando mantenimientos desde CRM...")
            mantenimientos = self.crm_client.get_mantenimientos_by_seriales(seriales)
            
            resultado['crm'] = {
                'seriales_consultados': len(set(seriales)),
                'mantenimientos_obtenidos': len(mantenimientos),
                'timestamp': get_now_gmt5_iso()
            }

            # Métricas adicionales para visibilidad
            seriales_consultados_set = set(seriales)
            seriales_en_respuesta_set = {m.get('serial') for m in mantenimientos if m.get('serial')}
            seriales_sin_resultado = list(seriales_consultados_set - seriales_en_respuesta_set)
            
            resultado['crm']['seriales_con_resultado'] = len(seriales_en_respuesta_set)
            resultado['crm']['seriales_sin_resultado'] = len(seriales_sin_resultado)
            resultado['crm']['list_seriales_sin_resultado'] = seriales_sin_resultado[:20] # Muestra de hasta 20

            logger.info(f"[INFO] De {len(seriales_consultados_set)} seriales consultados, {len(seriales_en_respuesta_set)} retornaron datos.")
            if seriales_sin_resultado:
                logger.warning(f"[AVISO] {len(seriales_sin_resultado)} seriales no retornaron mantenimientos.")
                if settings.DEBUG:
                    logger.debug(f"   Ejemplos de seriales sin resultado: {seriales_sin_resultado[:5]}")
            
            if not mantenimientos:
                logger.warning("[AVISO] No se obtuvieron mantenimientos del CRM para los seriales consultados.")
                resultado['errors'].append("No hay datos de mantenimientos en el CRM para estos seriales")
            
            # PASO 5: Comparar con BD e identificar nuevos
            logger.info("")
            logger.info("PASO 5/6: Comparando con BD para encontrar registros nuevos...")
            
            # Filtrar registros del CRM que tienen los campos clave para la unicidad
            # y que tienen fecha de fin de mantenimiento.
            mantenimientos_validos_crm = [
                m for m in mantenimientos 
                if m.get('nombre_ods') and m.get('reporte') and m.get('observaciones_reporte') and m.get('hora_salida')
            ]
            descartados_sin_campos_clave = len(mantenimientos) - len(mantenimientos_validos_crm)
            
            logger.info(f"Se obtuvieron {len(mantenimientos)} registros del CRM.")
            logger.info(f"Se descartaron {descartados_sin_campos_clave} registros por no tener la combinación (ODS, Reporte, Observaciones) o por no tener fecha de fin.")
            logger.info(f"Se procesarán {len(mantenimientos_validos_crm)} registros válidos.")

            # Obtener las "llaves" únicas de la base de datos
            existing_keys = await self.db_client.get_mantenimientos_existentes()
            logger.info(f"Se encontraron {len(existing_keys)} registros existentes en la BD (basado en ODS, Reporte y Observaciones).")

            # Identificar los mantenimientos nuevos comparando las llaves
            nuevos_mantenimientos_raw = []
            # Usamos un set para manejar eficientemente los registros que vienen del CRM, 
            # en caso de que el propio CRM envíe duplicados en una misma llamada.
            keys_unicas_crm = set()
            for mto in mantenimientos_validos_crm:
                # Construimos la misma llave que en el cliente de la BD
                key = (
                    mto.get('nombre_ods'), 
                    mto.get('reporte'), 
                    mto.get('observaciones_reporte')
                )
                if key not in keys_unicas_crm:
                    keys_unicas_crm.add(key)
                    # Si la llave no existe en la BD, es un registro nuevo
                    if key not in existing_keys:
                        nuevos_mantenimientos_raw.append(mto)

            # Ahora la matemática es más clara:
            # Los registros válidos del CRM se dividen en:
            # 1. Duplicados dentro del propio lote del CRM.
            # 2. Registros que ya existen en la BD.
            # 3. Registros nuevos a insertar.
            duplicados_en_crm = len(mantenimientos_validos_crm) - len(keys_unicas_crm)
            existentes_reales = len(keys_unicas_crm.intersection(existing_keys))

            logger.info(f"Total de registros nuevos a insertar: {len(nuevos_mantenimientos_raw)}")

            resultado['comparacion'] = {
                'registros_obtenidos_crm': len(mantenimientos),
                'registros_descartados_sin_campos_clave': descartados_sin_campos_clave,
                'registros_validos_crm': len(mantenimientos_validos_crm),
                'duplicados_en_crm': duplicados_en_crm,
                'existentes_en_bd': existentes_reales,
                'nuevos_a_insertar': len(nuevos_mantenimientos_raw) # Esto es conceptual, la inserción real puede variar
            }

            # PASO 6: Mapear e insertar solo los nuevos
            logger.info("")
            logger.info("PASO 6/6: Mapeando e insertando registros nuevos...")
            if nuevos_mantenimientos_raw:
                nuevos_mapeados = [self._map_crm_to_db(mto) for mto in nuevos_mantenimientos_raw]
                insert_stats = await self._insertar_en_lotes(nuevos_mapeados)
                
                resultado['database'] = {
                    'total_intentado': len(nuevos_mapeados),
                    'exitosos': insert_stats['insertados'],
                    'errores': insert_stats['errores']
                }
            else:
                logger.info("No hay registros nuevos para insertar.")
                resultado['database'] = {'total_intentado': 0, 'exitosos': 0, 'errores': 0}

            # Obtener estadísticas finales
            logger.info("")
            logger.info("[STATS] Obteniendo estadísticas finales de la tabla mantenimientos...")
            db_stats = await self.db_client.get_stats()
            resultado['database']['stats'] = db_stats
            resultado['success'] = True
            
        except Exception as e:
            logger.error(f"[ERROR] ERROR CRITICO en sincronización: {e}")
            import traceback
            logger.error(traceback.format_exc())
            resultado['errors'].append(str(e))
            resultado['success'] = False
            
        finally:
            end_time_obj = datetime.now(timezone(timedelta(hours=-5)))
            duration = (end_time_obj - start_time_obj).total_seconds()
            
            resultado['end_time'] = end_time_obj.strftime('%Y-%m-%dT%H:%M:%S.%f')
            resultado['duration_seconds'] = duration
            
            # Resumen final
            logger.info("")
            logger.info("=" * 80)
            logger.info("                    RESUMEN FINAL")
            logger.info("=" * 80)
            logger.info(f"Estado: {'[OK] EXITOSO' if resultado['success'] else '[ERROR] FALLIDO'}")
            logger.info(f"Duración: {duration:.2f} segundos")
            logger.info(f"Fin: {end_time_obj.strftime('%Y-%m-%d %H:%M:%S')}")
            
            seriales_total = resultado.get('seriales', {}).get('total', 0)
            crm_obtenidos = resultado.get('crm', {}).get('mantenimientos_obtenidos', 0)
            nuevos = resultado.get('comparacion', {}).get('nuevos_a_insertar', 0)
            insertados = resultado.get('database', {}).get('exitosos', 0)
            
            logger.info(f"Seriales consultados: {seriales_total}")
            logger.info(f"Mantenimientos desde CRM: {crm_obtenidos}")
            logger.info(f"Nuevos a insertar: {nuevos}")
            logger.info(f"Insertados exitosamente: {insertados}")
            if resultado.get('database', {}).get('errores', 0) > 0:
                logger.error(f"Errores en inserción: {resultado['database']['errores']}")
            
            if resultado.get('errors'):
                logger.error(f"Errores: {len(resultado['errors'])}")
                for error in resultado['errors']:
                    logger.error(f"  - {error}")
            
            logger.info("=" * 80)
            logger.info("")
        
        return resultado


def get_sync_service() -> "SyncService":
    """
    Factory function para obtener instancia del servicio de sincronización
    """
    return SyncService()