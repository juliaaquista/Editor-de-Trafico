from PyQt5 import uic
from PyQt5.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QPushButton, QLabel, QListWidgetItem, QSizePolicy, QVBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont
import os
import sys
from pathlib import Path
from View.zoom_view import ZoomGraphicsView

# ===== WIDGETS PERSONALIZADOS PARA LISTAS =====

class NodoListItemWidget(QWidget):
    """Widget personalizado para ítems de nodo en la lista lateral"""
    toggle_visibilidad = pyqtSignal(int)  # Señal con nodo_id
    
    def __init__(self, nodo_id, texto, visible=True, parent=None):
        super().__init__(parent)
        self.nodo_id = nodo_id
        self.visible = visible
        
        # Layout horizontal
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 1, 2, 1)  # Márgenes más pequeños
        layout.setSpacing(3)  # Espaciado reducido
        
        # Etiqueta con texto (ocupa la mayor parte del espacio)
        self.lbl_texto = QLabel(texto)
        self.lbl_texto.setStyleSheet("color: #e0e0e0; padding: 1px;")
        self.lbl_texto.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # Botón de ojo pequeño a la derecha
        self.btn_ojo = QPushButton()
        self.btn_ojo.setFixedSize(20, 20)  # Más pequeño: 20x20px
        self.btn_ojo.setObjectName("btnOjo")
        self.btn_ojo.clicked.connect(self._on_toggle_visibilidad)
        
        # Añadir primero el texto, luego el botón
        layout.addWidget(self.lbl_texto, 1)  # Factor de estiramiento 1
        layout.addWidget(self.btn_ojo, 0, Qt.AlignRight)  # Sin estiramiento, alineado a la derecha
        
        self.setLayout(layout)
        self.actualizar_estado()
    
    def _on_toggle_visibilidad(self):
        """Emite señal cuando se hace clic en el botón de ojo"""
        self.toggle_visibilidad.emit(self.nodo_id)
    
    def actualizar_estado(self):
        """Actualiza la apariencia del botón según el estado de visibilidad"""
        if self.visible:
            self.btn_ojo.setStyleSheet("""
                QPushButton#btnOjo {
                    background-color: #4CAF50;
                    border: 1px solid #388E3C;
                    border-radius: 3px;
                    color: white;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton#btnOjo:hover {
                    background-color: #45a049;
                    border-color: #2E7D32;
                }
            """)
            self.btn_ojo.setText("👁")
            self.lbl_texto.setStyleSheet("color: #e0e0e0; padding: 1px; font-size: 10px;")
        else:
            self.btn_ojo.setStyleSheet("""
                QPushButton#btnOjo {
                    background-color: #f44336;
                    border: 1px solid #D32F2F;
                    border-radius: 3px;
                    color: white;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton#btnOjo:hover {
                    background-color: #da190b;
                    border-color: #B71C1C;
                }
            """)
            self.btn_ojo.setText("👁")
            self.lbl_texto.setStyleSheet("color: #666666; text-decoration: line-through; padding: 1px; font-size: 10px;")

    def set_visible(self, visible):
        """Establece el estado de visibilidad y actualiza"""
        self.visible = visible
        self.actualizar_estado()

