import sys
import os
import io
import traceback
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para Windows (evita errores con caracteres especiales)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QFile, QTextStream
from PyQt5.QtGui import QFont
from View.view import EditorView
from Controller.editor_controller import EditorController

def excepthook(type, value, tb):
    print("="*50)
    print("EXCEPCIÓN NO CAPTURADA:")
    print(f"Tipo: {type.__name__}")
    print(f"Valor: {value}")
    print("\nTraceback:")
    traceback.print_tb(tb)
    print("="*50)

def cargar_estilos(app, ruta_estilos):
    """Carga la hoja de estilos QSS desde un archivo - VERSIÓN MEJORADA para Windows"""
    try:
        # Convertir a Path para manejo multiplataforma
        ruta = Path(ruta_estilos)
        
        # Verificar si el archivo existe
        if not ruta.exists():
            print(f"ADVERTENCIA: No se encontró {ruta_estilos}")
            print(f"Buscando en rutas alternativas...")
            
            # Intentar rutas alternativas comunes en Windows
            rutas_alternativas = [
                Path.cwd() / "Static" / "Scripts" / "estilos.qss",
                Path.cwd() / "estilos.qss",
                Path(__file__).parent / "Static" / "Scripts" / "estilos.qss",
                Path(sys.executable).parent / "Static" / "Scripts" / "estilos.qss"
            ]
            
            for alt_ruta in rutas_alternativas:
                if alt_ruta.exists():
                    ruta = alt_ruta
                    print(f"Encontrado en: {alt_ruta}")
                    break
        
        if not ruta.exists():
            print(f"ERROR: No se pudo encontrar el archivo de estilos")
            return False
        
        # Usar QFile para leer el archivo
        archivo = QFile(str(ruta))
        if archivo.open(QFile.ReadOnly | QFile.Text):
            stream = QTextStream(archivo)
            # Especificar codificación UTF-8 para Windows
            stream.setCodec("UTF-8")
            estilo = stream.readAll()
            archivo.close()
            app.setStyleSheet(estilo)
            print(f"✓ Estilos cargados desde: {ruta}")
            return True
        else:
            print(f"✗ No se pudo abrir {ruta}")
            return False
        
    except Exception as err:
        print(f"✗ Excepción al cargar estilos: {err}")
        traceback.print_exc()
        return False

def configurar_fuente_windows():
    """Configura fuente mejor para Windows"""
    # En Windows, a veces las fuentes por defecto no se renderizan bien
    font = QFont("Segoe UI", 9)
    QApplication.setFont(font)

def main():
    # Configurar manejo de excepciones
    sys.excepthook = excepthook
    
    # Crear aplicación
    app = QApplication(sys.argv)
    
    # Configurar para Windows
    configurar_fuente_windows()
    
    # Configurar variables de entorno para Qt en Windows
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ""
    
    print("="*50)
    print("INICIANDO APLICACIÓN EN WINDOWS")
    print(f"Directorio de trabajo: {os.getcwd()}")
    print(f"Directorio del script: {Path(__file__).parent}")
    print("="*50)
    
    # Ruta base del proyecto
    ruta_base = Path(__file__).parent
    
    # Ruta del archivo de estilos
    ruta_estilos = ruta_base / "Static" / "Scripts" / "estilos.qss"
    
    # Cargar estilos
    cargar_estilos(app, str(ruta_estilos))
    
    try:
        # Crear vista y controlador
        print("Creando vista...")
        view = EditorView()
        print("Creando controlador...")
        controller = EditorController(view)
        
        # CONECTAR EL CONTROLADOR A LA VISTA - IMPORTANTE PARA LOS EVENTOS DE TECLADO
        view.set_controller(controller)
        
        # Configuración específica para Windows
        print("Configurando para Windows...")
        
        # Mostrar ventana
        print("Mostrando ventana...")
        view.show()

        # Si se recibió un archivo .json como argumento, abrirlo automáticamente
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".json"):
            ruta_proyecto = sys.argv[1]
            if os.path.isfile(ruta_proyecto):
                print(f"Abriendo proyecto desde argumento: {ruta_proyecto}")
                controller.abrir_proyecto_desde_ruta(ruta_proyecto)

        # Mensaje de éxito
        print("="*50)
        print("APLICACIÓN INICIADA CORRECTAMENTE")
        print("="*50)
        print("Atajos de teclado disponibles:")
        print("  Enter: Finalizar creación de ruta")
        print("  Escape: Cancelar creación de ruta")
        print("  Suprimir: Eliminar nodo seleccionado")
        print("  Ctrl+Z: Deshacer movimiento de nodo")
        print("  Ctrl+Y: Rehacer movimiento de nodo")
        print("="*50)
        
        # Ejecutar aplicación
        return_code = app.exec_()
        print(f"\nAplicación finalizada con código: {return_code}")
        sys.exit(return_code)
        
    except Exception as e:
        print(f"\n✗ ERROR CRÍTICO DURANTE LA INICIALIZACIÓN:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()