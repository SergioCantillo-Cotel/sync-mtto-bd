#!/usr/bin/env python3
"""
Script de prueba para el Sync Mantenimientos Service
"""

import requests
import json
import time
from datetime import datetime


BASE_URL = "http://localhost:8001"


def print_header(text):
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)


def print_result(success, message):
    icon = "✅" if success else "❌"
    print(f"{icon} {message}")


def test_root():
    """Test endpoint raíz"""
    print_header("TEST 1: Endpoint Raíz")
    
    try:
        response = requests.get(f"{BASE_URL}/")
        response.raise_for_status()
        data = response.json()
        
        print(f"Status Code: {response.status_code}")
        print(f"Response:")
        print(json.dumps(data, indent=2))
        
        print_result(True, "Endpoint raíz funcionando")
        return True
        
    except Exception as e:
        print_result(False, f"Error: {str(e)}")
        return False


def test_health():
    """Test health check"""
    print_header("TEST 2: Health Check")
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        response.raise_for_status()
        data = response.json()
        
        print(f"Status Code: {response.status_code}")
        print(f"Response:")
        print(json.dumps(data, indent=2))
        
        is_healthy = data.get('status') == 'healthy'
        db_connected = data.get('database_connected', False)
        crm_configured = data.get('crm_configured', False)
        
        print(f"\nEstado: {data.get('status')}")
        print(f"Base de datos: {'✅ Conectada' if db_connected else '❌ No conectada'}")
        print(f"CRM: {'✅ Configurado' if crm_configured else '❌ No configurado'}")
        
        print_result(is_healthy, "Health check completado")
        return is_healthy
        
    except Exception as e:
        print_result(False, f"Error: {str(e)}")
        return False


def test_status():
    """Test endpoint de estado"""
    print_header("TEST 3: Estado de Sincronización")
    
    try:
        response = requests.get(f"{BASE_URL}/sync/status")
        response.raise_for_status()
        data = response.json()
        
        print(f"Status Code: {response.status_code}")
        print(f"Response:")
        print(json.dumps(data, indent=2))
        
        stats = data.get('statistics', {})
        print(f"\nEstadísticas actuales:")
        print(f"  • Total de registros: {stats.get('total_registros', 0)}")
        print(f"  • Dispositivos únicos: {stats.get('dispositivos_unicos', 0)}")
        print(f"  • Clientes únicos: {stats.get('clientes_unicos', 0)}")
        
        print_result(True, "Estado obtenido correctamente")
        return True
        
    except Exception as e:
        print_result(False, f"Error: {str(e)}")
        return False


def test_sync(truncate_first=False):
    """Test sincronización"""
    mode = "TRUNCATE + INSERT" if truncate_first else "UPSERT"
    print_header(f"TEST 4: Sincronización (Modo: {mode})")
    
    try:
        payload = {"truncate_first": truncate_first}
        
        print(f"Enviando request...")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        print(f"\n⏳ Esperando respuesta (esto puede tomar varios minutos)...\n")
        
        start_time = time.time()
        
        response = requests.post(
            f"{BASE_URL}/sync/mantenimientos",
            json=payload,
            timeout=600  # 10 minutos
        )
        
        elapsed_time = time.time() - start_time
        
        response.raise_for_status()
        data = response.json()
        
        print(f"Status Code: {response.status_code}")
        print(f"Tiempo de respuesta: {elapsed_time:.2f} segundos")
        print(f"\nResponse:")
        print(json.dumps(data, indent=2))
        
        success = data.get('success', False)
        
        if success:
            crm_stats = data.get('crm', {})
            db_stats = data.get('database', {})
            
            print(f"\n📊 Resumen:")
            print(f"  • Duración: {data.get('duration_seconds', 0):.2f}s")
            print(f"  • CRM: {crm_stats.get('total_consultado', 0)} registros")
            print(f"  • DB: {db_stats.get('exitosos', 0)}/{db_stats.get('total', 0)} exitosos")
            print(f"    - Insertados: {db_stats.get('insertados', 0)}")
            print(f"    - Actualizados: {db_stats.get('actualizados', 0)}")
            print(f"    - Errores: {db_stats.get('errores', 0)}")
            
            print_result(True, "Sincronización exitosa")
        else:
            errors = data.get('errors', [])
            print(f"\n❌ Errores:")
            for error in errors:
                print(f"  - {error}")
            
            print_result(False, "Sincronización fallida")
        
        return success
        
    except requests.exceptions.Timeout:
        print_result(False, "Timeout - La sincronización está tomando demasiado tiempo")
        return False
        
    except Exception as e:
        print_result(False, f"Error: {str(e)}")
        return False


def main():
    """Ejecuta todos los tests"""
    print("\n")
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║     Sync Mantenimientos Service - Suite de Pruebas       ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print(f"\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Base URL: {BASE_URL}")
    
    results = []
    
    # Test 1: Root
    results.append(("Root", test_root()))
    time.sleep(1)
    
    # Test 2: Health
    results.append(("Health", test_health()))
    time.sleep(1)
    
    # Test 3: Status
    results.append(("Status", test_status()))
    time.sleep(1)
    
    # Test 4: Sync (preguntar al usuario)
    print("\n" + "=" * 80)
    run_sync = input("¿Deseas ejecutar la sincronización? (s/n): ").lower()
    
    if run_sync == 's':
        truncate = input("¿Limpiar tabla antes de insertar? (s/n): ").lower()
        results.append(("Sync", test_sync(truncate_first=(truncate == 's'))))
    else:
        print("⏭️  Sincronización omitida")
    
    # Resumen final
    print_header("RESUMEN FINAL")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        icon = "✅" if success else "❌"
        print(f"{icon} {test_name}")
    
    print(f"\nResultado: {passed}/{total} tests pasados")
    
    if passed == total:
        print("\n✅ TODOS LOS TESTS PASARON")
        return 0
    else:
        print(f"\n❌ {total - passed} TEST(S) FALLARON")
        return 1


if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrumpidos por el usuario")
        exit(1)
