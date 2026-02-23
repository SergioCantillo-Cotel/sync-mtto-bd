import requests
import urllib3
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import time
from ..config.settings import get_settings

# Deshabilitar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
settings = get_settings()


class CRMClient:
    """
    Cliente para interactuar con el API del CRM Cotel
    El endpoint de mantenimientos requiere una lista de seriales
    """
    
    def __init__(self):
        self.base_url = settings.CRM_BASE_URL
        self.client_id = settings.CRM_CLIENT_ID
        self.client_secret = settings.CRM_CLIENT_SECRET
        self.timeout = settings.CRM_TIMEOUT
        
        # Token
        self.access_token = None
        self.token_expiry = None
        
        # Endpoints específicos del CRM Cotel
        self.token_url = f"{self.base_url}/crm/Api/access_token"
        self.equipos_url = f"{self.base_url}/crm/Api/V8/custom/IA/equipos-info"
        
        # Headers específicos del CRM Cotel
        self.base_headers = {
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json"
        }
        
        logger.info(f"CRMClient inicializado")
        logger.info(f"  Base URL: {self.base_url}")
        logger.info(f"  Token URL: {self.token_url}")
        logger.info(f"  Equipos URL: {self.equipos_url}")
    
    def get_access_token(self) -> str:
        """
        Obtiene un nuevo token de acceso usando las credenciales
        
        Returns:
            Token de acceso
            
        Raises:
            Exception: Si no se puede obtener el token
        """
        logger.info("[AUTH] Obteniendo token del CRM...")
        
        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            
            logger.debug(f"[REQUEST] POST {self.token_url}")
            logger.debug(f"   Grant type: client_credentials")
            logger.debug(f"   Client ID: {self.client_id}")
            
            response = requests.post(
                self.token_url,
                json=data,
                headers=self.base_headers,
                verify=False,  # SSL verification disabled
                timeout=self.timeout
            )
            
            logger.info(f"[RESPONSE] Status Code: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"[ERROR] Error Response: {response.text[:500]}")
                response.raise_for_status()
            
            tokens = response.json()
            logger.debug(f"   Response keys: {list(tokens.keys())}")
            
            self.access_token = tokens.get('access_token')
            
            if not self.access_token:
                raise ValueError(f"No se recibió access_token. Campos disponibles: {list(tokens.keys())}")
            
            # Establecer tiempo de expiración (1 hora por defecto)
            self.token_expiry = time.time() + 3600
            
            logger.info("[OK] Token obtenido exitosamente")
            logger.debug(f"   Token (últimos 10 chars): ...{self.access_token[-10:]}")
            logger.debug(f"   Expira en: 3600 segundos (1 hora)")
            
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] Error obteniendo token del CRM: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   Status: {e.response.status_code}")
                logger.error(f"   Response: {e.response.text[:500]}")
            raise Exception(f"Error de autenticación con CRM: {str(e)}")
            
        except Exception as e:
            logger.error(f"[ERROR] Error inesperado: {e}")
            raise
    
    def is_token_valid(self) -> bool:
        """
        Verifica si el token actual es válido
        
        Returns:
            True si el token es válido, False si no
        """
        if not self.access_token or not self.token_expiry:
            return False
        # 5 minutos de margen antes de expiración
        return time.time() < self.token_expiry - 300
    
    def ensure_valid_token(self) -> str:
        """
        Garantiza que tenemos un token válido
        
        Returns:
            Token válido
        """
        if not self.is_token_valid():
            logger.debug("Token expirado o no válido, obteniendo nuevo...")
            self.access_token = self.get_access_token()
        
        return self.access_token
    
    def get_mantenimientos_by_seriales(self, seriales: List[str]) -> List[Dict[str, Any]]:
        """
        Obtiene información de mantenimientos por números de serie
        
        Args:
            seriales: Lista de números de serie a consultar
            
        Returns:
            Lista de mantenimientos
            
        Raises:
            Exception: Si falla la consulta
        """
        logger.info("=" * 80)
        logger.info("[RESPONSE] CONSULTANDO MANTENIMIENTOS POR SERIALES")
        logger.info("=" * 80)
        
        try:
            token = self.ensure_valid_token()
            
            headers = self.base_headers.copy()
            headers["Authorization"] = f"Bearer {token}"
            
            # Convertir a lista si es necesario
            if hasattr(seriales, 'tolist'):
                seriales_list = seriales.tolist()
            else:
                seriales_list = list(seriales)
            
            data = {
                "seriales": seriales_list
            }
            
            logger.info(f"[QUERY] Consultando {len(seriales_list)} seriales")
            logger.debug(f"   Seriales: {seriales_list[:5]}..." if len(seriales_list) > 5 else f"   Seriales: {seriales_list}")
            logger.info(f"[WEB] POST {self.equipos_url}")
            logger.debug(f"[REQUEST] Headers: Authorization: Bearer ...{token[-10:]}")
            
            response = requests.post(
                self.equipos_url,
                json=data,
                headers=headers,
                verify=False,
                timeout=self.timeout
            )
            
            logger.info(f"[RESPONSE] Status Code: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"[ERROR] Error Response: {response.text[:500]}")
                response.raise_for_status()
            
            response_data = response.json()
            
            # Extraer datos
            mantenimientos = []
            
            if isinstance(response_data, dict):
                if 'data' in response_data:
                    mantenimientos = response_data['data']
                    logger.info(f"[OK] Mantenimientos extraídos del campo 'data'")
                else:
                    logger.warning(f"[AVISO] Respuesta no contiene campo 'data'")
                    logger.debug(f"   Campos disponibles: {list(response_data.keys())}")
                    mantenimientos = [response_data]
            elif isinstance(response_data, list):
                mantenimientos = response_data
                logger.info(f"[OK] Respuesta es lista directa")
            else:
                logger.warning(f"[AVISO] Formato inesperado: {type(response_data)}")
                mantenimientos = []
            
            logger.info(f"")
            logger.info(f"[STATS] RESUMEN DE CONSULTA:")
            logger.info(f"   * Seriales consultados: {len(seriales_list)}")
            logger.info(f"   * Mantenimientos obtenidos: {len(mantenimientos)}")
            logger.info(f"   * Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"")
            
            if mantenimientos and len(mantenimientos) > 0:
                logger.info(f"[NOTA] Ejemplo del primer mantenimiento:")
                primer_mto = mantenimientos[0]
                if isinstance(primer_mto, dict):
                    logger.info(f"   * Campos disponibles: {list(primer_mto.keys())}")
                    for key, value in list(primer_mto.items())[:5]:
                        logger.info(f"   * {key}: {value}")
                    if len(primer_mto) > 5:
                        logger.info(f"   * ... y {len(primer_mto) - 5} campos más")
            
            logger.info("=" * 80)
            
            return mantenimientos
            
        except requests.exceptions.Timeout:
            logger.error(f"[ERROR] Timeout consultando CRM (>{self.timeout}s)")
            raise Exception("Timeout al consultar el CRM")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] Error en request al CRM: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   Status: {e.response.status_code}")
                logger.error(f"   Respuesta: {e.response.text[:500]}")
            raise Exception(f"Error consultando mantenimientos: {str(e)}")
            
        except Exception as e:
            logger.error(f"[ERROR] Error inesperado: {e}")
            raise
    
    def get_mantenimientos(self, seriales: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Obtiene mantenimientos del CRM
        
        Args:
            seriales: Lista opcional de seriales a consultar.
                     Si no se proporciona, se deberá obtener de otra fuente.
            
        Returns:
            Lista de mantenimientos
        """
        if seriales is None:
            logger.warning("[AVISO] No se proporcionaron seriales. No se puede consultar el CRM.")
            logger.warning("[AVISO] El endpoint equipos-info requiere una lista de seriales.")
            return []
        
        return self.get_mantenimientos_by_seriales(seriales)
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Prueba la conexión con el CRM
        
        Returns:
            Diccionario con resultados de la prueba
        """
        result = {
            'base_url': self.base_url,
            'token_url': self.token_url,
            'equipos_url': self.equipos_url,
            'auth_success': False,
            'auth_error': None,
            'token_preview': None
        }
        
        # Probar autenticación
        try:
            token = self.get_access_token()
            result['auth_success'] = True
            result['token_preview'] = f"...{token[-10:]}"
        except Exception as e:
            result['auth_error'] = str(e)
        
        return result


def get_crm_client() -> CRMClient:
    """
    Factory function para obtener instancia del cliente CRM
    """
    return CRMClient()