from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QMessageBox, QComboBox
)
from PyQt5.QtCore import Qt

class DialogoParametros(QDialog):
    def __init__(self, parent=None, parametros=None):
        super().__init__(parent)
        self.setWindowTitle("Parámetros del Sistema")
        self.setMinimumSize(600, 500)

        # Aceptar tanto lista (nuevo formato) como dict (formato viejo)
        if isinstance(parametros, list):
            self.parametros = [p.copy() for p in parametros] if parametros else []
        elif isinstance(parametros, dict):
            # Convertir dict viejo a lista nueva
            self.parametros = [
                {"ID": k, "Valor": v, "Tipo": "REAL"} for k, v in parametros.items()
            ]
        else:
            self.parametros = []

        self.setup_ui()
        self.cargar_parametros_defecto()

    def setup_ui(self):
        layout_principal = QVBoxLayout()

        # Tabla para parámetros
        self.tabla = QTableWidget()
        self.tabla.setColumnCount(3)
        self.tabla.setHorizontalHeaderLabels(["ID", "Valor", "Tipo"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        layout_principal.addWidget(self.tabla)

        # Botones para agregar/eliminar
        botones_layout = QHBoxLayout()

        self.btn_agregar = QPushButton("Agregar Parámetro")
        self.btn_eliminar = QPushButton("Eliminar Seleccionado")

        self.btn_agregar.clicked.connect(self.agregar_parametro)
        self.btn_eliminar.clicked.connect(self.eliminar_parametro)

        botones_layout.addWidget(self.btn_agregar)
        botones_layout.addWidget(self.btn_eliminar)
        botones_layout.addStretch()

        layout_principal.addLayout(botones_layout)

        # Botones de guardar/cancelar
        botones_dialogo = QHBoxLayout()
        botones_dialogo.addStretch()

        self.btn_guardar = QPushButton("Guardar")
        self.btn_cancelar = QPushButton("Cancelar")

        self.btn_guardar.clicked.connect(self.guardar_parametros)
        self.btn_cancelar.clicked.connect(self.reject)

        botones_dialogo.addWidget(self.btn_guardar)
        botones_dialogo.addWidget(self.btn_cancelar)

        layout_principal.addLayout(botones_dialogo)

        self.setLayout(layout_principal)

    def cargar_parametros_defecto(self):
        """Carga los parámetros por defecto si no hay datos"""
        if not self.parametros:
            self.parametros = [
                {"ID": "G_AGV_ID", "Valor": 1, "Tipo": "BYTE"},
                {"ID": "G_thres_error_angle", "Valor": 5, "Tipo": "REAL"},
                {"ID": "G_dist_larguero", "Valor": 0.28, "Tipo": "REAL"},
                {"ID": "G_pulsos_por_grado_encoder", "Valor": 14.69, "Tipo": "REAL"},
                {"ID": "G_LAT_OFF", "Valor": 908, "Tipo": "REAL"},
                {"ID": "G_lateral_centro", "Valor": 46, "Tipo": "REAL"},
                {"ID": "G_LAT_MAX", "Valor": 1005, "Tipo": "REAL"},
                {"ID": "G_TACO_OFF", "Valor": 92, "Tipo": "REAL"},
                {"ID": "G_ALT_OFF", "Valor": 175, "Tipo": "REAL"},
                {"ID": "G_Offset_Lidar", "Valor": 0, "Tipo": "REAL"},
                {"ID": "G_t_stop_aprox_big", "Valor": 1, "Tipo": "REAL"},
                {"ID": "G_t_stop_r", "Valor": 0.4, "Tipo": "REAL"},
                {"ID": "G_PAL_L_P_off", "Valor": 0, "Tipo": "REAL"},
                {"ID": "G_PAL_A_P_off_peso", "Valor": 50, "Tipo": "REAL"},
                {"ID": "G_AGVS", "Valor": 2, "Tipo": "BYTE"},
            ]

        # Actualizar tabla
        self.actualizar_tabla()

    def actualizar_tabla(self):
        self.tabla.setRowCount(len(self.parametros))

        for i, param in enumerate(self.parametros):
            item_id = QTableWidgetItem(str(param.get("ID", "")))
            item_id.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)

            item_valor = QTableWidgetItem(str(param.get("Valor", 0)))
            item_valor.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)

            self.tabla.setItem(i, 0, item_id)
            self.tabla.setItem(i, 1, item_valor)

            # Combo para tipo
            combo_tipo = QComboBox()
            combo_tipo.addItems(["REAL", "BYTE"])
            tipo_actual = str(param.get("Tipo", "REAL"))
            idx = combo_tipo.findText(tipo_actual)
            if idx >= 0:
                combo_tipo.setCurrentIndex(idx)
            self.tabla.setCellWidget(i, 2, combo_tipo)

    def agregar_parametro(self):
        filas = self.tabla.rowCount()
        self.tabla.insertRow(filas)

        item_id = QTableWidgetItem("nuevo_parametro")
        item_id.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)

        item_valor = QTableWidgetItem("0")
        item_valor.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)

        self.tabla.setItem(filas, 0, item_id)
        self.tabla.setItem(filas, 1, item_valor)

        combo_tipo = QComboBox()
        combo_tipo.addItems(["REAL", "BYTE"])
        self.tabla.setCellWidget(filas, 2, combo_tipo)

        self.tabla.setCurrentCell(filas, 0)

    def eliminar_parametro(self):
        fila = self.tabla.currentRow()
        if fila >= 0:
            self.tabla.removeRow(fila)
        else:
            QMessageBox.warning(self, "Advertencia",
                              "Selecciona un parámetro para eliminar")

    def guardar_parametros(self):
        nuevos_parametros = []

        for fila in range(self.tabla.rowCount()):
            id_item = self.tabla.item(fila, 0)
            valor_item = self.tabla.item(fila, 1)
            combo_tipo = self.tabla.cellWidget(fila, 2)

            if id_item and valor_item:
                nombre = id_item.text().strip()
                valor = valor_item.text().strip()
                tipo = combo_tipo.currentText() if combo_tipo else "REAL"

                if nombre:
                    # Convertir valor numérico
                    try:
                        if '.' in valor:
                            valor = float(valor)
                        else:
                            valor = int(valor)
                    except ValueError:
                        pass

                    nuevos_parametros.append({
                        "ID": nombre,
                        "Valor": valor,
                        "Tipo": tipo
                    })

        self.parametros = nuevos_parametros
        self.accept()

    def obtener_parametros(self):
        return self.parametros
