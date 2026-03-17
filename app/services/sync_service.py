from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone, timedelta
import logging
import asyncio

from .crm_client import get_crm_client, CRMClient
from .database_api_client import get_database_api_client, DatabaseApiClient
from ..config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def get_now_gmt5_iso() -> str:
    gmt5_tz = timezone(timedelta(hours=-5))
    now_gmt5 = datetime.now(gmt5_tz)
    return now_gmt5.strftime('%Y-%m-%dT%H:%M:%S.%f')

class SyncService:
    """
    Servicio de sincronización de mantenimientos.

    FLUJO:
    1. Obtener seriales desde la API de la BD (tabla dispositivos)
    2. Consultar CRM con esos seriales
    3. Consultar API de la BD para obtener IDs y llaves compuestas existentes
    4. Comparar con DOBLE filtro (por ID primero, luego por llave compuesta)
    5. Insertar solo registros nuevos usando ON CONFLICT DO NOTHING como red de seguridad
    """
    
    def __init__(self):
        self.crm_client: CRMClient = get_crm_client()
        self.db_client: DatabaseApiClient = get_database_api_client()
        logger.info("SyncService inicializado")
    
    def _map_crm_to_db(self, mto: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mapea los datos del CRM a los campos de la base de datos.
        """
        mapped = {
            'maintenance_id': mto.get('id_reporte'),
            'ods_name': mto.get('nombre_ods'),
            'maintenance_type': mto.get('tipo_mantenimento'),
            'datetime_ods_create': mto.get('fecha_creacion'),
            'serial': mto.get('serial'),
            'report_id': mto.get('reporte'),
            'datetime_maintenance_end': mto.get('hora_salida'),
            'maintenance_remarks': mto.get('observaciones_reporte'),
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

                if nuevos_insertados > 0:
                    logger.info(f"   [OK] Lote {batch_num}: {nuevos_insertados} registros guardados.")
                else:
                    # Con ON CONFLICT DO NOTHING esto ya no es un error, sino un aviso normal
                    logger.info(f"   [INFO] Lote {batch_num}: 0 registros nuevos (todos eran duplicados ignorados por BD).")

            except Exception as e:
                errores += len(batch)
                logger.error(f"   [ERROR] Error insertando lote {batch_num}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"     [DETALLE_API] Código: {e.response.status_code}, Respuesta: {e.response.text}")
        
        return {'insertados': insertados, 'errores': errores}

    def _filtrar_nuevos(
        self,
        mantenimientos_validos_crm: List[Dict[str, Any]],
        existing: Dict[str, Set]
    ) -> tuple[List[Dict], Dict]:
        """
        [NUEVO] Filtra registros nuevos usando DOBLE capa de deduplicación.

        Capa 1 — Por maintenance_id (PK real):
            Si el id_reporte ya existe en la BD, el registro se descarta sin importar
            qué otros campos tenga. Esto previene el error 409.

        Capa 2 — Por llave compuesta (ods_name, report_id, maintenance_remarks):
            Si el contenido ya existe en la BD (aunque tenga distinto id), también
            se descarta. Evita duplicados de negocio.

        Returns:
            (lista_de_nuevos, dict_con_metricas)
        """
        existing_ids: Set[str] = existing["ids"]
        existing_composite: Set[tuple] = existing["composite_keys"]

        nuevos = []
        keys_vistas_en_este_lote: Set[str] = set()  # Para dedup dentro del propio lote del CRM

        descartados_por_id = 0
        descartados_por_composite = 0
        descartados_por_duplicado_crm = 0

        for mto in mantenimientos_validos_crm:
            mto_id = str(mto.get('id_reporte', '')) if mto.get('id_reporte') else None
            composite_key = (
                mto.get('nombre_ods'),
                mto.get('reporte'),
                mto.get('observaciones_reporte')
            )

            # Dedup dentro del propio lote del CRM (mismo id_reporte repetido)
            if mto_id and mto_id in keys_vistas_en_este_lote:
                descartados_por_duplicado_crm += 1
                continue
            if mto_id:
                keys_vistas_en_este_lote.add(mto_id)

            # CAPA 1: ¿Ya existe el PK en la BD?
            if mto_id and mto_id in existing_ids:
                descartados_por_id += 1
                continue

            # CAPA 2: ¿Ya existe el contenido en la BD?
            if composite_key in existing_composite:
                descartados_por_composite += 1
                continue

            nuevos.append(mto)

        metricas = {
            'descartados_por_id_existente': descartados_por_id,
            'descartados_por_contenido_existente': descartados_por_composite,
            'descartados_por_duplicado_crm': descartados_por_duplicado_crm,
            'nuevos_a_insertar': len(nuevos)
        }

        logger.info(f"[DEDUP] Descartados por maintenance_id ya existente: {descartados_por_id}")
        logger.info(f"[DEDUP] Descartados por contenido ya existente (llave compuesta): {descartados_por_composite}")
        logger.info(f"[DEDUP] Duplicados dentro del propio lote del CRM: {descartados_por_duplicado_crm}")
        logger.info(f"[DEDUP] Registros nuevos a insertar: {len(nuevos)}")

        return nuevos, metricas

    async def sync_mantenimientos(
        self, 
        truncate_first: bool = False,
        seriales: Optional[List[str]] = None,
        device_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta el proceso completo de sincronización de forma asíncrona.
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
        logger.info(f"Estrategia: Insertar solo registros nuevos (deduplicación doble + ON CONFLICT DO NOTHING)")
        logger.info("")
        
        resultado = {
            'success': False,
            'start_time': get_now_gmt5_iso(),
            'end_time': None,
            'duration_seconds': None,
            'seriales': {'source': None, 'total': 0, 'list': []},
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
            logger.info("")
            if truncate_first:
                logger.info("PASO 2/6: Limpiando tabla (TRUNCATE)...")
                await self.db_client.truncate_mantenimientos()
            else:
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
                logger.warning("[AVISO] No se obtuvieron seriales para los filtros especificados.")
                resultado['errors'].append(f"No hay seriales para los tipos de dispositivo '{device_types or 'TODOS'}'")
                raise Exception("Proceso detenido: no se encontraron seriales para continuar.")
            
            resultado['seriales']['total'] = len(seriales)
            resultado['seriales']['list'] = seriales[:10]
            logger.info(f"[OK] {len(seriales)} seriales a consultar en CRM.")
            
            # PASO 4: Consultar CRM
            logger.info("")
            logger.info("PASO 4/6: Consultando mantenimientos desde CRM...")
            mantenimientos = self.crm_client.get_mantenimientos_by_seriales(seriales)
            
            seriales_consultados_set = set(seriales)
            seriales_en_respuesta_set = {m.get('serial') for m in mantenimientos if m.get('serial')}
            seriales_sin_resultado = list(seriales_consultados_set - seriales_en_respuesta_set)
            
            resultado['crm'] = {
                'seriales_consultados': len(seriales_consultados_set),
                'seriales_con_resultado': len(seriales_en_respuesta_set),
                'seriales_sin_resultado': len(seriales_sin_resultado),
                'list_seriales_sin_resultado': seriales_sin_resultado[:20],
                'mantenimientos_obtenidos': len(mantenimientos),
                'timestamp': get_now_gmt5_iso()
            }

            logger.info(f"[INFO] De {len(seriales_consultados_set)} seriales, {len(seriales_en_respuesta_set)} retornaron datos.")
            if seriales_sin_resultado:
                logger.warning(f"[AVISO] {len(seriales_sin_resultado)} seriales no retornaron mantenimientos.")
            
            if not mantenimientos:
                logger.warning("[AVISO] No se obtuvieron mantenimientos del CRM.")
                resultado['errors'].append("No hay datos de mantenimientos en el CRM para estos seriales")
            
            # PASO 5: Comparar con BD — DOBLE CAPA DE DEDUPLICACIÓN
            logger.info("")
            logger.info("PASO 5/6: Comparando con BD (deduplicación por ID + contenido)...")
            
            # Filtrar registros sin campos clave o sin fecha de fin
            mantenimientos_validos_crm = [
                m for m in mantenimientos 
                if m.get('nombre_ods') and m.get('reporte') and m.get('observaciones_reporte') and m.get('hora_salida')
            ]
            descartados_sin_campos_clave = len(mantenimientos) - len(mantenimientos_validos_crm)
            
            logger.info(f"Registros del CRM: {len(mantenimientos)}")
            logger.info(f"Descartados por campos faltantes (sin ODS, Reporte, Observaciones o fecha fin): {descartados_sin_campos_clave}")
            logger.info(f"Registros válidos a comparar: {len(mantenimientos_validos_crm)}")

            # Obtener estado actual de la BD (IDs + llaves compuestas)
            # Pasamos 'seriales' para filtrar la consulta — en lugar de
            # descargar toda la tabla, solo traemos los registros de los
            # equipos que estamos procesando en esta ejecución.
            existing = await self.db_client.get_mantenimientos_existentes(seriales=seriales)

            # Aplicar doble filtro
            nuevos_mantenimientos_raw, metricas_dedup = self._filtrar_nuevos(
                mantenimientos_validos_crm, existing
            )

            resultado['comparacion'] = {
                'registros_obtenidos_crm': len(mantenimientos),
                'registros_descartados_sin_campos_clave': descartados_sin_campos_clave,
                'registros_validos_crm': len(mantenimientos_validos_crm),
                'descartados_por_id_existente': metricas_dedup['descartados_por_id_existente'],
                'descartados_por_contenido_existente': metricas_dedup['descartados_por_contenido_existente'],
                'duplicados_en_crm': metricas_dedup['descartados_por_duplicado_crm'],
                # Mantenemos 'existentes_en_bd' y 'nuevos_a_insertar' para compatibilidad con SyncResponse
                'existentes_en_bd': metricas_dedup['descartados_por_id_existente'] + metricas_dedup['descartados_por_contenido_existente'],
                'nuevos_a_insertar': metricas_dedup['nuevos_a_insertar']
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

            # Estadísticas finales
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
            errores_db = resultado.get('database', {}).get('errores', 0)
            
            logger.info(f"Seriales consultados: {seriales_total}")
            logger.info(f"Mantenimientos desde CRM: {crm_obtenidos}")
            logger.info(f"Nuevos a insertar: {nuevos}")
            logger.info(f"Insertados exitosamente: {insertados}")
            if errores_db > 0:
                logger.error(f"Errores en inserción: {errores_db}")
            
            if resultado.get('errors'):
                logger.error(f"Errores: {len(resultado['errors'])}")
                for error in resultado['errors']:
                    logger.error(f"  - {error}")
            
            logger.info("=" * 80)
            logger.info("")
        
        return resultado


def get_sync_service() -> "SyncService":
    return SyncService()