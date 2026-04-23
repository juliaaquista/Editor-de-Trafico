from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton,
                             QFormLayout, QGroupBox, QFrame, QWidget, QScrollArea)
from PyQt5.QtCore import Qt
from Model.schema import OBJETIVO_FIELDS

class DialogoPropiedadesObjetivo(QDialog):
    def __init__(self, parent=None, propiedades=None):
        super().__init__(parent)
        self.setWindowTitle("Propiedades de Objetivo")
        self.setMinimumWidth(450)
        
        # Estilos mejorados
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                background-color: #2b2b2b;
                color: #ffaa00;
                font-weight: bold;
            }
            QLabel {
                color: #e0e0e0;
                min-width: 130px;
                font-weight: normal;
                padding: 4px;
            }
            QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #4a4a4a;
                color: #ffffff;
                border: 1px solid #6a6a6a;
                border-radius: 3px;
                padding: 4px;
                min-width: 100px;
                selection-background-color: #ffaa00;
            }
            QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
                border: 1px solid #ffaa00;
                background-color: #5a5a5a;
            }
            QPushButton {
                background-color: #5a5a5a;
                color: #ffffff;
                border: 1px solid #6a6a6a;
                border-radius: 4px;
                padding: 6px 16px;
                min-width: 90px;
            }
            QPushButton:hover {
                background-color: #6a6a6a;
                border-color: #ffaa00;
            }
            QPushButton:default {
                background-color: #ffaa00;
                color: #2b2b2b;
                border-color: #ffaa00;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2b2b2b;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #5a5a5a;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #ffaa00;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)
        
        if propiedades is None:
            propiedades = {}

        # Tipo de objetivo actual (para validaciones condicionales: Cargador=4)
        try:
            self._objetivo = int(propiedades.get("objetivo", 0))
        except (TypeError, ValueError):
            self._objetivo = 0
        self._cancelado = False

        # Diccionario para almacenar los widgets dinámicos
        self.widgets = {}
        
        # Definir a qué grupo pertenece cada clave (si no está en ninguna, irá a "Otros")
        grupos = {
            "Ubicación": ["Pasillo", "Estanteria"],
            "Altura": ["Altura", "Altura_en_mm"],
            "Puntos de Referencia": ["Punto_Pasillo", "Punto_Escara", "Punto_desapr"],
            "Operación": ["FIFO", "Nombre", "Presicion", "Ir_a_desicion", "tipo_carga_descarga"],
            "Configuración Playa": ["numero_playa"]
        }
        
        # Layout principal con scroll
        layout_principal = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(12)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        
        # --- Crear grupos dinámicamente ---
        for grupo_nombre, claves in grupos.items():
            if not claves:
                continue
            # Crear grupo
            grupo = QGroupBox(grupo_nombre)
            form_layout = QFormLayout()
            form_layout.setLabelAlignment(Qt.AlignRight)
            form_layout.setSpacing(8)
            form_layout.setContentsMargins(10, 15, 10, 10)
            
            # Añadir cada campo del grupo
            for clave in claves:
                if clave not in OBJETIVO_FIELDS:
                    continue  # Si la clave no está en el esquema, se omite
                
                info = OBJETIVO_FIELDS[clave]
                valor_actual = propiedades.get(clave, info['default'])
                
                # Crear widget según el tipo
                if info['type'] == int:
                    widget = QSpinBox()
                    widget.setRange(-999999, 999999)
                    widget.setValue(int(valor_actual))
                elif info['type'] == float:
                    widget = QDoubleSpinBox()
                    widget.setRange(-999999.0, 999999.0)
                    widget.setValue(float(valor_actual))
                else:
                    widget = QLineEdit()
                    widget.setText(str(valor_actual))
                
                # Guardar el widget para después recuperar su valor
                self.widgets[clave] = widget
                
                # Usar el nombre de la columna CSV como etiqueta si existe, sino la clave
                etiqueta = info.get('csv_name', clave)
                # Añadir un QLabel personalizado para forzar estilo si es necesario
                label = QLabel(etiqueta + ":")
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                form_layout.addRow(label, widget)
            
            grupo.setLayout(form_layout)
            scroll_layout.addWidget(grupo)
        
        # --- Grupo "Otros" para las claves que no estén en ningún grupo ---
        todas_claves = set(OBJETIVO_FIELDS.keys())
        claves_agrupadas = set()
        for claves_grupo in grupos.values():
            claves_agrupadas.update(claves_grupo)
        otras_claves = todas_claves - claves_agrupadas
        
        if otras_claves:
            grupo_otros = QGroupBox("Otros")
            form_otros = QFormLayout()
            form_otros.setLabelAlignment(Qt.AlignRight)
            form_otros.setSpacing(8)
            form_otros.setContentsMargins(10, 15, 10, 10)
            for clave in sorted(otras_claves):
                info = OBJETIVO_FIELDS[clave]
                valor_actual = propiedades.get(clave, info['default'])
                if info['type'] == int:
                    widget = QSpinBox()
                    widget.setRange(-999999, 999999)
                    widget.setValue(int(valor_actual))
                elif info['type'] == float:
                    widget = QDoubleSpinBox()
                    widget.setRange(-999999.0, 999999.0)
                    widget.setValue(float(valor_actual))
                else:
                    widget = QLineEdit()
                    widget.setText(str(valor_actual))
                self.widgets[clave] = widget
                etiqueta = info.get('csv_name', clave)
                label = QLabel(etiqueta + ":")
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                form_otros.addRow(label, widget)
            grupo_otros.setLayout(form_otros)
            scroll_layout.addWidget(grupo_otros)
        
        # --- GRUPO CARGADOR: sólo para objetivo = 4 (Cargador) ---
        # Campo "Cargador (ID)" obligatorio != 0; se guarda en es_cargador.
        self.spin_cargador = QSpinBox()
        self.spin_cargador.setRange(0, 100000)
        try:
            es_cargador_actual = int(propiedades.get("es_cargador", 0))
        except (TypeError, ValueError):
            es_cargador_actual = 0
        self.spin_cargador.setValue(es_cargador_actual)

        if self._objetivo == 4:
            grupo_cargador = QGroupBox("Cargador")
            layout_cargador = QFormLayout()
            layout_cargador.setLabelAlignment(Qt.AlignRight)
            layout_cargador.setSpacing(8)
            layout_cargador.setContentsMargins(10, 15, 10, 10)
            lbl_c = QLabel("Cargador (ID):")
            lbl_c.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout_cargador.addRow(lbl_c, self.spin_cargador)
            grupo_cargador.setLayout(layout_cargador)
            scroll_layout.addWidget(grupo_cargador)

        scroll.setWidget(scroll_content)
        layout_principal.addWidget(scroll)
        
        # Separador y botones
        separador = QFrame()
        separador.setFrameShape(QFrame.HLine)
        separador.setFrameShadow(QFrame.Sunken)
        separador.setStyleSheet("background-color: #555555; margin: 5px 0px;")
        layout_principal.addWidget(separador)
        
        botones_layout = QHBoxLayout()
        botones_layout.addStretch()
        self.btn_aceptar = QPushButton("Aceptar")
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_aceptar.setDefault(True)
        self.btn_aceptar.clicked.connect(self._validar_y_aceptar)
        self.btn_cancelar.clicked.connect(self._cancelar)
        botones_layout.addWidget(self.btn_aceptar)
        botones_layout.addWidget(self.btn_cancelar)
        layout_principal.addLayout(botones_layout)

        # Estilos de validación
        self._estilo_normal_spin = (
            "QSpinBox { background-color: #4a4a4a; color: white; "
            "border: 1px solid #6a6a6a; }"
        )
        self._estilo_error_spin = (
            "QSpinBox { background-color: #4a4a4a; color: white; "
            "border: 2px solid #DC2828; }"
        )

        self.setLayout(layout_principal)

    def _cancelar(self):
        """Cancelar: marcar flag para que el controlador revierta el objetivo."""
        self._cancelado = True
        self.reject()

    def _validar_y_aceptar(self):
        """Valida el campo Cargador (ID) obligatorio != 0 cuando objetivo=4."""
        # Reset estilos
        self.spin_cargador.setStyleSheet(self._estilo_normal_spin)
        if self._objetivo == 4 and self.spin_cargador.value() == 0:
            self.spin_cargador.setStyleSheet(self._estilo_error_spin)
            return
        self.accept()

    def obtener_propiedades(self):
        """Devuelve un diccionario con los valores actuales de todos los widgets.
        Para objetivo=4 (Cargador) incluye el ID en es_cargador."""
        resultado = {}
        for clave, widget in self.widgets.items():
            if isinstance(widget, QSpinBox):
                valor = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                valor = widget.value()
            else:
                valor = widget.text()
            resultado[clave] = valor
        if self._objetivo == 4:
            resultado["es_cargador"] = self.spin_cargador.value()
        return resultado