class RutaListItemWidget(QWidget):
    """Widget personalizado para ítems de ruta en la lista lateral"""
    toggle_visibilidad = pyqtSignal(int)  # Señal con ruta_index
    solicitar_eliminacion = pyqtSignal(int)  # Señal para eliminar ruta

    def __init__(self, ruta_index, texto, visible=True, parent=None):
        super().__init__(parent)
        self.ruta_index = ruta_index
        self.visible = visible

        # Layout horizontal
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 1, 2, 1)  # Márgenes más pequeños
        layout.setSpacing(3)  # Espaciado reducido

        # Etiqueta con texto (ocupa la mayor parte del espacio)
        self.lbl_texto = QLabel(texto)
        self.lbl_texto.setStyleSheet("color: #e0e0e0; padding: 1px;")
        self.lbl_texto.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Botón de ojo pequeño a la derecha
        self.btn_ojo = QPushButton()
        self.btn_ojo.setFixedSize(20, 20)  # Más pequeño: 20x20px
        self.btn_ojo.setObjectName("btnOjo")
        self.btn_ojo.clicked.connect(self._on_toggle_visibilidad)

        # Botón de eliminar a la derecha del ojo
        self.btn_eliminar = QPushButton("X")
        self.btn_eliminar.setFixedSize(20, 20)
        self.btn_eliminar.setObjectName("btnEliminarRuta")
        self.btn_eliminar.setToolTip("Eliminar ruta")
        self.btn_eliminar.setStyleSheet("""
            QPushButton#btnEliminarRuta {
                background-color: #c62828;
                border: 1px solid #b71c1c;
                border-radius: 3px;
                color: white;
                font-size: 10px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }
            QPushButton#btnEliminarRuta:hover {
                background-color: #e53935;
                border-color: #c62828;
            }
        """)
        self.btn_eliminar.clicked.connect(self._on_solicitar_eliminacion)

        # Añadir primero el texto, luego los botones
        layout.addWidget(self.lbl_texto, 1)  # Factor de estiramiento 1
        layout.addWidget(self.btn_ojo, 0, Qt.AlignRight)  # Sin estiramiento, alineado a la derecha
        layout.addWidget(self.btn_eliminar, 0, Qt.AlignRight)

        self.setLayout(layout)
        self.actualizar_estado()
    
    def _on_toggle_visibilidad(self):
        """Emite señal cuando se hace clic en el botón de ojo"""
        self.toggle_visibilidad.emit(self.ruta_index)

    def _on_solicitar_eliminacion(self):
        """Emite señal cuando se hace clic en el botón de eliminar"""
        self.solicitar_eliminacion.emit(self.ruta_index)
    
    def actualizar_estado(self):
        """Actualiza la apariencia del botón según el estado de visibilidad"""
        if self.visible:
            self.btn_ojo.setStyleSheet("""
                QPushButton#btnOjo {
                    background-color: #2196F3;
                    border: 1px solid #1976D2;
                    border-radius: 3px;
                    color: white;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton#btnOjo:hover {
                    background-color: #0b7dda;
                    border-color: #1565C0;
                }
            """)
            self.btn_ojo.setText("👁")
            self.lbl_texto.setStyleSheet("color: #e0e0e0; padding: 1px; font-size: 10px;")
        else:
            self.btn_ojo.setStyleSheet("""
                QPushButton#btnOjo {
                    background-color: #ff9800;
                    border: 1px solid #F57C00;
                    border-radius: 3px;
                    color: white;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton#btnOjo:hover {
                    background-color: #e68a00;
                    border-color: #EF6C00;
                }
            """)
            self.btn_ojo.setText("👁")
            self.lbl_texto.setStyleSheet("color: #666666; text-decoration: line-through; padding: 1px; font-size: 10px;")

    def set_visible(self, visible):
        """Establece el estado de visibilidad y actualiza"""
        self.visible = visible
        self.actualizar_estado()

# ===== CLASE PRINCIPAL DE LA VISTA =====

