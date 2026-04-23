from PyQt5.QtWidgets import (
    QFileDialog, QGraphicsScene, QGraphicsPixmapItem,
    QButtonGroup, QListWidgetItem,
    QTableWidgetItem, QHeaderView, QMenu, QMessageBox, QDialog,
    QCheckBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox
)
from PyQt5.QtGui import QPixmap, QPen, QCursor
from PyQt5.QtCore import Qt, QEvent, QObject, QSize
from Model.Proyecto import Proyecto
from Model.ExportadorDB import ExportadorDB
from Model.ExportadorCSV import ExportadorCSV
from Model.stcm_parser import parse_stcm, STCMData
from Controller.mover_controller import MoverController
from Controller.colocar_controller import ColocarController
from Controller.ruta_controller import RutaController
from View.view import NodoListItemWidget, RutaListItemWidget
from View.node_item import NodoItem
from Model.Nodo import Nodo
from Model.schema import NODO_FIELDS, OBJETIVO_FIELDS
import ast
import copy


class _ComboObjetivoSinFlechas(QComboBox):
    """QComboBox que ignora flechas (Up/Down/Left/Right) y PageUp/PageDown
    mientras el popup está cerrado. Permite navegar la tabla con el teclado
    sin disparar accidentalmente el cambio de objetivo y la apertura del
    diálogo de propiedades avanzadas. Cuando el popup está abierto, las
    flechas funcionan normalmente para elegir un ítem."""

    def keyPressEvent(self, event):
        if not self.view().isVisible():
            tecla = event.key()
            if tecla in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                         Qt.Key_PageUp, Qt.Key_PageDown):
                event.ignore()
                return
        super().keyPressEvent(event)


class _PropertiesTableEnterFilter(QObject):
    """Filtro de eventos para la tabla de propiedades. Cuando el usuario
    presiona Enter/Return sobre una celda cuyo valor es un QComboBox
    (p.ej. el combo de 'objetivo'), abre su popup en vez de iniciar
    edición de la celda. Así se puede navegar la tabla con flechas y
    abrir el desplegable con Enter."""

    def __init__(self, table, parent=None):
        super().__init__(parent)
        self._table = table

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            row = self._table.currentRow()
            if row >= 0:
                widget = self._table.cellWidget(row, 1)
                if isinstance(widget, QComboBox):
                    widget.showPopup()
                    return True
        return False


