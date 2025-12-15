from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from services.crm_client import get_crm_client, CRMClient
from services.postgres_client import get_postgres_client, PostgresClient
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SyncService:
    """
    Servicio de sincronización de mantenimientos
    
    FLUJO:
    1. Obtener seriales desde tabla dispositivos
    2. Consultar CRM con esos seriales
    3. Consultar BD para ver qué ya existe
    4. Comparar y filtrar solo los nuevos
    5. Insertar solo registros nuevos (sin UPSERT)
    """
    
    def __init__(self):
        self.crm_client: CRMClient = get_crm_client()
        self.postgres_client: PostgresClient = get_postgres_client()
        logger.info("SyncService inicializado")
    
    def get_seriales_from_dispositivos(self, device_type: str = "Cooling Device") -> List[str]:
        """
        Obtiene lista de seriales desde la tabla dispositivos
        Filtra por device_type = 'Cooling Device'
        
        Args:
            device_type: Tipo de dispositivo a filtrar (default: "Cooling Device")
        
        Returns:
            Lista de seriales
        """
        logger.info("=" * 80)
        logger.info("[INFO] OBTENIENDO SERIALES DESDE TABLA DISPOSITIVOS")
        logger.info("=" * 80)
        logger.info(f"Tabla: monitoreo_equipos.dispositivos")
        logger.info(f"Filtro: device_type = '{device_type}'")
        logger.info(f"Campo serial: serial_number_device")
        
        try:
            # Query para obtener seriales de Cooling Devices
            query = """
            SELECT DISTINCT serial_number_device 
            FROM monitoreo_equipos.dispositivos 
            WHERE device_type = %s
            AND serial_number_device IS NOT NULL 
            AND serial_number_device != ''
            ORDER BY serial_number_device;
            """
            
            logger.debug(f"Ejecutando query:")
            logger.debug(f"  {query}")
            logger.debug(f"  Parámetros: device_type = '{device_type}'")
            
            self.postgres_client.cursor.execute(query, (device_type,))
            results = self.postgres_client.cursor.fetchall()
            
            seriales = [row[0] for row in results if row[0]]
            
            logger.info("")
            logger.info(f"[OK] {len(seriales)} seriales únicos encontrados")
            
            if seriales:
                logger.info(f"[NOTA] Primeros 10 seriales:")
                for i, serial in enumerate(seriales[:10], 1):
                    logger.info(f"   {i}. {serial}")
                if len(seriales) > 10:
                    logger.info(f"   ... y {len(seriales) - 10} más")
            else:
                logger.warning("[AVISO] No se encontraron seriales con los criterios especificados")
            
            logger.info("=" * 80)
            
            return seriales
            
        except Exception as e:
            logger.error(f"[ERROR] Error obteniendo seriales: {e}")
            return []
    
    def get_device_types_disponibles(self) -> List[str]:
        """
        Obtiene lista de tipos de dispositivos disponibles en la tabla
        Útil para debugging
        
        Returns:
            Lista de device_types
        """
        try:
            query = """
            SELECT DISTINCT device_type, COUNT(*) as cantidad
            FROM monitoreo_equipos.dispositivos 
            WHERE device_type IS NOT NULL
            GROUP BY device_type
            ORDER BY cantidad DESC;
            """
            
            self.postgres_client.cursor.execute(query)
            results = self.postgres_client.cursor.fetchall()
            
            logger.info("[INFO] Tipos de dispositivos disponibles:")
            for device_type, cantidad in results:
                logger.info(f"   * {device_type}: {cantidad} dispositivos")
            
            return [row[0] for row in results]
            
        except Exception as e:
            logger.error(f"[ERROR] Error obteniendo tipos de dispositivos: {e}")
            return []
    
    def sync_mantenimientos(
        self, 
        truncate_first: bool = False,
        seriales: Optional[List[str]] = None,
        device_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta el proceso completo de sincronización
        
        FLUJO NUEVO:
        1. Obtener seriales
        2. Consultar CRM
        3. Consultar BD (registros existentes)
        4. Comparar y filtrar nuevos
        5. Insertar solo nuevos
        
        Args:
            truncate_first: Si es True, limpia la tabla antes de insertar
            seriales: Lista opcional de seriales a consultar.
            device_type: Tipo de dispositivo a filtrar (default: "Cooling Device")
            
        Returns:
            Diccionario con resultados de la sincronización
        """
        start_time = datetime.now()
        
        # Device type por defecto
        if device_type is None:
            device_type = settings.DEVICE_TYPE_FILTER if hasattr(settings, 'DEVICE_TYPE_FILTER') else "Cooling Device"
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("         SINCRONIZACION DE MANTENIMIENTOS")
        logger.info("=" * 80)
        logger.info(f"Inicio: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Tabla origen: monitoreo_equipos.dispositivos")
        logger.info(f"Tabla destino: monitoreo_equipos.mantenimientos")
        logger.info(f"Filtro dispositivos: device_type = '{device_type}'")
        logger.info(f"Estrategia: Comparar CRM vs BD e insertar solo nuevos")
        logger.info("")
        
        resultado = {
            'success': False,
            'start_time': start_time.isoformat(),
            'end_time': None,
            'duration_seconds': None,
            'dispositivos': {
                'device_type_filter': device_type,
                'source': None,
                'total': 0,
                'list': []
            },
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
            # PASO 1: Conectar a PostgreSQL
            logger.info("PASO 1/7: Conectando a PostgreSQL...")
            self.postgres_client.connect()
            
            # PASO 2: Verificar que la tabla mantenimientos existe
            logger.info("")
            logger.info("PASO 2/7: Verificando tabla de destino...")
            self.postgres_client.verify_table_exists()
            
            # Opcional: Mostrar tipos de dispositivos disponibles
            if settings.DEBUG:
                logger.info("")
                logger.info("DEBUG: Tipos de dispositivos en tabla dispositivos:")
                self.get_device_types_disponibles()
            
            # PASO 3: Truncar si se solicita
            if truncate_first:
                logger.info("")
                logger.info("PASO 3/7: Limpiando tabla (TRUNCATE)...")
                logger.warning("[AVISO] ADVERTENCIA: Se eliminará todo el contenido de la tabla mantenimientos")
                self.postgres_client.truncate_table()
            else:
                logger.info("")
                logger.info("PASO 3/7: Omitiendo truncate...")
                logger.info("   * Se insertarán solo registros nuevos")
                logger.info("   * Los registros existentes NO se modificarán")
            
            # PASO 4: Obtener lista de seriales
            logger.info("")
            logger.info("PASO 4/7: Obteniendo lista de seriales...")
            
            if seriales is None:
                # Obtener seriales desde tabla dispositivos
                seriales = self.get_seriales_from_dispositivos(device_type=device_type)
                resultado['seriales']['source'] = f'PostgreSQL (dispositivos - {device_type})'
                resultado['dispositivos']['source'] = 'tabla dispositivos'
            else:
                resultado['seriales']['source'] = 'Parámetro del request'
                resultado['dispositivos']['source'] = 'request body'
                logger.info(f"[OK] Usando seriales proporcionados en el request: {len(seriales)}")
            
            if not seriales:
                logger.warning("[AVISO] No se obtuvieron seriales. No se puede consultar el CRM.")
                resultado['errors'].append(f"No hay seriales de tipo '{device_type}' para consultar")
                
                if settings.DEBUG:
                    logger.info("")
                    logger.info("[AYUDA] SUGERENCIAS:")
                    logger.info("   1. Verifica que existan dispositivos con device_type = 'Cooling Device'")
                    logger.info("   2. Verifica que tengan serial_number_device no nulo")
                    logger.info("   3. Puedes enviar seriales manualmente en el request")
                
                return resultado
            
            resultado['seriales']['total'] = len(seriales)
            resultado['seriales']['list'] = seriales[:10]
            resultado['dispositivos']['total'] = len(seriales)
            resultado['dispositivos']['device_type_filter'] = device_type
            
            logger.info(f"")
            logger.info(f"[OK] {len(seriales)} seriales a consultar en CRM")
            
            # PASO 5: Consultar CRM
            logger.info("")
            logger.info("PASO 5/7: Consultando mantenimientos desde CRM...")
            mantenimientos = self.crm_client.get_mantenimientos_by_seriales(seriales)
            
            resultado['crm'] = {
                'seriales_consultados': len(seriales),
                'mantenimientos_obtenidos': len(mantenimientos),
                'timestamp': datetime.now().isoformat()
            }
            
            if not mantenimientos:
                logger.warning("[AVISO] No se obtuvieron mantenimientos del CRM para estos seriales")
                logger.info("   Posibles causas:")
                logger.info("   * Los equipos no tienen mantenimientos registrados en el CRM")
                logger.info("   * Los seriales no coinciden con los del CRM")
                resultado['errors'].append("No hay datos de mantenimientos en el CRM para estos seriales")
                # No retornar aquí, continuar con stats
            
            # PASO 6: Consultar registros existentes en BD y comparar
            logger.info("")
            if mantenimientos:
                logger.info("PASO 6/7: Consultando registros existentes en BD...")
                existing_keys = self.postgres_client.get_existing_keys()
                
                resultado['comparacion'] = {
                    'registros_existentes_bd': len(existing_keys),
                    'registros_desde_crm': len(mantenimientos),
                    'timestamp': datetime.now().isoformat()
                }
                
                # PASO 7: Insertar solo los nuevos
                logger.info("")
                logger.info("PASO 7/7: Insertando solo registros nuevos...")
                insert_stats = self.postgres_client.insert_mantenimientos_nuevos(
                    mantenimientos, 
                    existing_keys
                )
                resultado['database'] = insert_stats
            else:
                logger.info("PASO 6/7: Omitiendo consulta de existentes (sin datos del CRM)")
                logger.info("PASO 7/7: Omitiendo inserción (sin datos del CRM)")
                resultado['database'] = {
                    'total': 0,
                    'insertados': 0,
                    'duplicados': 0,
                    'errores': 0,
                    'exitosos': 0
                }
            
            # Obtener estadísticas finales
            logger.info("")
            logger.info("[STATS] Obteniendo estadísticas finales de la tabla mantenimientos...")
            db_stats = self.postgres_client.get_stats()
            
            if db_stats:
                logger.info("")
                logger.info("=" * 80)
                logger.info("[REPORTE] ESTADISTICAS DE LA TABLA monitoreo_equipos.mantenimientos:")
                logger.info(f"   * Total de registros: {db_stats.get('total_registros', 0)}")
                logger.info(f"   * Dispositivos únicos: {db_stats.get('dispositivos_unicos', 0)}")
                logger.info(f"   * Clientes únicos: {db_stats.get('clientes_unicos', 0)}")
                if db_stats.get('primer_mantenimiento'):
                    logger.info(f"   * Primer mantenimiento: {db_stats.get('primer_mantenimiento')}")
                if db_stats.get('ultimo_mantenimiento'):
                    logger.info(f"   * Último mantenimiento: {db_stats.get('ultimo_mantenimiento')}")
                logger.info("=" * 80)
            
            resultado['database']['stats'] = db_stats
            resultado['success'] = True
            
        except Exception as e:
            logger.error(f"[ERROR] ERROR CRITICO en sincronización: {e}")
            resultado['errors'].append(str(e))
            resultado['success'] = False
            
        finally:
            # Siempre cerrar la conexión
            self.postgres_client.disconnect()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            resultado['end_time'] = end_time.isoformat()
            resultado['duration_seconds'] = duration
            
            # Resumen final
            logger.info("")
            logger.info("=" * 80)
            logger.info("                    RESUMEN FINAL")
            logger.info("=" * 80)
            logger.info(f"Estado: {'[OK] EXITOSO' if resultado['success'] else '[ERROR] FALLIDO'}")
            logger.info(f"Duración: {duration:.2f} segundos")
            logger.info(f"Fin: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if resultado.get('dispositivos'):
                disp = resultado['dispositivos']
                logger.info(f"Dispositivos: {disp['total']} de tipo '{disp['device_type_filter']}' (fuente: {disp['source']})")
            
            if resultado.get('seriales'):
                logger.info(f"Seriales: {resultado['seriales']['total']} consultados")
            
            if resultado.get('crm'):
                crm = resultado['crm']
                logger.info(f"CRM: {crm.get('mantenimientos_obtenidos', 0)} mantenimientos obtenidos")
            
            if resultado.get('comparacion'):
                comp = resultado['comparacion']
                logger.info(f"BD antes: {comp.get('registros_existentes_bd', 0)} registros existentes")
            
            if resultado.get('database'):
                db = resultado['database']
                logger.info(f"Resultado: {db.get('insertados', 0)} nuevos insertados, " +
                           f"{db.get('duplicados', 0)} ya existían")
            
            if resultado.get('errors'):
                logger.error(f"Errores: {len(resultado['errors'])}")
                for error in resultado['errors']:
                    logger.error(f"  - {error}")
            
            logger.info("=" * 80)
            logger.info("")
        
        return resultado


def get_sync_service() -> SyncService:
    """
    Factory function para obtener instancia del servicio de sincronización
    """
    return SyncService()