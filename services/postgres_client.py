import psycopg2
from psycopg2 import sql, extras
from typing import List, Dict, Any, Set, Tuple
from datetime import datetime
import logging
import uuid
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PostgresClient:
    """
    Cliente para interactuar con PostgreSQL
    Usa tabla existente: monitoreo_equipos.mantenimientos
    Estrategia: INSERT simple de registros nuevos (sin UPSERT)
    """
    
    def __init__(self):
        self.connection_params = {
            'host': settings.DB_HOST,
            'port': settings.DB_PORT,
            'database': settings.DB_NAME,
            'user': settings.DB_USER,
            'password': settings.DB_PASSWORD
        }
        self.conn = None
        self.cursor = None
        
        # Configuración de la tabla existente
        self.schema = "monitoreo_equipos"
        self.table = "mantenimientos"
        self.full_table_name = f"{self.schema}.{self.table}"
        
        logger.info(f"PostgresClient inicializado - Tabla: {self.full_table_name}")
        logger.info(f"  Estrategia: Comparar CRM vs BD e insertar solo nuevos")
    
    def connect(self):
        """
        Establece conexión con PostgreSQL
        
        Raises:
            Exception: Si no se puede conectar
        """
        try:
            logger.info(f"[CONEXION] Conectando a PostgreSQL...")
            logger.info(f"   Host: {settings.DB_HOST}:{settings.DB_PORT}")
            logger.info(f"   Database: {settings.DB_NAME}")
            logger.info(f"   User: {settings.DB_USER}")
            logger.info(f"   Tabla: {self.full_table_name}")
            
            self.conn = psycopg2.connect(**self.connection_params)
            self.cursor = self.conn.cursor()
            
            # Verificar conexión
            self.cursor.execute("SELECT version();")
            version = self.cursor.fetchone()
            
            logger.info(f"[OK] Conexión exitosa a PostgreSQL")
            logger.debug(f"   Versión: {version[0][:50]}...")
            
        except psycopg2.Error as e:
            logger.error(f"[ERROR] Error conectando a PostgreSQL: {e}")
            raise Exception(f"Error de conexión a base de datos: {str(e)}")
    
    def disconnect(self):
        """
        Cierra conexión con PostgreSQL
        """
        try:
            if self.cursor:
                self.cursor.close()
            if self.conn:
                self.conn.close()
            logger.info("[CERRADO] Conexión a PostgreSQL cerrada")
        except Exception as e:
            logger.error(f"[ERROR] Error cerrando conexión: {e}")
    
    def verify_table_exists(self):
        """
        Verifica que la tabla existe
        
        Raises:
            Exception: Si la tabla no existe
        """
        try:
            logger.info(f"[VERIFICACION] Verificando tabla {self.full_table_name}...")
            
            # Verificar que la tabla existe
            query = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = %s 
                AND table_name = %s
            );
            """
            
            self.cursor.execute(query, (self.schema, self.table))
            exists = self.cursor.fetchone()[0]
            
            if not exists:
                raise Exception(f"La tabla {self.full_table_name} no existe")
            
            logger.info(f"[OK] Tabla {self.full_table_name} encontrada")
            
            # Verificar columnas
            column_query = """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = %s 
            AND table_name = %s
            ORDER BY ordinal_position;
            """
            
            self.cursor.execute(column_query, (self.schema, self.table))
            columns = self.cursor.fetchall()
            
            logger.info(f"[INFO] Columnas de la tabla:")
            for col_name, col_type in columns:
                logger.info(f"   * {col_name}: {col_type}")
            
        except psycopg2.Error as e:
            logger.error(f"[ERROR] Error verificando tabla: {e}")
            raise Exception(f"Error verificando estructura de tabla: {str(e)}")
    
    def truncate_table(self):
        """
        Limpia completamente la tabla de mantenimientos
        
        [AVISO] CUIDADO: Esta operación es irreversible
        """
        try:
            logger.warning(f"[AVISO] TRUNCANDO tabla {self.full_table_name}...")
            
            # Usar CASCADE por si hay foreign keys
            query = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE;").format(
                sql.Identifier(self.schema, self.table)
            )
            
            self.cursor.execute(query)
            self.conn.commit()
            
            logger.info("[OK] Tabla truncada exitosamente")
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"[ERROR] Error truncando tabla: {e}")
            raise Exception(f"Error limpiando tabla: {str(e)}")
    
    def get_existing_keys(self) -> Set[Tuple[str, str]]:
        """
        Obtiene las combinaciones existentes de (report_id, maintenance_remarks) de la BD
        
        Returns:
            Set de tuplas (report_id, maintenance_remarks)
        """
        try:
            logger.info("[QUERY] Consultando registros existentes en BD...")
            
            query = sql.SQL("""
            SELECT report_id, maintenance_remarks
            FROM {table}
            WHERE report_id IS NOT NULL 
            AND maintenance_remarks IS NOT NULL;
            """).format(
                table=sql.Identifier(self.schema, self.table)
            )
            
            self.cursor.execute(query)
            results = self.cursor.fetchall()
            
            # Crear set de tuplas para búsqueda rápida
            existing_keys = {(row[0], row[1]) for row in results}
            
            logger.info(f"[OK] {len(existing_keys)} registros existentes en BD")
            logger.debug(f"   Primeros 5: {list(existing_keys)[:5]}")
            
            return existing_keys
            
        except psycopg2.Error as e:
            logger.error(f"[ERROR] Error consultando registros existentes: {e}")
            return set()
    
    def _map_crm_to_db(self, mto: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mapea los datos del CRM a los campos de la base de datos
        
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
    
    def insert_mantenimientos_nuevos(
        self, 
        mantenimientos: List[Dict[str, Any]],
        existing_keys: Set[Tuple[str, str]]
    ) -> Dict[str, int]:
        """
        Inserta solo los mantenimientos NUEVOS (que no existen en BD)
        Compara con existing_keys para determinar qué insertar
        
        Args:
            mantenimientos: Lista de mantenimientos del CRM
            existing_keys: Set de (report_id, maintenance_remarks) existentes en BD
            
        Returns:
            Diccionario con estadísticas de inserción
        """
        logger.info("=" * 80)
        logger.info("[GUARDANDO] INSERTANDO SOLO REGISTROS NUEVOS")
        logger.info("=" * 80)
        
        total = len(mantenimientos)
        insertados = 0
        duplicados = 0
        errores = 0
        batch_size = settings.BATCH_SIZE
        
        try:
            logger.info(f"[STATS] Configuración de inserción:")
            logger.info(f"   * Tabla: {self.full_table_name}")
            logger.info(f"   * Total desde CRM: {total}")
            logger.info(f"   * Existentes en BD: {len(existing_keys)}")
            logger.info(f"   * Tamaño de lote: {batch_size}")
            logger.info("")
            
            # Filtrar solo los nuevos
            nuevos = []
            for mto in mantenimientos:
                mapped = self._map_crm_to_db(mto)
                
                # Validar campos clave
                report_id = mapped.get('report_id')
                maintenance_remarks = mapped.get('maintenance_remarks')
                
                if not report_id or not maintenance_remarks:
                    errores += 1
                    logger.debug(f"   [SKIP] Sin report_id o maintenance_remarks")
                    continue
                
                # Verificar si ya existe
                key = (report_id, maintenance_remarks)
                if key in existing_keys:
                    duplicados += 1
                    logger.debug(f"   [DUPLICADO] {report_id} - {maintenance_remarks[:30]}...")
                    continue
                
                # Es nuevo, agregar a lista
                nuevos.append(mapped)
            
            logger.info("")
            logger.info(f"[FILTRADO] Resumen de comparación:")
            logger.info(f"   * Total del CRM: {total}")
            logger.info(f"   * Ya existen en BD: {duplicados}")
            logger.info(f"   * Con errores/incompletos: {errores}")
            logger.info(f"   * NUEVOS a insertar: {len(nuevos)}")
            logger.info("")
            
            if not nuevos:
                logger.info("[INFO] No hay registros nuevos para insertar")
                return {
                    'total': total,
                    'insertados': 0,
                    'duplicados': duplicados,
                    'errores': errores,
                    'exitosos': 0
                }
            
            # Insertar en lotes
            total_batches = (len(nuevos) + batch_size - 1) // batch_size
            logger.info(f"[INFO] Insertando en {total_batches} lotes...")
            logger.info("")
            
            for i in range(0, len(nuevos), batch_size):
                batch = nuevos[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                
                logger.info(f"[LOTE] Procesando lote {batch_num}/{total_batches} ({len(batch)} registros)...")
                
                for idx, mapped_data in enumerate(batch, 1):
                    try:
                        # INSERT simple (sin ON CONFLICT)
                        insert_query = sql.SQL("""
                        INSERT INTO {table} (
                            maintenance_id, ods_name, maintenance_type, device_id, device_name,
                            device_brand, device_model, device_type, datetime_ods_create,
                            serial, report_id, datetime_maintenance_end, maintenance_remarks,
                            report_status, nit, customer_name
                        ) VALUES (
                            %(maintenance_id)s, %(ods_name)s, %(maintenance_type)s, %(device_id)s, %(device_name)s,
                            %(device_brand)s, %(device_model)s, %(device_type)s, %(datetime_ods_create)s,
                            %(serial)s, %(report_id)s, %(datetime_maintenance_end)s, %(maintenance_remarks)s,
                            %(report_status)s, %(nit)s, %(customer_name)s
                        );
                        """).format(
                            table=sql.Identifier(self.schema, self.table)
                        )
                        
                        self.cursor.execute(insert_query, mapped_data)
                        insertados += 1
                        
                        # Log progreso cada 10 registros
                        if idx % 10 == 0:
                            logger.debug(f"    Insertados {idx}/{len(batch)} del lote actual")
                    
                    except psycopg2.Error as e:
                        errores += 1
                        logger.error(f"   [ERROR] Error insertando registro {i + idx}")
                        logger.error(f"   [ERROR] report_id: {mapped_data.get('report_id', 'N/A')}")
                        logger.error(f"   [ERROR] Mensaje: {str(e)[:200]}")
                        self.conn.rollback()
                        continue
                
                # Commit del lote
                self.conn.commit()
                logger.info(f"   [OK] Lote {batch_num} insertado y commiteado")
                logger.info("")
            
            # Resumen final
            logger.info("=" * 80)
            logger.info("[STATS] RESUMEN DE INSERCION:")
            logger.info(f"   * Total del CRM: {total}")
            logger.info(f"   * Ya existían: {duplicados}")
            logger.info(f"   * [OK] Insertados: {insertados}")
            logger.info(f"   * [ERROR] Errores: {errores}")
            logger.info(f"   * Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 80)
            
            return {
                'total': total,
                'insertados': insertados,
                'duplicados': duplicados,
                'errores': errores,
                'exitosos': insertados
            }
            
        except Exception as e:
            self.conn.rollback()
            logger.error(f"[ERROR] Error crítico en inserción: {e}")
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de la tabla de mantenimientos
        
        Returns:
            Diccionario con estadísticas
        """
        try:
            stats_query = sql.SQL("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT serial) as dispositivos_unicos,
                COUNT(DISTINCT customer_name) as clientes_unicos,
                MIN(datetime_maintenance_end) as primer_mantenimiento,
                MAX(datetime_maintenance_end) as ultimo_mantenimiento
            FROM {table};
            """).format(
                table=sql.Identifier(self.schema, self.table)
            )
            
            self.cursor.execute(stats_query)
            result = self.cursor.fetchone()
            
            return {
                'total_registros': result[0],
                'dispositivos_unicos': result[1],
                'clientes_unicos': result[2],
                'primer_mantenimiento': result[3],
                'ultimo_mantenimiento': result[4]
            }
            
        except psycopg2.Error as e:
            logger.error(f"[ERROR] Error obteniendo estadísticas: {e}")
            return {}


def get_postgres_client() -> PostgresClient:
    """
    Factory function para obtener instancia del cliente PostgreSQL
    """
    return PostgresClient()