class EditorView(QMainWindow):
    # Callback que el controller puede asignar para interceptar el cierre
    on_close_callback = None

    def __init__(self):
        super().__init__()

        # Buscar el archivo .ui en múltiples ubicaciones
        ui_paths = [
            Path(__file__).parent / "editor.ui",
            Path.cwd() / "View" / "editor.ui",
            Path(sys.executable).parent / "View" / "editor.ui"
        ]
        
        ui_file = None
        for path in ui_paths:
            if path.exists():
                ui_file = str(path)
                print(f"✓ Archivo UI encontrado en: {path}")
                break
        
        if not ui_file:
            raise FileNotFoundError("No se pudo encontrar el archivo editor.ui")
        
        # Cargar UI
        uic.loadUi(ui_file, self)

        # --- SPLITTERS REDIMENSIONABLES ---
        # Splitter horizontal: mapa | panel lateral
        if hasattr(self, "splitter"):
            self.splitter.setStretchFactor(0, 4)   # mapa: ocupa más
            self.splitter.setStretchFactor(1, 1)   # panel lateral: menos
            self.splitter.setSizes([800, 280])
            self.splitter.setChildrenCollapsible(False)
            self.splitter.setHandleWidth(6)

        # Splitter vertical del panel lateral: nodos / rutas / propiedades
        if hasattr(self, "sideSplitter"):
            # Reparto inicial 1/3 - 1/3 - 1/3
            self.sideSplitter.setStretchFactor(0, 1)
            self.sideSplitter.setStretchFactor(1, 1)
            self.sideSplitter.setStretchFactor(2, 1)
            self.sideSplitter.setSizes([200, 200, 200])
            self.sideSplitter.setHandleWidth(6)

        self.menuParametros = self.menuBar().addMenu("Parámetros")
        #self.actionParametros = self.menuParametros.addAction("Configurar Parámetros...")

        # Sustituir el QGraphicsView por ZoomGraphicsView
        self.zoomView = ZoomGraphicsView(self)
        self.zoomView.setObjectName("marco_trabajo")
        
        # Configuraciones específicas para Windows
        self.zoomView.setViewportUpdateMode(self.zoomView.FullViewportUpdate)
        self.zoomView.setOptimizationFlag(self.zoomView.DontAdjustForAntialiasing, False)
        
        # Reemplazar en el layout
        if hasattr(self, 'workLayout') and self.workLayout is not None:
            self.workLayout.replaceWidget(self.marco_trabajo, self.zoomView)
            self.marco_trabajo.deleteLater()
            self.marco_trabajo = self.zoomView
        else:
            print("✗ ADVERTENCIA: No se encontró workLayout")
            self.marco_trabajo = self.zoomView
        
        # --- BARRA DE INFORMACIÓN EN PARTE INFERIOR ---
        # Contenedor horizontal para modo + coordenadas
        status_bar_widget = QWidget()
        status_bar_layout = QHBoxLayout(status_bar_widget)
        status_bar_layout.setContentsMargins(5, 0, 5, 0)
        status_bar_layout.setSpacing(10)

        # Label del modo (ocupa el espacio principal)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #e6edf3;
                padding: 2px;
                font-size: 11px;
            }
        """)

        # Label de coordenadas (a la derecha, ancho fijo)
        self.coords_label = QLabel("X: -- Y: --")
        self.coords_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.coords_label.setFixedWidth(180)
        self.coords_label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #8b949e;
                padding: 2px;
                font-size: 11px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
        """)

        status_bar_layout.addWidget(self.status_label, 1)
        status_bar_layout.addWidget(self.coords_label, 0)

        status_bar_widget.setFixedHeight(25)
        status_bar_widget.setStyleSheet("""
            QWidget {
                background-color: #161b22;
                border-top: 1px solid #30363d;
            }
        """)

        # Agregar al layout principal
        if hasattr(self.centralwidget, 'layout'):
            main_layout = self.centralwidget.layout()
            if main_layout:
                main_layout.addWidget(status_bar_widget)
        
        # Referencia al controlador (se establecerá después)
        self.controller = None
        
        # Establecer texto inicial
        self.actualizar_descripcion_modo("navegacion")
    
    def actualizar_descripcion_modo(self, modo):
        """Actualiza la descripción del modo en la barra inferior"""
        descripciones = {
            "navegacion": "Modo navegación: Usa el ratón para desplazarte por el mapa. Haz clic en un nodo para seleccionarlo.",
            "mover": "Modo mover: Arrastra los nodos para cambiar su posición. Usa Ctrl+Z para deshacer y Ctrl+Y para rehacer. Mantener pulsado botón scroll del ratón para navegar.",
            "colocar": "Modo colocar: Haz clic en el mapa para colocar un nuevo nodo. Puede pulsar Escape para salir del modo. Mantener pulsado botón scroll del ratón para navegar.",
            "ruta": "Modo ruta: Haz clic en nodos existentes o en el mapa para crear nuevos nodos y formar una ruta. Presiona Enter para finalizar la ruta o Escape para cancelar. Mantener pulsado botón scroll del ratón para navegar.",
            "duplicar": "Modo duplicar: Click en un nodo lo marca en naranja. Ctrl+Click en otros nodos para agregarlos a la selección. Click en zona vacía para colocar los duplicados. Escape para salir."
        }
        
        texto = descripciones.get(modo, "Modo desconocido")
        self.status_label.setText(texto)
        print(f"✓ Descripción del modo actualizada: {modo}")
    
    def actualizar_coordenadas(self, x_m, y_m):
        """Actualiza las coordenadas del cursor en la barra inferior (en metros)"""
        self.coords_label.setText(f"X: {x_m:.2f} m  Y: {y_m:.2f} m")

    def limpiar_coordenadas(self):
        """Limpia las coordenadas cuando el cursor sale del mapa"""
        self.coords_label.setText("X: -- Y: --")

    def set_controller(self, controller):
        """Establece la referencia al controlador"""
        self.controller = controller
    
    def _focus_en_widget_editable(self):
        """Comprueba si el foco está en un widget editable (tabla de propiedades, etc.)"""
        from PyQt5.QtWidgets import QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget
        focused = self.focusWidget()
        if focused is None:
            return False
        # Si el foco está directamente en un editor de celda
        if isinstance(focused, (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox)):
            return True
        # Si el foco está en la tabla de propiedades
        if hasattr(self, 'propertiesTable') and isinstance(focused, QTableWidget):
            if focused is self.propertiesTable:
                return True
        return False

    def keyPressEvent(self, event):
        """Captura eventos de teclado para atajos globales"""
        try:
            # Pasar el evento al controlador primero
            if self.controller:
                en_editable = self._focus_en_widget_editable()

                # Check for Enter/Return - Finalizar ruta (solo si no estamos editando)
                if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                    if not en_editable:
                        self.controller.finalizar_ruta_actual()
                        event.accept()
                        return

                # Check for Escape - Cancelar ruta
                elif event.key() == Qt.Key_Escape:
                    self.controller.cancelar_ruta_actual()
                    event.accept()
                    return

                # Check for Delete - Eliminar nodo (solo si no estamos editando)
                elif event.key() == Qt.Key_Delete:
                    if not en_editable:
                        self.controller.eliminar_nodo_seleccionado()
                        event.accept()
                        return

                # Check for Ctrl+Z - Deshacer
                elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
                    self.controller.deshacer_movimiento()
                    event.accept()
                    return

                # Check for Ctrl+Y - Rehacer
                elif event.key() == Qt.Key_Y and event.modifiers() == Qt.ControlModifier:
                    self.controller.rehacer_movimiento()
                    event.accept()
                    return

        except Exception as e:
            print(f"Error en keyPressEvent: {e}")

        # Pasar el evento a la clase base para manejo normal
        super().keyPressEvent(event)

    def closeEvent(self, event):
        """Intercepta el cierre de ventana (X) para preguntar si guardar."""
        if self.on_close_callback:
            if not self.on_close_callback():
                event.ignore()  # Cancelar cierre
                return
        event.accept()