class EditorController(QObject):
    def __init__(self, view, proyecto=None):
        super().__init__()
        self.view = view
        self.proyecto = proyecto
        
        # --- ESCALA GLOBAL: 1 píxel = 0.05 metros ---
        self.ESCALA = 0.05

        # --- Dimensiones del mapa en píxeles (para invertir eje Y y limitar escena) ---
        self.alto_mapa_px = 0
        self.ancho_mapa_px = 0
        # Offset del origen: esquina inferior izquierda del área blanca del mapa
        self.offset_x_px = 0
        self.offset_y_px = 0  # En coordenadas de pantalla (Y crece hacia abajo)

        # --- NUEVO: Estado del cursor ---
        self._cursor_sobre_nodo = False
        self._arrastrando_nodo = False  # Para rastrear si estamos arrastrando un nodo

        self._conectar_señales_proyecto()
        self._arrastrando_mapa_con_izquierdo = False

        # --- Inicializar escena con padre ---
        self.scene = QGraphicsScene(self.view.marco_trabajo)
        self.view.marco_trabajo.setScene(self.scene)

        # Conexión: selección en el mapa
        self.scene.selectionChanged.connect(self.seleccionar_nodo_desde_mapa)

        # Conexión: selección en la lista lateral
        self.view.nodosList.itemSelectionChanged.connect(self.seleccionar_nodo_desde_lista)

        header = self.view.propertiesTable.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        # --- Etiqueta de nodo seleccionado arriba de la tabla de propiedades ---
        self.lbl_nodo_seleccionado = QLabel("")
        self.lbl_nodo_seleccionado.setStyleSheet("""
            QLabel {
                background-color: #2D2D30;
                color: #FFFFFF;
                font-size: 16px;
                font-weight: bold;
                padding: 6px 10px;
                border: 1px solid #3F3F46;
                border-radius: 4px;
                margin-bottom: 4px;
            }
        """)
        self.lbl_nodo_seleccionado.setAlignment(Qt.AlignCenter)
        self.lbl_nodo_seleccionado.hide()
        # Insertar antes de la tabla (posición 0 del layout)
        self.view.groupProperties.layout().insertWidget(0, self.lbl_nodo_seleccionado)

        # --- Menú Proyecto ---
        nueva_ventana_action = self.view.menuProyecto.addAction("Nueva ventana")
        nueva_ventana_action.triggered.connect(self._abrir_nueva_ventana)
        self.view.menuProyecto.addSeparator()
        nuevo_action = self.view.menuProyecto.addAction("Nuevo")
        abrir_action = self.view.menuProyecto.addAction("Abrir")
        guardar_action = self.view.menuProyecto.addAction("Guardar")
        guardar_como_action = self.view.menuProyecto.addAction("Guardar como...")
        importar_action = self.view.menuProyecto.addAction("Importar proyecto...")
        importar_action.triggered.connect(self.importar_proyecto)
        cerrar_action = self.view.menuProyecto.addAction("Cerrar proyecto")
        cerrar_action.triggered.connect(self.cerrar_proyecto)

        # --- Submenú Exportar ---
        self.view.menuProyecto.addSeparator()  # Separador visual
        exportar_sqlite_action = self.view.menuProyecto.addAction("Exportar a SQLite...")
        exportar_sqlite_action.triggered.connect(self.exportar_a_sqlite)

        # --- Opción para exportar a CSV ---
        exportar_csv_action = self.view.menuProyecto.addAction("Exportar a CSV...")
        exportar_csv_action.triggered.connect(self.exportar_a_csv)

        nuevo_action.triggered.connect(self.nuevo_proyecto)
        abrir_action.triggered.connect(self.abrir_proyecto)
        guardar_action.triggered.connect(self.guardar_proyecto)
        guardar_como_action.triggered.connect(self.guardar_proyecto_como)

        # Interceptar cierre de ventana (botón X)
        self.view.on_close_callback = self._on_close_window

        # --- Subcontroladores---
        self.mover_ctrl = MoverController(self.proyecto, self.view, self)
        self.colocar_ctrl = ColocarController(self.proyecto, self.view, self)
        self.ruta_ctrl = RutaController(self.proyecto, self.view, self)

        #Menu parametros
        # Verificar si el menú ya existe en la vista
        if hasattr(self.view, 'menuParametros'):
            action_parametros = self.view.menuParametros.addAction("Configurar Parámetros...")
            action_parametros.triggered.connect(self.mostrar_dialogo_parametros)
        else:
            # Crear dinámicamente si no existe
            self.view.menuParametros = self.view.menuBar().addMenu("Parámetros")
            action_parametros = self.view.menuParametros.addAction("Configurar Parámetros...")
            action_parametros.triggered.connect(self.mostrar_dialogo_parametros)

        # Menu parametros playa
        if hasattr(self.view, 'menuParametrosPlaya'):
            action_parametros_playa = self.view.menuParametrosPlaya.addAction("Configurar Parámetros Playa...")
            action_parametros_playa.triggered.connect(self.mostrar_dialogo_parametros_playa)
        else:
            # Crear dinámicamente si no existe
            self.view.menuParametrosPlaya = self.view.menuBar().addMenu("Parámetros Playa")
            action_parametros_playa = self.view.menuParametrosPlaya.addAction("Configurar Parámetros Playa...")
            action_parametros_playa.triggered.connect(self.mostrar_dialogo_parametros_playa)

        # Menu parametros carga/descarga
        if hasattr(self.view, 'menuParametrosCargaDescarga'):
            action_parametros_carga_descarga = self.view.menuParametrosCargaDescarga.addAction("Configurar Parámetros Carga/Descarga...")
            action_parametros_carga_descarga.triggered.connect(self.mostrar_dialogo_parametros_carga_descarga)
        else:
            # Crear dinámicamente si no existe
            self.view.menuParametrosCargaDescarga = self.view.menuBar().addMenu("Parámetros Carga/Descarga")
            action_parametros_carga_descarga = self.view.menuParametrosCargaDescarga.addAction("Configurar Parámetros Carga/Descarga...")
            action_parametros_carga_descarga.triggered.connect(self.mostrar_dialogo_parametros_carga_descarga)

        # --- Grupo de botones de modo ---
        self.modo_group = QButtonGroup()
        self.modo_group.setExclusive(False)

        self.modo_group.addButton(self.view.mover_button)
        self.modo_group.addButton(self.view.colocar_vertice_button)
        self.modo_group.addButton(self.view.crear_ruta_button)
        if hasattr(self.view, "duplicar_nodo_button"):
            self.modo_group.addButton(self.view.duplicar_nodo_button)

        self.modo_group.buttonClicked.connect(self.cambiar_modo)
        self.modo_actual = None
        self.ruta_archivo_actual = None  # Ruta del archivo JSON del proyecto abierto
        self.proyecto_modificado = False  # Flag de cambios sin guardar

        # Estado inicial: modo por defecto (navegación)
        self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.ScrollHandDrag)

        self.scene.selectionChanged.connect(self.manejar_seleccion_nodo)

        self._changing_selection = False
        self._updating_ui = False
        self._updating_from_table = False

        # mantener referencias a las líneas de rutas dibujadas
        self._route_lines = []            
        self._highlight_lines = []        

        # instalar filtro de eventos en el viewport
        try:
            self.view.marco_trabajo.viewport().installEventFilter(self)
        except Exception:
            pass

        # Instalar filtro de eventos en la ventana principal para manejo de teclado
        self.view.installEventFilter(self)

        # Filtro para que Enter sobre una celda con QComboBox abra su popup
        # (permite usar el combo de objetivo navegando con flechas + Enter).
        if hasattr(self.view, "propertiesTable"):
            self._props_enter_filter = _PropertiesTableEnterFilter(
                self.view.propertiesTable, self
            )
            self.view.propertiesTable.installEventFilter(self._props_enter_filter)

        if hasattr(self.view, "rutasList"):
            try:
                self.view.rutasList.itemSelectionChanged.disconnect(self.seleccionar_ruta_desde_lista)
            except Exception:
                pass
            self.view.rutasList.itemSelectionChanged.connect(self.seleccionar_ruta_desde_lista)

        # Índice de la ruta actualmente seleccionada
        self.ruta_actual_idx = None
        
        # --- SISTEMA DE DESHACER/REHACER (UNDO/REDO) ---
        self.historial_movimientos = []  # Lista de movimientos
        self.indice_historial = -1  # Puntero a la posición actual en el historial (-1 = vacío)
        self.max_historial = 100  # Límite de cambios en el historial
        # Movimiento actual en progreso (para guardar en historial)
        self.movimiento_actual = None  # {'nodo': nodo_item, 'x_inicial': x, 'y_inicial': y}
        self._ejecutando_deshacer_rehacer = False

        # --- SISTEMA DE VISIBILIDAD MEJORADO CON RECONSTRUCCIÓN DE RUTAS ---
        self.visibilidad_nodos = {}  # {nodo_id: visible} - Para UI
        self.visibilidad_rutas = {}  # {ruta_index: visible} - Para líneas
        self.nodo_en_rutas = {}  # {nodo_id: [ruta_index1, ...]} - Relaciones originales
        
        # Rutas reconstruidas para dibujo (excluyendo nodos ocultos)
        self.rutas_para_dibujo = []  # Lista de rutas reconstruidas para dibujar
        
        # --- CAMBIO: Conectar botones de visibilidad como interruptores ---
        if hasattr(self.view, "btnOcultarTodo"):
            self.view.btnOcultarTodo.setText("Ocultar Nodos")  # Cambiar texto inicial
            self.view.btnOcultarTodo.clicked.connect(self.toggle_visibilidad_nodos)
        if hasattr(self.view, "btnMostrarTodo"):
            self.view.btnMostrarTodo.setText("Ocultar Rutas")  # Cambiar texto inicial
            self.view.btnMostrarTodo.clicked.connect(self.toggle_visibilidad_rutas)
            self.view.btnMostrarTodo.setEnabled(True)  # Inicialmente habilitado
        
        # Si hay proyecto inicial, configurarlo
        if self.proyecto:
            self._actualizar_referencias_proyecto(self.proyecto)
            self.inicializar_visibilidad()
            # Asegurar que los botones estén inicializados
            self._actualizar_lista_nodos_con_widgets()
        
        # --- NUEVO: Actualizar descripción del modo inicial ---
        self.actualizar_descripcion_modo()

        # --- Estado del modo de duplicación (botón "Duplicar nodo") ---
        # El modo tiene dos fases dentro del mismo botón:
        # 1. Selección: el usuario hace click en nodos para añadirlos a la lista
        #    a duplicar (click nuevamente los quita). Ctrl no es necesario.
        # 2. Colocación: mientras hay nodos seleccionados y el cursor está sobre
        #    una zona vacía, se muestran "fantasmas" siguiendo al cursor. Un
        #    click en zona vacía coloca los duplicados y limpia la selección
        #    para poder continuar duplicando.
        self._modo_duplicar_activo = False
        self._duplicar_items_seleccionados = []  # NodoItems marcados para duplicar
        self._duplicar_ghost_items = []  # Lista de (ellipse, dx, dy)

        # Asegurar que el cursor inicial sea correcto
        self._actualizar_cursor()

    def _registrar_eliminacion_nodo(self, nodo_copia, rutas_afectadas):
        """
        Registra la eliminación de un nodo en el historial UNDO/REDO.
        
        Args:
            nodo_copia: Copia del nodo eliminado
            rutas_afectadas: Lista de rutas que contenían el nodo antes de eliminarlo
        """
        try:
            # Si estamos en medio del historial (por deshacer previo), eliminar movimientos futuros
            if self.indice_historial < len(self.historial_movimientos) - 1:
                self.historial_movimientos = self.historial_movimientos[:self.indice_historial + 1]
            
            # GUARDAR SNAPSHOT COMPLETO DEL ESTADO DESPUÉS DE LA ELIMINACIÓN
            # 1. Estado de las rutas después de la eliminación
            rutas_despues = []
            for idx, ruta in enumerate(self.proyecto.rutas):
                try:
                    # Copia profunda de la ruta
                    ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                    rutas_despues.append(copy.deepcopy(ruta_dict))
                except Exception as e:
                    print(f"Error copiando ruta {idx} para historial: {e}")
                    rutas_despues.append(None)
            
            # 2. Estado de visibilidad después de la eliminación
            visibilidad_nodos_despues = copy.deepcopy(self.visibilidad_nodos)
            visibilidad_rutas_despues = copy.deepcopy(self.visibilidad_rutas)
            nodo_en_rutas_despues = copy.deepcopy(self.nodo_en_rutas)
            
            # Crear entrada del historial para eliminación
            eliminacion = {
                'tipo': 'eliminacion',
                'nodo': nodo_copia,
                'rutas_afectadas': rutas_afectadas,  # Para deshacer (estado antes)
                'rutas_despues': rutas_despues,       # Para rehacer (estado después)
                'visibilidad_nodos_despues': visibilidad_nodos_despues,
                'visibilidad_rutas_despues': visibilidad_rutas_despues,
                'nodo_en_rutas_despues': nodo_en_rutas_despues,
                'descripcion': f"Eliminación de nodo ID {nodo_copia.get('id')}"
            }
            
            # Agregar al historial
            self.historial_movimientos.append(eliminacion)
            
            # Limitar tamaño del historial
            if len(self.historial_movimientos) > self.max_historial:
                self.historial_movimientos.pop(0)
            else:
                self.indice_historial += 1
            
            # Mover puntero a la última posición
            self.indice_historial = len(self.historial_movimientos) - 1
            
            
        except Exception as e:
            print(f"Error registrando eliminación en historial: {e}")

    # --- MÉTODOS DE CONVERSIÓN PÍXELES-METROS ---
    def pixeles_a_metros(self, valor_px):
        """Convierte píxeles a metros usando la escala global."""
        return valor_px * self.ESCALA

    def metros_a_pixeles(self, valor_m):
        """Convierte metros a píxeles usando la escala global."""
        return valor_m / self.ESCALA

    def x_px_a_metros(self, x_px):
        """Convierte X de píxeles a metros, restando el offset del origen."""
        return (x_px - self.offset_x_px) * self.ESCALA

    def x_metros_a_px(self, x_m):
        """Convierte X de metros a píxeles, sumando el offset del origen."""
        return (x_m / self.ESCALA) + self.offset_x_px

    def y_px_a_metros(self, y_px):
        """Convierte Y de píxeles (crece hacia abajo) a metros (crece hacia arriba), desde el offset."""
        return (self.offset_y_px - y_px) * self.ESCALA

    def y_metros_a_px(self, y_m):
        """Convierte Y de metros (crece hacia arriba) a píxeles (crece hacia abajo), desde el offset."""
        return self.offset_y_px - (y_m / self.ESCALA)

    def format_coords_m(self, x_px, y_px):
        """Formatea coordenadas en metros con 2 decimales."""
        x_m = self.x_px_a_metros(x_px)
        y_m = self.y_px_a_metros(y_px)
        return f"{x_m:.2f}, {y_m:.2f}"

    def _limpiar_propiedades(self):
        """Limpia la tabla de propiedades y oculta la etiqueta de nodo."""
        self.view.propertiesTable.clear()
        self.view.propertiesTable.setRowCount(0)
        self.view.propertiesTable.setColumnCount(2)
        self.view.propertiesTable.setHorizontalHeaderLabels(["Propiedad", "Valor"])
        if hasattr(self, 'lbl_nodo_seleccionado'):
            self.lbl_nodo_seleccionado.hide()

    # --- MÉTODOS PARA GESTIÓN DE PUNTEROS ---
    def _actualizar_cursor(self, cursor_tipo=None):
        """
        Actualiza el cursor del viewport según el modo y situación.
        
        Args:
            cursor_tipo: Puede ser None (auto-determinar) o un valor de Qt.CursorShape
        """
        try:
            # Depuración para entender qué está pasando
            
            if cursor_tipo is not None:
                # Si se especifica un cursor específico, usarlo
                self.view.marco_trabajo.viewport().setCursor(QCursor(cursor_tipo))
                return
            
            # Determinar cursor según el modo actual y estado
            if self.modo_actual is None:
                # MODO POR DEFECTO (navegación)
                if self._cursor_sobre_nodo:
                    # ABSOLUTAMENTE SIEMPRE PointingHandCursor cuando está sobre un nodo
                    cursor = Qt.PointingHandCursor
                else:
                    # Dejar que Qt maneje el cursor de navegación (ScrollHandDrag)
                    self.view.marco_trabajo.viewport().unsetCursor()
                    return
                    
            elif self.modo_actual == "mover":
                # MODO MOVER - CORREGIDO
                if self._arrastrando_nodo:
                    # Mano cerrada cuando se está arrastrando un nodo
                    cursor = Qt.ClosedHandCursor
                elif self._cursor_sobre_nodo:
                    # PointingHandCursor cuando está sobre un nodo pero NO arrastrando
                    cursor = Qt.PointingHandCursor
                else:
                    # Flecha cuando no está sobre un nodo
                    cursor = Qt.ArrowCursor
                    
            elif self.modo_actual == "colocar":
                # MODO COLOCAR VÉRTICE - SIEMPRE flecha
                cursor = Qt.ArrowCursor
                
            elif self.modo_actual == "ruta":
                # MODO RUTA - AHORA IGUAL QUE MODO MOVER (sin arrastre)
                if self._cursor_sobre_nodo:
                    # PointingHandCursor cuando está sobre un nodo
                    cursor = Qt.PointingHandCursor
                else:
                    # Flecha cuando no está sobre un nodo
                    cursor = Qt.ArrowCursor
                    
            else:
                # Cualquier otro modo
                cursor = Qt.ArrowCursor
            
            # Aplicar el cursor
            self.view.marco_trabajo.viewport().setCursor(QCursor(cursor))
            
        except Exception as e:
            print(f"Error al actualizar cursor: {e}")


    def nodo_hover_entered(self, nodo_item):
        """Cuando el ratón entra en un nodo"""
        self._cursor_sobre_nodo = True
        self._actualizar_cursor()

    def nodo_hover_leaved(self, nodo_item):
        """Cuando el ratón sale de un nodo"""
        self._cursor_sobre_nodo = False
        self._actualizar_cursor()

    def nodo_arrastre_iniciado(self):
        """Cuando se inicia el arrastre de un nodo en modo mover"""
        if self.modo_actual == "mover":
            self._arrastrando_nodo = True
            self._actualizar_cursor()

    def nodo_arrastre_terminado(self):
        """Cuando se termina el arrastre de un nodo"""
        self._arrastrando_nodo = False
        self._actualizar_cursor()

    # --- MÉTODOS NUEVOS PARA MANEJO DE PROYECTO ---
    def _resetear_modo_actual(self):
        """Resetea el modo actual para forzar reconfiguración"""
        modo_temp = self.modo_actual
        self.modo_actual = None
        
        # Desactivar todos los botones primero
        for b in (self.view.mover_button,
                  self.view.colocar_vertice_button, self.view.crear_ruta_button):
            b.setChecked(False)
        
        # Re-activar el modo si es necesario
        if modo_temp:
            boton = None
            if modo_temp == "mover":
                boton = self.view.mover_button
            elif modo_temp == "colocar":
                boton = self.view.colocar_vertice_button
            elif modo_temp == "ruta":
                boton = self.view.crear_ruta_button
            
            if boton:
                boton.setChecked(True)
                self.cambiar_modo(boton)

    def _limpiar_ui_completa(self):
        """Limpia toda la UI para nuevo proyecto"""
        # Limpiar escena
        self.scene.clear()
        
        # Limpiar listas
        self.view.nodosList.clear()
        if hasattr(self.view, "rutasList"):
            self.view.rutasList.clear()
        
        # Limpiar tabla de propiedades
        self._limpiar_propiedades()

        # Limpiar líneas de ruta
        self._clear_route_lines()
        self._clear_highlight_lines()
        
        # Resetear índices
        self.ruta_actual_idx = None
        self._changing_selection = False
        self._updating_ui = False
        self._updating_from_table = False
        
        # Limpiar historial cuando se crea/abre un nuevo proyecto
        self._limpiar_historial()
        
        # Limpiar visibilidad
        self.visibilidad_nodos.clear()
        self.visibilidad_rutas.clear()
        self.nodo_en_rutas.clear()
        
        # Resetear textos y estados de botones de visibilidad
        if hasattr(self.view, "btnOcultarTodo"):
            self.view.btnOcultarTodo.setText("Ocultar Nodos")
        if hasattr(self.view, "btnMostrarTodo"):
            self.view.btnMostrarTodo.setText("Ocultar Rutas")
            self.view.btnMostrarTodo.setEnabled(True)  # Habilitado inicialmente
        

    # +++ NUEVOS MÉTODOS PARA PARÁMETROS +++
    def mostrar_dialogo_parametros(self):
        """Muestra el diálogo de configuración de parámetros"""
        from View.dialogo_parametros import DialogoParametros
        
        # Obtener parámetros actuales del proyecto
        parametros_actuales = getattr(self.proyecto, 'parametros', None)
        
        dialogo = DialogoParametros(self.view, parametros_actuales)
        
        if dialogo.exec_() == QDialog.Accepted:
            nuevos_parametros = dialogo.obtener_parametros()
            
            # Guardar en el proyecto
            if not hasattr(self.proyecto, 'parametros'):
                self.proyecto.parametros = {}
            
            self.proyecto.parametros = nuevos_parametros
            self.proyecto_modificado = True

            QMessageBox.information(self.view, "Parámetros",
                                  "Parámetros guardados correctamente.")
    
    def mostrar_dialogo_parametros_playa(self):
        """Muestra el diálogo de configuración de parámetros de playa"""
        from View.dialogo_parametros_playa import DialogoParametrosPlaya
        
        # Obtener parámetros de playa actuales del proyecto
        parametros_playa_actuales = getattr(self.proyecto, 'parametros_playa', None)
        
        dialogo = DialogoParametrosPlaya(self.view, parametros_playa_actuales)
        
        if dialogo.exec_() == QDialog.Accepted:
            nuevos_parametros = dialogo.obtener_parametros()
            
            # Guardar en el proyecto
            if not hasattr(self.proyecto, 'parametros_playa'):
                self.proyecto.parametros_playa = {}
            
            self.proyecto.parametros_playa = nuevos_parametros
            self.proyecto_modificado = True

            QMessageBox.information(self.view, "Parámetros Playa",
                                  "Parámetros de playa guardados correctamente.")

    def mostrar_dialogo_parametros_carga_descarga(self):
        """Muestra el diálogo de configuración de parámetros de carga/descarga"""
        from View.dialogo_parametros_carga_descarga import DialogoParametrosCargaDescarga
        
        # Obtener parámetros de carga/descarga actuales del proyecto
        parametros_carga_descarga_actuales = getattr(self.proyecto, 'parametros_carga_descarga', None)
        
        dialogo = DialogoParametrosCargaDescarga(self.view, parametros_carga_descarga_actuales)
        
        if dialogo.exec_() == QDialog.Accepted:
            nuevos_parametros = dialogo.obtener_parametros()
            
            # Guardar en el proyecto
            if not hasattr(self.proyecto, 'parametros_carga_descarga'):
                self.proyecto.parametros_carga_descarga = {}
            
            self.proyecto.parametros_carga_descarga = nuevos_parametros
            self.proyecto_modificado = True

            QMessageBox.information(self.view, "Parámetros Carga/Descarga",
                                "Parámetros de carga/descarga guardados correctamente.")


    # --- Gestión de modos ---
    def cambiar_modo(self, boton):
        
        # Si el botón ya estaba activado y se hace clic, se desactiva
        if not boton.isChecked():
            # Desactivar todos los modos
            self.modo_actual = None
            self.mover_ctrl.desactivar()
            self.colocar_ctrl.desactivar()
            # Salir de modo duplicar si estaba activo
            if getattr(self, "_modo_duplicar_activo", False):
                self._salir_modo_duplicar()
            
            # IMPORTANTE: Desconectar señales de movimiento
            try:
                for item in self.scene.items():
                    if isinstance(item, NodoItem):
                        try:
                            item.moved.disconnect()
                        except Exception:
                            pass
            except Exception:
                pass
            
            # IMPORTANTE: CORRECCIÓN CRÍTICA - SIEMPRE DESACTIVAR EL CONTROLADOR DE RUTA
            try:
                self.ruta_ctrl.desactivar()
            except Exception as e:
                print(f"Error al desactivar ruta: {e}")
            
            # VOLVER AL MODO POR DEFECTO: navegación del mapa
            self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.ScrollHandDrag)
            
            # desactivar movimiento en nodos
            for item in self.scene.items():
                if isinstance(item, NodoItem):
                    try:
                        item.setFlag(item.ItemIsMovable, False)
                        item.setFlag(item.ItemIsFocusable, True)
                    except Exception:
                        pass
            
            # Restaurar colores normales de nodos
            self.restaurar_colores_nodos()
            
            
            # --- NUEVO: Actualizar descripción del modo ---
            self.actualizar_descripcion_modo()
            
            # --- NUEVO: Resetear estado de arrastre y actualizar cursor ---
            self._arrastrando_nodo = False
            self._cursor_sobre_nodo = False
            self._actualizar_cursor()
            
            return

        # Desactivar los otros botones
        otros_botones = [self.view.mover_button, self.view.colocar_vertice_button,
                         self.view.crear_ruta_button]
        if hasattr(self.view, "duplicar_nodo_button"):
            otros_botones.append(self.view.duplicar_nodo_button)
        for b in otros_botones:
            if b is not boton:
                b.setChecked(False)

        # Si cambiamos a un modo distinto de duplicar, salir del modo duplicar
        if getattr(self, "_modo_duplicar_activo", False) and \
                (not hasattr(self.view, "duplicar_nodo_button")
                 or boton is not self.view.duplicar_nodo_button):
            self._salir_modo_duplicar()

        if boton == self.view.mover_button:
            # --- MODO MOVER ---
            self.modo_actual = "mover"
            self.mover_ctrl.activar()
            self.colocar_ctrl.desactivar()
            
            # IMPORTANTE: Desactivar modo ruta
            try:
                self.ruta_ctrl.desactivar()
            except Exception:
                pass
            
            # IMPORTANTE: Desactivar arrastre del mapa (NoDrag)
            self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.NoDrag)

            # Activar movimiento en todos los nodos
            for item in self.scene.items():
                if isinstance(item, NodoItem):
                    try:
                        item.setFlag(item.ItemIsMovable, True)
                        item.setFlag(item.ItemIsFocusable, True)
                    except Exception:
                        pass

            
            # --- NUEVO: Actualizar descripción del modo ---
            self.actualizar_descripcion_modo("mover")
            
            # --- NUEVO: Resetear estado de arrastre y actualizar cursor ---
            self._arrastrando_nodo = False
            self._cursor_sobre_nodo = False
            self._actualizar_cursor()

        elif boton == self.view.colocar_vertice_button:
            # --- MODO COLOCAR ---
            self.modo_actual = "colocar"
            self.colocar_ctrl.activar()
            self.mover_ctrl.desactivar()
            
            # IMPORTANTE: Desactivar modo ruta
            try:
                self.ruta_ctrl.desactivar()
            except Exception:
                pass
            
            self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.NoDrag)
            
            
            # --- NUEVO: Actualizar descripción del modo ---
            self.actualizar_descripcion_modo("colocar")
            
            # --- NUEVO: Resetear estado de arrastre y actualizar cursor ---
            self._arrastrando_nodo = False
            self._cursor_sobre_nodo = False
            self._actualizar_cursor()

        elif hasattr(self.view, "duplicar_nodo_button") and boton == self.view.duplicar_nodo_button:
            # --- MODO DUPLICAR ---
            if not self.proyecto:
                print("✗ ERROR: No hay proyecto cargado. Crea o abre un proyecto primero.")
                boton.setChecked(False)
                QMessageBox.warning(self.view, "Error",
                                    "No hay proyecto cargado. Crea o abre un proyecto primero.")
                return
            self.modo_actual = "duplicar"
            self.mover_ctrl.desactivar()
            self.colocar_ctrl.desactivar()
            try:
                self.ruta_ctrl.desactivar()
            except Exception:
                pass
            self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.NoDrag)
            self._entrar_modo_duplicar()
            self._arrastrando_nodo = False
            self._cursor_sobre_nodo = False
            self._actualizar_cursor()

        elif boton == self.view.crear_ruta_button:
            # --- MODO RUTA ---
            self.modo_actual = "ruta"
            
            # IMPORTANTE: Verificar que tenemos un proyecto
            if not self.proyecto:
                print("✗ ERROR: No hay proyecto cargado. Crea o abre un proyecto primero.")
                boton.setChecked(False)
                QMessageBox.warning(self.view, "Error", 
                                "No hay proyecto cargado. Crea o abre un proyecto primero.")
                return
                    
            
            # Activar modo ruta
            self.ruta_ctrl.activar()
            self.mover_ctrl.desactivar()
            self.colocar_ctrl.desactivar()
            self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.NoDrag)
            
            
            # --- NUEVO: Actualizar descripción del modo ---
            self.actualizar_descripcion_modo("ruta")
            
            # --- NUEVO: Resetear estado de arrastre y actualizar cursor ---
            self._arrastrando_nodo = False
            self._cursor_sobre_nodo = False
            self._actualizar_cursor()

        # Actualizar líneas después de cambiar modo
        self.actualizar_lineas_rutas()
    
    # --- NUEVO MÉTODO: Actualizar descripción del modo ---
    def actualizar_descripcion_modo(self, modo=None):
        """
        Actualiza la descripción del modo actual en la barra inferior.
        Si no se especifica modo, usa self.modo_actual.
        """
        if modo is None:
            modo = self.modo_actual
        
        # Si no hay modo activo, usar navegación por defecto
        if modo is None:
            modo = "navegacion"
        
        # Llamar al método de la vista para actualizar
        if hasattr(self.view, 'actualizar_descripcion_modo'):
            try:
                self.view.actualizar_descripcion_modo(modo)
            except Exception as e:
                print(f"Error al actualizar descripción del modo: {e}")

    # --- MÉTODOS PARA MANEJO DE EVENTOS DE TECLADO ---
    
    def finalizar_ruta_actual(self):
        """Finaliza la creación de la ruta actual cuando se presiona Enter"""
        if self.modo_actual == "ruta":
            try:
                # Finalizar la ruta primero
                self.ruta_ctrl.finalizar_ruta_con_enter()
                
                # Desactivar el botón de ruta después de finalizar
                self.view.crear_ruta_button.setChecked(False)
                # Y llamar a cambiar_modo para limpiar todo
                self.cambiar_modo(self.view.crear_ruta_button)
                
                # --- NUEVO: Actualizar descripción al volver a modo navegación ---
                self.actualizar_descripcion_modo("navegacion")
                
            except Exception as e:
                print(f"Error al finalizar ruta con Enter: {e}")
    
    def cancelar_ruta_actual(self):
        """Cancela la creación de la ruta actual cuando se presiona Escape.
        También sale del modo duplicar si está activo."""
        # En lugar de código específico para ruta, llamamos al método general
        if self.modo_actual in ("ruta", "duplicar"):
            self.cancelar_modo_actual()
    
    def eliminar_nodo_seleccionado(self):
        """Elimina el nodo seleccionado cuando se presiona Suprimir, mostrando confirmación"""
        try:
            seleccionados_escena = self.scene.selectedItems()
            seleccionados_lista = self.view.nodosList.selectedItems()

            nodo_a_eliminar = None
            nodo_item_a_eliminar = None

            # 1) Buscar primero un NodoItem entre los seleccionados de la escena
            for item in seleccionados_escena:
                if isinstance(item, NodoItem):
                    nodo_a_eliminar = item.nodo
                    nodo_item_a_eliminar = item
                    break

            # 2) Si no hay nodo en la escena, mirar la lista lateral
            #    (puede caer aquí cuando el usuario seleccionó por la lista
            #    o cuando el nodo está oculto y no tiene NodoItem visible)
            if nodo_a_eliminar is None and seleccionados_lista:
                for it in seleccionados_lista:
                    candidato = it.data(Qt.UserRole)
                    if candidato is None:
                        # Fallback: buscar por widget.nodo_id
                        widget = self.view.nodosList.itemWidget(it)
                        if widget and hasattr(widget, 'nodo_id'):
                            candidato = self._obtener_nodo_actual(widget.nodo_id)
                    if candidato is not None:
                        nodo_a_eliminar = candidato
                        break

            if nodo_a_eliminar is None:
                # No hay nada que borrar — no mostramos error, simplemente salimos
                return

            nodo_id = nodo_a_eliminar.get('id')

            reply = QMessageBox.question(
                self.view,
                "Confirmar eliminación",
                f"¿Estás seguro de que quieres eliminar el nodo ID {nodo_id}?\n\n"
                f"Esta acción eliminará el nodo y reconfigurará las rutas que lo contengan.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply != QMessageBox.Yes:
                return

            # Si todavía no tenemos un NodoItem (selección por lista), intentar
            # localizarlo en la escena. Si tampoco está ahí, eliminar igual:
            # eliminar_nodo() tolera nodo_item=None y limpia por id.
            if nodo_item_a_eliminar is None:
                for sit in self.scene.items():
                    if isinstance(sit, NodoItem) and sit.nodo.get('id') == nodo_id:
                        nodo_item_a_eliminar = sit
                        break

            self.eliminar_nodo(nodo_a_eliminar, nodo_item_a_eliminar)

        except Exception as e:
            print(f"Error al eliminar nodo: {e}")
            QMessageBox.warning(self.view, "Error",
                            f"No se pudo eliminar el nodo:\n{str(e)}")

    def keyPressEvent(self, event):
        """Maneja eventos de teclado globales"""
        try:
            # Tecla Suprimir (Delete)
            if event.key() == Qt.Key_Delete:
                self.eliminar_nodo_seleccionado()
                event.accept()
            # Ctrl+Z para deshacer
            elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
                self.deshacer_movimiento()
                event.accept()
            # Ctrl+Y para rehacer
            elif event.key() == Qt.Key_Y and event.modifiers() == Qt.ControlModifier:
                self.rehacer_movimiento()
                event.accept()
            # Enter para finalizar ruta
            elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                self.finalizar_ruta_actual()
                event.accept()
            # Escape para cancelar cualquier modo activo y volver a navegación
            elif event.key() == Qt.Key_Escape:
                self.cancelar_modo_actual()
                event.accept()
            else:
                event.ignore()
        except Exception as e:
            print(f"Error en keyPressEvent: {e}")
            event.ignore()

    def cancelar_modo_actual(self):
        """
        Cancela cualquier modo activo y regresa al modo navegación.
        Se llama cuando se presiona la tecla Escape.
        """
        try:
            
            # Si ya estamos en modo navegación (None), no hacer nada
            if self.modo_actual is None:
                return
            
            # Determinar qué botón está activo basado en el modo actual
            boton_activo = None
            
            if self.modo_actual == "mover":
                boton_activo = self.view.mover_button
            
            elif self.modo_actual == "colocar":
                boton_activo = self.view.colocar_vertice_button
                
                # IMPORTANTE: Cancelar cualquier acción pendiente en modo colocar
                try:
                    self.colocar_ctrl.desactivar()
                except Exception as e:
                    print(f"Error al desactivar modo colocar: {e}")
            
            elif self.modo_actual == "ruta":
                boton_activo = self.view.crear_ruta_button

                # IMPORTANTE: Cancelar la ruta actual primero
                try:
                    self.ruta_ctrl.cancelar_ruta_actual()
                except Exception as e:
                    print(f"Error al cancelar ruta: {e}")

            elif self.modo_actual == "duplicar":
                if hasattr(self.view, "duplicar_nodo_button"):
                    boton_activo = self.view.duplicar_nodo_button
                # _salir_modo_duplicar se invoca desde cambiar_modo al desactivar
            
            # Desactivar el botón y cambiar al modo navegación
            if boton_activo and boton_activo.isChecked():
                boton_activo.setChecked(False)
                
                # Llamar a cambiar_modo para realizar la desactivación completa
                self.cambiar_modo(boton_activo)
            
            # Forzar actualización del cursor
            self._actualizar_cursor()
            
            # Mostrar mensaje de confirmación
            
            # Actualizar descripción del modo
            self.actualizar_descripcion_modo("navegacion")
            
        except Exception as e:
            print(f"Error al cancelar modo actual: {e}")

    # --- SISTEMA DE DESHACER/REHACER (UNDO/REDO) ---
    # --- MÉTODOS PARA REGISTRAR CAMBIOS DE PROPIEDADES ---
    def registrar_cambio_propiedad_nodo(self, nodo_id, propiedad, valor_anterior, valor_nuevo):
        """
        Registra un cambio de propiedad de un nodo en el historial UNDO/REDO.
        
        Args:
            nodo_id: ID del nodo
            propiedad: Nombre de la propiedad (ej: 'objetivo', 'es_cargador')
            valor_anterior: Valor antes del cambio
            valor_nuevo: Valor después del cambio
        """
        if self._ejecutando_deshacer_rehacer:
            return
        
        try:
            # Si estamos en medio del historial (por deshacer previo), eliminar movimientos futuros
            if self.indice_historial < len(self.historial_movimientos) - 1:
                self.historial_movimientos = self.historial_movimientos[:self.indice_historial + 1]
            
            # Crear entrada del historial
            cambio = {
                'tipo': 'cambio_propiedad_nodo',
                'nodo_id': nodo_id,
                'propiedad': propiedad,
                'valor_anterior': valor_anterior,
                'valor_nuevo': valor_nuevo,
                'descripcion': f"Cambio de {propiedad} en nodo {nodo_id}: {valor_anterior} → {valor_nuevo}"
            }
            
            # Agregar al historial
            self.historial_movimientos.append(cambio)
            
            # Limitar tamaño del historial
            if len(self.historial_movimientos) > self.max_historial:
                self.historial_movimientos.pop(0)
            else:
                self.indice_historial += 1
            
            # Mover puntero a la última posición
            self.indice_historial = len(self.historial_movimientos) - 1
            
            
        except Exception as e:
            print(f"Error registrando cambio de propiedad de nodo: {e}")

    def _registrar_creacion_nodo(self, nodo):
        """
        Registra la creación de un nodo en el historial UNDO/REDO.
        
        Args:
            nodo: El nodo creado (con ID, X, Y, objetivo, es_cargador, etc.)
        """
        if self._ejecutando_deshacer_rehacer:
            return
        
        try:
            # Si estamos en medio del historial (por deshacer previo), eliminar movimientos futuros
            if self.indice_historial < len(self.historial_movimientos) - 1:
                self.historial_movimientos = self.historial_movimientos[:self.indice_historial + 1]
            
            # Crear entrada del historial
            creacion = {
                'tipo': 'creacion',
                'nodo': copy.deepcopy(nodo),
                'descripcion': f"Creación de nodo ID {nodo.get('id')}"
            }
            
            # Agregar al historial
            self.historial_movimientos.append(creacion)
            
            # Limitar tamaño del historial
            if len(self.historial_movimientos) > self.max_historial:
                self.historial_movimientos.pop(0)
            
            # Actualizar el índice al nuevo elemento
            self.indice_historial = len(self.historial_movimientos) - 1
            
            
        except Exception as e:
            print(f"Error registrando creación de nodo: {e}")

    # --- MÉTODOS PARA DESHACER/REHACER CREACIÓN DE NODOS ---
    def _deshacer_creacion_nodo(self, accion):
        """Deshace la creación de un nodo (es decir, lo elimina)"""
        try:
            self._ejecutando_deshacer_rehacer = True
            
            nodo = accion['nodo']
            nodo_id = nodo.get('id')
            
            
            # ANTES de eliminar: verificar si está en la secuencia de ruta
            en_secuencia_ruta = False
            if hasattr(self, 'ruta_ctrl') and self.ruta_ctrl.activo:
                en_secuencia_ruta = self.ruta_ctrl.contiene_nodo_en_secuencia(nodo_id)
            
            # Buscar el nodo en la escena y en el proyecto
            nodo_item_a_eliminar = None
            nodo_en_proyecto = None
            
            # Buscar en la escena
            for item in self.scene.items():
                if isinstance(item, NodoItem) and item.nodo.get('id') == nodo_id:
                    nodo_item_a_eliminar = item
                    nodo_en_proyecto = item.nodo
                    break
            
            # Si no está en la escena, buscar en el proyecto
            if not nodo_en_proyecto:
                for n in self.proyecto.nodos:
                    if n.get('id') == nodo_id:
                        nodo_en_proyecto = n
                        break
            
            # Eliminar el nodo (sin registrar en historial)
            if nodo_en_proyecto:
                # Usar eliminación sin historial
                self._eliminar_nodo_sin_historial(nodo_en_proyecto, nodo_item_a_eliminar)
            
            # DESPUÉS de eliminar: si estaba en secuencia de ruta, actualizar
            if en_secuencia_ruta:
                self.ruta_ctrl.remover_nodo_de_secuencia(nodo_id)
                
                # Si después de remover no quedan nodos, limpiar estado
                if not self.ruta_ctrl._nodes_seq:
                    pass
                    # Restaurar colores de todos los nodos
                    self.restaurar_colores_nodos()
            
            # Decrementar índice del historial
            self.indice_historial -= 1
            
            
        except Exception as e:
            print(f"Error deshaciendo creación de nodo: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._ejecutando_deshacer_rehacer = False

    def _rehacer_creacion_nodo(self, accion):
        """Rehace la creación de un nodo (es decir, lo vuelve a crear)"""
        try:
            self._ejecutando_deshacer_rehacer = True
            
            nodo = accion['nodo']
            nodo_id = nodo.get('id')
            x = nodo.get('X')
            y = nodo.get('Y')
            objetivo = nodo.get('objetivo', 0)
            es_cargador = nodo.get('es_cargador', 0)
            angulo = nodo.get('A', 0)
            
            
            # Verificar si el nodo ya existe (no debería, pero por seguridad)
            nodo_existente = None
            for n in self.proyecto.nodos:
                if n.get('id') == nodo_id:
                    nodo_existente = n
                    break
            
            if nodo_existente:
                pass
            else:
                # Crear nuevo nodo en el proyecto (sin registrar en historial)
                nuevo_nodo = {
                    "id": nodo_id,
                    "X": x,
                    "Y": y,
                    "objetivo": objetivo,
                    "es_cargador": es_cargador,
                    "A": angulo
                }
                self.proyecto.nodos.append(nuevo_nodo)
                
                # Crear NodoItem visual
                nodo_item = self._create_nodo_item(nuevo_nodo)
                
                # Inicializar visibilidad
                self._inicializar_nodo_visibilidad(nuevo_nodo, agregar_a_lista=True)
                
                # Actualizar lista de nodos
                self._actualizar_lista_nodos_con_widgets()
                
                # Redibujar rutas si es necesario
                self._dibujar_rutas()
                
            
            # IMPORTANTE: No necesitamos agregar a secuencia de ruta automáticamente
            # porque el usuario debe decidir si quiere añadirlo nuevamente a la ruta
            
        except Exception as e:
            print(f"Error rehaciendo creación de nodo: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._ejecutando_deshacer_rehacer = False

    def registrar_cambio_propiedad_ruta(self, ruta_idx, propiedad, valor_anterior, valor_nuevo):
        """
        Registra un cambio de propiedad de una ruta en el historial UNDO/REDO.
        
        Args:
            ruta_idx: Índice de la ruta
            propiedad: Nombre de la propiedad (ej: 'nombre', 'origen', 'destino', 'visita')
            valor_anterior: Valor antes del cambio
            valor_nuevo: Valor después del cambio
        """
        if self._ejecutando_deshacer_rehacer:
            return
        
        try:
            # Si estamos en medio del historial (por deshacer previo), eliminar movimientos futuros
            if self.indice_historial < len(self.historial_movimientos) - 1:
                self.historial_movimientos = self.historial_movimientos[:self.indice_historial + 1]
            
            # Crear entrada del historial
            cambio = {
                'tipo': 'cambio_propiedad_ruta',
                'ruta_idx': ruta_idx,
                'propiedad': propiedad,
                'valor_anterior': valor_anterior,
                'valor_nuevo': valor_nuevo,
                'descripcion': f"Cambio de {propiedad} en ruta {ruta_idx}"
            }
            
            # Agregar al historial
            self.historial_movimientos.append(cambio)
            
            # Limitar tamaño del historial
            if len(self.historial_movimientos) > self.max_historial:
                self.historial_movimientos.pop(0)
            else:
                self.indice_historial += 1
            
            # Mover puntero a la última posición
            self.indice_historial = len(self.historial_movimientos) - 1
            
            
        except Exception as e:
            print(f"Error registrando cambio de propiedad de ruta: {e}")

    def _deshacer_cambio_propiedad_nodo(self, accion):
        """Deshace un cambio de propiedad de nodo usando el patrón observer"""
        try:
            self._ejecutando_deshacer_rehacer = True
            
            nodo_id = accion['nodo_id']
            propiedad = accion['propiedad']
            valor_anterior = accion['valor_anterior']
            
            
            # Buscar el nodo
            nodo = self.obtener_nodo_por_id(nodo_id)
            if not nodo:
                print(f"Error: Nodo {nodo_id} no encontrado")
                self._ejecutando_deshacer_rehacer = False
                return
            
            # Convertir valores si es necesario
            if propiedad in ["X", "Y"]:
                # Convertir de metros a píxeles
                try:
                    valor_metros = float(valor_anterior)
                    valor_pixeles = self.metros_a_pixeles(valor_metros)
                    
                    # IMPORTANTE: Usar el proyecto para actualizar (emitirá señal)
                    self.proyecto.actualizar_nodo({
                        "id": nodo_id,
                        propiedad: valor_pixeles
                    })
                    
                    
                except ValueError as e:
                    print(f"Error convirtiendo valor: {e}")
            else:
                # Otras propiedades - usar el proyecto para actualizar
                self.proyecto.actualizar_nodo({
                    "id": nodo_id,
                    propiedad: valor_anterior
                })
                
            
            # Decrementar índice del historial
            self.indice_historial -= 1
            
        except Exception as e:
            print(f"Error deshaciendo cambio de propiedad de nodo: {e}")
        finally:
            self._ejecutando_deshacer_rehacer = False

    def _rehacer_cambio_propiedad_nodo(self, accion):
        """Rehace un cambio de propiedad de nodo usando el patrón observer"""
        try:
            self._ejecutando_deshacer_rehacer = True
            
            nodo_id = accion['nodo_id']
            propiedad = accion['propiedad']
            valor_nuevo = accion['valor_nuevo']
            
            
            # Buscar el nodo
            nodo = self.obtener_nodo_por_id(nodo_id)
            if not nodo:
                print(f"Error: Nodo {nodo_id} no encontrado")
                self._ejecutando_deshacer_rehacer = False
                return
            
            # Convertir valores si es necesario
            if propiedad in ["X", "Y"]:
                # Convertir de metros a píxeles
                try:
                    valor_metros = float(valor_nuevo)
                    valor_pixeles = self.metros_a_pixeles(valor_metros)
                    
                    # IMPORTANTE: Usar el proyecto para actualizar (emitirá señal)
                    self.proyecto.actualizar_nodo({
                        "id": nodo_id,
                        propiedad: valor_pixeles
                    })
                    
                    
                except ValueError as e:
                    print(f"Error convirtiendo valor: {e}")
            else:
                # Otras propiedades - usar el proyecto para actualizar
                self.proyecto.actualizar_nodo({
                    "id": nodo_id,
                    propiedad: valor_nuevo
                })
                
            
        except Exception as e:
            print(f"Error rehaciendo cambio de propiedad de nodo: {e}")
        finally:
            self._ejecutando_deshacer_rehacer = False

    def _deshacer_cambio_propiedad_ruta(self, accion):
        """Deshace un cambio de propiedad de ruta"""
        try:
            self._ejecutando_deshacer_rehacer = True
            
            ruta_idx = accion['ruta_idx']
            propiedad = accion['propiedad']
            valor_anterior = accion['valor_anterior']
            
            
            # Verificar que existe la ruta
            if ruta_idx >= len(self.proyecto.rutas):
                print(f"Error: Ruta {ruta_idx} no encontrada")
                self._ejecutando_deshacer_rehacer = False
                return
            
            ruta = self.proyecto.rutas[ruta_idx]
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta
            
            # Aplicar el valor anterior según la propiedad
            if propiedad == "nombre":
                ruta_dict["nombre"] = valor_anterior
            elif propiedad == "origen":
                try:
                    origen_id = int(valor_anterior)
                    nodo_existente = next((n for n in self.proyecto.nodos 
                                        if self._obtener_id_nodo(n) == origen_id), None)
                    if nodo_existente:
                        ruta_dict["origen"] = nodo_existente
                    else:
                        ruta_dict["origen"] = {"id": origen_id, "X": 0, "Y": 0}
                except ValueError:
                    print(f"Error: ID de origen inválido: {valor_anterior}")
            elif propiedad == "destino":
                try:
                    destino_id = int(valor_anterior)
                    nodo_existente = next((n for n in self.proyecto.nodos 
                                        if self._obtener_id_nodo(n) == destino_id), None)
                    if nodo_existente:
                        ruta_dict["destino"] = nodo_existente
                    else:
                        ruta_dict["destino"] = {"id": destino_id, "X": 0, "Y": 0}
                except ValueError:
                    print(f"Error: ID de destino inválido: {valor_anterior}")
            elif propiedad == "visita":
                try:
                    # Parsear lista de IDs
                    if valor_anterior.startswith('[') and valor_anterior.endswith(']'):
                        valor_anterior = valor_anterior[1:-1]
                    
                    ids_texto = [id_str.strip() for id_str in valor_anterior.split(',')] if valor_anterior else []
                    nueva_visita = []
                    
                    for id_str in ids_texto:
                        if id_str:
                            try:
                                nodo_id = int(id_str)
                                nodo_existente = next((n for n in self.proyecto.nodos 
                                                    if self._obtener_id_nodo(n) == nodo_id), None)
                                if nodo_existente:
                                    nueva_visita.append(nodo_existente)
                                else:
                                    nueva_visita.append({"id": nodo_id, "X": 0, "Y": 0})
                            except ValueError:
                                pass
                    
                    ruta_dict["visita"] = nueva_visita
                except Exception as e:
                    print(f"Error procesando visita: {e}")
            
            # Actualizar la ruta en el proyecto
            self.proyecto.actualizar_ruta(ruta_idx, ruta_dict)
            
            # Actualizar UI
            self._actualizar_widget_ruta_en_lista(ruta_idx)
            self._dibujar_rutas()
            
            # Si esta ruta está seleccionada, actualizar propiedades
            if self.ruta_actual_idx == ruta_idx:
                self.mostrar_propiedades_ruta(ruta)
            
            # Decrementar índice del historial
            self.indice_historial -= 1
            
            
        except Exception as e:
            print(f"Error deshaciendo cambio de propiedad de ruta: {e}")
        finally:
            self._ejecutando_deshacer_rehacer = False

    def _rehacer_cambio_propiedad_ruta(self, accion):
        """Rehace un cambio de propiedad de ruta"""
        try:
            self._ejecutando_deshacer_rehacer = True
            
            ruta_idx = accion['ruta_idx']
            propiedad = accion['propiedad']
            valor_nuevo = accion['valor_nuevo']
            
            
            # Verificar que existe la ruta
            if ruta_idx >= len(self.proyecto.rutas):
                print(f"Error: Ruta {ruta_idx} no encontrada")
                self._ejecutando_deshacer_rehacer = False
                return
            
            ruta = self.proyecto.rutas[ruta_idx]
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta
            
            # Aplicar el valor nuevo según la propiedad
            if propiedad == "nombre":
                ruta_dict["nombre"] = valor_nuevo
            elif propiedad == "origen":
                try:
                    origen_id = int(valor_nuevo)
                    nodo_existente = next((n for n in self.proyecto.nodos 
                                        if self._obtener_id_nodo(n) == origen_id), None)
                    if nodo_existente:
                        ruta_dict["origen"] = nodo_existente
                    else:
                        ruta_dict["origen"] = {"id": origen_id, "X": 0, "Y": 0}
                except ValueError:
                    print(f"Error: ID de origen inválido: {valor_nuevo}")
            elif propiedad == "destino":
                try:
                    destino_id = int(valor_nuevo)
                    nodo_existente = next((n for n in self.proyecto.nodos 
                                        if self._obtener_id_nodo(n) == destino_id), None)
                    if nodo_existente:
                        ruta_dict["destino"] = nodo_existente
                    else:
                        ruta_dict["destino"] = {"id": destino_id, "X": 0, "Y": 0}
                except ValueError:
                    print(f"Error: ID de destino inválido: {valor_nuevo}")
            elif propiedad == "visita":
                try:
                    # Parsear lista de IDs
                    if valor_nuevo.startswith('[') and valor_nuevo.endswith(']'):
                        valor_nuevo = valor_nuevo[1:-1]
                    
                    ids_texto = [id_str.strip() for id_str in valor_nuevo.split(',')] if valor_nuevo else []
                    nueva_visita = []
                    
                    for id_str in ids_texto:
                        if id_str:
                            try:
                                nodo_id = int(id_str)
                                nodo_existente = next((n for n in self.proyecto.nodos 
                                                    if self._obtener_id_nodo(n) == nodo_id), None)
                                if nodo_existente:
                                    nueva_visita.append(nodo_existente)
                                else:
                                    nueva_visita.append({"id": nodo_id, "X": 0, "Y": 0})
                            except ValueError:
                                pass
                    
                    ruta_dict["visita"] = nueva_visita
                except Exception as e:
                    print(f"Error procesando visita: {e}")
            
            # Actualizar la ruta en el proyecto
            self.proyecto.actualizar_ruta(ruta_idx, ruta_dict)
            
            # Actualizar UI
            self._actualizar_widget_ruta_en_lista(ruta_idx)
            self._dibujar_rutas()
            
            # Si esta ruta está seleccionada, actualizar propiedades
            if self.ruta_actual_idx == ruta_idx:
                self.mostrar_propiedades_ruta(ruta)
            
            
        except Exception as e:
            print(f"Error rehaciendo cambio de propiedad de ruta: {e}")
        finally:
            self._ejecutando_deshacer_rehacer = False


    def _limpiar_historial(self):
        """Limpia el historial de movimientos"""
        self.historial_movimientos = []
        self.indice_historial = -1
        self.movimiento_actual = None
        print("Historial de movimientos limpiado")
    
    def registrar_movimiento_iniciado(self, nodo_item, x_inicial, y_inicial):
        """Registra el inicio de un movimiento (cuando se empieza a arrastrar un nodo)"""
        try:
            nodo_id = nodo_item.nodo.get('id')
            if nodo_id is None:
                return
                
            self.movimiento_actual = {
                'nodo_item': nodo_item,
                'nodo_id': nodo_id,
                'x_inicial': x_inicial,
                'y_inicial': y_inicial
            }
            
            # NUEVO: Iniciar arrastre para cambiar cursor
            self.nodo_arrastre_iniciado()
        except Exception as e:
            print(f"Error registrando movimiento iniciado: {e}")
    
    def registrar_movimiento_finalizado(self, nodo_item, x_inicial, y_inicial, x_final, y_final):
        """Registra el final de un movimiento y lo agrega al historial"""
        self.proyecto_modificado = True
        try:
            # Verificar que tenemos un movimiento en progreso
            if not self.movimiento_actual:
                return
                
            # Verificar que es el mismo nodo
            nodo_id = nodo_item.nodo.get('id')
            if nodo_id != self.movimiento_actual['nodo_id']:
                return
            
            # Verificar que realmente hubo movimiento
            if x_inicial == x_final and y_inicial == y_final:
                self.movimiento_actual = None
                return
            
            # Si estamos en medio del historial (por deshacer previo), eliminar movimientos futuros
            if self.indice_historial < len(self.historial_movimientos) - 1:
                self.historial_movimientos = self.historial_movimientos[:self.indice_historial + 1]
            
            # Crear entrada del historial
            movimiento = {
                'nodo_id': nodo_id,
                'x_anterior': x_inicial,
                'y_anterior': y_inicial,
                'x_nueva': x_final,
                'y_nueva': y_final
            }
            
            # Agregar al historial
            self.historial_movimientos.append(movimiento)
            
            # Limitar tamaño del historial a max_historial
            if len(self.historial_movimientos) > self.max_historial:
                # Eliminar el movimiento más antiguo
                self.historial_movimientos.pop(0)
            else:
                # Incrementar índice solo si no estamos eliminando elementos
                self.indice_historial += 1
            
            # Mover puntero a la última posición
            self.indice_historial = len(self.historial_movimientos) - 1
            
            # Mostrar en metros
            x_inicial_m = self.pixeles_a_metros(x_inicial)
            y_inicial_m = self.pixeles_a_metros(y_inicial)
            x_final_m = self.pixeles_a_metros(x_final)
            y_final_m = self.pixeles_a_metros(y_final)
            
        except Exception as e:
            print(f"Error registrando movimiento finalizado: {e}")
        finally:
            self.movimiento_actual = None
            # NUEVO: Terminar arrastre para cambiar cursor
            self.nodo_arrastre_terminado()
    
    def deshacer_movimiento(self):
        """Deshace el último movimiento (Ctrl+Z)"""
        if self.indice_historial < 0:
            return
            
        try:
            # Obtener la acción actual
            accion = self.historial_movimientos[self.indice_historial]
            
            # Verificar el tipo de acción
            tipo = accion.get('tipo')
            
            if tipo == 'eliminacion':
                self._deshacer_eliminacion_nodo(accion)
            elif tipo == 'cambio_propiedad_nodo':
                self._deshacer_cambio_propiedad_nodo(accion)
            elif tipo == 'cambio_propiedad_ruta':
                self._deshacer_cambio_propiedad_ruta(accion)
            elif tipo == 'creacion':
                self._deshacer_creacion_nodo(accion)  # NUEVO
            else:
                # Acción de movimiento (comportamiento original)
                self._deshacer_movimiento_original(accion)
                
        except Exception as e:
            print(f"Error deshaciendo acción: {e}")

        
    def _deshacer_movimiento_original(self, movimiento):
        """Método auxiliar para deshacer movimientos (código original)"""
        nodo_id = movimiento['nodo_id']
        x_anterior = movimiento['x_anterior']
        y_anterior = movimiento['y_anterior']
        
        # Mostrar en metros
        x_anterior_m = self.pixeles_a_metros(x_anterior)
        y_anterior_m = self.pixeles_a_metros(y_anterior)
        
        # Buscar el nodo en la escena
        nodo_encontrado = False
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                if item.nodo.get('id') == nodo_id:
                    # Mover el nodo a la posición anterior
                    item.setPos(x_anterior - item.size / 2, y_anterior - item.size / 2)
                    
                    # Actualizar el modelo
                    if isinstance(item.nodo, dict):
                        item.nodo["X"] = x_anterior
                        item.nodo["Y"] = y_anterior
                    else:
                        setattr(item.nodo, "X", x_anterior)
                        setattr(item.nodo, "Y", y_anterior)
                    
                    # Actualizar UI
                    self.actualizar_lista_nodo(item.nodo)
                    self.actualizar_propiedades_valores(item.nodo, claves=("X", "Y"))
                    
                    # Actualizar rutas
                    self._dibujar_rutas()
                    
                    nodo_encontrado = True
                    break
        
        if nodo_encontrado:
            # Decrementar índice del historial
            self.indice_historial -= 1
        else:
            print(f"Error: No se encontró el nodo {nodo_id}")

    def _deshacer_eliminacion_nodo(self, eliminacion):
        """
        Deshace la eliminación de un nodo restaurándolo junto con sus rutas.
        Usa el estado 'antes' guardado en el historial.
        """
        try:
            nodo = eliminacion['nodo']
            rutas_afectadas = eliminacion['rutas_afectadas']
            nodo_id = nodo.get('id')
            
            
            # 1) Restaurar el nodo en el proyecto
            self.proyecto.nodos.append(nodo)
            
            # 2) Restaurar las rutas afectadas a su estado original
            for ruta_info in rutas_afectadas:
                ruta_idx = ruta_info['indice']
                ruta_original = ruta_info['ruta_original']
                
                if ruta_idx < len(self.proyecto.rutas):
                    self.proyecto.rutas[ruta_idx] = ruta_original
                else:
                    self.proyecto.rutas.append(ruta_original)
            
            # 3) Restaurar visibilidad y relaciones (usar estado del momento actual)
            self.visibilidad_nodos[nodo_id] = True
            
            # Reconstruir relaciones para este nodo
            if nodo_id not in self.nodo_en_rutas:
                self.nodo_en_rutas[nodo_id] = []
            
            # Buscar en qué rutas está este nodo
            for idx, ruta in enumerate(self.proyecto.rutas):
                try:
                    ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                    self._normalize_route_nodes(ruta_dict)
                    
                    # Verificar si la ruta contiene el nodo
                    if self._ruta_contiene_nodo(ruta_dict, nodo_id):
                        if idx not in self.nodo_en_rutas[nodo_id]:
                            self.nodo_en_rutas[nodo_id].append(idx)
                except Exception as e:
                    print(f"Error verificando ruta {idx}: {e}")
            
            # 4) Crear y añadir el NodoItem visual a la escena
            nodo_item = self._create_nodo_item(nodo)
            
            # 5) Inicializar visibilidad del nodo restaurado
            self._inicializar_nodo_visibilidad(nodo, agregar_a_lista=True)
            
            # 6) Actualizar listas y dibujar rutas
            self._actualizar_lista_nodos_con_widgets()
            self._actualizar_lista_rutas_con_widgets()
            self._dibujar_rutas()
            
            # 7) Decrementar índice del historial
            self.indice_historial -= 1
            
            
        except Exception as e:
            print(f"Error deshaciendo eliminación: {e}")

    def _eliminar_nodo_sin_historial(self, nodo, nodo_item):
        """
        Elimina un nodo sin registrar en el historial UNDO/REDO.
        Usado para rehacer eliminaciones y para deshacer creaciones.
        """
        try:
            nodo_id = nodo.get("id")
            
            # 1) Quitar de la escena el NodoItem visual
            try:
                if getattr(nodo_item, "scene", None) and nodo_item.scene() is not None:
                    self.scene.removeItem(nodo_item)
            except Exception:
                pass
            
            # 2) Quitar del modelo
            for i, n in enumerate(self.proyecto.nodos):
                if n.get("id") == nodo_id:
                    self.proyecto.nodos.pop(i)
                    break
            
            # 3) Eliminar de visibilidad y relaciones
            if nodo_id in self.visibilidad_nodos:
                del self.visibilidad_nodos[nodo_id]
            if nodo_id in self.nodo_en_rutas:
                del self.nodo_en_rutas[nodo_id]
            
            # 4) Reconfigurar rutas
            self._reconfigurar_rutas_por_eliminacion(nodo_id)
            
            # 5) IMPORTANTE: Reconstruir relaciones de TODAS las rutas después de la eliminación
            self._actualizar_todas_relaciones_nodo_ruta()
            
            # 6) Actualizar UI
            self._actualizar_lista_nodos_con_widgets()
            self._dibujar_rutas()
            self._actualizar_lista_rutas_con_widgets()
            
            
        except Exception as e:
            print(f"Error en eliminación sin historial: {e}")

    def _rehacer_eliminacion_nodo(self, eliminacion):
        """
        Rehace la eliminación de un nodo restaurando el estado COMPLETO después de la eliminación.
        """
        try:
            nodo = eliminacion['nodo']
            rutas_despues = eliminacion['rutas_despues']
            nodo_id = nodo.get('id')
            
            
            # 1) RESTAURAR ESTADO COMPLETO DE LAS RUTAS
            self.proyecto.rutas = []
            for ruta_dict in rutas_despues:
                if ruta_dict is not None:
                    self.proyecto.rutas.append(ruta_dict)
            
            # 2) RESTAURAR ESTADO COMPLETO DE VISIBILIDAD
            self.visibilidad_nodos = eliminacion.get('visibilidad_nodos_despues', {})
            self.visibilidad_rutas = eliminacion.get('visibilidad_rutas_despues', {})
            self.nodo_en_rutas = eliminacion.get('nodo_en_rutas_despues', {})
            
            # 3) ACTUALIZAR NODOS DEL PROYECTO (eliminar el nodo reinsertado)
            self.proyecto.nodos = [n for n in self.proyecto.nodos if n.get('id') != nodo_id]
            
            # 4) ELIMINAR NODOITEM DE LA ESCENA
            nodo_item_a_eliminar = None
            for item in self.scene.items():
                if isinstance(item, NodoItem) and item.nodo.get('id') == nodo_id:
                    nodo_item_a_eliminar = item
                    break
            
            if nodo_item_a_eliminar:
                try:
                    if nodo_item_a_eliminar.scene() is not None:
                        self.scene.removeItem(nodo_item_a_eliminar)
                except Exception as e:
                    print(f"Error removiendo nodo de escena: {e}")
            
            # 5) ACTUALIZAR UI COMPLETA
            self._actualizar_lista_nodos_con_widgets()
            self._actualizar_lista_rutas_con_widgets()
            self._dibujar_rutas()
            
            
        except Exception as e:
            print(f"Error rehaciendo eliminación: {e}")
            # En caso de error, revertir el incremento del índice
            if self.indice_historial > 0:
                self.indice_historial -= 1

    def _rehacer_movimiento_original(self, movimiento):
        """Método auxiliar para rehacer movimientos (código original)"""
        nodo_id = movimiento['nodo_id']
        x_nueva = movimiento['x_nueva']
        y_nueva = movimiento['y_nueva']
        
        # Mostrar en metros
        x_nueva_m = self.pixeles_a_metros(x_nueva)
        y_nueva_m = self.pixeles_a_metros(y_nueva)
        
        # Buscar el nodo en la escena
        nodo_encontrado = False
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                if item.nodo.get('id') == nodo_id:
                    # Mover el nodo a la nueva posición
                    item.setPos(x_nueva - item.size / 2, y_nueva - item.size / 2)
                    
                    # Actualizar el modelo
                    if isinstance(item.nodo, dict):
                        item.nodo["X"] = x_nueva
                        item.nodo["Y"] = y_nueva
                    else:
                        setattr(item.nodo, "X", x_nueva)
                        setattr(item.nodo, "Y", y_nueva)
                    
                    # Actualizar UI
                    self.actualizar_lista_nodo(item.nodo)
                    self.actualizar_propiedades_valores(item.nodo, claves=("X", "Y"))
                    
                    # Actualizar rutas
                    self._dibujar_rutas()
                    
                    nodo_encontrado = True
                    break
        
        if not nodo_encontrado:
            print(f"Error: No se encontró el nodo {nodo_id}")
            # Si no encontramos el nodo, revertir el incremento del índice
            self.indice_historial -= 1

    
    def rehacer_movimiento(self):
        """Rehacer el movimiento deshecho (Ctrl+Y)"""
        if self.indice_historial >= len(self.historial_movimientos) - 1:
            return
            
        try:
            # Incrementar índice primero
            self.indice_historial += 1
            
            # Obtener la acción a rehacer
            accion = self.historial_movimientos[self.indice_historial]
            
            # Verificar el tipo de acción
            tipo = accion.get('tipo')
            
            if tipo == 'eliminacion':
                self._rehacer_eliminacion_nodo(accion)
            elif tipo == 'cambio_propiedad_nodo':
                self._rehacer_cambio_propiedad_nodo(accion)
            elif tipo == 'cambio_propiedad_ruta':
                self._rehacer_cambio_propiedad_ruta(accion)
            elif tipo == 'creacion':
                self._rehacer_creacion_nodo(accion)  # NUEVO
            else:
                # Acción de movimiento (comportamiento original)
                self._rehacer_movimiento_original(accion)
                
        except Exception as e:
            print(f"Error rehaciendo acción: {e}")
            # En caso de error, revertir el incremento del índice
            if self.indice_historial > 0:
                self.indice_historial -= 1

    def _ruta_contiene_nodo(self, ruta_dict, nodo_id):
        """Verifica si una ruta contiene un nodo específico"""
        try:
            # Origen
            origen = ruta_dict.get("origen")
            if origen and isinstance(origen, dict) and origen.get('id') == nodo_id:
                return True
            
            # Destino
            destino = ruta_dict.get("destino")
            if destino and isinstance(destino, dict) and destino.get('id') == nodo_id:
                return True
            
            # Visita
            for nodo_visita in ruta_dict.get("visita", []):
                if isinstance(nodo_visita, dict) and nodo_visita.get('id') == nodo_id:
                    return True
            
            return False
        except Exception:
            return False

    # --- FUNCIONES DE PROYECTO ---

    def _abrir_nueva_ventana(self):
        """Lanza una nueva instancia independiente de la aplicación (sin proyecto)"""
        self._abrir_en_nueva_ventana(None)

    def _abrir_en_nueva_ventana(self, ruta_archivo=None):
        """Lanza una nueva instancia de la app, opcionalmente con un proyecto"""
        import subprocess
        import sys
        from pathlib import Path
        main_py = str(Path(__file__).resolve().parent.parent / "main.py")
        cmd = [sys.executable, main_py]
        if ruta_archivo:
            cmd.append(ruta_archivo)
        subprocess.Popen(cmd, cwd=str(Path(main_py).parent))

    def nuevo_proyecto(self):
        # Verificar cambios sin guardar antes de crear uno nuevo
        if self.proyecto and self.proyecto_modificado:
            resp = QMessageBox.question(
                self.view, "Proyecto sin guardar",
                "Hay cambios sin guardar. ¿Desea guardar antes de crear un nuevo proyecto?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if resp == QMessageBox.Cancel:
                return
            if resp == QMessageBox.Yes:
                self.guardar_proyecto()

        ruta_mapa, _ = QFileDialog.getOpenFileName(
            self.view, "Seleccionar mapa", "",
            "Mapas (*.stcm *.png *.jpg *.jpeg *.bmp);;STCM (*.stcm);;Imágenes (*.png *.jpg *.jpeg *.bmp)"
        )
        if not ruta_mapa:
            return

        stcm_data = None
        if ruta_mapa.lower().endswith(".stcm"):
            try:
                stcm_data = parse_stcm(ruta_mapa)
                ruta_mapa = stcm_data.image_path  # Usar el PNG generado
            except Exception as err:
                print("✗ Error al parsear archivo STCM:", err)
                return

        # Crear nuevo proyecto
        self.proyecto = Proyecto(ruta_mapa)
        self.ruta_archivo_actual = None  # Proyecto nuevo, sin archivo aún

        # Guardar metadatos STCM en el proyecto para persistencia
        if stcm_data:
            self.proyecto.stcm_origin_x = stcm_data.origin_x
            self.proyecto.stcm_origin_y = stcm_data.origin_y
            self.proyecto.stcm_resolution_x = stcm_data.resolution_x
            self.proyecto.stcm_resolution_y = stcm_data.resolution_y
            self.ESCALA = stcm_data.resolution_x

        # Actualizar referencias en TODOS los subcontroladores
        self._actualizar_referencias_proyecto(self.proyecto)

        # Limpiar UI (esto también limpia el historial)
        self._limpiar_ui_completa()

        # Mostrar mapa (con o sin offset STCM)
        if stcm_data:
            self._mostrar_mapa_stcm(ruta_mapa, stcm_data)
        else:
            self._mostrar_mapa(ruta_mapa)

        # Resetear botones y modo
        self._resetear_modo_actual()

        # Inicializar sistema de visibilidad
        self.inicializar_visibilidad()

        print("✓ Nuevo proyecto creado con mapa:", ruta_mapa)
        self.diagnosticar_estado_proyecto()

    def abrir_proyecto(self):
        """Abre un proyecto. Si ya hay uno cargado, lo abre en una ventana nueva."""
        ruta_archivo, _ = QFileDialog.getOpenFileName(
            self.view, "Abrir proyecto", "", "JSON Files (*.json)"
        )
        if not ruta_archivo:
            return

        # Si ya hay un proyecto abierto, lanzar en ventana nueva
        if self.proyecto:
            self._abrir_en_nueva_ventana(ruta_archivo)
            return

        # Sin proyecto previo: cargar en esta misma ventana
        self.abrir_proyecto_desde_ruta(ruta_archivo)

    def abrir_proyecto_desde_ruta(self, ruta_archivo):
        """Carga un proyecto .json en la ventana actual (sin diálogo de archivo)."""
        try:
            # 1) Desconectar señales del proyecto viejo ANTES de tocar nada
            proyecto_viejo = self.proyecto
            if proyecto_viejo:
                self._desconectar_señales_proyecto(proyecto_viejo)

            # 2) Limpiar toda la UI (escena, listas, propiedades, historial)
            self._limpiar_ui_completa()
            self.proyecto = None

            # 3) Cargar el nuevo proyecto
            nuevo_proyecto = Proyecto.cargar(ruta_archivo)

            # Asegurarse de que todos los nodos tengan campo "objetivo"
            for nodo in nuevo_proyecto.nodos:
                if isinstance(nodo, dict):
                    if "objetivo" not in nodo:
                        nodo["objetivo"] = 0
                elif not hasattr(nodo, "objetivo"):
                    setattr(nodo, "objetivo", 0)

            # 4) Asignar y conectar señales del nuevo proyecto
            self._actualizar_referencias_proyecto(nuevo_proyecto)

            # Restaurar escala y offsets desde metadatos STCM si están disponibles
            if hasattr(self.proyecto, 'stcm_resolution_x') and self.proyecto.stcm_resolution_x:
                self.ESCALA = self.proyecto.stcm_resolution_x

            if self.proyecto.mapa:
                # Si el proyecto tiene metadatos STCM, usar offsets exactos
                if (hasattr(self.proyecto, 'stcm_origin_x') and
                        self.proyecto.stcm_origin_x is not None and
                        hasattr(self.proyecto, 'stcm_resolution_x') and
                        self.proyecto.stcm_resolution_x):
                    print(f"[CARGAR] Usando offsets STCM guardados: "
                          f"origin=({self.proyecto.stcm_origin_x}, {self.proyecto.stcm_origin_y}), "
                          f"resolution=({self.proyecto.stcm_resolution_x}, {self.proyecto.stcm_resolution_y})")
                    stcm_data = STCMData()
                    stcm_data.origin_x = self.proyecto.stcm_origin_x
                    stcm_data.origin_y = self.proyecto.stcm_origin_y
                    stcm_data.resolution_x = self.proyecto.stcm_resolution_x
                    stcm_data.resolution_y = self.proyecto.stcm_resolution_y
                    from PyQt5.QtGui import QPixmap as _QP
                    _pm = _QP(self.proyecto.mapa)
                    stcm_data.width = _pm.width()
                    stcm_data.height = _pm.height()
                    self._mostrar_mapa_stcm(self.proyecto.mapa, stcm_data)
                else:
                    print(f"[CARGAR] SIN metadatos STCM → auto-detección de offset")
                    self._mostrar_mapa(self.proyecto.mapa)

            # Crear NodoItem correctamente
            for nodo in self.proyecto.nodos:
                try:
                    nodo_item = self._create_nodo_item(nodo)
                except Exception:
                    nodo_item = NodoItem(nodo, editor=self)
                    try:
                        nodo_item.setFlag(nodo_item.ItemIsSelectable, True)
                        nodo_item.setFlag(nodo_item.ItemIsFocusable, True)
                        nodo_item.setFlag(nodo_item.ItemIsMovable, (self.modo_actual == "mover"))
                        nodo_item.setAcceptedMouseButtons(Qt.LeftButton)
                        nodo_item.setZValue(1)
                        self.scene.addItem(nodo_item)
                        nodo_item.moved.connect(self.on_nodo_moved)
                    except Exception:
                        pass

                self._inicializar_nodo_visibilidad(nodo, agregar_a_lista=True)

            self.inicializar_visibilidad()
            self._actualizar_lista_nodos_con_widgets()
            self._dibujar_rutas()
            self._mostrar_rutas_lateral()

            self.ruta_archivo_actual = ruta_archivo
            self.proyecto_modificado = False
            print("✓ Proyecto cargado desde:", ruta_archivo)
            self.diagnosticar_estado_proyecto()
        except Exception as err:
            print("✗ Error al abrir proyecto:", err)
            import traceback
            traceback.print_exc()

    def importar_proyecto(self):
        """Importa nodos, rutas y parámetros de otro proyecto JSON al actual.
        En conflictos de ID se le pregunta al usuario qué hacer.
        Las rutas se remapean con los nuevos IDs; se descartan las que usen
        nodos salteados. Las coordenadas originales se preservan."""
        if not self.proyecto:
            QMessageBox.warning(self.view, "Importar proyecto",
                                "Primero abrí o creá un proyecto destino.")
            return

        ruta_archivo, _ = QFileDialog.getOpenFileName(
            self.view, "Importar proyecto (JSON)", "", "JSON Files (*.json)"
        )
        if not ruta_archivo:
            return

        try:
            proyecto_src = Proyecto.cargar(ruta_archivo)
        except Exception as e:
            QMessageBox.critical(self.view, "Importar proyecto",
                                 f"No se pudo leer el proyecto:\n{e}")
            return

        # --- 0) Diálogo de selección de elementos a importar ---
        from View.dialogo_importar_seleccion import DialogoImportarSeleccion
        dlg_sel = DialogoImportarSeleccion(self.view, proyecto_src)
        if dlg_sel.exec_() != QDialog.Accepted:
            return

        rutas_seleccionadas = dlg_sel.rutas_indices
        importar_todos_nodos = dlg_sel.importar_todos_los_nodos
        importar_nodos_sueltos = dlg_sel.importar_nodos_sueltos
        importar_playa = dlg_sel.importar_parametros_playa
        importar_cd = dlg_sel.importar_parametros_carga_descarga

        if (not rutas_seleccionadas and not importar_todos_nodos
                and not importar_nodos_sueltos and not importar_playa
                and not importar_cd):
            QMessageBox.information(self.view, "Importar proyecto",
                                    "No seleccionaste nada para importar.")
            return

        # --- 1) Preparar índice de IDs actuales ---
        def _nid(n):
            try:
                return int(n.get("id") if hasattr(n, "get") else getattr(n, "id", 0))
            except (TypeError, ValueError):
                return 0
        ids_actuales = {_nid(n) for n in self.proyecto.nodos}

        # --- 1.b) Determinar subconjunto de nodos origen a importar ---
        def _ref_id(ref):
            if ref is None:
                return None
            if isinstance(ref, int):
                return ref
            if isinstance(ref, dict):
                try:
                    return int(ref.get("id"))
                except (TypeError, ValueError):
                    return None
            if hasattr(ref, "get"):
                try:
                    return int(ref.get("id"))
                except (TypeError, ValueError):
                    return None
            return None

        ids_nodos_a_importar = set()
        if importar_todos_nodos:
            ids_nodos_a_importar = {_nid(n) for n in proyecto_src.nodos}
        else:
            # Siempre incluir los nodos referenciados por rutas seleccionadas
            for idx in rutas_seleccionadas:
                if idx < 0 or idx >= len(proyecto_src.rutas):
                    continue
                ruta = proyecto_src.rutas[idx]
                if isinstance(ruta, dict):
                    for key in ("origen", "destino"):
                        rid = _ref_id(ruta.get(key))
                        if rid is not None:
                            ids_nodos_a_importar.add(rid)
                    for v in (ruta.get("visita") or []):
                        rid = _ref_id(v)
                        if rid is not None:
                            ids_nodos_a_importar.add(rid)
            if importar_nodos_sueltos:
                ids_src = {_nid(n) for n in proyecto_src.nodos}
                ids_nodos_a_importar |= ids_src  # suma los sueltos

        nodos_src_filtrados = [
            n for n in proyecto_src.nodos if _nid(n) in ids_nodos_a_importar
        ]

        # --- 2) Pre-calcular conflictos para saber "restantes" ---
        conflictos_pendientes = sum(
            1 for n in nodos_src_filtrados if _nid(n) in ids_actuales
        )

        # --- 3) Resolver IDs: id_source -> id_destino (o None si se saltea) ---
        from View.dialogo_importar_nodo import DialogoImportarNodo

        def _siguiente_id_libre():
            base = max(ids_actuales | {0}) + 1
            while base in ids_actuales:
                base += 1
            return base

        id_map = {}
        accion_global = None   # si el usuario eligió "aplicar a todos"
        ids_nodos_destino = set(ids_actuales)  # incluye los que vamos sumando

        for nodo_src in nodos_src_filtrados:
            sid = _nid(nodo_src)
            if sid not in ids_nodos_destino:
                # Sin conflicto: mantener ID original
                id_map[sid] = sid
                ids_nodos_destino.add(sid)
                continue

            # Hay conflicto: aplicar acción global o preguntar
            conflictos_pendientes -= 1
            accion = accion_global
            if accion is None:
                nodo_actual = next(
                    (n for n in self.proyecto.nodos if _nid(n) == sid), None
                )
                nuevo_sugerido = max(ids_nodos_destino | {0}) + 1
                src_dict = nodo_src.to_dict() if hasattr(nodo_src, "to_dict") else nodo_src
                act_dict = nodo_actual.to_dict() if hasattr(nodo_actual, "to_dict") else nodo_actual
                dlg = DialogoImportarNodo(
                    self.view, src_dict, act_dict or {},
                    nuevo_sugerido, restantes=conflictos_pendientes
                )
                if dlg.exec_() == QDialog.Rejected:
                    # Cancelar importación
                    print("✗ Importación cancelada por el usuario.")
                    return
                accion = dlg.accion
                if dlg.aplicar_a_todos:
                    accion_global = accion

            if accion == "saltear":
                id_map[sid] = None
            else:  # nuevo_id
                nuevo = max(ids_nodos_destino | {0}) + 1
                id_map[sid] = nuevo
                ids_nodos_destino.add(nuevo)

        # --- 4) Agregar nodos importados con IDs remapeados ---
        nodos_importados = 0
        for nodo_src in nodos_src_filtrados:
            sid = _nid(nodo_src)
            nuevo_id = id_map.get(sid)
            if nuevo_id is None:
                continue
            datos = nodo_src.to_dict() if hasattr(nodo_src, "to_dict") else dict(nodo_src)
            datos = copy.deepcopy(datos)
            datos["id"] = nuevo_id
            # Actualizar Punto_encarar si apuntaba a sí mismo
            pe = datos.get("Punto_encarar", 0)
            try:
                pe_int = int(pe) if pe not in (None, "") else 0
            except (TypeError, ValueError):
                pe_int = 0
            if pe_int == sid:
                datos["Punto_encarar"] = nuevo_id
            elif pe_int in id_map and id_map[pe_int] is not None:
                datos["Punto_encarar"] = id_map[pe_int]

            # Crear nodo (objeto Nodo igual que al cargar) y agregarlo
            try:
                nodo_obj = Nodo(datos)
            except Exception:
                nodo_obj = datos
            self.proyecto.nodos.append(nodo_obj)
            try:
                self.proyecto.nodo_agregado.emit(nodo_obj)
            except Exception:
                pass
            nodos_importados += 1

        # --- 5) Remapear rutas y agregarlas ---
        rutas_importadas = 0
        rutas_descartadas = 0

        def _remap_nodo_ref(ref):
            """Dado un nodo de ruta (int o dict), devuelve el nuevo dict con
            id remapeado, o None si el nodo fue salteado."""
            if ref is None:
                return None
            if isinstance(ref, int):
                oid = ref
                new_id = id_map.get(oid)
                if new_id is None:
                    return None
                return new_id
            if hasattr(ref, "to_dict"):
                ref = ref.to_dict()
            if isinstance(ref, dict):
                oid = ref.get("id")
                try:
                    oid = int(oid)
                except (TypeError, ValueError):
                    return None
                new_id = id_map.get(oid)
                if new_id is None:
                    return None
                nuevo = copy.deepcopy(ref)
                nuevo["id"] = new_id
                return nuevo
            return None

        for idx_r, ruta_src in enumerate(proyecto_src.rutas):
            if idx_r not in rutas_seleccionadas:
                continue
            try:
                ruta = ruta_src.to_dict() if hasattr(ruta_src, "to_dict") else dict(ruta_src)
            except Exception:
                ruta = ruta_src
            ruta = copy.deepcopy(ruta)

            nueva_ruta = {"nombre": ruta.get("nombre", "Ruta importada")}
            origen_m = _remap_nodo_ref(ruta.get("origen"))
            destino_m = _remap_nodo_ref(ruta.get("destino"))
            if origen_m is None or destino_m is None:
                rutas_descartadas += 1
                continue

            visita_orig = ruta.get("visita", []) or []
            visita_m = []
            descartar = False
            for v in visita_orig:
                vm = _remap_nodo_ref(v)
                if vm is None:
                    descartar = True
                    break
                visita_m.append(vm)
            if descartar:
                rutas_descartadas += 1
                continue

            nueva_ruta["origen"] = origen_m
            nueva_ruta["destino"] = destino_m
            if visita_m:
                nueva_ruta["visita"] = visita_m
            try:
                self.proyecto.agregar_ruta(nueva_ruta)
                rutas_importadas += 1
            except Exception as e:
                print(f"✗ Error al agregar ruta importada: {e}")
                rutas_descartadas += 1

        # --- 6) Merge parámetros de playa y carga/descarga (renumerar si colisión) ---
        playas_importadas = 0
        ids_playa_act = {int(p.get("ID", 0)) for p in self.proyecto.parametros_playa}
        fuente_playa = (getattr(proyecto_src, "parametros_playa", []) or []) if importar_playa else []
        for p_src in fuente_playa:
            p = copy.deepcopy(p_src)
            pid = int(p.get("ID", 0) or 0)
            if pid in ids_playa_act:
                nuevo = (max(ids_playa_act) + 1) if ids_playa_act else 1
                p["ID"] = nuevo
                ids_playa_act.add(nuevo)
            else:
                ids_playa_act.add(pid)
            self.proyecto.parametros_playa.append(p)
            playas_importadas += 1
        if playas_importadas:
            try:
                self.proyecto.parametros_playa_modificados.emit(self.proyecto.parametros_playa)
            except Exception:
                pass

        cargas_importadas = 0
        ids_cd_act = {int(c.get("ID", 0)) for c in self.proyecto.parametros_carga_descarga}
        fuente_cd = (getattr(proyecto_src, "parametros_carga_descarga", []) or []) if importar_cd else []
        for c_src in fuente_cd:
            c = copy.deepcopy(c_src)
            cid = int(c.get("ID", 0) or 0)
            if cid in ids_cd_act:
                nuevo = (max(ids_cd_act) + 1) if ids_cd_act else 1
                c["ID"] = nuevo
                ids_cd_act.add(nuevo)
            else:
                ids_cd_act.add(cid)
            self.proyecto.parametros_carga_descarga.append(c)
            cargas_importadas += 1
        if cargas_importadas:
            try:
                self.proyecto.parametros_carga_descarga_modificados.emit(
                    self.proyecto.parametros_carga_descarga
                )
            except Exception:
                pass

        # --- 7) Refrescar UI ---
        try:
            self._limpiar_ui_completa_preservando_proyecto = True
        except Exception:
            pass
        # Recrear NodoItem de los nodos nuevos
        try:
            nodos_existentes_en_escena = {
                id(it.nodo) if hasattr(it, "nodo") else None
                for it in self.scene.items() if isinstance(it, NodoItem)
            }
        except Exception:
            nodos_existentes_en_escena = set()
        for nodo in self.proyecto.nodos:
            if id(nodo) in nodos_existentes_en_escena:
                continue
            try:
                self._create_nodo_item(nodo)
            except Exception:
                pass
            self._inicializar_nodo_visibilidad(nodo, agregar_a_lista=True)

        self._actualizar_lista_nodos_con_widgets()
        self._dibujar_rutas()
        self._mostrar_rutas_lateral()
        self.proyecto_modificado = True
        self.proyecto.proyecto_cambiado.emit()

        QMessageBox.information(
            self.view, "Importar proyecto",
            f"Importación completada.\n\n"
            f"• Nodos importados: {nodos_importados}\n"
            f"• Rutas importadas: {rutas_importadas}\n"
            f"• Rutas descartadas (por nodos salteados): {rutas_descartadas}\n"
            f"• Parámetros de playa importados: {playas_importadas}\n"
            f"• Parámetros carga/descarga importados: {cargas_importadas}"
        )
        print(f"✓ Importación: {nodos_importados} nodos, {rutas_importadas} rutas, "
              f"{rutas_descartadas} rutas descartadas, {playas_importadas} playas, "
              f"{cargas_importadas} carga/descarga.")

    def _finalizar_rutas_pendientes(self):
        """Finaliza rutas en construcción antes de guardar."""
        if hasattr(self, 'ruta_ctrl') and self.ruta_ctrl and hasattr(self.ruta_ctrl, '_nodes_seq'):
            if len(self.ruta_ctrl._nodes_seq) >= 2:
                print("✓ Finalizando ruta en construcción antes de guardar...")
                self.ruta_ctrl._finalize_route()

    def guardar_proyecto(self):
        """Guardar: si ya tiene archivo, guarda ahí. Si no, abre diálogo."""
        if not self.proyecto:
            print("No hay proyecto cargado para guardar")
            return

        self._finalizar_rutas_pendientes()

        # Si ya tiene archivo, guardar directamente
        if self.ruta_archivo_actual:
            try:
                self.proyecto.guardar(self.ruta_archivo_actual)
                self.proyecto_modificado = False
                print("✓ Proyecto guardado en:", self.ruta_archivo_actual)
            except Exception as err:
                print("✗ Error al guardar proyecto:", err)
        else:
            # Si no tiene archivo, usar "Guardar como..."
            self.guardar_proyecto_como()

    def guardar_proyecto_como(self):
        """Guardar como: siempre abre diálogo para elegir ubicación."""
        if not self.proyecto:
            print("No hay proyecto cargado para guardar")
            return

        self._finalizar_rutas_pendientes()

        ruta_archivo, _ = QFileDialog.getSaveFileName(
            self.view, "Guardar proyecto como...", "", "JSON Files (*.json)"
        )
        if not ruta_archivo:
            return
        if not ruta_archivo.lower().endswith(".json"):
            ruta_archivo += ".json"
        try:
            self.proyecto.guardar(ruta_archivo)
            self.ruta_archivo_actual = ruta_archivo
            self.proyecto_modificado = False
            print("✓ Proyecto guardado en:", ruta_archivo)
        except Exception as err:
            print("✗ Error al guardar proyecto:", err)

    def cerrar_proyecto(self):
        """Cierra el proyecto actual sin cerrar la app."""
        if not self.proyecto:
            return

        # Solo preguntar si hay cambios sin guardar
        if self.proyecto_modificado:
            from PyQt5.QtWidgets import QMessageBox
            resp = QMessageBox.question(
                self.view, "Cerrar proyecto",
                "Hay cambios sin guardar. ¿Desea guardar antes de cerrar?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )

            if resp == QMessageBox.Cancel:
                return
            if resp == QMessageBox.Yes:
                self.guardar_proyecto()

        # Limpiar todo
        self._limpiar_ui_completa()
        self.proyecto = None
        self.ruta_archivo_actual = None

        # Limpiar etiqueta de nodo seleccionado
        if hasattr(self, 'lbl_nodo_seleccionado'):
            self.lbl_nodo_seleccionado.setText("")
            self.lbl_nodo_seleccionado.hide()

        # Resetear modo
        self.modo_actual = "navegacion"
        self.actualizar_descripcion_modo("navegacion")

        # Limpiar barra de estado
        if hasattr(self.view, 'statusBar'):
            self.view.statusBar().showMessage("Sin proyecto abierto")

        print("✓ Proyecto cerrado")

    def _on_close_window(self):
        """Callback cuando el usuario cierra la ventana con X. Retorna True para cerrar, False para cancelar."""
        if not self.proyecto or not self.proyecto_modificado:
            return True  # No hay cambios, cerrar directamente

        from PyQt5.QtWidgets import QMessageBox
        resp = QMessageBox.question(
            self.view, "Cerrar aplicación",
            "Hay cambios sin guardar. ¿Desea guardar antes de salir?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )

        if resp == QMessageBox.Cancel:
            return False  # Cancelar cierre
        if resp == QMessageBox.Yes:
            self.guardar_proyecto()
        return True  # Cerrar

    def _detectar_offset_mapa(self, ruta_mapa):
        """Detecta automáticamente el offset del área blanca (plano real) en el mapa LIDAR.
        Busca la esquina inferior izquierda del área blanca como origen (0,0)."""
        from PyQt5.QtGui import QImage
        image = QImage(ruta_mapa)
        if image.format() != QImage.Format_ARGB32:
            image = image.convertToFormat(QImage.Format_ARGB32)
        w, h = image.width(), image.height()
        umbral = 240  # Píxeles con valor > umbral se consideran "blanco" (piso)
        paso = max(1, min(w, h) // 100)  # Muestreo para velocidad

        # Buscar primera columna con blanco significativo (borde izquierdo del plano)
        offset_x = 0
        for x in range(w):
            columna_blanca = 0
            muestras = 0
            for y in range(0, h, paso):
                muestras += 1
                pixel = image.pixelColor(x, y)
                if pixel.red() > umbral and pixel.green() > umbral and pixel.blue() > umbral:
                    columna_blanca += 1
            if muestras > 0 and columna_blanca / muestras > 0.05:
                offset_x = x
                break

        # Buscar última fila con blanco significativo (borde inferior del plano)
        offset_y = h - 1
        for y in range(h - 1, -1, -1):
            fila_blanca = 0
            muestras = 0
            for x_s in range(0, w, paso):
                muestras += 1
                pixel = image.pixelColor(x_s, y)
                if pixel.red() > umbral and pixel.green() > umbral and pixel.blue() > umbral:
                    fila_blanca += 1
            if muestras > 0 and fila_blanca / muestras > 0.05:
                offset_y = y
                break

        self.offset_x_px = offset_x
        self.offset_y_px = offset_y
        print(f"[MAPA-AUTO] Offset: X={offset_x}px, Y={offset_y}px | "
              f"imagen={w}x{h} | ESCALA={self.ESCALA} | "
              f"NOTA: Y=0 se fija en el borde inferior del área blanca (sin origin STCM)")

    def _mostrar_mapa(self, ruta_mapa):
        # Limpia la escena y coloca el mapa al fondo sin interceptar clics
        self.scene.clear()
        pixmap = QPixmap(ruta_mapa)
        self.alto_mapa_px = pixmap.height()
        self.ancho_mapa_px = pixmap.width()

        # Detectar offset automáticamente
        self._detectar_offset_mapa(ruta_mapa)
        pm_item = QGraphicsPixmapItem(pixmap)
        pm_item.setAcceptedMouseButtons(Qt.NoButton)
        pm_item.setFlag(QGraphicsPixmapItem.ItemIsSelectable, False)
        pm_item.setFlag(QGraphicsPixmapItem.ItemIsFocusable, False)
        pm_item.setZValue(0)
        self.scene.addItem(pm_item)
        self._ajustar_vista_al_mapa(pixmap)

    def _mostrar_mapa_stcm(self, ruta_mapa, stcm_data):
        """Muestra el mapa usando la imagen completa del archivo como referencia:
        (0,0) queda en la esquina inferior izquierda del bitmap (blanco + negro),
        que coincide con el origen físico del mapa según los metadatos STCM."""
        self.scene.clear()
        pixmap = QPixmap(ruta_mapa)
        self.alto_mapa_px = pixmap.height()
        self.ancho_mapa_px = pixmap.width()

        # (0,0) en la esquina inferior izquierda del bitmap completo.
        # Equivalente a los offsets STCM cuando origin ≈ 0.
        self.offset_x_px = 0
        self.offset_y_px = self.alto_mapa_px

        print(f"[MAPA-STCM] Offset: X={self.offset_x_px}px, Y={self.offset_y_px}px (esquina inferior izquierda del bitmap) | "
              f"origin STCM=({stcm_data.origin_x}, {stcm_data.origin_y}) | "
              f"resolution=({stcm_data.resolution_x}, {stcm_data.resolution_y}) | "
              f"size={stcm_data.width}x{stcm_data.height} | ESCALA={self.ESCALA}")

        pm_item = QGraphicsPixmapItem(pixmap)
        pm_item.setAcceptedMouseButtons(Qt.NoButton)
        pm_item.setFlag(QGraphicsPixmapItem.ItemIsSelectable, False)
        pm_item.setFlag(QGraphicsPixmapItem.ItemIsFocusable, False)
        pm_item.setZValue(0)
        self.scene.addItem(pm_item)
        self._ajustar_vista_al_mapa(pixmap)

    def _ajustar_vista_al_mapa(self, pixmap):
        """Ajusta el sceneRect al tamaño del bitmap y centra la vista
        mostrando el mapa completo."""
        try:
            from PyQt5.QtCore import QRectF
            rect = QRectF(0, 0, pixmap.width(), pixmap.height())
            self.scene.setSceneRect(rect)
            self.view.marco_trabajo.resetTransform()
            # Resetear contador interno de zoom si existe
            try:
                self.view.marco_trabajo.zoom_level = 0
            except Exception:
                pass
            self.view.marco_trabajo.fitInView(rect, Qt.KeepAspectRatio)
        except Exception as e:
            print(f"Error ajustando vista al mapa: {e}")

    # --- Helper centralizado para crear NodoItem ---
    def _create_nodo_item(self, nodo, size=15):
        """
        Crea (o recupera) un NodoItem visual para el nodo del modelo,
        lo configura (flags, z-order), conecta la señal moved y lo añade a la escena.
        Devuelve el NodoItem creado.
        """
        # Si ya existe un NodoItem en la escena para este nodo, devolverlo
        for it in self.scene.items():
            if isinstance(it, NodoItem) and getattr(it, "nodo", None) == nodo:
                return it

        # Asegurar que el nodo tenga campo objetivo
        if isinstance(nodo, dict):
            if "objetivo" not in nodo:
                nodo["objetivo"] = 0  # Valor por defecto
        elif hasattr(nodo, "objetivo"):
            pass  # Ya tiene el atributo
        else:
            try:
                setattr(nodo, "objetivo", 0)  # Valor por defecto
            except Exception:
                pass

        # Crear nuevo NodoItem
        nodo_item = NodoItem(nodo, size=size, editor=self)

        # CONEXIÓN DE SEÑALES HOVER - NUEVO
        try:
            nodo_item.hover_entered.connect(self.nodo_hover_entered)
            nodo_item.hover_leaved.connect(self.nodo_hover_leaved)
        except Exception as e:
            print(f"Error conectando señales hover: {e}")

        # Flags básicos: seleccionable y focusable siempre; movible según modo actual
        try:
            nodo_item.setFlag(nodo_item.ItemIsSelectable, True)
            nodo_item.setFlag(nodo_item.ItemIsFocusable, True)
            nodo_item.setFlag(nodo_item.ItemIsMovable, (self.modo_actual == "mover"))
            # Aceptar ambos botones; el RightButton lo consume contextMenuEvent
            nodo_item.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
            nodo_item.setZValue(1)
        except Exception:
            pass

        # Conectar la señal moved para que el editor actualice modelo/UI cuando se suelte
        try:
            nodo_item.moved.connect(self.on_nodo_moved)
        except Exception:
            pass

        # Añadir a la escena y devolver
        try:
            self.scene.addItem(nodo_item)
        except Exception:
            pass

        return nodo_item

    # ============================================================
    # MODO DUPLICAR NODOS (botón "Duplicar nodo")
    # ============================================================
    def _entrar_modo_duplicar(self):
        """Entra al modo duplicar: los clicks en nodos los marcan/desmarcan
        para ser duplicados; los clicks en zona vacía los colocan."""
        self._modo_duplicar_activo = True
        self._duplicar_items_seleccionados = []
        self._duplicar_ghost_items = []
        try:
            self.actualizar_descripcion_modo("duplicar")
        except Exception:
            pass
        print("✓ Modo Duplicar activado. Click en nodos para marcarlos, "
              "click en zona vacía para colocar duplicados, Escape para salir.")

    def _salir_modo_duplicar(self):
        """Sale del modo duplicar: borra fantasmas y quita los marcados."""
        self._eliminar_ghosts_duplicar()
        for it in list(self._duplicar_items_seleccionados):
            try:
                it.set_marcado_duplicar(False)
            except Exception:
                pass
        self._duplicar_items_seleccionados = []
        self._modo_duplicar_activo = False

    def _eliminar_ghosts_duplicar(self):
        """Elimina los items fantasma (círculos y etiquetas) de la escena."""
        try:
            for tpl in self._duplicar_ghost_items:
                ghost = tpl[0]
                label = tpl[3] if len(tpl) > 3 else None
                try:
                    self.scene.removeItem(ghost)
                except Exception:
                    pass
                if label is not None:
                    try:
                        self.scene.removeItem(label)
                    except Exception:
                        pass
        except Exception:
            pass
        self._duplicar_ghost_items = []

    def _crear_ghosts_duplicar(self):
        """Crea los círculos fantasma + etiquetas de coordenadas para los
        nodos actualmente marcados."""
        self._eliminar_ghosts_duplicar()
        if not self._duplicar_items_seleccionados:
            return
        from PyQt5.QtGui import QBrush as _QBrush, QPen as _QPen, QColor as _QColor, QFont
        from PyQt5.QtWidgets import QGraphicsSimpleTextItem, QGraphicsRectItem
        from PyQt5.QtCore import QRectF as _QRectF

        # Anchor = primer nodo marcado
        anchor_item = self._duplicar_items_seleccionados[0]
        try:
            ax = int(anchor_item.nodo.get("X", 0))
            ay = int(anchor_item.nodo.get("Y", 0))
        except Exception:
            return

        for it in self._duplicar_items_seleccionados:
            try:
                x = int(it.nodo.get("X", 0))
                y = int(it.nodo.get("Y", 0))
            except Exception:
                continue
            dx, dy = x - ax, y - ay
            try:
                ghost = self.scene.addEllipse(
                    -7.5, -7.5, 15, 15,
                    _QPen(_QColor(0, 180, 60, 220), 2),
                    _QBrush(_QColor(0, 180, 60, 120))
                )
                ghost.setZValue(2000)
                ghost.setAcceptedMouseButtons(Qt.NoButton)

                # Etiqueta con coordenadas en vivo (texto + fondo)
                label = QGraphicsSimpleTextItem("")
                label.setBrush(_QBrush(_QColor(255, 255, 255)))
                font = QFont()
                font.setPointSize(9)
                font.setBold(True)
                label.setFont(font)
                label.setZValue(2001)
                label.setAcceptedMouseButtons(Qt.NoButton)
                # Fondo semitransparente
                bg = QGraphicsRectItem()
                bg.setBrush(_QBrush(_QColor(0, 0, 0, 180)))
                bg.setPen(_QPen(_QColor(0, 180, 60, 220), 1))
                bg.setZValue(2000.5)
                bg.setAcceptedMouseButtons(Qt.NoButton)
                self.scene.addItem(bg)
                self.scene.addItem(label)

                self._duplicar_ghost_items.append((ghost, dx, dy, label, bg))
            except Exception as e:
                print(f"Error creando fantasma de duplicación: {e}")

    def _mover_ghosts_duplicar(self, cx, cy):
        """Mueve los fantasmas para que su ancla quede en (cx, cy) y
        actualiza las etiquetas con las coordenadas en metros."""
        if not self._duplicar_ghost_items:
            return
        from PyQt5.QtCore import QRectF as _QRectF
        try:
            for tpl in self._duplicar_ghost_items:
                ghost = tpl[0]
                dx, dy = tpl[1], tpl[2]
                label = tpl[3] if len(tpl) > 3 else None
                bg = tpl[4] if len(tpl) > 4 else None
                gx = cx + dx
                gy = cy + dy
                ghost.setPos(gx, gy)
                ghost.setVisible(True)
                if label is not None:
                    x_m = self.x_px_a_metros(gx)
                    y_m = self.y_px_a_metros(gy)
                    label.setText(f"({x_m:.2f}, {y_m:.2f})")
                    # Posicionar texto a la derecha y un poco arriba del fantasma
                    label.setPos(gx + 10, gy - 22)
                    label.setVisible(True)
                    if bg is not None:
                        br = label.boundingRect()
                        pad = 3
                        bg.setRect(_QRectF(
                            gx + 10 - pad, gy - 22 - pad,
                            br.width() + 2*pad, br.height() + 2*pad
                        ))
                        bg.setVisible(True)
        except Exception:
            pass

    def _ocultar_ghosts_duplicar(self):
        """Oculta los fantasmas y etiquetas (p.ej. cursor sobre nodo)."""
        try:
            for tpl in self._duplicar_ghost_items:
                ghost = tpl[0]
                label = tpl[3] if len(tpl) > 3 else None
                bg = tpl[4] if len(tpl) > 4 else None
                ghost.setVisible(False)
                if label is not None:
                    label.setVisible(False)
                if bg is not None:
                    bg.setVisible(False)
        except Exception:
            pass

    def _duplicar_click_nodo(self, nodo_item, con_ctrl: bool):
        """Gestiona el click sobre un nodo en modo duplicar.

        - Sin Ctrl: reemplaza la selección actual con solo este nodo
          y muestra los fantasmas inmediatamente.
        - Con Ctrl: toggle (agrega/quita de la selección) SIN crear fantasmas;
          los fantasmas aparecen cuando el usuario suelta Ctrl.
        """
        if con_ctrl:
            if nodo_item in self._duplicar_items_seleccionados:
                self._duplicar_items_seleccionados.remove(nodo_item)
                try:
                    nodo_item.set_marcado_duplicar(False)
                except Exception:
                    pass
            else:
                self._duplicar_items_seleccionados.append(nodo_item)
                try:
                    nodo_item.set_marcado_duplicar(True)
                except Exception:
                    pass
            # Con Ctrl: ocultar fantasmas mientras el usuario sigue seleccionando
            self._eliminar_ghosts_duplicar()
        else:
            # Reemplazar: limpiar marcas previas y marcar sólo este
            for it in list(self._duplicar_items_seleccionados):
                try:
                    it.set_marcado_duplicar(False)
                except Exception:
                    pass
            self._duplicar_items_seleccionados = [nodo_item]
            try:
                nodo_item.set_marcado_duplicar(True)
            except Exception:
                pass
            # Sin Ctrl: mostrar fantasmas de inmediato
            self._crear_ghosts_duplicar()
        print(f"  Duplicar: {len(self._duplicar_items_seleccionados)} nodo(s) marcado(s)")

    def _duplicar_colocar_en(self, cx, cy):
        """Crea los duplicados en la posición indicada y limpia la selección
        para que el usuario pueda continuar duplicando otros nodos."""
        if not self._duplicar_items_seleccionados or not self.proyecto:
            return
        # Datos + offsets relativos al primer nodo marcado
        anchor_item = self._duplicar_items_seleccionados[0]
        try:
            ax = int(anchor_item.nodo.get("X", 0))
            ay = int(anchor_item.nodo.get("Y", 0))
        except Exception:
            return

        datos_a_duplicar = []
        for it in self._duplicar_items_seleccionados:
            try:
                origen = it.nodo.to_dict() if hasattr(it.nodo, "to_dict") else dict(it.nodo)
            except Exception:
                origen = {}
            datos_copia = copy.deepcopy(origen)
            datos_copia.pop("id", None)
            x = int(origen.get("X", 0))
            y = int(origen.get("Y", 0))
            datos_a_duplicar.append((datos_copia, x - ax, y - ay))

        nuevos_items = []
        for datos_copia, dx, dy in datos_a_duplicar:
            nx = int(cx + dx)
            ny = int(cy + dy)
            nodo_item = self.crear_nodo(nx, ny, registrar_historial=True)
            if nodo_item is None:
                continue
            props = {k: v for k, v in datos_copia.items()
                     if k not in ("X", "Y", "id")}
            try:
                nodo_item.nodo.update(props)
            except Exception:
                for k, v in props.items():
                    try:
                        if isinstance(nodo_item.nodo, dict):
                            nodo_item.nodo[k] = v
                        else:
                            setattr(nodo_item.nodo, k, v)
                    except Exception:
                        pass
            try:
                nodo_item.actualizar_objetivo()
            except Exception:
                pass
            nuevos_items.append(nodo_item)

        try:
            self._actualizar_lista_nodos_con_widgets()
        except Exception:
            pass

        print(f"✓ Duplicados {len(nuevos_items)} nodo(s). "
              f"Sigue marcando nodos para continuar o desactiva el modo.")

        # Desmarcar los nodos origen y limpiar selección
        for it in list(self._duplicar_items_seleccionados):
            try:
                it.set_marcado_duplicar(False)
            except Exception:
                pass
        self._duplicar_items_seleccionados = []
        self._eliminar_ghosts_duplicar()
        self.proyecto_modificado = True

    def crear_nodo(self, x=100, y=100, registrar_historial=True):
        """
        Crea un nuevo nodo en las coordenadas especificadas.
        """
        if not self.proyecto:
            print("No hay proyecto cargado")
            return None

        self.proyecto_modificado = True
        try:
            
            # Primero agregar al modelo
            nodo = self.proyecto.agregar_nodo(x, y)

            # Asegurar que el nodo tenga todos los campos necesarios
            if isinstance(nodo, dict):
                if "objetivo" not in nodo:
                    nodo["objetivo"] = 0
                if "es_cargador" not in nodo:
                    nodo["es_cargador"] = 0
                # Las propiedades de objetivo ya están inicializadas en agregar_nodo
            elif hasattr(nodo, "objetivo"):
                pass  # Ya tiene el atributo
            else:
                setattr(nodo, "objetivo", 0)
                setattr(nodo, "es_cargador", 0)
                # Las propiedades de objetivo se inicializarán cuando se necesiten

            # Crear NodoItem con referencia al editor usando helper centralizado
            try:
                nodo_item = self._create_nodo_item(nodo)
            except Exception as e:
                print(f"Error al crear NodoItem: {e}")
                nodo_item = NodoItem(nodo, editor=self)
                try:
                    nodo_item.setFlag(nodo_item.ItemIsSelectable, True)
                    nodo_item.setFlag(nodo_item.ItemIsFocusable, True)
                    nodo_item.setFlag(nodo_item.ItemIsMovable, (self.modo_actual == "mover"))
                    nodo_item.setAcceptedMouseButtons(Qt.LeftButton)
                    nodo_item.setZValue(1)
                    self.scene.addItem(nodo_item)
                    nodo_item.moved.connect(self.on_nodo_moved)
                except Exception as e2:
                    print(f"Error al configurar NodoItem: {e2}")
                    return None

            # --- NUEVA FUNCIÓN PARA INICIALIZAR VISIBILIDAD ---
            self._inicializar_nodo_visibilidad(nodo, agregar_a_lista=True)
            
            # Si hay rutas, actualizar todas las relaciones (para consistencia)
            if hasattr(self.proyecto, 'rutas') and self.proyecto.rutas:
                self._actualizar_todas_relaciones_nodo_ruta()

            # Mostrar en metros (con offset)
            x_m = self.x_px_a_metros(x)
            y_m = self.y_px_a_metros(y)

            # Mostrar tipo de nodo
            objetivo = nodo.get('objetivo', 0)
            es_cargador = nodo.get('es_cargador', 0)
            if es_cargador != 0:
                tipo = "CARGADOR"
            elif objetivo == 1:
                tipo = "CARGAR"
            elif objetivo == 2:
                tipo = "DESCARGAR"
            elif objetivo == 3:
                tipo = "I/O"
            elif objetivo == 5:
                tipo = "PASO"
            else:
                tipo = "Normal"
                
            # REGISTRAR CREACIÓN EN HISTORIAL (NUEVO)
            if registrar_historial:
                self._registrar_creacion_nodo(nodo)

            return nodo_item
                
        except Exception as e:
            print(f"ERROR en crear_nodo: {e}")
            import traceback
            traceback.print_exc()
            return None

    # --- NUEVA FUNCIÓN CENTRALIZADA PARA INICIALIZAR VISIBILIDAD ---
    def _inicializar_nodo_visibilidad(self, nodo, agregar_a_lista=True):
        """
        Inicializa completamente el sistema de visibilidad para un nodo.
        Se usa tanto al crear nodos nuevos como al cargarlos desde archivo.
        
        Args:
            nodo: El objeto nodo a inicializar
            agregar_a_lista: Si True, agrega el nodo a la lista lateral con widget
        """
        try:
            nodo_id = nodo.get('id')
            if nodo_id is None:
                return
            
            # 1. Inicializar visibilidad del nodo si no existe
            if nodo_id not in self.visibilidad_nodos:
                self.visibilidad_nodos[nodo_id] = True
            
            # 2. Inicializar relaciones nodo-ruta si no existen
            if nodo_id not in self.nodo_en_rutas:
                self.nodo_en_rutas[nodo_id] = []
            
            # 3. Buscar en rutas existentes si este nodo está en alguna
            for idx, ruta in enumerate(self.proyecto.rutas):
                try:
                    ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                except Exception:
                    ruta_dict = ruta
                
                self._normalize_route_nodes(ruta_dict)
                
                # Verificar si la ruta contiene este nodo
                contiene_nodo = False
                
                # Origen
                origen = ruta_dict.get("origen")
                if origen and isinstance(origen, dict) and origen.get('id') == nodo_id:
                    contiene_nodo = True
                
                # Destino
                destino = ruta_dict.get("destino")
                if not contiene_nodo and destino and isinstance(destino, dict) and destino.get('id') == nodo_id:
                    contiene_nodo = True
                
                # Visita
                if not contiene_nodo:
                    for nodo_visita in ruta_dict.get("visita", []):
                        if isinstance(nodo_visita, dict) and nodo_visita.get('id') == nodo_id:
                            contiene_nodo = True
                            break
                
                if contiene_nodo:
                    if idx not in self.nodo_en_rutas[nodo_id]:
                        self.nodo_en_rutas[nodo_id].append(idx)
            
            # 4. Agregar a la lista lateral con widget de visibilidad
            if agregar_a_lista:
                x_px = nodo.get('X', 0)
                y_px = nodo.get('Y', 0)
                # Convertir a metros (con offset)
                x_m = self.x_px_a_metros(x_px)
                y_m = self.y_px_a_metros(y_px)
                objetivo = nodo.get('objetivo', 0)
                
                # Determinar texto según objetivo
                if objetivo == 1:
                    texto_objetivo = "Dejada"
                elif objetivo == 2:
                    texto_objetivo = "Cogida"
                elif objetivo == 3:
                    texto_objetivo = "I/O"
                elif objetivo == 5:
                    texto_objetivo = "Paso"
                else:
                    texto_objetivo = "Sin objetivo"
                
                # Mostrar coordenadas en metros con 2 decimales
                texto = f"ID {nodo_id} - {texto_objetivo} ({x_m:.2f}, {y_m:.2f})"
                
                # Verificar si el nodo ya está en la lista (búsqueda exhaustiva)
                nodo_en_lista = False
                for i in range(self.view.nodosList.count()):
                    item = self.view.nodosList.item(i)
                    widget = self.view.nodosList.itemWidget(item)
                    if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                        nodo_en_lista = True
                        # Actualizar el widget existente
                        widget.lbl_texto.setText(texto)
                        widget.set_visible(self.visibilidad_nodos.get(nodo_id, True))
                        break
                
                # Si no está en la lista, agregarlo
                if not nodo_en_lista:
                    item = QListWidgetItem()
                    item.setData(Qt.UserRole, nodo)
                    item.setSizeHint(QSize(0, 24))
                    
                    widget = NodoListItemWidget(
                        nodo_id, 
                        texto, 
                        self.visibilidad_nodos.get(nodo_id, True)
                    )
                    widget.toggle_visibilidad.connect(self.toggle_visibilidad_nodo)
                    
                    self.view.nodosList.addItem(item)
                    self.view.nodosList.setItemWidget(item, widget)

        except Exception as e:
            print(f"ERROR en _inicializar_nodo_visibilidad: {e}")

    # --- NUEVOS MÉTODOS PARA RESALTADO Y DETECCIÓN DE NODOS SUPERPUESTOS ---
    def resaltar_nodo_seleccionado(self, nodo_item):
        """Resalta el nodo seleccionado con color especial"""
        # Restaurar color normal a todos los nodos primero
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.set_normal_color()
        
        # Aplicar color de selección al nodo específico
        nodo_item.set_selected_color()
        
        # También resaltar nodos de ruta si hay una ruta seleccionada
        if hasattr(self, 'ruta_actual_idx') and self.ruta_actual_idx is not None:
            self.resaltar_nodos_ruta()

    def resaltar_nodos_ruta(self, ruta=None):
        """Resalta todos los nodos que pertenecen a una ruta seleccionada"""
        if not ruta:
            if not hasattr(self, 'ruta_actual_idx') or self.ruta_actual_idx is None:
                return
            if not self.proyecto or not hasattr(self.proyecto, 'rutas'):
                return
            if self.ruta_actual_idx >= len(self.proyecto.rutas):
                return
            ruta = self.proyecto.rutas[self.ruta_actual_idx]
        
        try:
            ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
        except Exception:
            ruta_dict = ruta
        
        self._normalize_route_nodes(ruta_dict)
        
        # Coleccionar todos los nodos de la ruta
        nodos_ruta = []
        if ruta_dict.get("origen"):
            nodos_ruta.append(ruta_dict["origen"])
        if ruta_dict.get("visita"):
            nodos_ruta.extend(ruta_dict["visita"])
        if ruta_dict.get("destino"):
            nodos_ruta.append(ruta_dict["destino"])
        
        # Resaltar cada nodo de la ruta - FORZAR color de ruta incluso si está seleccionado
        for nodo in nodos_ruta:
            for item in self.scene.items():
                if isinstance(item, NodoItem):
                    if item.nodo == nodo or (
                        isinstance(item.nodo, dict) and isinstance(nodo, dict) and
                        item.nodo.get('id') == nodo.get('id')
                    ):
                        item.set_route_selected_color()
                        break

    def _resaltar_nodos_de_ruta(self, ruta):
        """Método mejorado para resaltar nodos de una ruta específica"""
        try:
            # Convertir ruta a diccionario si es necesario
            ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
        except Exception:
            ruta_dict = ruta
        
        # Normalizar la ruta
        self._normalize_route_nodes(ruta_dict)
        
        # Obtener todos los nodos de la ruta
        nodos_ruta = []
        
        # Origen
        origen = ruta_dict.get("origen")
        if origen:
            if isinstance(origen, dict):
                nodos_ruta.append(origen)
            else:
                # Intentar obtener como objeto Nodo
                try:
                    nodo_id = origen.get('id') if hasattr(origen, 'get') else getattr(origen, 'id', None)
                    if nodo_id:
                        nodos_ruta.append(origen)
                except Exception:
                    pass
        
        # Visita
        visita = ruta_dict.get("visita", [])
        for nodo_visita in visita:
            if isinstance(nodo_visita, dict):
                nodos_ruta.append(nodo_visita)
            else:
                try:
                    nodo_id = nodo_visita.get('id') if hasattr(nodo_visita, 'get') else getattr(nodo_visita, 'id', None)
                    if nodo_id:
                        nodos_ruta.append(nodo_visita)
                except Exception:
                    pass
        
        # Destino
        destino = ruta_dict.get("destino")
        if destino:
            if isinstance(destino, dict):
                nodos_ruta.append(destino)
            else:
                try:
                    nodo_id = destino.get('id') if hasattr(destino, 'get') else getattr(destino, 'id', None)
                    if nodo_id:
                        nodos_ruta.append(destino)
                except Exception:
                    pass
        
        # Resaltar cada nodo en la escena
        for nodo_ruta in nodos_ruta:
            # Obtener el ID del nodo de la ruta
            if isinstance(nodo_ruta, dict):
                nodo_ruta_id = nodo_ruta.get('id')
            else:
                try:
                    nodo_ruta_id = nodo_ruta.get('id') if hasattr(nodo_ruta, 'get') else getattr(nodo_ruta, 'id', None)
                except Exception:
                    nodo_ruta_id = None
            
            if nodo_ruta_id is None:
                continue
                
            # Buscar el NodoItem correspondiente en la escena
            for item in self.scene.items():
                if isinstance(item, NodoItem):
                    # Obtener el ID del nodo del item
                    item_nodo = item.nodo
                    if isinstance(item_nodo, dict):
                        item_id = item_nodo.get('id')
                    else:
                        try:
                            item_id = item_nodo.get('id') if hasattr(item_nodo, 'get') else getattr(item_nodo, 'id', None)
                        except Exception:
                            item_id = None
                    
                    # Si los IDs coinciden, resaltar el nodo
                    if item_id is not None and str(item_id) == str(nodo_ruta_id):
                        item.set_route_selected_color()
                        break

    def restaurar_colores_nodos(self):
        """Restaura todos los nodos a su color normal"""
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.set_normal_color()

    # --- Sincronización lista ↔ mapa---
    def seleccionar_nodo_desde_lista(self):
        if self._changing_selection:
            return
        items = self.view.nodosList.selectedItems()
        if not items:
            return
        
        # Obtener el nodo del widget
        for i in range(self.view.nodosList.count()):
            item = self.view.nodosList.item(i)
            if item.isSelected():
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id'):
                    nodo_id = widget.nodo_id
                    nodo = self.obtener_nodo_por_id(nodo_id)
                    if nodo:
                        self._changing_selection = True
                        try:
                            # Deseleccionar rutas primero
                            if hasattr(self.view, "rutasList"):
                                self.view.rutasList.clearSelection()
                            
                            # Primero restaurar todos los nodos a color normal
                            self.restaurar_colores_nodos()
                            
                            # Deseleccionar todo en la escena primero
                            for scene_item in self.scene.selectedItems():
                                scene_item.setSelected(False)
                            
                            # Buscar y seleccionar el nodo correspondiente
                            for scene_item in self.scene.items():
                                if isinstance(scene_item, NodoItem) and scene_item.nodo.get('id') == nodo_id:
                                    scene_item.setSelected(True)
                                    # Solo aplicar color de selección (no de ruta)
                                    scene_item.set_selected_color()
                                    self.view.marco_trabajo.centerOn(scene_item)
                                    self.mostrar_propiedades_nodo(nodo)
                                    break
                        finally:
                            self._changing_selection = False
                    break

    def seleccionar_nodo_desde_mapa(self):
        if self._changing_selection:
            return
        # Protección contra scene eliminada durante teardown de la app
        try:
            seleccionados = self.scene.selectedItems()
        except RuntimeError:
            return
        if not seleccionados:
            return
        nodo_item = seleccionados[0]
        nodo = nodo_item.nodo

        # --- DETECCIÓN DE NODOS SUPERPUESTOS ---
        # Verificar si hay más nodos en la misma posición (o muy cerca)
        pos = nodo_item.scenePos()
        # Usar un rectángulo pequeño alrededor del punto para detectar nodos cercanos
        search_rect = nodo_item.boundingRect().translated(pos)
        search_rect.adjust(-5, -5, 5, 5)  # Expandir un poco el área de búsqueda
        
        items_en_pos = self.scene.items(search_rect)
        nodos_en_pos = []
        
        for item in items_en_pos:
            if isinstance(item, NodoItem):
                # Verificar si está realmente superpuesto (misma posición aproximada)
                item_pos = item.scenePos()
                if (abs(item_pos.x() - pos.x()) < 10 and 
                    abs(item_pos.y() - pos.y()) < 10):
                    nodos_en_pos.append(item)
        
        if len(nodos_en_pos) > 1:
            # Hay nodos superpuestos, mostrar menú
            self.mostrar_menu_nodos_superpuestos(nodos_en_pos, pos)
            return  # El menú manejará la selección

        # --- CONTINUAR CON SELECCIÓN NORMAL ---
        self._changing_selection = True
        try:
            # Deseleccionar rutas primero
            if hasattr(self.view, "rutasList"):
                self.view.rutasList.clearSelection()
            
            # Primero restaurar todos los nodos a color normal
            self.restaurar_colores_nodos()
            
            # Deseleccionar todos los nodos primero
            for item in self.scene.selectedItems():
                if item != nodo_item:
                    item.setSelected(False)
            
            # Resaltar el nodo seleccionado
            nodo_item.set_selected_color()
            
            # Sincronizar con la lista lateral
            nodo_id = nodo.get('id')
            for i in range(self.view.nodosList.count()):
                item = self.view.nodosList.item(i)
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                    self.view.nodosList.setCurrentItem(item)
                    self.mostrar_propiedades_nodo(nodo)
                    break
        finally:
            self._changing_selection = False

    def mostrar_menu_nodos_superpuestos(self, nodos, pos):
        """Muestra un diálogo con checkboxes para seleccionar nodos superpuestos"""
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Nodos superpuestos")
        dialog.setStyleSheet("""
            QDialog {
                background-color: #161b22;
                color: #e6edf3;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
            QLabel {
                color: #58a6ff;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 0px;
            }
            QCheckBox {
                color: #e6edf3;
                font-size: 11px;
                spacing: 8px;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QCheckBox:hover {
                background-color: #21262d;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #30363d;
                border-radius: 3px;
                background-color: #0d1117;
            }
            QCheckBox::indicator:checked {
                background-color: #1f6feb;
                border-color: #58a6ff;
            }
            QPushButton {
                background-color: #21262d;
                color: #e6edf3;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 11px;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #8b949e;
            }
            QPushButton#btnAceptar {
                background-color: #1f6feb;
                border-color: #58a6ff;
                color: #ffffff;
            }
            QPushButton#btnAceptar:hover {
                background-color: #388bfd;
            }
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        titulo = QLabel(f"Selecciona los nodos ({len(nodos)} detectados)")
        layout.addWidget(titulo)

        dialog._resultado = []

        nodo_buttons = []
        for nodo_item in nodos:
            nodo = nodo_item.nodo
            objetivo = nodo.get('objetivo', 0)
            texto_objetivo = "Dejada" if objetivo == 1 else "Cogida" if objetivo == 2 else "I/O" if objetivo == 3 else "Cargador" if objetivo == 4 else "Paso" if objetivo == 5 else "Normal"

            x_m = self.x_px_a_metros(nodo.get('X', 0))
            y_m = self.y_px_a_metros(nodo.get('Y', 0))

            btn = QPushButton(f"  Nodo {nodo.get('id')} - {texto_objetivo} ({x_m:.2f}, {y_m:.2f})")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding: 8px 12px;
                    font-size: 11px;
                }
            """)

            def hacer_seleccion_unica(checked, item=nodo_item):
                dialog._resultado = [item]
                dialog.accept()

            btn.clicked.connect(hacer_seleccion_unica)
            layout.addWidget(btn)
            nodo_buttons.append((btn, nodo_item))

        # Separador y botón Todos
        layout.addSpacing(4)
        btn_todos = QPushButton("Todos")
        btn_todos.setObjectName("btnAceptar")
        btn_todos.setCursor(Qt.PointingHandCursor)

        def seleccionar_todos():
            dialog._resultado = [item for _, item in nodo_buttons]
            dialog.accept()

        btn_todos.clicked.connect(seleccionar_todos)
        layout.addWidget(btn_todos)

        if dialog.exec_() == QDialog.Accepted:
            seleccionados = dialog._resultado
            if len(seleccionados) == 1:
                self.seleccionar_nodo_especifico(seleccionados[0].nodo)
            elif len(seleccionados) > 1:
                self.seleccionar_nodos_multiples(seleccionados)

    def seleccionar_nodos_multiples(self, nodo_items):
        """Selecciona múltiples nodos para moverlos juntos"""
        self._changing_selection = True
        try:
            # Limpiar selecciones previas
            for item in self.scene.selectedItems():
                item.setSelected(False)
            self.restaurar_colores_nodos()

            # Seleccionar todos los nodos del grupo
            ids = []
            for nodo_item in nodo_items:
                nodo_item.setSelected(True)
                nodo_item.set_selected_color()
                nodo_id = nodo_item.nodo.get("id", "?") if hasattr(nodo_item, 'nodo') else "?"
                ids.append(str(nodo_id))

            # Mostrar los IDs en la etiqueta de propiedades
            if hasattr(self, 'lbl_nodo_seleccionado'):
                self.lbl_nodo_seleccionado.setText(f"Nodos #{', #'.join(ids)}")
                self.lbl_nodo_seleccionado.show()
        finally:
            self._changing_selection = False
            self._actualizar_cursor()

    def seleccionar_nodo_especifico(self, nodo):
        """Selecciona un nodo específico desde el menú de superposición"""
        self._changing_selection = True
        try:
            # Limpiar selecciones previas
            for item in self.scene.selectedItems():
                item.setSelected(False)

            # Primero restaurar todos los nodos a color normal
            self.restaurar_colores_nodos()
            
            # Seleccionar el nodo específico en la escena
            for item in self.scene.items():
                if isinstance(item, NodoItem) and item.nodo == nodo:
                    item.setSelected(True)
                    item.set_selected_color()
                    self.view.marco_trabajo.centerOn(item)
                    break
            
            # Sincronizar con la lista lateral
            nodo_id = nodo.get('id')
            for i in range(self.view.nodosList.count()):
                item = self.view.nodosList.item(i)
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                    self.view.nodosList.setCurrentItem(item)
                    self.mostrar_propiedades_nodo(nodo)
                    break
        finally:
            self._changing_selection = False
            self._actualizar_cursor()

    def _actualizar_label_lateral_nodo(self, nodo):
        """Actualiza solo el texto del widget lateral de un nodo, SIN tocar la tabla
        de propiedades. Se usa cuando el usuario está editando una celda y no
        queremos destruir la celda en curso."""
        nodo_id = nodo.get('id')
        for i in range(self.view.nodosList.count()):
            item = self.view.nodosList.item(i)
            widget = self.view.nodosList.itemWidget(item)
            if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                x_px = nodo.get('X', 0)
                y_px = nodo.get('Y', 0)
                x_m = self.x_px_a_metros(x_px)
                y_m = self.y_px_a_metros(y_px)
                objetivo = nodo.get('objetivo', 0)
                if objetivo == 1:
                    texto_objetivo = "Dejada"
                elif objetivo == 2:
                    texto_objetivo = "Cogida"
                elif objetivo == 3:
                    texto_objetivo = "I/O"
                elif objetivo == 5:
                    texto_objetivo = "Paso"
                else:
                    texto_objetivo = "Sin objetivo"
                widget.lbl_texto.setText(f"ID {nodo_id} - {texto_objetivo} ({x_m:.2f}, {y_m:.2f})")
                break

    def actualizar_lista_nodo(self, nodo):
        """Actualizar la lista lateral del panel de propiedades con las coordenadas nuevas (en metros)"""
        nodo_id = nodo.get('id')
        for i in range(self.view.nodosList.count()):
            item = self.view.nodosList.item(i)
            widget = self.view.nodosList.itemWidget(item)
            if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                x_px = nodo.get('X', 0)
                y_px = nodo.get('Y', 0)
                # Convertir a metros (con offset)
                x_m = self.x_px_a_metros(x_px)
                y_m = self.y_px_a_metros(y_px)
                objetivo = nodo.get('objetivo', 0)
                
                # Determinar texto según objetivo
                if objetivo == 1:
                    texto_objetivo = "Dejada"
                elif objetivo == 2:
                    texto_objetivo = "Cogida"
                elif objetivo == 3:
                    texto_objetivo = "I/O"
                elif objetivo == 5:
                    texto_objetivo = "Paso"
                else:
                    texto_objetivo = "Sin objetivo"
                
                # Mostrar en metros con 2 decimales
                widget.lbl_texto.setText(f"ID {nodo_id} - {texto_objetivo} ({x_m:.2f}, {y_m:.2f})")
                break

        # Refrescar el panel de propiedades si el nodo esta seleccionado
        seleccionados = self.view.nodosList.selectedItems()
        if seleccionados:
            for i in range(self.view.nodosList.count()):
                item = self.view.nodosList.item(i)
                if item.isSelected():
                    widget = self.view.nodosList.itemWidget(item)
                    if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                        self.mostrar_propiedades_nodo(nodo)
                        break

    def _mostrar_rutas_lateral(self):
        """
        Rellena la lista lateral de rutas con widgets personalizados.
        """
        self._actualizar_lista_rutas_con_widgets()

    def seleccionar_ruta_desde_lista(self):
        """
        Maneja selección/deselección en rutasList:
        - limpia highlights previos,
        - si no hay selección limpia propertiesTable,
        - si hay selección muestra propiedades y resalta sin duplicar líneas.
        """
        if not hasattr(self.view, "rutasList"):
            return

        items = self.view.rutasList.selectedItems()

        # limpiar highlights previos
        self._clear_highlight_lines()

        if not items:
            # limpiar propertiesTable
            try:
                self.view.propertiesTable.itemChanged.disconnect(self._actualizar_propiedad_ruta)
            except Exception:
                pass
            self._limpiar_propiedades()
            try:
                self.view.propertiesTable.itemChanged.connect(self._actualizar_propiedad_ruta)
            except Exception:
                pass
            self.ruta_actual_idx = None
            
            # Restaurar colores normales de TODOS los nodos
            for item in self.scene.items():
                if isinstance(item, NodoItem):
                    item.set_normal_color()
                    # Restaurar z-values normales
                    item.setZValue(1)
            return

        # Guardar el índice de la ruta seleccionada
        for i in range(self.view.rutasList.count()):
            item = self.view.rutasList.item(i)
            if item.isSelected():
                widget = self.view.rutasList.itemWidget(item)
                if widget and hasattr(widget, 'ruta_index'):
                    self.ruta_actual_idx = widget.ruta_index
                    ruta = self.obtener_ruta_por_indice(self.ruta_actual_idx)
                    break
        
        if self.ruta_actual_idx is None:
            return

        # IMPORTANTE: Restaurar todos los nodos a color normal y z-value normal primero
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.set_normal_color()
                item.setZValue(1)

        # Deseleccionar todos los nodos primero
        self._changing_selection = True
        try:
            # Deseleccionar nodos en la lista lateral
            self.view.nodosList.clearSelection()
            
            # Deseleccionar nodos en la escena
            for item in self.scene.selectedItems():
                item.setSelected(False)
        finally:
            self._changing_selection = False
        
        self.mostrar_propiedades_ruta(ruta)

        # Resaltar nodos de la ruta - VERSIÓN MEJORADA
        self._resaltar_nodos_de_ruta(ruta)

        # resaltar la ruta seleccionada con líneas amarillas
        try:
            highlight_pen = QPen(Qt.yellow, 3)
            ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            self._normalize_route_nodes(ruta_dict)
            puntos = []
            if ruta_dict.get("origen"):
                puntos.append(ruta_dict.get("origen"))
            puntos.extend(ruta_dict.get("visita", []) or [])
            if ruta_dict.get("destino"):
                puntos.append(ruta_dict.get("destino"))

            for i in range(len(puntos) - 1):
                n1, n2 = puntos[i], puntos[i + 1]
                try:
                    l = self.scene.addLine(n1["X"], n1["Y"], n2["X"], n2["Y"], highlight_pen)
                    l.setZValue(0.7)
                    l.setData(0, ("route_highlight", i))
                    self._highlight_lines.append(l)
                except Exception:
                    pass
        except Exception:
            pass

    def _obtener_ruta_completa(self, ruta_dict):
        """Obtiene todos los nodos de la ruta en orden: origen, visitas, destino"""
        nodos = []
        
        # Origen
        origen = ruta_dict.get("origen")
        if origen:
            nodos.append(origen)
        
        # Visita
        visita = ruta_dict.get("visita", [])
        nodos.extend(visita)
        
        # Destino
        destino = ruta_dict.get("destino")
        if destino:
            nodos.append(destino)
        
        return nodos

    def mostrar_propiedades_ruta(self, ruta):
        """
        Muestra la ruta en propertiesTable con el formato:
        Nombre: nombre_ruta
        Origen: id_origen
        Destino: id_destino  
        Ruta completa: [id_origen, id1, id2, id3, id_destino]
        """
        if not ruta:
            return

        try:
            ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
        except Exception:
            ruta_dict = ruta

        self._normalize_route_nodes(ruta_dict)

        try:
            self.view.propertiesTable.itemChanged.disconnect(self._actualizar_propiedad_ruta)
        except Exception:
            pass
        
        self.view.propertiesTable.blockSignals(True)
        self._limpiar_propiedades()

        # Obtener IDs de la ruta completa
        ruta_completa_ids = self._obtener_ids_ruta_completa(ruta_dict)
        ruta_completa_str = f"[{', '.join(str(id) for id in ruta_completa_ids)}]"
        
        # Obtener origen y destino actuales
        origen_id = self._obtener_id_nodo(ruta_dict.get("origen"))
        destino_id = self._obtener_id_nodo(ruta_dict.get("destino"))
        
        # Mostrar propiedades
        propiedades = [
            ("Nombre", ruta_dict.get("nombre", "Ruta")),
            ("Origen", origen_id),
            ("Destino", destino_id),
            ("Ruta completa", ruta_completa_str)
        ]

        self.view.propertiesTable.setRowCount(len(propiedades))

        for row, (clave, valor) in enumerate(propiedades):
            key_item = QTableWidgetItem(clave)
            key_item.setFlags(Qt.ItemIsEnabled)
            self.view.propertiesTable.setItem(row, 0, key_item)

            val_item = QTableWidgetItem(str(valor))
            val_item.setFlags(val_item.flags() | Qt.ItemIsEditable)
            val_item.setData(Qt.UserRole, (ruta_dict, clave.lower()))
            self.view.propertiesTable.setItem(row, 1, val_item)

        self.view.propertiesTable.blockSignals(False)
        self.view.propertiesTable.itemChanged.connect(self._actualizar_propiedad_ruta)

    def _obtener_id_nodo(self, nodo):
        """Obtiene el ID de un nodo, manejando diferentes formatos"""
        if not nodo:
            return ""
        
        if isinstance(nodo, dict):
            return nodo.get("id", "")
        elif hasattr(nodo, "id"):
            return getattr(nodo, "id", "")
        else:
            return str(nodo)

    def _obtener_ids_visita(self, visita):
        """Convierte una lista de nodos de visita en una lista de IDs"""
        if not visita:
            return "[]"
        
        ids = []
        for nodo in visita:
            ids.append(self._obtener_id_nodo(nodo))
        return f"[{', '.join(str(id) for id in ids)}]"

    def _obtener_ids_ruta_completa(self, ruta_dict):
        """Devuelve una lista de IDs de la ruta completa (origen + visita + destino)"""
        ids = []
        
        # Origen
        origen = ruta_dict.get("origen")
        if origen:
            origen_id = self._obtener_id_nodo(origen)
            if origen_id:
                ids.append(origen_id)
        
        # Visita (nodos intermedios)
        visita = ruta_dict.get("visita", [])
        for nodo_visita in visita:
            nodo_id = self._obtener_id_nodo(nodo_visita)
            if nodo_id:
                ids.append(nodo_id)
        
        # Destino
        destino = ruta_dict.get("destino")
        if destino:
            destino_id = self._obtener_id_nodo(destino)
            if destino_id and (not ids or destino_id != ids[0]):  # No agregar si es igual al origen
                ids.append(destino_id)
        
        return ids

    def _actualizar_ruta_desde_ids(self, ruta_dict, ids_ruta):
        """
        Actualiza la estructura de ruta (origen, visita, destino) a partir de una lista de IDs.
        Mantiene compatibilidad con la estructura existente.
        """
        if not ids_ruta:
            ruta_dict["origen"] = None
            ruta_dict["destino"] = None
            ruta_dict["visita"] = []
            return
        
        # Primer elemento es el origen
        primer_id = ids_ruta[0]
        nodo_existente = next((n for n in self.proyecto.nodos 
                            if self._obtener_id_nodo(n) == primer_id), None)
        if nodo_existente:
            ruta_dict["origen"] = nodo_existente
        else:
            ruta_dict["origen"] = {"id": primer_id, "X": 0, "Y": 0}
        
        # Último elemento es el destino (si hay más de un elemento)
        if len(ids_ruta) > 1:
            ultimo_id = ids_ruta[-1]
            nodo_existente = next((n for n in self.proyecto.nodos 
                                if self._obtener_id_nodo(n) == ultimo_id), None)
            if nodo_existente:
                ruta_dict["destino"] = nodo_existente
            else:
                ruta_dict["destino"] = {"id": ultimo_id, "X": 0, "Y": 0}
        else:
            # Si solo hay un elemento, el destino es el mismo que el origen
            ruta_dict["destino"] = ruta_dict["origen"]
        
        # Elementos intermedios son la visita
        if len(ids_ruta) > 2:
            nueva_visita = []
            for id_intermedio in ids_ruta[1:-1]:
                nodo_existente = next((n for n in self.proyecto.nodos 
                                    if self._obtener_id_nodo(n) == id_intermedio), None)
                if nodo_existente:
                    nueva_visita.append(nodo_existente)
                else:
                    nueva_visita.append({"id": id_intermedio, "X": 0, "Y": 0})
            ruta_dict["visita"] = nueva_visita
        else:
            ruta_dict["visita"] = []
            
    def _actualizar_propiedad_ruta(self, item):
        """Actualiza la ruta a través del proyecto para notificar cambios"""
        if item.column() != 1:
            return
            
        try:
            # Verificar que tenemos una ruta seleccionada
            if self.ruta_actual_idx is None:
                return

            # Obtener la ruta actual del proyecto
            if self.ruta_actual_idx >= len(self.proyecto.rutas):
                print("Índice de ruta inválido")
                return

            ruta_original = self.proyecto.rutas[self.ruta_actual_idx]
            # Convertir a diccionario
            try:
                ruta_dict = ruta_original.to_dict() if hasattr(ruta_original, "to_dict") else ruta_original
            except Exception:
                ruta_dict = ruta_original

            # Obtener el campo y el valor del item de la tabla
            data = item.data(Qt.UserRole)
            if not data or not isinstance(data, tuple):
                return
            campo = data[1]
            texto = item.text().strip()
            
            # Obtener el valor anterior ANTES de cambiarlo
            valor_anterior = None
            if campo == "nombre":
                valor_anterior = ruta_dict.get("nombre", "")
            elif campo == "origen":
                valor_anterior = self._obtener_id_nodo(ruta_dict.get("origen"))
            elif campo == "destino":
                valor_anterior = self._obtener_id_nodo(ruta_dict.get("destino"))
            elif campo == "ruta completa":
                # Obtener la ruta completa actual como string
                ruta_completa_ids = self._obtener_ids_ruta_completa(ruta_dict)
                valor_anterior = f"[{', '.join(str(id) for id in ruta_completa_ids)}]"
            
            
            # Procesar según el campo
            valor_nuevo = None
            if campo == "nombre":
                valor_nuevo = texto
                ruta_dict["nombre"] = texto
                
            elif campo == "origen":
                try:
                    nuevo_origen_id = int(texto)
                    # Obtener la ruta completa actual
                    ruta_completa_ids = self._obtener_ids_ruta_completa(ruta_dict)
                    
                    if ruta_completa_ids:
                        # Actualizar solo el primer elemento
                        ruta_completa_ids[0] = nuevo_origen_id
                    else:
                        # Si no hay ruta, crear una nueva
                        ruta_completa_ids = [nuevo_origen_id]
                    
                    # Reconstruir ruta a partir de la lista de IDs
                    self._actualizar_ruta_desde_ids(ruta_dict, ruta_completa_ids)
                    valor_nuevo = nuevo_origen_id
                except ValueError:
                    print(f"Error: ID de origen debe ser un número entero")
                    return
                    
            elif campo == "destino":
                try:
                    nuevo_destino_id = int(texto)
                    # Obtener la ruta completa actual
                    ruta_completa_ids = self._obtener_ids_ruta_completa(ruta_dict)
                    
                    if ruta_completa_ids:
                        # Actualizar solo el último elemento
                        if len(ruta_completa_ids) > 1:
                            ruta_completa_ids[-1] = nuevo_destino_id
                        else:
                            # Si solo hay un elemento, agregar el destino
                            ruta_completa_ids.append(nuevo_destino_id)
                    else:
                        # Si no hay ruta, crear una nueva
                        ruta_completa_ids = [nuevo_destino_id]
                    
                    # Reconstruir ruta a partir de la lista de IDs
                    self._actualizar_ruta_desde_ids(ruta_dict, ruta_completa_ids)
                    valor_nuevo = nuevo_destino_id
                except ValueError:
                    print(f"Error: ID de destino debe ser un número entero")
                    return
                    
            elif campo == "ruta completa":
                try:
                    # Parsear lista de IDs: [1, 2, 3] o 1, 2, 3
                    if texto.startswith('[') and texto.endswith(']'):
                        texto = texto[1:-1]
                    
                    ids_texto = [id_str.strip() for id_str in texto.split(',')] if texto else []
                    nueva_ruta_completa = []
                    
                    for id_str in ids_texto:
                        if id_str:  # Ignorar strings vacíos
                            try:
                                nodo_id = int(id_str)
                                nueva_ruta_completa.append(nodo_id)
                            except ValueError:
                                print(f"Error: ID de ruta debe ser número entero: {id_str}")
                    
                    # Reconstruir ruta a partir de la lista de IDs
                    self._actualizar_ruta_desde_ids(ruta_dict, nueva_ruta_completa)
                    valor_nuevo = f"[{', '.join(str(id) for id in nueva_ruta_completa)}]"
                    
                except Exception as e:
                    print(f"Error procesando ruta completa: {e}")
                    return

            # Registrar cambio en historial
            if valor_anterior is not None and valor_nuevo is not None and valor_anterior != valor_nuevo:
                self.registrar_cambio_propiedad_ruta(
                    self.ruta_actual_idx,
                    campo,
                    str(valor_anterior) if valor_anterior is not None else "",
                    str(valor_nuevo) if valor_nuevo is not None else ""
                )

            # Normalizar y actualizar referencia en proyecto.rutas usando el método del proyecto
            self._normalize_route_nodes(ruta_dict)
            self.proyecto.actualizar_ruta(self.ruta_actual_idx, ruta_dict)
            
            # Actualizar el texto en la lista lateral de rutas
            self._actualizar_widget_ruta_en_lista(self.ruta_actual_idx)
            
            # Redibujar rutas
            self._dibujar_rutas()
            
            # Actualizar la tabla de propiedades para mostrar cambios
            if self.ruta_actual_idx == self.ruta_actual_idx:
                self.mostrar_propiedades_ruta(ruta_dict)
            
            
        except Exception as err:
            print("Error en _actualizar_propiedad_ruta:", err)

    def _dibujar_rutas(self):
        try:
            self._clear_route_lines()
        except Exception as e:
            print(f"Error en clear: {e}")

        if not getattr(self, "proyecto", None) or not hasattr(self.proyecto, "rutas"):
            return

        self._reparar_referencias_rutas()
        self.rutas_para_dibujo = self._reconstruir_rutas_para_dibujo()
        
        base_pen = QPen(Qt.red, 2)
        base_pen.setCosmetic(True)
        self._route_lines = []

        for ruta_idx, ruta_reconstruida in enumerate(self.rutas_para_dibujo):
            if not ruta_reconstruida or len(ruta_reconstruida) < 2:
                self._route_lines.append([])
                continue

            route_line_items = []
            
            for i in range(len(ruta_reconstruida) - 1):
                n1, n2 = ruta_reconstruida[i], ruta_reconstruida[i + 1]

                # --- OBTENER Tipo_curva DEL NODO DESTINO ---
                tipo_curva_valor = 0
                nodo_id = None
                if isinstance(n2, dict):
                    nodo_id = n2.get('id')
                elif hasattr(n2, 'get'):
                    nodo_id = n2.get('id')

                if nodo_id is not None:
                    nodo_actual = self._obtener_nodo_actual(nodo_id)
                    if nodo_actual:
                        raw = nodo_actual.get('Tipo_curva', 0)
                        try:
                            tipo_curva_valor = int(raw)
                        except (ValueError, TypeError):
                            tipo_curva_valor = 0
                # -------------------------------------------

                segment_pen = QPen(base_pen)
                if tipo_curva_valor != 0:
                    segment_pen.setStyle(Qt.DashLine)
                else:
                    segment_pen.setStyle(Qt.SolidLine)
                
                try:
                    x1 = n1.get("X", 0) if isinstance(n1, dict) else getattr(n1, "X", 0)
                    y1 = n1.get("Y", 0) if isinstance(n1, dict) else getattr(n1, "Y", 0)
                    x2 = n2.get("X", 0) if isinstance(n2, dict) else getattr(n2, "X", 0)
                    y2 = n2.get("Y", 0) if isinstance(n2, dict) else getattr(n2, "Y", 0)
                    
                    line_item = self.scene.addLine(x1, y1, x2, y2, segment_pen)
                    line_item.setZValue(0.5)
                    line_item.setData(0, ("route_line", ruta_idx, i))
                    line_item.setVisible(True)
                    route_line_items.append(line_item)
                except Exception as e:
                    print(f"Error dibujando segmento: {e}")
                    continue
            
            self._route_lines.append(route_line_items)

        self.view.marco_trabajo.viewport().update()

    # --- Propiedades de nodo en QListWidget editable ---   
    def mostrar_propiedades_nodo(self, nodo):
        if self._updating_ui:
            return
        self._updating_ui = True

        try:
            try:
                self.view.propertiesTable.itemChanged.disconnect(self._actualizar_propiedad_nodo)
            except Exception:
                pass
            
            self.view.propertiesTable.blockSignals(True)

            self.view.propertiesTable.clear()
            self.view.propertiesTable.setColumnCount(2)
            self.view.propertiesTable.setHorizontalHeaderLabels(["Propiedad", "Valor"])

            propiedades = nodo.to_dict() if hasattr(nodo, "to_dict") else nodo

            # Mostrar ID del nodo en la etiqueta superior
            nodo_id = propiedades.get("id", "?") if isinstance(propiedades, dict) else "?"
            self.lbl_nodo_seleccionado.setText(f"Nodo #{nodo_id}")
            self.lbl_nodo_seleccionado.show()
            
            # Propiedades básicas desde el esquema: todas las de NODO_FIELDS salvo 'id'
            # y las que pertenecen a OBJETIVO_FIELDS (que se editan en el diálogo avanzado).
            # Se excluye 'es_cargador' porque se maneja dentro del combo de objetivo.
            propiedades_basicas = [
                k for k in NODO_FIELDS.keys()
                if k != 'id' and k not in OBJETIVO_FIELDS and k != 'es_cargador'
            ]
            claves_filtradas = [k for k in propiedades_basicas if k in propiedades]

            # Si el nodo tiene objetivo != 0 (y no es "Paso"=5), añadimos espacio para el botón
            objetivo = propiedades.get("objetivo", 0)
            if objetivo != 0 and objetivo != 5:
                total_filas = len(claves_filtradas) + 2  # +1 para separador, +1 para botón
            else:
                total_filas = len(claves_filtradas)
            
            self.view.propertiesTable.setRowCount(total_filas)

            # Opciones del desplegable de objetivo con colores
            OBJETIVO_OPCIONES = [
                (0, "Normal", "#0078D7"),
                (1, "Dejada", "#DC2828"),
                (2, "Cogida", "#00B43C"),
                (3, "I/O", "#9600C8"),
                (4, "Cargador", "#E68200"),
                (5, "Paso", "#BBBBBB"),
            ]

            # Mostrar propiedades básicas
            for row, clave in enumerate(claves_filtradas):
                valor = propiedades.get(clave)

                # Convertir X e Y a metros para mostrar (con offset)
                if clave == "X" and isinstance(valor, (int, float)):
                    valor = self.x_px_a_metros(valor)
                elif clave == "Y" and isinstance(valor, (int, float)):
                    valor = self.y_px_a_metros(valor)

                # Nombres de display con unidades / etiquetas legibles
                nombres_display = {
                    "timeout": "timeout (s)",
                    "seg_2d_tras": "seguridad 2d trasera",
                }
                nombre_mostrar = nombres_display.get(clave, clave)

                key_item = QTableWidgetItem(nombre_mostrar)
                key_item.setFlags(Qt.ItemIsEnabled)
                self.view.propertiesTable.setItem(row, 0, key_item)

                # Para "objetivo" y "es_cargador", usar combo desplegable
                if clave == "objetivo":
                    # Subclase que ignora flechas con popup cerrado para que la
                    # navegación con teclado en la tabla no abra el diálogo
                    # de objetivo sin querer.
                    combo = _ComboObjetivoSinFlechas()
                    combo.setFocusPolicy(Qt.ClickFocus)
                    # Colores para referencia rápida
                    colores_combo = [c for _, _, c in OBJETIVO_OPCIONES]

                    def _aplicar_color_combo(cb, idx, colores=colores_combo):
                        """Aplica el color correspondiente al texto del combo"""
                        color_hex = colores[idx] if idx < len(colores) else "#FFFFFF"
                        cb.setStyleSheet(f"""
                            QComboBox {{
                                background-color: #3c3c3c;
                                color: {color_hex};
                                border: 1px solid #555;
                                padding: 2px 5px;
                                font-size: 13px;
                                font-weight: bold;
                            }}
                            QComboBox::drop-down {{
                                border: none;
                            }}
                            QComboBox QAbstractItemView {{
                                background-color: #2d2d2d;
                                color: white;
                                selection-background-color: #555;
                            }}
                        """)

                    current_val = int(valor) if valor is not None else 0
                    current_index = 0
                    for i, (val, nombre, color) in enumerate(OBJETIVO_OPCIONES):
                        combo.addItem(f"  ● {nombre}", val)
                        from PyQt5.QtGui import QColor as QC
                        combo.model().item(i).setForeground(QC(color))
                        if val == current_val:
                            current_index = i

                    combo.setCurrentIndex(current_index)
                    _aplicar_color_combo(combo, current_index)

                    def on_objetivo_activated(index, n=nodo, cb=combo):
                        """Solo se dispara cuando el USUARIO selecciona del combo"""
                        try:
                            _aplicar_color_combo(cb, index)
                            new_val = cb.itemData(index)
                            old_val = n.get("objetivo", 0)
                            if new_val == old_val:
                                return
                            if new_val == 4:
                                # Mantener es_cargador actual si ya tenía un valor, si no forzar a 0
                                # (el diálogo de propiedades pedirá el ID obligatoriamente)
                                actual_cargador = int(n.get("es_cargador", 0) or 0)
                                self.proyecto.actualizar_nodo({"id": n.get("id"), "objetivo": 4, "es_cargador": actual_cargador})
                            else:
                                self.proyecto.actualizar_nodo({"id": n.get("id"), "objetivo": new_val, "es_cargador": 0})
                            # "Paso" (5) se comporta como Normal (0): no abre diálogo de objetivo
                            # ni agrega propiedades avanzadas; sólo cambia el color y el valor en CSV.
                            if new_val == 5:
                                self._on_nodo_modificado(n)
                                return
                            if new_val != 0:
                                punto_encarar = n.get("Punto_encarar", 0)
                                if punto_encarar == 0 or punto_encarar == "0":
                                    if isinstance(n, dict):
                                        n["Punto_encarar"] = n.get("id", 0)
                                    else:
                                        n.update({"Punto_encarar": n.get("id", 0)})
                                # Nombre por defecto según tipo de objetivo
                                nombres_default = {1: "Dejada", 2: "Cogida", 3: "I/O", 4: "Cargador"}
                                nombre_actual = n.get("Nombre", "")
                                if not nombre_actual or nombre_actual in ("", "Dejada", "Cogida", "I/O", "Cargador"):
                                    nombre_def = nombres_default.get(new_val, "")
                                    if isinstance(n, dict):
                                        n["Nombre"] = nombre_def
                                    else:
                                        n.update({"Nombre": nombre_def})
                                # Abrir popup ANTES de refrescar la tabla
                                # Abrir popup: si cancela, revertir objetivo
                                resultado = self._mostrar_dialogo_propiedades_objetivo(n)
                                if resultado == "cancelado":
                                    # Revertir objetivo al valor anterior
                                    if old_val == 4:
                                        self.proyecto.actualizar_nodo({"id": n.get("id"), "objetivo": old_val, "es_cargador": 1})
                                    else:
                                        self.proyecto.actualizar_nodo({"id": n.get("id"), "objetivo": old_val, "es_cargador": 0})
                                    if isinstance(n, dict):
                                        n["Nombre"] = ""
                                    else:
                                        n.update({"Nombre": ""})
                                    self._on_nodo_modificado(n)
                                    return
                            self._on_nodo_modificado(n)
                        except Exception as e:
                            print(f"ERROR en on_objetivo_activated: {e}")
                            import traceback
                            traceback.print_exc()

                    combo.activated.connect(on_objetivo_activated)
                    self.view.propertiesTable.setCellWidget(row, 1, combo)
                    continue

                # Para X/Y, mostrar con 4 decimales para evitar ruido por
                # imprecisión de float (p.ej. "47.36999999999999" en vez de "47.37")
                if clave in ("X", "Y"):
                    try:
                        texto_celda = f"{float(valor):.4f}"
                    except (ValueError, TypeError):
                        texto_celda = str(valor)
                else:
                    texto_celda = str(valor)
                val_item = QTableWidgetItem(texto_celda)
                val_item.setFlags(val_item.flags() | Qt.ItemIsEditable)
                val_item.setData(Qt.UserRole, (nodo, clave))
                self.view.propertiesTable.setItem(row, 1, val_item)
            
            # Si el nodo tiene objetivo != 0 (y no es "Paso"=5), añadir un botón para editar propiedades avanzadas
            if objetivo != 0 and objetivo != 5:
                fila_separador = len(claves_filtradas)
                fila_boton = fila_separador + 1
                
                # Crear una fila separadora (opcional, pero mejora la visualización)
                separator_item = QTableWidgetItem("")
                separator_item.setFlags(Qt.NoItemFlags)
                separator_item.setBackground(Qt.lightGray)
                self.view.propertiesTable.setItem(fila_separador, 0, separator_item)
                
                # Crear una celda combinada para el separador
                self.view.propertiesTable.setSpan(fila_separador, 0, 1, 2)
                
                # Crear un widget con un botón para propiedades avanzadas
                from PyQt5.QtWidgets import QPushButton
                boton = QPushButton("Propiedades Avanzadas...")
                boton.setStyleSheet("""
                    QPushButton {
                        background-color: #4a4a4a;
                        color: white;
                        border: 1px solid #555555;
                        border-radius: 3px;
                        padding: 5px;
                    }
                    QPushButton:hover {
                        background-color: #5a5a5a;
                    }
                """)
                boton.clicked.connect(lambda: self._mostrar_dialogo_propiedades_objetivo(nodo))
                
                # Crear item para la etiqueta
                label_item = QTableWidgetItem("Configuración Avanzada:")
                label_item.setFlags(Qt.ItemIsEnabled)
                self.view.propertiesTable.setItem(fila_boton, 0, label_item)
                
                # Colocar el botón en la columna de valor
                self.view.propertiesTable.setCellWidget(fila_boton, 1, boton)
                
        finally:
            self.view.propertiesTable.blockSignals(False)
            self.view.propertiesTable.itemChanged.connect(self._actualizar_propiedad_nodo)
        self._updating_ui = False

    def _mostrar_dialogo_propiedades_objetivo(self, nodo):
        """Muestra el diálogo de propiedades de objetivo para un nodo"""
        # Obtener las propiedades actuales del nodo
        if hasattr(nodo, 'to_dict'):
            propiedades_actuales = nodo.to_dict()
        elif isinstance(nodo, dict):
            propiedades_actuales = nodo
        else:
            propiedades_actuales = {}

        # Pre-cargar Punto_encarar con el ID del nodo si no tiene valor
        punto_encarar = propiedades_actuales.get("Punto_encarar", 0)
        if punto_encarar == 0 or punto_encarar == "0":
            propiedades_actuales["Punto_encarar"] = propiedades_actuales.get("id", 0)

        # Crear y mostrar el diálogo
        from View.dialogo_propiedades_objetivo import DialogoPropiedadesObjetivo
        dialogo = DialogoPropiedadesObjetivo(self.view, propiedades_actuales)
        
        if dialogo.exec_() == QDialog.Accepted:
            # Obtener las propiedades del diálogo
            nuevas_propiedades = dialogo.obtener_propiedades()

            # Registrar cada cambio individual en el historial
            for clave, valor in nuevas_propiedades.items():
                valor_anterior = propiedades_actuales.get(clave)
                if valor_anterior is not None and valor_anterior != valor:
                    self.registrar_cambio_propiedad_nodo(
                        nodo.get('id'),
                        clave,
                        valor_anterior,
                        valor
                    )

            # Actualizar todas las propiedades a la vez
            datos_actualizacion = {"id": nodo.get('id')}
            datos_actualizacion.update(nuevas_propiedades)
            self.proyecto.actualizar_nodo(datos_actualizacion)
            return True
        # Distinguir Cancelar (revertir) de cerrar con X (ya se validó y aceptó arriba)
        if getattr(dialogo, '_cancelado', False):
            return "cancelado"
        return True
            

    def _actualizar_propiedad_nodo(self, item):
        """Actualiza la propiedad de un nodo a través del proyecto para notificar cambios"""
        if self._updating_ui or item.column() != 1:
            return
        self.proyecto_modificado = True

        try:
            nodo, clave = item.data(Qt.UserRole)
        except Exception:
            return

        texto = item.text()
        
        # Obtener el valor anterior ANTES de cambiarlo
        valor_anterior = None
        if hasattr(nodo, 'get'):
            valor_anterior = nodo.get(clave)
        elif hasattr(nodo, clave):
            valor_anterior = getattr(nodo, clave)
        
        # Detectar si estamos editando el campo "objetivo"
        if clave == "objetivo":
            try:
                nuevo_objetivo = int(texto)
                valor_anterior_int = int(valor_anterior) if valor_anterior is not None else 0
                
                # Solo proceder si realmente hay un cambio
                if nuevo_objetivo != valor_anterior_int:
                    # Registrar el cambio en historial
                    if valor_anterior is not None:
                        self.registrar_cambio_propiedad_nodo(
                            nodo.get('id'), 
                            clave, 
                            valor_anterior, 
                            nuevo_objetivo
                        )
                    
                    # Actualizar el objetivo
                    self.proyecto.actualizar_nodo({
                        "id": nodo.get('id'),
                        clave: nuevo_objetivo
                    })
                    
                    # Si el objetivo cambia a un valor diferente de 0 (y antes era 0)
                    # mostrar diálogo de propiedades de objetivo
                    if nuevo_objetivo != 0 and valor_anterior_int == 0:
                        # Pequeño delay para asegurar que la UI se actualice
                        from PyQt5.QtCore import QTimer
                        QTimer.singleShot(100, lambda: self._mostrar_dialogo_propiedades_objetivo(nodo))
                    
                    # Si el objetivo cambia de diferente de 0 a 0
                    elif nuevo_objetivo == 0 and valor_anterior_int != 0:
                        pass  # Las propiedades avanzadas se mantienen pero no se muestran

                return  # Salir ya que hemos manejado el cambio de objetivo
                    
            except ValueError:
                print(f"Error: objetivo debe ser un número entero")
                # Restaurar el valor anterior
                if valor_anterior is not None:
                    item.setText(str(valor_anterior))
                return
        
        # Si la clave es X o Y, parsear como float aceptando coma o punto decimal
        if clave in ["X", "Y"]:
            try:
                texto_normalizado = texto.replace(',', '.').strip()
                valor_metros = float(texto_normalizado)
            except (ValueError, TypeError):
                print(f"Error: Valor de {clave} debe ser un número (recibido: {repr(texto)})")
                # Restaurar el valor anterior en la celda
                if valor_anterior is not None:
                    if clave == "Y":
                        anterior_m = self.y_px_a_metros(valor_anterior)
                    else:
                        anterior_m = self.x_px_a_metros(valor_anterior)
                    self._updating_ui = True
                    try:
                        item.setText(f"{anterior_m:.4f}")
                    finally:
                        self._updating_ui = False
                return

            # Convertir metros a píxeles (con offset)
            if clave == "Y":
                valor_pixeles = self.y_metros_a_px(valor_metros)
            else:
                valor_pixeles = self.x_metros_a_px(valor_metros)

            # Registrar en historial (en metros para el usuario)
            if valor_anterior is not None:
                if clave == "Y":
                    valor_anterior_metros = self.y_px_a_metros(valor_anterior)
                else:
                    valor_anterior_metros = self.x_px_a_metros(valor_anterior)
                self.registrar_cambio_propiedad_nodo(
                    nodo.get('id'),
                    clave,
                    valor_anterior_metros,
                    valor_metros
                )

            # Marcar que la modificación viene desde la tabla:
            # _on_nodo_modificado evitará refrescar la tabla y romper la edición.
            self._updating_from_table = True
            try:
                self.proyecto.actualizar_nodo({
                    "id": nodo.get('id'),
                    clave: valor_pixeles
                })
            finally:
                self._updating_from_table = False

            # Forzar actualización visual del NodoItem en la escena
            nodo_id = nodo.get('id')
            for scene_item in self.scene.items():
                if isinstance(scene_item, NodoItem) and scene_item.nodo.get('id') == nodo_id:
                    scene_item.actualizar_posicion()
                    scene_item.update()
                    break
            return

        # Para todas las demás propiedades, intentar parsear como literal de Python
        try:
            valor = ast.literal_eval(texto)
        except Exception:
            valor = texto

        try:
            if valor_anterior is not None and valor_anterior != valor:
                self.registrar_cambio_propiedad_nodo(
                    nodo.get('id'),
                    clave,
                    valor_anterior,
                    valor
                )

            self._updating_from_table = True
            try:
                self.proyecto.actualizar_nodo({
                    "id": nodo.get('id'),
                    clave: valor
                })
            finally:
                self._updating_from_table = False

        except Exception as err:
            print("Error actualizando nodo en el modelo:", err)
            

    # --- Eliminar nodo con reconfiguración de rutas ---
    def eliminar_nodo(self, nodo, nodo_item):
        """
        Elimina un nodo del proyecto y de la escena. Además:
        - Reconfigura las rutas que contengan este nodo según su posición:
        * Si es el origen: toma el primer elemento de visita como nuevo origen
        * Si es el destino: toma el último elemento de visita como nuevo destino
        * Si es intermedio: elimina el nodo de la visita y reconecta
        - Actualiza la lista lateral de nodos y rutas y limpia el panel de propiedades si procede.
        """
        self.proyecto_modificado = True
        try:
            # GUARDAR INFORMACIÓN PARA UNDO
            # Guardar una copia profunda del nodo y rutas afectadas
            nodo_copia = copy.deepcopy(nodo)
            
            # Encontrar todas las rutas que contienen este nodo
            rutas_afectadas = []
            if hasattr(self.proyecto, 'rutas'):
                for idx, ruta in enumerate(self.proyecto.rutas):
                    try:
                        ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                        self._normalize_route_nodes(ruta_dict)
                        
                        # Verificar si la ruta contiene el nodo
                        contiene_nodo = False
                        
                        # Origen
                        origen = ruta_dict.get("origen")
                        if origen and isinstance(origen, dict) and origen.get('id') == nodo.get('id'):
                            contiene_nodo = True
                        
                        # Destino
                        destino = ruta_dict.get("destino")
                        if not contiene_nodo and destino and isinstance(destino, dict) and destino.get('id') == nodo.get('id'):
                            contiene_nodo = True
                        
                        # Visita
                        if not contiene_nodo:
                            for nodo_visita in ruta_dict.get("visita", []):
                                if isinstance(nodo_visita, dict) and nodo_visita.get('id') == nodo.get('id'):
                                    contiene_nodo = True
                                    break
                        
                        if contiene_nodo:
                            # Guardar una copia de la ruta antes de modificar
                            rutas_afectadas.append({
                                'indice': idx,
                                'ruta_original': copy.deepcopy(ruta_dict)
                            })
                    except Exception as e:
                        print(f"Error al procesar ruta para undo: {e}")
                        continue
            
            nodo_id = nodo.get("id")

            # 1) Quitar de la escena el NodoItem visual.
            #    Si nos pasaron el item, lo intentamos directo. Además
            #    barremos la escena buscando por id por si quedó algún
            #    NodoItem duplicado/huérfano (esto evitaba que el vértice
            #    "no se eliminara" cuando el item recibido estaba stale).
            try:
                if nodo_item is not None and getattr(nodo_item, "scene", None) and nodo_item.scene() is not None:
                    self.scene.removeItem(nodo_item)
            except Exception:
                pass

            try:
                for sit in list(self.scene.items()):
                    if isinstance(sit, NodoItem) and sit.nodo.get('id') == nodo_id:
                        try:
                            self.scene.removeItem(sit)
                        except Exception:
                            pass
            except Exception:
                pass

            # Forzar repintado completo de la escena para eliminar
            # residuos visuales del nodo (artefactos por rotación/margen extra)
            try:
                self.scene.update()
                self.view.marco_trabajo.viewport().update()
            except Exception:
                pass

            # 2) Quitar del modelo por identidad o por id
            nodo_encontrado = False
            try:
                if nodo in self.proyecto.nodos:
                    self.proyecto.nodos.remove(nodo)
                    nodo_encontrado = True
                else:
                    # Buscar por ID
                    for i, n in enumerate(self.proyecto.nodos):
                        if n.get("id") == nodo_id:
                            self.proyecto.nodos.pop(i)
                            nodo_encontrado = True
                            break
            except Exception:
                # fallback por id
                self.proyecto.nodos = [n for n in getattr(self.proyecto, "nodos", []) if n.get("id") != nodo_id]
                nodo_encontrado = True

            if not nodo_encontrado:
                print(f"Advertencia: Nodo {nodo_id} no encontrado en proyecto.nodos")

            # 3) Eliminar de visibilidad y relaciones
            if nodo_id in self.visibilidad_nodos:
                del self.visibilidad_nodos[nodo_id]
            if nodo_id in self.nodo_en_rutas:
                del self.nodo_en_rutas[nodo_id]

            # 4) RECONFIGURAR RUTAS en lugar de eliminarlas
            try:
                self._reconfigurar_rutas_por_eliminacion(nodo_id)
            except Exception as err:
                print("Error reconfigurando rutas:", err)
                # fallback: redibujar todo
                try:
                    self._dibujar_rutas()
                    self._mostrar_rutas_lateral()
                except Exception:
                    pass

            # 5) Si el nodo estaba seleccionado, limpiar propiedades y deseleccionar visualmente
            try:
                seleccionados = self.view.nodosList.selectedItems()
                if seleccionados:
                    for i in range(self.view.nodosList.count()):
                        item = self.view.nodosList.item(i)
                        widget = self.view.nodosList.itemWidget(item)
                        if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                            self._limpiar_propiedades()
                            break
            except Exception:
                pass

            # 6) Actualizar lista de nodos
            self._actualizar_lista_nodos_con_widgets()

            # 7) REGISTRAR LA ELIMINACIÓN EN EL HISTORIAL
            self._registrar_eliminacion_nodo(nodo_copia, rutas_afectadas)

            print(f"Nodo eliminado: {nodo_id}")
        except Exception as err:
            print("Error eliminando nodo:", err)

    def _reconfigurar_rutas_por_eliminacion(self, nodo_id_eliminado):
        """
        Reconfigura las rutas que contienen el nodo eliminado según su posición:
        - Si es origen: primer elemento de visita como nuevo origen
        - Si es destino: último elemento de visita como nuevo destino
        - Si es intermedio: elimina el nodo de la visita y reconecta
        - Si la ruta queda con solo un nodo, se elimina automáticamente
        """
        if not getattr(self, "proyecto", None):
            return

        nuevas_rutas = []
        
        for ruta in getattr(self.proyecto, "rutas", []) or []:
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta

            # Normalizar la ruta primero
            self._normalize_route_nodes(ruta_dict)
            
            origen = ruta_dict.get("origen")
            visita = ruta_dict.get("visita", []) or []
            destino = ruta_dict.get("destino")
            
            # Verificar si la ruta contiene el nodo eliminado
            contiene_nodo = False
            posicion_en_ruta = None
            
            # Verificar origen
            if origen and isinstance(origen, dict) and origen.get("id") == nodo_id_eliminado:
                contiene_nodo = True
                posicion_en_ruta = "origen"
            
            # Verificar destino
            if not contiene_nodo and destino and isinstance(destino, dict) and destino.get("id") == nodo_id_eliminado:
                contiene_nodo = True
                posicion_en_ruta = "destino"
            
            # Verificar visita
            if not contiene_nodo:
                for i, nodo_visita in enumerate(visita):
                    if isinstance(nodo_visita, dict) and nodo_visita.get("id") == nodo_id_eliminado:
                        contiene_nodo = True
                        posicion_en_ruta = f"visita_{i}"
                        break
            
            if not contiene_nodo:
                # La ruta no contiene el nodo eliminado, se mantiene igual
                nuevas_rutas.append(ruta)
                continue
            
            
            # RECONFIGURACIÓN SEGÚN POSICIÓN
            if posicion_en_ruta == "origen":
                # Si es el origen: tomar primer elemento de visita como nuevo origen
                if visita:
                    nuevo_origen = visita[0]
                    nueva_visita = visita[1:]  # resto de la visita
                    nuevo_destino = destino

                    ruta_dict["origen"] = nuevo_origen
                    ruta_dict["visita"] = nueva_visita
                    ruta_dict["destino"] = nuevo_destino

                    # Verificar si la ruta queda con al menos 2 nodos
                    if self._ruta_tiene_al_menos_dos_nodos(ruta_dict):
                        nuevas_rutas.append(ruta_dict)
                else:
                    # No hay visita, el destino pasa a ser el nuevo origen
                    if destino:
                        ruta_dict["origen"] = destino
                        ruta_dict["visita"] = []
                        ruta_dict["destino"] = None

                        # Verificar si la ruta queda con al menos 2 nodos
                        if self._ruta_tiene_al_menos_dos_nodos(ruta_dict):
                            nuevas_rutas.append(ruta_dict)
                    # else: No hay destino, la ruta queda inválida - se elimina

            elif posicion_en_ruta == "destino":
                # Si es el destino: tomar último elemento de visita como nuevo destino
                if visita:
                    nuevo_origen = origen
                    nueva_visita = visita[:-1]  # todos menos el último
                    nuevo_destino = visita[-1]  # último elemento

                    ruta_dict["origen"] = nuevo_origen
                    ruta_dict["visita"] = nueva_visita
                    ruta_dict["destino"] = nuevo_destino

                    # Verificar si la ruta queda con al menos 2 nodos
                    if self._ruta_tiene_al_menos_dos_nodos(ruta_dict):
                        nuevas_rutas.append(ruta_dict)
                else:
                    # No hay visita, el origen pasa a ser el nuevo destino
                    if origen:
                        ruta_dict["origen"] = None
                        ruta_dict["visita"] = []
                        ruta_dict["destino"] = origen

                        # Verificar si la ruta queda con al menos 2 nodos
                        if self._ruta_tiene_al_menos_dos_nodos(ruta_dict):
                            nuevas_rutas.append(ruta_dict)
                    # else: No hay origen, la ruta queda inválida - se elimina

            elif posicion_en_ruta.startswith("visita_"):
                # Si es intermedio: eliminar de la visita y mantener conexión
                posicion = int(posicion_en_ruta.split("_")[1])

                nuevo_origen = origen
                nueva_visita = [n for i, n in enumerate(visita) if i != posicion]
                nuevo_destino = destino

                ruta_dict["origen"] = nuevo_origen
                ruta_dict["visita"] = nueva_visita
                ruta_dict["destino"] = nuevo_destino

                # Verificar si la ruta queda con al menos 2 nodos
                if self._ruta_tiene_al_menos_dos_nodos(ruta_dict):
                    nuevas_rutas.append(ruta_dict)

            else:
                # Caso por defecto - mantener la ruta si tiene al menos 2 nodos
                if self._ruta_tiene_al_menos_dos_nodos(ruta_dict):
                    nuevas_rutas.append(ruta)
        
        # Actualizar las rutas del proyecto
        try:
            self.proyecto.rutas = nuevas_rutas
        except Exception:
            setattr(self.proyecto, "rutas", nuevas_rutas)
        
        # Actualizar visibilidad de rutas y relaciones
        self.visibilidad_rutas.clear()
        self.nodo_en_rutas.clear()
        for idx in range(len(nuevas_rutas)):
            self.visibilidad_rutas[idx] = True
            # Reconstruir relaciones
            self._actualizar_relaciones_nodo_ruta(idx, nuevas_rutas[idx])
        
        # Redibujar rutas y actualizar UI
        try:
            self._dibujar_rutas()
            self._mostrar_rutas_lateral()
        except Exception as err:
            print("Error actualizando UI después de reconfigurar rutas:", err)

    def _ruta_tiene_al_menos_dos_nodos(self, ruta_dict):
        """
        Verifica si una ruta tiene al menos 2 nodos (origen, destino o nodos en visita).
        Una ruta necesita al menos 2 nodos para poder trazar líneas entre ellos.
        """
        try:
            # Contar nodos en origen, destino y visita
            count = 0
            
            if ruta_dict.get("origen") is not None:
                count += 1
            
            if ruta_dict.get("destino") is not None:
                count += 1
            
            count += len(ruta_dict.get("visita", []) or [])
            
            return count >= 2
        except Exception:
            return False

    # --- Normalizador mejorado para rutas ---
    def _normalize_route_nodes(self, ruta_dict):
        """
        RECONSTRUYE COMPLETAMENTE las referencias de nodos en las rutas
        usando los nodos actuales del proyecto. VERSIÓN CORREGIDA.
        """
        try:
            # 1. NORMALIZAR ORIGEN - Buscar el nodo actual en self.proyecto.nodos
            origen = ruta_dict.get("origen")
            if origen:
                if isinstance(origen, dict) and 'id' in origen:
                    origen_id = origen['id']
                    
                    # Buscar el nodo ACTUAL en el proyecto
                    nodo_actual = None
                    for nodo in getattr(self.proyecto, "nodos", []):
                        try:
                            # Usar nodo.get() para objetos Nodo
                            if hasattr(nodo, 'get'):
                                if nodo.get('id') == origen_id:
                                    nodo_actual = nodo
                                    break
                            elif isinstance(nodo, dict) and nodo.get('id') == origen_id:
                                nodo_actual = nodo
                                break
                        except Exception as e:
                            continue
                    
                    if nodo_actual:
                        # Actualizar las coordenadas del origen con las del nodo actual
                        if hasattr(nodo_actual, 'get'):
                            origen['X'] = nodo_actual.get('X')
                            origen['Y'] = nodo_actual.get('Y')
                        else:
                            origen['X'] = nodo_actual.get('X', origen.get('X', 0))
                            origen['Y'] = nodo_actual.get('Y', origen.get('Y', 0))
                        ruta_dict["origen"] = origen
            
            # 2. NORMALIZAR DESTINO 
            destino = ruta_dict.get("destino")
            if destino:
                if isinstance(destino, dict) and 'id' in destino:
                    destino_id = destino['id']
                    
                    # Buscar el nodo ACTUAL en el proyecto
                    nodo_actual = None
                    for nodo in getattr(self.proyecto, "nodos", []):
                        try:
                            # Usar nodo.get() para objetos Nodo
                            if hasattr(nodo, 'get'):
                                if nodo.get('id') == destino_id:
                                    nodo_actual = nodo
                                    break
                            elif isinstance(nodo, dict) and nodo.get('id') == destino_id:
                                nodo_actual = nodo
                                break
                        except Exception as e:
                            continue
                    
                    if nodo_actual:
                        # Actualizar las coordenadas del destino con las del nodo actual
                        if hasattr(nodo_actual, 'get'):
                            destino['X'] = nodo_actual.get('X')
                            destino['Y'] = nodo_actual.get('Y')
                        else:
                            destino['X'] = nodo_actual.get('X', destino.get('X', 0))
                            destino['Y'] = nodo_actual.get('Y', destino.get('Y', 0))
                        ruta_dict["destino"] = destino
            
            # 3. NORMALIZAR VISITA
            visita = ruta_dict.get("visita", []) or []
            nueva_visita = []
            
            for v in visita:
                if isinstance(v, dict) and 'id' in v:
                    visita_id = v['id']
                    
                    # Buscar el nodo ACTUAL en el proyecto
                    nodo_actual = None
                    for nodo in getattr(self.proyecto, "nodos", []):
                        try:
                            # Usar nodo.get() para objetos Nodo
                            if hasattr(nodo, 'get'):
                                if nodo.get('id') == visita_id:
                                    nodo_actual = nodo
                                    break
                            elif isinstance(nodo, dict) and nodo.get('id') == visita_id:
                                nodo_actual = nodo
                                break
                        except Exception as e:
                            continue
                    
                    if nodo_actual:
                        # Actualizar las coordenadas de la visita con las del nodo actual
                        if hasattr(nodo_actual, 'get'):
                            v['X'] = nodo_actual.get('X')
                            v['Y'] = nodo_actual.get('Y')
                        else:
                            v['X'] = nodo_actual.get('X', v.get('X', 0))
                            v['Y'] = nodo_actual.get('Y', v.get('Y', 0))
                        nueva_visita.append(v)
                    else:
                        nueva_visita.append(v)
                else:
                    nueva_visita.append(v)
            
            ruta_dict["visita"] = nueva_visita
            
        except Exception as e:
            print(f"ERROR CRÍTICO en _normalize_route_nodes: {e}")

    # --- MÉTODOS NUEVOS PARA REPARACIÓN DE REFERENCIAS ---
    
    def _reparar_referencias_rutas(self):
        """
        REPARA LAS RUTAS: Asegura que todos los nodos en las rutas existan en el proyecto
        y actualiza las referencias con los nodos actuales. VERSIÓN CORREGIDA.
        """
        if not hasattr(self.proyecto, "nodos") or not hasattr(self.proyecto, "rutas"):
            return

        # Crear mapa de nodos por ID para búsqueda rápida 
        mapa_nodos = {}
        for nodo in self.proyecto.nodos:
            try:
                # CORRECCIÓN: Usar nodo.get() para objetos Nodo
                if hasattr(nodo, 'get'):
                    nodo_id = nodo.get('id')
                else:
                    nodo_id = nodo.get('id') if isinstance(nodo, dict) else None
                    
                if nodo_id is not None:
                    mapa_nodos[nodo_id] = nodo
            except Exception as e:
                pass

        for ruta_idx, ruta in enumerate(self.proyecto.rutas):
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                
                # Reparar ORIGEN 
                origen = ruta_dict.get("origen")
                if origen and isinstance(origen, dict) and 'id' in origen:
                    origen_id = origen['id']
                    if origen_id in mapa_nodos:
                        # Actualizar coordenadas en lugar de reemplazar el objeto
                        nodo_actual = mapa_nodos[origen_id]
                        if hasattr(nodo_actual, 'get'):
                            origen['X'] = nodo_actual.get('X')
                            origen['Y'] = nodo_actual.get('Y')
                        else:
                            origen['X'] = nodo_actual.get('X', origen.get('X', 0))
                            origen['Y'] = nodo_actual.get('Y', origen.get('Y', 0))
                
                # Reparar DESTINO 
                destino = ruta_dict.get("destino")
                if destino and isinstance(destino, dict) and 'id' in destino:
                    destino_id = destino['id']
                    if destino_id in mapa_nodos:
                        # Actualizar coordenadas en lugar de reemplazar el objeto
                        nodo_actual = mapa_nodos[destino_id]
                        if hasattr(nodo_actual, 'get'):
                            destino['X'] = nodo_actual.get('X')
                            destino['Y'] = nodo_actual.get('Y')
                        else:
                            destino['X'] = nodo_actual.get('X', destino.get('X', 0))
                            destino['Y'] = nodo_actual.get('Y', destino.get('Y', 0))
                
                # Reparar VISITA
                visita = ruta_dict.get("visita", [])
                nueva_visita = []
                for v in visita:
                    if isinstance(v, dict) and 'id' in v:
                        visita_id = v['id']
                        if visita_id in mapa_nodos:
                            # Actualizar coordenadas en lugar de reemplazar el objeto
                            nodo_actual = mapa_nodos[visita_id]
                            if hasattr(nodo_actual, 'get'):
                                v['X'] = nodo_actual.get('X')
                                v['Y'] = nodo_actual.get('Y')
                            else:
                                v['X'] = nodo_actual.get('X', v.get('X', 0))
                                v['Y'] = nodo_actual.get('Y', v.get('Y', 0))
                            nueva_visita.append(v)
                        else:
                            nueva_visita.append(v)
                    else:
                        nueva_visita.append(v)
                
                ruta_dict["visita"] = nueva_visita
                
                # Actualizar la ruta en el proyecto
                self.proyecto.rutas[ruta_idx] = ruta_dict
                    
            except Exception as e:
                print(f"Error reparando ruta {ruta_idx}: {e}")

    # --- Actualizar líneas cuando un nodo se mueve ---
    def on_nodo_moved(self, nodo_item):
        """Versión CORREGIDA para actualización en tiempo real durante arrastre"""
        try:
            self.proyecto_modificado = True
            # Verificar que estamos en modo mover
            if self.modo_actual != "mover":
                return
                
            
            nodo = getattr(nodo_item, "nodo", None)
            if not nodo:
                print("ERROR: nodo_item no tiene atributo 'nodo'")
                return

            # Obtener posición ACTUAL del nodo DURANTE el arrastre
            scene_pos = nodo_item.scenePos()
            x = int(scene_pos.x() + nodo_item.size / 2)
            y = int(scene_pos.y() + nodo_item.size / 2)

            # Obtener ID del nodo movido - FORMA MEJORADA
            nodo_id = None
            
            # Método 1: Intentar obtener directamente del nodo
            if isinstance(nodo, dict):
                nodo_id = nodo.get("id")
            elif hasattr(nodo, "get"):
                nodo_id = nodo.get("id")
            elif hasattr(nodo, "id"):
                nodo_id = getattr(nodo, "id")
            
            # Método 2: Si aún no tenemos ID, intentar del nodo_item
            if nodo_id is None and hasattr(nodo_item, "nodo_id"):
                nodo_id = getattr(nodo_item, "nodo_id", None)
            
            # Método 3: Último recurso - buscar en el proyecto
            if nodo_id is None and self.proyecto:
                for n in self.proyecto.nodos:
                    # Comparar por referencia o por posición
                    if n is nodo or (isinstance(n, dict) and n.get('X') == x and n.get('Y') == y):
                        nodo_id = n.get('id') if isinstance(n, dict) else getattr(n, 'id', None)
                        break

            if nodo_id is None:
                print(f"ERROR: No se pudo obtener ID del nodo. Tipo nodo: {type(nodo)}")
                # Intentar una última opción: si el nodo tiene __dict__
                if hasattr(nodo, "__dict__"):
                    if 'id' in nodo.__dict__:
                        nodo_id = nodo.__dict__['id']
                
                if nodo_id is None:
                    return

            
            # ACTUALIZACIÓN EN TIEMPO REAL de todas las rutas que contienen este nodo
            self._actualizar_rutas_con_nodo_en_tiempo_real(nodo_id, x, y)

            # ACTUALIZACIÓN EN TIEMPO REAL de la tabla de propiedades
            self._actualizar_propiedades_en_tiempo_real(nodo, x, y)

        except Exception as err:
            print(f"ERROR en on_nodo_moved: {err}")
            import traceback
            traceback.print_exc()

    def _actualizar_propiedades_en_tiempo_real(self, nodo, x, y):
        """Actualiza solo X e Y en la tabla de propiedades durante el arrastre"""
        try:
            tabla = self.view.propertiesTable
            tabla.blockSignals(True)

            # Convertir pixeles a metros (con offset)
            x_metros = self.x_px_a_metros(x)
            y_metros = self.y_px_a_metros(y)

            # Buscar las filas de X e Y y actualizar solo esas celdas
            for row in range(tabla.rowCount()):
                key_item = tabla.item(row, 0)
                if key_item:
                    clave = key_item.text()
                    if clave == "X":
                        val_item = tabla.item(row, 1)
                        if val_item:
                            val_item.setText(str(x_metros))
                    elif clave == "Y":
                        val_item = tabla.item(row, 1)
                        if val_item:
                            val_item.setText(str(y_metros))

            tabla.blockSignals(False)
        except Exception as err:
            try:
                self.view.propertiesTable.blockSignals(False)
            except Exception:
                pass

    def _actualizar_rutas_con_nodo_en_tiempo_real(self, nodo_id, x, y):
        """Actualiza TODAS las rutas que contienen el nodo movido, usando las coordenadas en tiempo real"""
        if not getattr(self, "proyecto", None) or not hasattr(self.proyecto, "rutas"):
            return
        
        
        # Buscar todas las rutas que contienen este nodo
        rutas_a_actualizar = []
        for idx, ruta in enumerate(self.proyecto.rutas):
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                
                # Verificar si la ruta contiene el nodo movido
                contiene_nodo = False
                
                # Función auxiliar para comparar IDs
                def comparar_ids(nodo_ruta, target_id):
                    if nodo_ruta is None:
                        return False
                    if isinstance(nodo_ruta, dict):
                        return nodo_ruta.get("id") == target_id
                    elif hasattr(nodo_ruta, "get"):
                        return nodo_ruta.get("id") == target_id
                    elif hasattr(nodo_ruta, "id"):
                        return getattr(nodo_ruta, "id") == target_id
                    return False
                
                # Verificar origen
                if ruta_dict.get("origen") and comparar_ids(ruta_dict["origen"], nodo_id):
                    contiene_nodo = True
                
                # Verificar destino
                if not contiene_nodo and ruta_dict.get("destino") and comparar_ids(ruta_dict["destino"], nodo_id):
                    contiene_nodo = True
                
                # Verificar visita
                if not contiene_nodo:
                    for nodo_visita in ruta_dict.get("visita", []):
                        if comparar_ids(nodo_visita, nodo_id):
                            contiene_nodo = True
                            break
                
                if contiene_nodo:
                    rutas_a_actualizar.append((idx, ruta_dict))
            except Exception as e:
                print(f"Error verificando ruta {idx}: {e}")
                continue
        
        # Si no hay rutas que actualizar, salir
        if not rutas_a_actualizar:
            return
        
        
        # Actualizar las líneas de TODAS las rutas afectadas
        self._actualizar_lineas_rutas_en_tiempo_real(rutas_a_actualizar, nodo_id, x, y)


    def _obtener_id_de_nodo(self, nodo):
        """Obtiene el ID de un nodo de manera segura"""
        if not nodo:
            return None
        if isinstance(nodo, dict):
            return nodo.get("id")
        elif hasattr(nodo, "get"):
            return nodo.get("id")
        elif hasattr(nodo, "id"):
            return getattr(nodo, "id")
        return None

    def _actualizar_lineas_rutas_en_tiempo_real(self, rutas_info, nodo_id, x, y):
        base_pen = QPen(Qt.red, 2)
        base_pen.setCosmetic(True)
        
        # Eliminar líneas de las rutas afectadas
        for idx, ruta_dict in rutas_info:
            if idx < len(self._route_lines):
                for line_item in self._route_lines[idx]:
                    try:
                        if line_item and line_item.scene() is not None:
                            self.scene.removeItem(line_item)
                    except Exception:
                        pass
                self._route_lines[idx] = []
        
        for idx, ruta_dict in rutas_info:
            ruta_actualizada = dict(ruta_dict)
            self._actualizar_coordenadas_en_ruta(ruta_actualizada, nodo_id, x, y)
            puntos = self._obtener_puntos_de_ruta(ruta_actualizada)
            
            if len(puntos) < 2 or not self._ruta_es_visible(ruta_actualizada):
                continue
            
            route_line_items = []
            for i in range(len(puntos) - 1):
                n1, n2 = puntos[i], puntos[i + 1]

                # --- OBTENER Tipo_curva DEL NODO DESTINO ---
                tipo_curva_valor = 0
                nodo_id_dest = None
                if isinstance(n2, dict):
                    nodo_id_dest = n2.get('id')
                elif hasattr(n2, 'get'):
                    nodo_id_dest = n2.get('id')

                if nodo_id_dest is not None:
                    nodo_actual = self._obtener_nodo_actual(nodo_id_dest)
                    if nodo_actual:
                        raw = nodo_actual.get('Tipo_curva', 0)
                        try:
                            tipo_curva_valor = int(raw)
                        except (ValueError, TypeError):
                            tipo_curva_valor = 0
                # -------------------------------------------

                segment_pen = QPen(base_pen)
                if tipo_curva_valor != 0:
                    segment_pen.setStyle(Qt.DashLine)
                else:
                    segment_pen.setStyle(Qt.SolidLine)
                
                try:
                    x1 = self._obtener_coordenada_x(n1)
                    y1 = self._obtener_coordenada_y(n1)
                    x2 = self._obtener_coordenada_x(n2)
                    y2 = self._obtener_coordenada_y(n2)
                    
                    if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
                        line_item = self.scene.addLine(x1, y1, x2, y2, segment_pen)
                        line_item.setZValue(0.5)
                        line_item.setData(0, ("route_line", idx, i))
                        line_item.setVisible(True)
                        route_line_items.append(line_item)
                except Exception as e:
                    print(f"Error dibujando segmento {i}: {e}")
                    continue
            
            while len(self._route_lines) <= idx:
                self._route_lines.append([])
            self._route_lines[idx] = route_line_items
        
        self.view.marco_trabajo.viewport().update()

    def _actualizar_coordenadas_en_ruta(self, ruta_dict, nodo_id, x, y):
        """Actualiza las coordenadas de un nodo específico en una ruta (en TODOS los roles)"""
        # Actualizar origen
        if ruta_dict.get("origen") and self._obtener_id_de_nodo(ruta_dict["origen"]) == nodo_id:
            if isinstance(ruta_dict["origen"], dict):
                ruta_dict["origen"]["X"] = x
                ruta_dict["origen"]["Y"] = y
            elif hasattr(ruta_dict["origen"], "update"):
                ruta_dict["origen"].update({"X": x, "Y": y})

        # Actualizar destino (siempre verificar, no elif)
        if ruta_dict.get("destino") and self._obtener_id_de_nodo(ruta_dict["destino"]) == nodo_id:
            if isinstance(ruta_dict["destino"], dict):
                ruta_dict["destino"]["X"] = x
                ruta_dict["destino"]["Y"] = y
            elif hasattr(ruta_dict["destino"], "update"):
                ruta_dict["destino"].update({"X": x, "Y": y})

        # Actualizar visita (siempre verificar, no else)
        for nodo_visita in ruta_dict.get("visita", []):
            if self._obtener_id_de_nodo(nodo_visita) == nodo_id:
                if isinstance(nodo_visita, dict):
                    nodo_visita["X"] = x
                    nodo_visita["Y"] = y
                elif hasattr(nodo_visita, "update"):
                    nodo_visita.update({"X": x, "Y": y})

    def _obtener_puntos_de_ruta(self, ruta_dict):
        """Obtiene todos los puntos de una ruta en orden"""
        puntos = []
        
        if ruta_dict.get("origen"):
            puntos.append(ruta_dict["origen"])
        
        if ruta_dict.get("visita"):
            puntos.extend(ruta_dict["visita"])
        
        if ruta_dict.get("destino"):
            puntos.append(ruta_dict["destino"])
        
        return puntos

    def _ruta_es_visible(self, ruta_dict):
        """Verifica si todos los nodos de una ruta están visibles"""
        puntos = self._obtener_puntos_de_ruta(ruta_dict)
        
        for punto in puntos:
            nodo_id = self._obtener_id_de_nodo(punto)
            if nodo_id is not None and not self.visibilidad_nodos.get(nodo_id, True):
                return False
        
        return True

    def _obtener_coordenada_x(self, nodo):
        """Obtiene la coordenada X de un nodo de manera segura"""
        if isinstance(nodo, dict):
            return nodo.get("X", 0)
        elif hasattr(nodo, "get"):
            return nodo.get("X", 0)
        elif hasattr(nodo, "X"):
            return getattr(nodo, "X", 0)
        return 0

    def _obtener_coordenada_y(self, nodo):
        """Obtiene la coordenada Y de un nodo de manera segura"""
        if isinstance(nodo, dict):
            return nodo.get("Y", 0)
        elif hasattr(nodo, "get"):
            return nodo.get("Y", 0)
        elif hasattr(nodo, "Y"):
            return getattr(nodo, "Y", 0)
        return 0

    def _actualizar_rutas_con_nodo(self, nodo_id, nueva_x, nueva_y):
        """Actualiza solo las rutas que contienen el nodo movido (más eficiente)"""
        if not getattr(self, "proyecto", None) or not hasattr(self.proyecto, "rutas"):
            return
        
        # Buscar rutas que contienen este nodo
        rutas_a_actualizar = []
        for idx, ruta in enumerate(self.proyecto.rutas):
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                self._normalize_route_nodes(ruta_dict)
                
                # Verificar si la ruta contiene el nodo movido
                contiene_nodo = False
                if ruta_dict.get("origen") and ruta_dict["origen"].get("id") == nodo_id:
                    contiene_nodo = True
                elif ruta_dict.get("destino") and ruta_dict["destino"].get("id") == nodo_id:
                    contiene_nodo = True
                else:
                    for nodo_visita in ruta_dict.get("visita", []):
                        if nodo_visita.get("id") == nodo_id:
                            contiene_nodo = True
                            break
                
                if contiene_nodo:
                    rutas_a_actualizar.append(idx)
            except Exception:
                continue
        
        # Actualizar solo las líneas de las rutas afectadas
        self._actualizar_lineas_rutas_especificas(rutas_a_actualizar, nodo_id, nueva_x, nueva_y)

    def _actualizar_lineas_rutas_especificas(self, indices_rutas, nodo_id=None, nueva_x=None, nueva_y=None):
        """Actualiza solo las líneas de las rutas especificadas por sus índices"""
        if not indices_rutas:
            return
        
        # Eliminar líneas de estas rutas específicas
        for idx in indices_rutas:
            if idx < len(self._route_lines):
                for line_item in self._route_lines[idx]:
                    try:
                        if line_item and line_item.scene() is not None:
                            self.scene.removeItem(line_item)
                    except Exception:
                        pass
                self._route_lines[idx] = []
        
        # Volver a dibujar estas rutas
        pen = QPen(Qt.red, 2)
        pen.setCosmetic(True)
        
        for idx in indices_rutas:
            if idx >= len(self.proyecto.rutas):
                continue
                
            ruta = self.proyecto.rutas[idx]
            
            # Verificar si la ruta está visible
            if not self.visibilidad_rutas.get(idx, True):
                continue
                
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta

            self._normalize_route_nodes(ruta_dict)
            
            # Si estamos actualizando un nodo específico, actualizar sus coordenadas en la ruta
            if nodo_id and nueva_x is not None and nueva_y is not None:
                if ruta_dict.get("origen") and ruta_dict["origen"].get("id") == nodo_id:
                    ruta_dict["origen"]["X"] = nueva_x
                    ruta_dict["origen"]["Y"] = nueva_y
                elif ruta_dict.get("destino") and ruta_dict["destino"].get("id") == nodo_id:
                    ruta_dict["destino"]["X"] = nueva_x
                    ruta_dict["destino"]["Y"] = nueva_y
                else:
                    for nodo_visita in ruta_dict.get("visita", []):
                        if nodo_visita.get("id") == nodo_id:
                            nodo_visita["X"] = nueva_x
                            nodo_visita["Y"] = nueva_y
                            break
            
            # Obtener puntos
            puntos = []
            if ruta_dict.get("origen"):
                puntos.append(ruta_dict["origen"])
            puntos.extend(ruta_dict.get("visita", []) or [])
            if ruta_dict.get("destino"):
                puntos.append(ruta_dict["destino"])

            if len(puntos) < 2:
                continue

            # Verificar que todos los nodos de la ruta estén visibles
            todos_visibles = True
            for punto in puntos:
                if isinstance(punto, dict):
                    nodo_id_punto = punto.get('id')
                    if nodo_id_punto is not None and not self.visibilidad_nodos.get(nodo_id_punto, True):
                        todos_visibles = False
                        break
            
            if not todos_visibles:
                continue

            route_line_items = []
            for i in range(len(puntos) - 1):
                n1, n2 = puntos[i], puntos[i + 1]
                
                try:
                    x1 = n1.get("X", 0) if isinstance(n1, dict) else getattr(n1, "X", 0)
                    y1 = n1.get("Y", 0) if isinstance(n1, dict) else getattr(n1, "Y", 0)
                    x2 = n2.get("X", 0) if isinstance(n2, dict) else getattr(n2, "X", 0)
                    y2 = n2.get("Y", 0) if isinstance(n2, dict) else getattr(n2, "Y", 0)
                    
                    line_item = self.scene.addLine(x1, y1, x2, y2, pen)
                    line_item.setZValue(0.5)
                    line_item.setData(0, ("route_line", idx, i))
                    line_item.setVisible(True)
                    
                    route_line_items.append(line_item)
                    
                except Exception:
                    continue
            
            if idx >= len(self._route_lines):
                self._route_lines.extend([[]] * (idx - len(self._route_lines) + 1))
            
            self._route_lines[idx] = route_line_items

        # Forzar actualización de la vista
        self.view.marco_trabajo.viewport().update()

    # --- Utilidades para líneas y rutas ---
    def _clear_route_lines(self):
        """
        Elimina todas las líneas de rutas guardadas en self._route_lines de la escena.
        Versión mejorada.
        """
        try:
            # eliminar líneas rojas
            for route_lines in getattr(self, "_route_lines", []) or []:
                for li in (route_lines or []):
                    try:
                        if li and li.scene() is not None:
                            self.scene.removeItem(li)
                    except Exception:
                        pass
        except Exception:
            pass
        
        # reset
        self._route_lines = []

    def _clear_highlight_lines(self):
        """Elimina todas las líneas de highlight (amarillas) de la escena."""
        try:
            for hl in getattr(self, "_highlight_lines", []) or []:
                try:
                    if hl and hl.scene() is not None:
                        self.scene.removeItem(hl)
                except Exception:
                    pass
        except Exception:
            pass
        self._highlight_lines = []

    def actualizar_lineas_rutas(self):
        """Fuerza la actualización de todas las líneas de ruta"""
        self._dibujar_rutas()
        if hasattr(self.view, "rutasList") and self.view.rutasList.selectedItems():
            self.seleccionar_ruta_desde_lista()

    # --- Event filter (NOTA: sobrescrito por el segundo eventFilter más abajo;
    #     conservado para referencia, no se ejecuta) ---
    def _eventFilter_deprecated(self, obj, event):
       # Detectar teclas presionadas
        if event.type() == QEvent.KeyPress:
            # Pasar el evento a keyPressEvent para manejo centralizado
            self.keyPressEvent(event)
            return True
        
        # Detectar movimiento del ratón para actualizar cursor y coordenadas
        if event.type() == QEvent.MouseMove:
            # Obtener posición actual del ratón
            pos = self.view.marco_trabajo.mapToScene(event.pos())
            items = self.scene.items(pos)

            # Actualizar coordenadas en la barra inferior (con offset, limitado al mapa)
            x_m = self.x_px_a_metros(pos.x())
            y_m = self.y_px_a_metros(pos.y())
            self.view.actualizar_coordenadas(x_m, y_m)

            # Si el modo duplicar está activo: los ghosts siguen al cursor
            # solo cuando está sobre zona vacía (no sobre un nodo).
            if getattr(self, "_modo_duplicar_activo", False):
                hay_nodo = any(isinstance(it, NodoItem) for it in items)
                if hay_nodo:
                    self._ocultar_ghosts_duplicar()
                else:
                    self._mover_ghosts_duplicar(pos.x(), pos.y())

            # Verificar si hay nodos en la posición actual
            hay_nodo = any(isinstance(it, NodoItem) for it in items)

            # Actualizar estado de hover
            if hay_nodo and not self._cursor_sobre_nodo:
                self._cursor_sobre_nodo = True
                self._actualizar_cursor()
            elif not hay_nodo and self._cursor_sobre_nodo:
                self._cursor_sobre_nodo = False
                self._actualizar_cursor()
        
        # Detectar click izquierdo en el viewport
        if event.type() == QEvent.MouseButtonPress:
            # Mapear a escena
            pos = self.view.marco_trabajo.mapToScene(event.pos())

            # PRIMERO: Si estamos en modo ruta o modo colocar, NO manejar el clic aquí
            # Los controladores respectivos manejarán los clics a través de su eventFilter
            if self.modo_actual in ["ruta", "colocar"]:
                return False  # Dejar que el controlador respectivo maneje el clic
            
            # SEGUNDO: Comportamiento normal (solo si NO estamos en modo ruta o colocar)
            items = self.scene.items(pos)
            if not any(isinstance(it, NodoItem) for it in items):
                # Click fuera de nodo
                
                # Resetear estados de cursor
                if self._arrastrando_nodo:
                    self._arrastrando_nodo = False
                
                self._cursor_sobre_nodo = False
                self._actualizar_cursor()
                
                # Resto del código existente...
                try:
                    for it in self.scene.selectedItems():
                        it.setSelected(False)
                except Exception:
                    pass
                
                for item in self.scene.items():
                    if isinstance(item, NodoItem):
                        item.setZValue(1)
                    
                try:
                    self.view.nodosList.clearSelection()
                except Exception:
                    pass
                
                try:
                    if hasattr(self.view, "rutasList"):
                        self.view.rutasList.clearSelection()
                except Exception:
                        pass
                
                self._clear_highlight_lines()

                try:
                    self._limpiar_propiedades()
                except Exception:
                    pass

                for item in self.scene.items():
                    if isinstance(item, NodoItem):
                        item.set_normal_color()
        
        # NUEVO: Detectar liberación del botón del ratón
        if event.type() == QEvent.MouseButtonRelease:
            # Resetear estado de arrastre si aún está activo
            if self._arrastrando_nodo:
                self._arrastrando_nodo = False
            
            # Forzar actualización del cursor
            self._actualizar_cursor()
        
        return False

    def diagnosticar_estado_proyecto(self):
        """Diagnóstico completo del estado del proyecto"""
        if not self.proyecto:
            return
        # Method kept for compatibility but prints removed

    # --- SISTEMA DE VISIBILIDAD CON LÓGICA DE RUTAS INCLUYENDO NODOS ---
    def inicializar_visibilidad(self):
        """Inicializa el sistema de visibilidad para todos los elementos"""
        if not self.proyecto:
            return
        
        
        # Inicializar visibilidad de nodos como VISIBLES (True)
        for nodo in self.proyecto.nodos:
            nodo_id = nodo.get('id')
            if nodo_id is not None:
                self.visibilidad_nodos[nodo_id] = True  # Inicialmente visibles
        
        # Inicializar visibilidad de rutas como VISIBLES (True)
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = True  # Inicialmente visibles
            
        # Inicializar relaciones nodo-ruta
        self._actualizar_todas_relaciones_nodo_ruta()
        
        # Actualizar listas con widgets
        self._actualizar_lista_nodos_con_widgets()
        self._actualizar_lista_rutas_con_widgets()
        
        # Asegurar que los botones muestren el estado inicial correcto
        if hasattr(self.view, "btnOcultarTodo"):
            self.view.btnOcultarTodo.setText("Ocultar Nodos")
        if hasattr(self.view, "btnMostrarTodo"):
            self.view.btnMostrarTodo.setText("Ocultar Rutas")
            self.view.btnMostrarTodo.setEnabled(True)  # Habilitado porque nodos visibles
        

    # --- NUEVOS MÉTODOS PARA INTERRUPTORES DE VISIBILIDAD ---
    def toggle_visibilidad_nodos(self):
        """Alterna la visibilidad de TODOS los nodos (y por tanto de TODAS las rutas)"""
        if not self.proyecto:
            return
        
        # Verificar si actualmente los nodos están visibles
        nodos_visibles = any(self.visibilidad_nodos.values()) if self.visibilidad_nodos else False
        
        if nodos_visibles:
            # Si están visibles, ocultar TODOS los nodos y TODAS las rutas
            self.ocultar_todos_los_nodos()
            self.view.btnOcultarTodo.setText("Mostrar Nodos")
            # Deshabilitar botón de rutas porque no hay nodos visibles
            if hasattr(self.view, "btnMostrarTodo"):
                self.view.btnMostrarTodo.setEnabled(False)
                self.view.btnMostrarTodo.setText("Ocultar Rutas")  # Resetear texto
        else:
            # Si están ocultos, mostrar TODOS los nodos y TODAS las rutas
            self.mostrar_todos_los_nodos_y_rutas()
            self.view.btnOcultarTodo.setText("Ocultar Nodos")
            # Habilitar botón de rutas porque ahora hay nodos visibles
            if hasattr(self.view, "btnMostrarTodo"):
                self.view.btnMostrarTodo.setEnabled(True)
                self.view.btnMostrarTodo.setText("Ocultar Rutas")  # Resetear a estado inicial

    def toggle_visibilidad_rutas(self):
        """Alterna la visibilidad de TODAS las rutas (solo funciona si los nodos están visibles)"""
        if not self.proyecto:
            return
        
        # Verificar que los nodos estén visibles
        nodos_visibles = any(self.visibilidad_nodos.values()) if self.visibilidad_nodos else False
        if not nodos_visibles:
            return
        
        # Verificar si actualmente las rutas están visibles
        rutas_visibles = any(self.visibilidad_rutas.values()) if self.visibilidad_rutas else False
        
        if rutas_visibles:
            # Si están visibles, ocultar solo las líneas de ruta
            self.ocultar_todas_las_rutas()
            self.view.btnMostrarTodo.setText("Mostrar Rutas")
        else:
            # Si están ocultas, mostrar las líneas de ruta
            self.mostrar_todas_las_rutas()
            self.view.btnMostrarTodo.setText("Ocultar Rutas")

    def ocultar_todos_los_nodos(self):
        """Oculta TODOS los nodos y TODAS las rutas"""
        
        # Ocultar todos los nodos en la escena
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.setVisible(False)
                nodo_id = item.nodo.get('id')
                if nodo_id is not None:
                    self.visibilidad_nodos[nodo_id] = False
        
        # Ocultar todas las rutas (porque dependen de nodos)
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = False
        
        # Limpiar líneas de rutas
        self._clear_route_lines()
        self._clear_highlight_lines()
        
        # Actualizar widgets en las listas
        self._actualizar_lista_nodos_con_widgets()
        self._actualizar_lista_rutas_con_widgets()
        
        # Deseleccionar cualquier ruta seleccionada
        if hasattr(self.view, "rutasList"):
            self.view.rutasList.clearSelection()
        
        # Resetear el índice de ruta seleccionada
        self.ruta_actual_idx = None
        
        # Limpiar tabla de propiedades
        self._limpiar_propiedades()

        # Restaurar colores normales de TODOS los nodos
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.set_normal_color()
        

    def mostrar_todos_los_nodos_y_rutas(self):
        """Muestra TODOS los nodos y TODAS las rutas (fuerza mostrar rutas)"""
        
        # Mostrar todos los nodos en la escena
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.setVisible(True)
                nodo_id = item.nodo.get('id')
                if nodo_id is not None:
                    self.visibilidad_nodos[nodo_id] = True
        
        # Mostrar TODAS las rutas (forzar estado visible)
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = True
        
        # Actualizar widgets en las listas
        self._actualizar_lista_nodos_con_widgets()
        self._actualizar_lista_rutas_con_widgets()
        
        # Redibujar rutas
        self._dibujar_rutas()
        

    def ocultar_todas_las_rutas(self):
        """Oculta solo las líneas de las rutas, manteniendo los nodos visibles"""
        
        # Ocultar todas las rutas
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = False
        
        # Limpiar líneas de rutas
        self._clear_route_lines()
        self._clear_highlight_lines()
        
        # Actualizar widgets en la lista de rutas
        self._actualizar_lista_rutas_con_widgets()
        
        # Deseleccionar cualquier ruta seleccionada
        if hasattr(self.view, "rutasList"):
            self.view.rutasList.clearSelection()
        
        # Resetear el índice de ruta seleccionada
        self.ruta_actual_idx = None
        
        # Restaurar colores normales de TODOS los nodos
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.set_normal_color()
        

    def mostrar_todas_las_rutas(self):
        """Muestra todas las líneas de las rutas (solo si los nodos están visibles)"""
        
        # Mostrar todas las rutas
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = True
        
        # Redibujar rutas (solo se dibujarán si los nodos están visibles)
        self._dibujar_rutas()
        
        # Actualizar widgets en la lista de rutas
        self._actualizar_lista_rutas_con_widgets()
        

    # --- MÉTODOS COMPATIBLES (actualizados) ---
    def ocultar_todo(self):
        """Método compatible - oculta nodos y rutas"""
        self.ocultar_todos_los_nodos()
        self.view.btnOcultarTodo.setText("Mostrar Nodos")
        if hasattr(self.view, "btnMostrarTodo"):
            self.view.btnMostrarTodo.setEnabled(False)

    def mostrar_todo(self):
        """Método compatible - muestra nodos y rutas"""
        self.mostrar_todos_los_nodos_y_rutas()
        self.view.btnOcultarTodo.setText("Ocultar Nodos")
        if hasattr(self.view, "btnMostrarTodo"):
            self.view.btnMostrarTodo.setEnabled(True)
            self.view.btnMostrarTodo.setText("Ocultar Rutas")
    
    def _actualizar_todas_relaciones_nodo_ruta(self):
        """Actualiza todas las relaciones entre nodos y rutas"""
        self.nodo_en_rutas.clear()
        
        for idx, ruta in enumerate(self.proyecto.rutas):
            self._actualizar_relaciones_nodo_ruta(idx, ruta)
    
    def _actualizar_relaciones_nodo_ruta(self, ruta_idx, ruta):
        """Actualiza las relaciones para una ruta específica"""
        try:
            ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
        except Exception:
            ruta_dict = ruta
        
        self._normalize_route_nodes(ruta_dict)
        
        # Obtener todos los nodos de la ruta
        nodos = []
        if ruta_dict.get("origen"):
            nodos.append(ruta_dict["origen"])
        nodos.extend(ruta_dict.get("visita", []) or [])
        if ruta_dict.get("destino"):
            nodos.append(ruta_dict["destino"])
        
        # Actualizar relaciones
        for nodo in nodos:
            if isinstance(nodo, dict):
                nodo_id = nodo.get('id')
                if nodo_id is not None:
                    if nodo_id not in self.nodo_en_rutas:
                        self.nodo_en_rutas[nodo_id] = []
                    if ruta_idx not in self.nodo_en_rutas[nodo_id]:
                        self.nodo_en_rutas[nodo_id].append(ruta_idx)
    
    def _obtener_nodo_actual(self, nodo_id):
        """Devuelve el nodo actual del proyecto dado su ID, o None si no existe."""
        for nodo in self.proyecto.nodos:
            if nodo.get('id') == nodo_id:
                return nodo
        return None

    def _obtener_nodos_de_ruta(self, ruta_idx, solo_visibles=False):
        """Obtiene todos los nodos de una ruta específica, opcionalmente solo los visibles"""
        if ruta_idx >= len(self.proyecto.rutas):
            return []
        
        ruta = self.proyecto.rutas[ruta_idx]
        try:
            ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
        except Exception:
            ruta_dict = ruta
        
        self._normalize_route_nodes(ruta_dict)
        
        nodos = []
        
        # Origen
        origen = ruta_dict.get("origen")
        if origen:
            if not solo_visibles or (isinstance(origen, dict) and self.visibilidad_nodos.get(origen.get('id'), True)):
                nodos.append(origen)
        
        # Visita
        visita = ruta_dict.get("visita", []) or []
        for nodo_visita in visita:
            if not solo_visibles or (isinstance(nodo_visita, dict) and self.visibilidad_nodos.get(nodo_visita.get('id'), True)):
                nodos.append(nodo_visita)
        
        # Destino
        destino = ruta_dict.get("destino")
        if destino:
            if not solo_visibles or (isinstance(destino, dict) and self.visibilidad_nodos.get(destino.get('id'), True)):
                nodos.append(destino)
        
        return nodos
    
    def _actualizar_lista_nodos_con_widgets(self):
        """Actualiza la lista de nodos con widgets personalizados"""
        self.view.nodosList.clear()
        
        for nodo in self.proyecto.nodos:
            self._inicializar_nodo_visibilidad(nodo, agregar_a_lista=True)
        
    
    def _actualizar_lista_rutas_con_widgets(self):
        """Actualiza la lista de rutas con widgets personalizados"""
        if not hasattr(self.view, "rutasList"):
            return
            
        self.view.rutasList.clear()
        
        for idx, ruta in enumerate(self.proyecto.rutas):
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta

            # Normalizar para obtener ids legibles
            self._normalize_route_nodes(ruta_dict)
            origen = ruta_dict.get("origen")
            destino = ruta_dict.get("destino")

            origen_id = origen.get("id", "?") if isinstance(origen, dict) else str(origen)
            destino_id = destino.get("id", "?") if isinstance(destino, dict) else str(destino)
            
            # Obtener el nombre de la ruta, por defecto "Ruta"
            nombre_ruta = ruta_dict.get("nombre", "Ruta")
            
            # Texto en formato: "nombre: id_origen -> id_destino"
            item_text = f"{nombre_ruta}: {origen_id}→{destino_id}"
            
            item = QListWidgetItem()
            item.setData(Qt.UserRole, ruta_dict)
            item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setSizeHint(QSize(0, 24))
            
            widget = RutaListItemWidget(
                idx, 
                item_text, 
                self.visibilidad_rutas.get(idx, True)
            )
            widget.toggle_visibilidad.connect(self.toggle_visibilidad_ruta)
            widget.solicitar_eliminacion.connect(self._confirmar_eliminar_ruta)

            self.view.rutasList.addItem(item)
            self.view.rutasList.setItemWidget(item, widget)
        
    
    def _confirmar_eliminar_ruta(self, ruta_index):
        """Muestra diálogo de confirmación y elimina la ruta si el usuario acepta"""
        if not self.proyecto or ruta_index >= len(self.proyecto.rutas):
            return

        # Obtener info de la ruta para el mensaje
        ruta = self.proyecto.rutas[ruta_index]
        ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
        nombre = ruta_dict.get("nombre", "Ruta")
        origen = ruta_dict.get("origen", {})
        destino = ruta_dict.get("destino", {})
        origen_id = origen.get("id", "?") if isinstance(origen, dict) else str(origen)
        destino_id = destino.get("id", "?") if isinstance(destino, dict) else str(destino)

        respuesta = QMessageBox.question(
            self.view,
            "Confirmar eliminacion",
            f"Desea eliminar la ruta '{nombre}: {origen_id} -> {destino_id}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if respuesta == QMessageBox.Yes:
            # Limpiar highlights si la ruta eliminada estaba seleccionada
            if self.ruta_actual_idx == ruta_index:
                self._clear_highlight_lines()
                self.ruta_actual_idx = None

            # Ajustar índice de ruta seleccionada si es necesario
            elif self.ruta_actual_idx is not None and self.ruta_actual_idx > ruta_index:
                self.ruta_actual_idx -= 1

            # Eliminar del diccionario de visibilidad
            if ruta_index in self.visibilidad_rutas:
                del self.visibilidad_rutas[ruta_index]
            # Reindexar visibilidad para rutas posteriores
            nuevas_vis = {}
            for k, v in self.visibilidad_rutas.items():
                if k > ruta_index:
                    nuevas_vis[k - 1] = v
                else:
                    nuevas_vis[k] = v
            self.visibilidad_rutas = nuevas_vis

            # Eliminar la ruta del modelo
            self.proyecto.eliminar_ruta(ruta_index)

            # Redibujar y actualizar lista
            self._dibujar_rutas()
            self._actualizar_lista_rutas_con_widgets()

    def ocultar_todo(self):
        """Oculta todos los nodos y rutas de la interfaz"""
        if not self.proyecto:
            QMessageBox.warning(self.view, "Advertencia", "No hay proyecto cargado")
            return
        
        
        # Ocultar todos los nodos en la escena
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.setVisible(False)
                nodo_id = item.nodo.get('id')
                if nodo_id is not None:
                    self.visibilidad_nodos[nodo_id] = False
        
        # Ocultar todas las rutas
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = False
        
        # Limpiar líneas de rutas
        self._clear_route_lines()
        self._clear_highlight_lines()
        
        # Actualizar listas laterales
        self._actualizar_lista_nodos_con_widgets()
        self._actualizar_lista_rutas_con_widgets()
        
        # Deseleccionar cualquier ruta seleccionada
        if hasattr(self.view, "rutasList"):
            self.view.rutasList.clearSelection()
        
        # Resetear el índice de ruta seleccionada
        self.ruta_actual_idx = None
        
        # Limpiar tabla de propiedades
        self._limpiar_propiedades()

        # Restaurar colores normales de todos los nodos
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.set_normal_color()

    
    def mostrar_todo(self):
        """Muestra todos los nodos y rutas de la interfaz"""
        if not self.proyecto:
            QMessageBox.warning(self.view, "Advertencia", "No hay proyecto cargado")
            return
        
        
        # Mostrar todos los nodos en la escena
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                item.setVisible(True)
                nodo_id = item.nodo.get('id')
                if nodo_id is not None:
                    self.visibilidad_nodos[nodo_id] = True
        
        # Mostrar todas las rutas
        for idx in range(len(self.proyecto.rutas)):
            self.visibilidad_rutas[idx] = True
        
        # Redibujar rutas
        self._dibujar_rutas()
        
        # Actualizar listas laterales
        self._actualizar_lista_nodos_con_widgets()
        self._actualizar_lista_rutas_con_widgets()
        
    
    def toggle_visibilidad_nodo(self, nodo_id):
        """Alterna la visibilidad de un nodo específico y reconstruye rutas"""
        if not self.proyecto:
            return
        
        # Inicializar si no está inicializado
        if nodo_id not in self.visibilidad_nodos:
            self.visibilidad_nodos[nodo_id] = True
        
        # Alternar estado
        nuevo_estado = not self.visibilidad_nodos[nodo_id]
        self.visibilidad_nodos[nodo_id] = nuevo_estado
        
        # Buscar y actualizar el NodoItem correspondiente en la escena
        for item in self.scene.items():
            if isinstance(item, NodoItem):
                if item.nodo.get('id') == nodo_id:
                    item.setVisible(nuevo_estado)
                    break
        
        # Obtener lista de rutas que contienen este nodo
        rutas_con_nodo = self.nodo_en_rutas.get(nodo_id, [])
        
        if not nuevo_estado:
            # Si estamos OCULTANDO el nodo
            
            # Si el nodo está siendo ocultado y está seleccionado, deseleccionarlo
            for item in self.scene.selectedItems():
                if isinstance(item, NodoItem) and item.nodo.get('id') == nodo_id:
                    item.setSelected(False)
                    break
            
            # Deseleccionar en la lista lateral
            for i in range(self.view.nodosList.count()):
                item = self.view.nodosList.item(i)
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                    self.view.nodosList.setCurrentItem(None)
                    break
            
            # Limpiar tabla de propiedades si este nodo estaba seleccionado
            seleccionados = self.view.nodosList.selectedItems()
            if not seleccionados:
                self._limpiar_propiedades()
        
        else:
            # Si estamos MOSTRANDO el nodo
            # El nodo se incluirá automáticamente en la reconstrucción
            pass

        # Actualizar widget en la lista
        self._actualizar_widget_nodo_en_lista(nodo_id)
        
        # Reconstruir y dibujar rutas
        self._dibujar_rutas()
        
        # Si hay una ruta seleccionada y contiene este nodo, actualizar sus highlights
        if self.ruta_actual_idx is not None and self.ruta_actual_idx in rutas_con_nodo:
            self.seleccionar_ruta_desde_lista()
        
        
    def _actualizar_relaciones_nodo_visible(self, nodo_id):
        """Reconstruye relaciones cuando un nodo se vuelve visible"""
        if not self.proyecto:
            return
        
        # Limpiar relaciones antiguas
        if nodo_id in self.nodo_en_rutas:
            self.nodo_en_rutas[nodo_id] = []
        
        # Buscar en todas las rutas si contienen este nodo
        for idx, ruta in enumerate(self.proyecto.rutas):
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta
            
            self._normalize_route_nodes(ruta_dict)
            
            # Verificar si la ruta contiene el nodo
            nodo_encontrado = False
            
            # Verificar origen
            origen = ruta_dict.get("origen")
            if origen and isinstance(origen, dict) and origen.get('id') == nodo_id:
                nodo_encontrado = True
            
            # Verificar destino
            destino = ruta_dict.get("destino")
            if not nodo_encontrado and destino and isinstance(destino, dict) and destino.get('id') == nodo_id:
                nodo_encontrado = True
            
            # Verificar visita
            if not nodo_encontrado:
                for nodo_visita in ruta_dict.get("visita", []):
                    if isinstance(nodo_visita, dict) and nodo_visita.get('id') == nodo_id:
                        nodo_encontrado = True
                        break
            
            # Si la ruta contiene el nodo, agregar a relaciones
            if nodo_encontrado:
                if nodo_id not in self.nodo_en_rutas:
                    self.nodo_en_rutas[nodo_id] = []
                if idx not in self.nodo_en_rutas[nodo_id]:
                    self.nodo_en_rutas[nodo_id].append(idx)
        

    def toggle_visibilidad_ruta(self, ruta_index):
        """Alterna la visibilidad de una ruta específica (SOLO líneas, como el botón global)"""
        if not self.proyecto or ruta_index >= len(self.proyecto.rutas):
            return
        
        # Inicializar si no está inicializado
        if ruta_index not in self.visibilidad_rutas:
            self.visibilidad_rutas[ruta_index] = True
        
        # Alternar estado (solo visibilidad de líneas)
        nuevo_estado = not self.visibilidad_rutas[ruta_index]
        self.visibilidad_rutas[ruta_index] = nuevo_estado
        
        # IMPORTANTE: NO MODIFICAR LA VISIBILIDAD DE LOS NODOS
        # Solo afectamos a las líneas de la ruta
        
        # Actualizar visualización de rutas
        self._dibujar_rutas()
        
        # Si la ruta que se está ocultando es la que está seleccionada, limpiar los highlights
        if not nuevo_estado and self.ruta_actual_idx == ruta_index:
            # Limpiar las líneas amarillas de resaltado
            self._clear_highlight_lines()
            
            # Restaurar colores normales de los nodos de esta ruta (pero los nodos siguen visibles)
            nodos_ruta = self._obtener_nodos_de_ruta(ruta_index)
            for nodo in nodos_ruta:
                if isinstance(nodo, dict):
                    nodo_id = nodo.get('id')
                    if nodo_id is not None:
                        for item in self.scene.items():
                            if isinstance(item, NodoItem) and item.nodo.get('id') == nodo_id:
                                # Solo restaurar color si no está seleccionado por otra razón
                                if not item.isSelected():
                                    item.set_normal_color()
                                break
        
        # Actualizar widget en la lista
        self._actualizar_widget_ruta_en_lista(ruta_index)
        
    
    def _actualizar_widget_nodo_en_lista(self, nodo_id):
        """Actualiza el widget de un nodo en la lista lateral"""
        for i in range(self.view.nodosList.count()):
            item = self.view.nodosList.item(i)
            widget = self.view.nodosList.itemWidget(item)
            if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                widget.set_visible(self.visibilidad_nodos.get(nodo_id, True))
                break
    
    def _actualizar_widget_ruta_en_lista(self, ruta_index):
        """Actualiza el widget de una ruta en la lista lateral"""
        if not hasattr(self.view, "rutasList"):
            return
            
        for i in range(self.view.rutasList.count()):
            item = self.view.rutasList.item(i)
            widget = self.view.rutasList.itemWidget(item)
            if widget and hasattr(widget, 'ruta_index') and widget.ruta_index == ruta_index:
                # Actualizar el texto del widget
                ruta = self.proyecto.rutas[ruta_index]
                try:
                    ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
                except Exception:
                    ruta_dict = ruta
                self._normalize_route_nodes(ruta_dict)
                origen = ruta_dict.get("origen")
                destino = ruta_dict.get("destino")
                origen_id = origen.get("id", "?") if isinstance(origen, dict) else str(origen)
                destino_id = destino.get("id", "?") if isinstance(destino, dict) else str(destino)
                nombre_ruta = ruta_dict.get("nombre", "Ruta")
                item_text = f"{nombre_ruta}: {origen_id}→{destino_id}"
                widget.lbl_texto.setText(item_text)
                widget.set_visible(self.visibilidad_rutas.get(ruta_index, True))
                break
    
    def obtener_nodo_por_id(self, nodo_id):
        """Busca un nodo por su ID"""
        for nodo in self.proyecto.nodos:
            if nodo.get('id') == nodo_id:
                return nodo
        return None
    
    def obtener_ruta_por_indice(self, ruta_index):
        """Busca una ruta por su índice"""
        if 0 <= ruta_index < len(self.proyecto.rutas):
            return self.proyecto.rutas[ruta_index]
        return None

    # --- NUEVO MÉTODO PARA EXPORTACIÓN SQLITE ---
    def exportar_a_sqlite(self):
        """Exporta el proyecto actual a bases de datos SQLite separadas."""
        if not self.proyecto:
            QMessageBox.warning(
                self.view,
                "No hay proyecto",
                "Debes crear o abrir un proyecto primero."
            )
            return
        
        # Verificar que hay datos para exportar
        if not self.proyecto.nodos and not self.proyecto.rutas:
            QMessageBox.warning(
                self.view,
                "Proyecto vacío",
                "El proyecto no contiene nodos ni rutas para exportar."
            )
            return
        
        # Obtener estadísticas
        nodos_con_objetivo = [n for n in self.proyecto.nodos if n.get("objetivo", 0) != 0]
        parametros = getattr(self.proyecto, 'parametros', {})
        tiene_parametros = bool(parametros)
        parametros_playa = getattr(self.proyecto, 'parametros_playa', [])
        tiene_parametros_playa = bool(parametros_playa)
        parametros_carga_descarga = getattr(self.proyecto, 'parametros_carga_descarga', [])
        tiene_parametros_carga_descarga = bool(parametros_carga_descarga)
        
        # Mostrar diálogo de confirmación
        archivos_a_crear = []
        if self.proyecto.nodos:
            archivos_a_crear.append("nodos.db (todos los atributos de nodos)")
        if self.proyecto.rutas:
            archivos_a_crear.append("rutas.db (IDs: origen, destino, visitados)")
        if nodos_con_objetivo:
            archivos_a_crear.append("objetivos.db (nodos con objetivo != 0)")
        if tiene_parametros:
            archivos_a_crear.append("parametros.db (parámetros del sistema)")
        if tiene_parametros_playa:
            archivos_a_crear.append("parametros_playa.db (parámetros de playa)")
        if tiene_parametros_carga_descarga:
            archivos_a_crear.append("tipo_carga_descarga.db (parámetros de carga/descarga)")
        
        confirmacion = QMessageBox.question(
            self.view,
            "Confirmar exportación a SQLite",
            f"¿Exportar proyecto actual a SQLite?\n\n"
            f"• Nodos: {len(self.proyecto.nodos)}\n"
            f"• Rutas: {len(self.proyecto.rutas)}\n"
            f"• Nodos Objetivo: {len(nodos_con_objetivo)}\n"
            f"• Parámetros: {len(parametros)} parámetros\n"
            f"• Playas: {len(parametros_playa)} playas\n"
            f"• Tipos Carga/Descarga: {len(parametros_carga_descarga)}\n\n"
            f"Se crearán {len(archivos_a_crear)} archivos:\n" + "\n".join([f"  - {archivo}" for archivo in archivos_a_crear]) + "\n\n"
            f"Coordenadas exportadas en METROS (escala: {self.ESCALA})",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if confirmacion == QMessageBox.Yes:
            # Llamar al exportador pasando la escala
            ExportadorDB.exportar(self.proyecto, self.view, self.ESCALA, self.alto_mapa_px, self.offset_x_px, self.offset_y_px)

    # En el método exportar_a_csv del EditorController:
    def exportar_a_csv(self):
        """Exporta el proyecto actual a archivos CSV separados."""
        if not self.proyecto:
            QMessageBox.warning(
                self.view,
                "No hay proyecto",
                "Debes crear o abrir un proyecto primero."
            )
            return

        # Verificar que hay datos para exportar
        if not self.proyecto.nodos and not self.proyecto.rutas:
            QMessageBox.warning(
                self.view,
                "Proyecto vacío",
                "El proyecto no contiene nodos ni rutas para exportar."
            )
            return

        nodos_con_objetivo = [n for n in self.proyecto.nodos if n.get("objetivo", 0) != 0]
        
        # Obtener parámetros si existen
        parametros = getattr(self.proyecto, 'parametros', {})
        tiene_parametros = bool(parametros)
        parametros_playa = getattr(self.proyecto, 'parametros_playa', [])
        tiene_parametros_playa = bool(parametros_playa)
        parametros_carga_descarga = getattr(self.proyecto, 'parametros_carga_descarga', [])
        tiene_parametros_carga_descarga = bool(parametros_carga_descarga)

        # Mostrar diálogo de confirmación actualizado
        archivos_a_crear = []
        if self.proyecto.nodos:
            archivos_a_crear.append("puntos.csv (todos los atributos de nodos)")
        if self.proyecto.rutas:
            archivos_a_crear.append("rutas.csv (IDs: origen, destino, visitados)")
        if nodos_con_objetivo:
            archivos_a_crear.append("objetivos.csv (IDs y propiedades avanzadas)")
        if tiene_parametros:
            archivos_a_crear.append("parametros.csv (parámetros del sistema)")
        if tiene_parametros_playa:
            archivos_a_crear.append("parametros_playa.csv (parámetros de playa)")
        if tiene_parametros_carga_descarga:
            archivos_a_crear.append("pasos.csv (parámetros de carga/descarga)")

        confirmacion = QMessageBox.question(
            self.view,
            "Confirmar exportación a CSV",
            f"¿Exportar proyecto actual a CSV?\n\n"
            f"• Nodos: {len(self.proyecto.nodos)}\n"
            f"• Rutas: {len(self.proyecto.rutas)}\n"
            f"• Nodos Objetivo: {len(nodos_con_objetivo)}\n"
            f"• Parámetros: {len(parametros)} parámetros\n"
            f"• Playas: {len(parametros_playa)} playas\n"
            f"• Tipos Carga/Descarga: {len(parametros_carga_descarga)}\n\n"
            f"Se crearán {len(archivos_a_crear)} archivos:\n" + "\n".join([f"  - {archivo}" for archivo in archivos_a_crear]) + "\n\n"
            f"Coordenadas exportadas en METROS (escala: {self.ESCALA})",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if confirmacion == QMessageBox.Yes:
            # Llamar al exportador CSV pasando la escala
            ExportadorCSV.exportar(self.proyecto, self.view, self.ESCALA, self.alto_mapa_px, self.offset_x_px, self.offset_y_px)


    def manejar_seleccion_nodo(self):
        """Maneja la selección de nodos, ajustando z-values para nodos solapados"""
        # Protección contra scene eliminada durante teardown de la app
        try:
            seleccionados = self.scene.selectedItems()
            items = self.scene.items()
        except RuntimeError:
            return

        # Primero, restaurar todos los nodos a su z-value normal
        for item in items:
            if isinstance(item, NodoItem):
                if not item.isSelected():
                    item.setZValue(1)  # Valor z normal para nodos no seleccionados
        
        # Si hay nodos seleccionados, asegurarse de que estén encima
        for item in seleccionados:
            if isinstance(item, NodoItem):
                # Establecer un valor z muy alto
                item.setZValue(1000)
                
                # Verificar si hay nodos en la misma posición (solapados)
                pos = item.scenePos()
                rect = item.boundingRect().translated(pos)
                
                # Buscar nodos en la misma posición
                nodos_solapados = []
                for otro_item in items:
                    if isinstance(otro_item, NodoItem) and otro_item != item:
                        otro_pos = otro_item.scenePos()
                        # Verificar si están muy cerca (dentro de 5 píxeles)
                        if (abs(otro_pos.x() - pos.x()) < 5 and 
                            abs(otro_pos.y() - pos.y()) < 5):
                            nodos_solapados.append(otro_item)
                
                # Si hay nodos solapados, asegurarse de que el seleccionado esté encima
                if nodos_solapados:
                    # El nodo seleccionado ya está en z=1000
                    # Los otros nodos solapados los ponemos en z=999 para que queden justo debajo
                    for nodo_solapado in nodos_solapados:
                        nodo_solapado.setZValue(999)


    def seleccionar_nodo_desde_lista(self):
        """Versión modificada para manejar nodos solapados"""
        if self._changing_selection:
            return
        items = self.view.nodosList.selectedItems()
        if not items:
            return
        
        # Obtener el nodo del widget
        for i in range(self.view.nodosList.count()):
            item = self.view.nodosList.item(i)
            if item.isSelected():
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id'):
                    nodo_id = widget.nodo_id
                    nodo = self.obtener_nodo_por_id(nodo_id)
                    if nodo:
                        self._changing_selection = True
                        try:
                            # Deseleccionar rutas primero
                            if hasattr(self.view, "rutasList"):
                                self.view.rutasList.clearSelection()
                            
                            # Primero restaurar todos los nodos a color normal
                            self.restaurar_colores_nodos()
                            
                            # Deseleccionar todo en la escena primero
                            for scene_item in self.scene.selectedItems():
                                scene_item.setSelected(False)
                            
                            # Buscar y seleccionar el nodo correspondiente
                            for scene_item in self.scene.items():
                                if isinstance(scene_item, NodoItem) and scene_item.nodo.get('id') == nodo_id:
                                    scene_item.setSelected(True)
                                    
                                    # Asegurar que el nodo esté encima de todos
                                    scene_item.setZValue(1000)
                                    
                                    # Verificar si hay nodos solapados
                                    pos = scene_item.scenePos()
                                    rect = scene_item.boundingRect().translated(pos)
                                    
                                    # Buscar nodos solapados
                                    for otro_item in self.scene.items():
                                        if isinstance(otro_item, NodoItem) and otro_item != scene_item:
                                            otro_pos = otro_item.scenePos()
                                            if (abs(otro_pos.x() - pos.x()) < 10 and 
                                                abs(otro_pos.y() - pos.y()) < 10):
                                                # Nodo solapado, ponerlo justo debajo
                                                otro_item.setZValue(999)
                                    
                                    # Aplicar color de selección
                                    scene_item.set_selected_color()
                                    self.view.marco_trabajo.centerOn(scene_item)
                                    self.mostrar_propiedades_nodo(nodo)
                                    break
                        finally:
                            self._changing_selection = False
                    break

    def seleccionar_nodo_especifico(self, nodo):
        """Selecciona un nodo específico desde el menú de superposición - Versión modificada"""
        self._changing_selection = True
        try:
            # Limpiar selecciones previas
            for item in self.scene.selectedItems():
                item.setSelected(False)
            
            # Primero restaurar todos los nodos a color normal
            self.restaurar_colores_nodos()
            
            # Buscar y seleccionar el nodo específico en la escena
            for item in self.scene.items():
                if isinstance(item, NodoItem) and item.nodo == nodo:
                    item.setSelected(True)
                    
                    # Asegurar que el nodo seleccionado esté encima
                    item.setZValue(1000)
                    
                    # Verificar si hay nodos solapados
                    pos = item.scenePos()
                    
                    # Poner otros nodos solapados justo debajo
                    for otro_item in self.scene.items():
                        if isinstance(otro_item, NodoItem) and otro_item != item:
                            otro_pos = otro_item.scenePos()
                            if (abs(otro_pos.x() - pos.x()) < 10 and 
                                abs(otro_pos.y() - pos.y()) < 10):
                                otro_item.setZValue(999)
                    
                    item.set_selected_color()
                    self.view.marco_trabajo.centerOn(item)
                    break
            
            # Sincronizar con la lista lateral
            nodo_id = nodo.get('id')
            for i in range(self.view.nodosList.count()):
                item = self.view.nodosList.item(i)
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo_id:
                    self.view.nodosList.setCurrentItem(item)
                    self.mostrar_propiedades_nodo(nodo)
                    break
        finally:
            self._changing_selection = False

    def eventFilter(self, obj, event):
        # Detectar teclas presionadas
        if event.type() == QEvent.KeyPress:
            self.keyPressEvent(event)
            return True

        # Detectar liberación de Ctrl en modo duplicar → mostrar fantasmas
        if event.type() == QEvent.KeyRelease:
            if getattr(self, "_modo_duplicar_activo", False) and \
                    event.key() in (Qt.Key_Control, Qt.Key_Meta):
                if self._duplicar_items_seleccionados and not self._duplicar_ghost_items:
                    self._crear_ghosts_duplicar()

        # Detectar movimiento del ratón para actualizar cursor dinámicamente
        if event.type() == QEvent.MouseMove:
            pos = self.view.marco_trabajo.mapToScene(event.pos())
            items = self.scene.items(pos)
            hay_nodo = any(isinstance(it, NodoItem) for it in items)

            # --- MODO DUPLICAR: mover los fantasmas con el cursor ---
            if getattr(self, "_modo_duplicar_activo", False):
                if hay_nodo:
                    self._ocultar_ghosts_duplicar()
                else:
                    self._mover_ghosts_duplicar(pos.x(), pos.y())

            if hay_nodo and not self._cursor_sobre_nodo:
                self._cursor_sobre_nodo = True
                self._actualizar_cursor()
            elif not hay_nodo and self._cursor_sobre_nodo:
                self._cursor_sobre_nodo = False
                self._actualizar_cursor()

        # Detectar click izquierdo en el viewport
        if event.type() == QEvent.MouseButtonPress:
            pos = self.view.marco_trabajo.mapToScene(event.pos())
            items = self.scene.items(pos)
            hay_nodo = any(isinstance(it, NodoItem) for it in items)

            # --- MODO DUPLICAR ---
            # - Click izquierdo sobre nodo (sin Ctrl): reemplaza selección
            # - Ctrl+click sobre nodo: toggle
            # - Click izquierdo sobre zona vacía (sin Ctrl): coloca duplicados
            if getattr(self, "_modo_duplicar_activo", False):
                if event.button() == Qt.LeftButton:
                    nodo_bajo_cursor = next(
                        (it for it in items if isinstance(it, NodoItem)), None
                    )
                    con_ctrl = bool(event.modifiers() & Qt.ControlModifier)
                    if nodo_bajo_cursor is not None:
                        self._duplicar_click_nodo(nodo_bajo_cursor, con_ctrl)
                    else:
                        if not con_ctrl:
                            self._duplicar_colocar_en(pos.x(), pos.y())
                    return True
                # Otros botones en modo duplicar: consumir
                return True

            # --- MODO MOVER: comportamiento dual con botón izquierdo ---
            if self.modo_actual == "mover" and event.button() == Qt.LeftButton:
                if not hay_nodo:
                    # Clic en fondo: activar arrastre del mapa (navegación)
                    self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.ScrollHandDrag)
                    self._arrastrando_mapa_con_izquierdo = True
                    return False  # Dejar que el viewport procese el evento
                else:
                    # Clic sobre un nodo: no intervenimos (el nodo se encarga)
                    return False

            # --- OTROS MODOS (ruta, colocar): dejar que los controladores respectivos manejen el clic ---
            if self.modo_actual in ["ruta", "colocar"]:
                return False

            # --- COMPORTAMIENTO NORMAL (cuando NO estamos en modo ruta o colocar) ---
            if not hay_nodo:
                # Resetear estados de cursor
                if self._arrastrando_nodo:
                    self._arrastrando_nodo = False
                self._cursor_sobre_nodo = False
                self._actualizar_cursor()

                # Deseleccionar items en la escena
                try:
                    for it in self.scene.selectedItems():
                        it.setSelected(False)
                except Exception:
                    pass

                # Restaurar z-values normales
                for item in self.scene.items():
                    if isinstance(item, NodoItem):
                        item.setZValue(1)

                # Deseleccionar lista de nodos
                try:
                    self.view.nodosList.clearSelection()
                except Exception:
                    pass

                # Deseleccionar lista de rutas y limpiar highlights
                try:
                    if hasattr(self.view, "rutasList"):
                        self.view.rutasList.clearSelection()
                except Exception:
                    pass

                self._clear_highlight_lines()

                # Limpiar tabla de propiedades
                try:
                    self._limpiar_propiedades()
                except Exception:
                    pass

                # Restaurar colores normales de todos los nodos
                for item in self.scene.items():
                    if isinstance(item, NodoItem):
                        item.set_normal_color()

        # Detectar liberación del botón del ratón
        if event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton and self._arrastrando_mapa_con_izquierdo:
                # Finalizar arrastre de mapa: restaurar dragMode y actualizar cursor
                if self.modo_actual == "mover":
                    self.view.marco_trabajo.setDragMode(self.view.marco_trabajo.NoDrag)
                self._arrastrando_mapa_con_izquierdo = False
                self._actualizar_cursor()

            # Resetear estado de arrastre de nodo si aún está activo
            if self._arrastrando_nodo:
                self._arrastrando_nodo = False
                self._actualizar_cursor()

            return False

        return False
    
    # --- OBSERVER PATTERN: MÉTODOS PARA ACTUALIZACIÓN AUTOMÁTICA ---
    def _desconectar_señales_proyecto(self, proyecto=None):
        """Desconecta las señales del proyecto para evitar slots huérfanos"""
        proy = proyecto or self.proyecto
        if not proy:
            return
        for signal, slot in [
            (proy.nodo_agregado, self._on_nodo_agregado),
            (proy.nodo_modificado, self._on_nodo_modificado),
            (proy.ruta_agregada, self._on_ruta_agregada),
            (proy.ruta_modificada, self._on_ruta_modificada),
            (proy.proyecto_cambiado, self._on_proyecto_cambiado),
        ]:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _conectar_señales_proyecto(self):
        """Conecta las señales del proyecto para actualizar la UI automáticamente"""
        if not self.proyecto:
            return

        # Desconectar primero por si ya estaban conectadas (evita duplicados)
        self._desconectar_señales_proyecto()

        # Conectar señales de cambios
        self.proyecto.nodo_agregado.connect(self._on_nodo_agregado)
        self.proyecto.nodo_modificado.connect(self._on_nodo_modificado)
        self.proyecto.ruta_agregada.connect(self._on_ruta_agregada)
        self.proyecto.ruta_modificada.connect(self._on_ruta_modificada)
        self.proyecto.proyecto_cambiado.connect(self._on_proyecto_cambiado)
    
    def _on_nodo_agregado(self, nodo):
        """Se llama automáticamente cuando se agrega un nuevo nodo"""
        
        # Inicializar visibilidad del nodo
        self._inicializar_nodo_visibilidad(nodo, agregar_a_lista=True)
        
        # Actualizar rutas si existen
        self._dibujar_rutas()
    
    def _on_nodo_modificado(self, nodo):
        """Se llama automáticamente cuando se modifica un nodo"""

        # Si la modificación viene desde la tabla de propiedades, NO refrescar
        # la tabla: rebuild destruiría la celda que el usuario está editando
        # (provocaba que al cambiar Y se "moviera" X, etc.)
        editando_desde_tabla = getattr(self, '_updating_from_table', False)

        if editando_desde_tabla:
            # Solo actualizar la etiqueta lateral del nodo, sin tocar la tabla
            self._actualizar_label_lateral_nodo(nodo)
        else:
            # Actualizar lista lateral del nodo (puede regenerar la tabla)
            self.actualizar_lista_nodo(nodo)

            # Actualizar propiedades si el nodo está seleccionado
            seleccionados = self.view.nodosList.selectedItems()
            for i in range(self.view.nodosList.count()):
                item = self.view.nodosList.item(i)
                widget = self.view.nodosList.itemWidget(item)
                if widget and hasattr(widget, 'nodo_id') and widget.nodo_id == nodo.get('id'):
                    if item.isSelected():
                        self.mostrar_propiedades_nodo(nodo)
                    break

        # Actualizar rutas que contengan este nodo
        self._dibujar_rutas()
        
        # Actualizar NodoItem visual si existe
        for item in self.scene.items():
            if isinstance(item, NodoItem) and item.nodo.get('id') == nodo.get('id'):
                # Actualizar objetivo (puede afectar icono)
                item.actualizar_objetivo()
                
                # Actualizar posición si cambió X o Y
                # CORRECCIÓN: Manejar dict y objetos Nodo correctamente
                has_x = False
                has_y = False
                
                if isinstance(nodo, dict):
                    has_x = "X" in nodo
                    has_y = "Y" in nodo
                else:
                    # Si es un objeto Nodo, usar hasattr
                    has_x = hasattr(nodo, "X")
                    has_y = hasattr(nodo, "Y")
                
                if has_x or has_y:
                    item.actualizar_posicion()
                
                # Forzar repintado para cualquier propiedad (incluyendo ángulo "A")
                item.update()
                
                break
    
    def _on_ruta_agregada(self, ruta):
        """Se llama automáticamente cuando se agrega una nueva ruta"""
        
        # Actualizar lista lateral de rutas
        self._actualizar_lista_rutas_con_widgets()
        
        # Redibujar rutas
        self._dibujar_rutas()
        
        # Actualizar relaciones nodo-ruta
        self._actualizar_todas_relaciones_nodo_ruta()
    
    def _on_ruta_modificada(self, ruta):
        """Se llama automáticamente cuando se modifica una ruta"""
        
        # Actualizar lista lateral de rutas
        self._actualizar_lista_rutas_con_widgets()
        
        # Redibujar rutas
        self._dibujar_rutas()
        
        # Si hay una ruta seleccionada, actualizar sus propiedades
        if hasattr(self.view, "rutasList") and self.view.rutasList.selectedItems():
            for i in range(self.view.rutasList.count()):
                item = self.view.rutasList.item(i)
                if item.isSelected():
                    widget = self.view.rutasList.itemWidget(item)
                    if widget and hasattr(widget, 'ruta_index'):
                        self.mostrar_propiedades_ruta(self.proyecto.rutas[widget.ruta_index])
                        break
    
    def _on_proyecto_cambiado(self):
        """Se llama automáticamente cuando hay cambios generales en el proyecto"""
        self.proyecto_modificado = True

        # Actualizar relaciones nodo-ruta
        self._actualizar_todas_relaciones_nodo_ruta()

        # Forzar actualización visual
        self.view.marco_trabajo.viewport().update()
    
    def _actualizar_referencias_proyecto(self, proyecto):
        """Actualiza todas las referencias al proyecto en controladores y subcontroladores"""
        self.proyecto = proyecto
        
        # Reconectar señales del proyecto
        self._conectar_señales_proyecto()
        
        # Actualizar en subcontroladores
        self.mover_ctrl.proyecto = proyecto
        self.colocar_ctrl.proyecto = proyecto
        self.ruta_ctrl.proyecto = proyecto
        
        # IMPORTANTE: Resetear el estado de los subcontroladores
        if self.modo_actual:
            self._resetear_modo_actual()
        

    def forzar_actualizacion_cursor(self):
        """Fuerza la actualización del cursor, útil para debug"""
        self._actualizar_cursor()


    def _reconstruir_rutas_para_dibujo(self):
        """
        Reconstruye todas las rutas excluyendo nodos ocultos.
        Similar a _reconfigurar_rutas_por_eliminacion pero temporal.
        """
        if not self.proyecto:
            return []
        
        rutas_reconstruidas = []
        
        for ruta_idx, ruta in enumerate(self.proyecto.rutas):
            # Verificar si la ruta está visible globalmente
            if not self.visibilidad_rutas.get(ruta_idx, True):
                rutas_reconstruidas.append([])  # Ruta completamente oculta
                continue
                
            try:
                ruta_dict = ruta.to_dict() if hasattr(ruta, "to_dict") else ruta
            except Exception:
                ruta_dict = ruta
            
            # Normalizar la ruta
            self._normalize_route_nodes(ruta_dict)
            
            # Obtener todos los nodos de la ruta en orden
            puntos_completos = []
            if ruta_dict.get("origen"):
                puntos_completos.append(ruta_dict["origen"])
            puntos_completos.extend(ruta_dict.get("visita", []) or [])
            if ruta_dict.get("destino"):
                puntos_completos.append(ruta_dict["destino"])
            
            # Filtrar solo nodos visibles
            puntos_visibles = []
            for punto in puntos_completos:
                if isinstance(punto, dict):
                    nodo_id = punto.get('id')
                    if nodo_id is not None and self.visibilidad_nodos.get(nodo_id, True):
                        puntos_visibles.append(punto)
            
            # Reconstruir ruta excluyendo nodos ocultos
            ruta_reconstruida = self._reconstruir_ruta_saltando_nodos_ocultos(puntos_completos, puntos_visibles)
            rutas_reconstruidas.append(ruta_reconstruida)
        
        return rutas_reconstruidas
    
    def _reconstruir_ruta_saltando_nodos_ocultos(self, puntos_completos, puntos_visibles):
        """
        Reconstruye una ruta saltando nodos ocultos, similar a cuando se elimina un nodo.
        
        Args:
            puntos_completos: Todos los nodos de la ruta en orden
            puntos_visibles: Solo los nodos visibles de la ruta
        
        Returns:
            Lista de nodos para dibujar la ruta (puede tener menos nodos que la original)
        """
        if len(puntos_visibles) == len(puntos_completos):
            # Todos los nodos visibles, ruta intacta
            return puntos_completos
        
        if len(puntos_visibles) < 2:
            # No hay suficientes nodos visibles para dibujar una ruta
            return []
        
        # Crear mapa de visibilidad por índice
        visibilidad_por_indice = []
        for punto in puntos_completos:
            if isinstance(punto, dict):
                nodo_id = punto.get('id')
                visible = nodo_id is not None and self.visibilidad_nodos.get(nodo_id, True)
            else:
                visible = False
            visibilidad_por_indice.append(visible)
        
        # Reconstruir ruta saltando nodos ocultos
        ruta_reconstruida = []
        
        for i, punto in enumerate(puntos_completos):
            if not visibilidad_por_indice[i]:
                # Nodo oculto, omitirlo
                continue
                
            if i == 0 or i == len(puntos_completos) - 1:
                # Origen o destino: siempre incluirlo si está visible
                ruta_reconstruida.append(punto)
            else:
                # Nodo intermedio: incluirlo si está visible
                ruta_reconstruida.append(punto)
        
        # Si después de reconstruir tenemos menos de 2 nodos, retornar vacío
        return ruta_reconstruida if len(ruta_reconstruida) >= 2 else []
    
    def forzar_actualizacion_cursor(self):
        """Fuerza la actualización del cursor, útil para debug"""
        self._actualizar_cursor()