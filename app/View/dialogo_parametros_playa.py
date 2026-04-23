from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QMessageBox,
    QLabel, QInputDialog, QLineEdit
)
from PyQt5.QtCore import Qt

class DialogoParametrosPlaya(QDialog):
    def __init__(self, parent=None, parametros_playa=None):
        super().__init__(parent)
        self.setWindowTitle("Parámetros de Playa")
        self.setMinimumSize(1000, 600)
        
        # Propiedades base (fijas)
        self.propiedades_base = [
            "ID", "vertical", "Columnas", "Filas", "Pose_num",
            "Detectar_con_lidar_seguridad", "id_col", "id_row", "ref_final"
        ]
        
        # Propiedades personalizadas (dinámicas)
        self.propiedades_personalizadas = []
        
        # Inicializar parámetros de playa
        self.parametros_playa = parametros_playa.copy() if parametros_playa else []
        
        # EXTRAER PROPIEDADES PERSONALIZADAS DE LOS DATOS CARGADOS
        if self.parametros_playa:
            self._extraer_propiedades_personalizadas()
        
        self.setup_ui()
        self.cargar_parametros_defecto()
    
    def _extraer_propiedades_personalizadas(self):
        """Extrae propiedades personalizadas de los datos cargados"""
        propiedades_encontradas = set()
        
        for playa in self.parametros_playa:
            if isinstance(playa, dict):
                # Agregar todas las claves que no son propiedades base
                for clave in playa.keys():
                    if clave not in self.propiedades_base and clave not in self.propiedades_personalizadas:
                        propiedades_encontradas.add(clave)
        
        # Agregar propiedades encontradas manteniendo el orden de aparición
        for playa in self.parametros_playa:
            if isinstance(playa, dict):
                for clave in playa.keys():
                    if clave in propiedades_encontradas and clave not in self.propiedades_personalizadas:
                        self.propiedades_personalizadas.append(clave)
        
        print(f"Propiedades personalizadas extraídas: {self.propiedades_personalizadas}")
    
    def setup_ui(self):
        layout_principal = QVBoxLayout()
        
        # Información
        info_label = QLabel(
            "Cada fila representa un conjunto de parámetros de playa, que se vincula con la propiedad avanzada 'número playa' de los objetivos.\n"
            "Las columnas gris claro son propiedades fijas. Puede agregar columnas personalizadas.\n"
            "Cada conjunto debe tener un ID único."
        )
        info_label.setStyleSheet("font-style: italic; color: #666;")
        layout_principal.addWidget(info_label)
        
        # Tabla para parámetros de playa
        self.tabla = QTableWidget()
        self.actualizar_columnas_tabla()
        
        # Configurar header igual que en el otro diálogo
        header = self.tabla.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        
        layout_principal.addWidget(self.tabla)
        
        # Botones para filas
        filas_layout = QHBoxLayout()
        
        self.btn_agregar_fila = QPushButton("Agregar Fila")
        self.btn_eliminar_fila = QPushButton("Eliminar Fila Seleccionada")
        
        self.btn_agregar_fila.clicked.connect(self.agregar_playa)
        self.btn_eliminar_fila.clicked.connect(self.eliminar_playa)
        
        filas_layout.addWidget(self.btn_agregar_fila)
        filas_layout.addWidget(self.btn_eliminar_fila)
        filas_layout.addStretch()
        
        layout_principal.addLayout(filas_layout)
        
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
    
    def actualizar_columnas_tabla(self):
        """Actualiza las columnas de la tabla con propiedades base y personalizadas"""
        todas_las_propiedades = self.propiedades_base + self.propiedades_personalizadas
        self.tabla.setColumnCount(len(todas_las_propiedades))
        self.tabla.setHorizontalHeaderLabels(todas_las_propiedades)
    
    def cargar_parametros_defecto(self):
        """Carga un conjunto por defecto si no hay datos"""
        if not self.parametros_playa:
            # Un solo conjunto por defecto
            self.parametros_playa = [{
                "ID": 1,
                "vertical": 0,
                "Columnas": 10,
                "Filas": 10,
                "Pose_num": 0,
                "Detectar_con_lidar_seguridad": 0,
                "id_col": 1,
                "id_row": 1,
                "ref_final": 0
            }]
        
        # Actualizar tabla
        self.actualizar_tabla()
    
    def actualizar_tabla(self):
        """Actualiza el contenido de la tabla con los datos actuales"""
        todas_las_propiedades = self.propiedades_base + self.propiedades_personalizadas
        self.tabla.setRowCount(len(self.parametros_playa))
        
        for i, playa in enumerate(self.parametros_playa):
            for j, propiedad in enumerate(todas_las_propiedades):
                valor = playa.get(propiedad, "")
                item = QTableWidgetItem(str(valor))
                
                # TODAS las celdas son editables (igual que en el otro diálogo)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                
                # SIN color de fondo especial - igual que en el otro diálogo
                # NO aplicamos background color para que se vea normal
                
                self.tabla.setItem(i, j, item)
        
        # Ajustar ancho de columnas automáticamente
        self.tabla.resizeColumnsToContents()
        
        # Después de ajustar, asegurar que las columnas tengan un ancho mínimo
        for i in range(self.tabla.columnCount()):
            if self.tabla.columnWidth(i) < 100:
                self.tabla.setColumnWidth(i, 100)
    
    def agregar_propiedad_personalizada(self):
        """Agrega una nueva propiedad personalizada como columna"""
        nombre, ok = QInputDialog.getText(
            self, 
            "Nueva Propiedad Personalizada",
            "Ingrese el nombre de la nueva propiedad:",
            QLineEdit.Normal
        )
        
        if ok and nombre:
            nombre = nombre.strip()
            if nombre and nombre not in self.propiedades_base and nombre not in self.propiedades_personalizadas:
                self.propiedades_personalizadas.append(nombre)
                self.actualizar_columnas_tabla()
                self.actualizar_tabla()
            elif nombre in self.propiedades_base or nombre in self.propiedades_personalizadas:
                QMessageBox.warning(self, "Error", f"La propiedad '{nombre}' ya existe.")
    
    def eliminar_propiedad_personalizada(self):
        """Elimina la propiedad personalizada seleccionada"""
        columna = self.tabla.currentColumn()
        if columna >= 0:
            todas_las_propiedades = self.propiedades_base + self.propiedades_personalizadas
            if columna < len(todas_las_propiedades):
                propiedad = todas_las_propiedades[columna]
                
                if propiedad in self.propiedades_personalizadas:
                    respuesta = QMessageBox.question(
                        self,
                        "Confirmar eliminación",
                        f"¿Está seguro de eliminar la propiedad '{propiedad}'?\nEsta acción eliminará todos los datos de esta columna.",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    
                    if respuesta == QMessageBox.Yes:
                        self.propiedades_personalizadas.remove(propiedad)
                        self.actualizar_columnas_tabla()
                        self.actualizar_tabla()
                else:
                    QMessageBox.warning(self, "Error", "No se pueden eliminar propiedades base.")
        else:
            QMessageBox.warning(self, "Advertencia", "Seleccione una columna personalizada para eliminar.")
    
    def agregar_playa(self):
        """Agrega una nueva fila (playa) a la tabla"""
        # Calcular el próximo ID
        max_id = 0
        for i in range(self.tabla.rowCount()):
            item = self.tabla.item(i, 0)  # Columna ID
            if item and item.text().strip():
                try:
                    pid = int(item.text().strip())
                    if pid > max_id:
                        max_id = pid
                except ValueError:
                    pass
        
        # Agregar nueva fila
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        
        # Configurar valores por defecto
        valores_por_defecto = {
            "ID": str(max_id + 1),
            "vertical": "0",
            "Columnas": "10",
            "Filas": "10",
            "Pose_num": "0",
            "Detectar_con_lidar_seguridad": "0",
            "id_col": "1",
            "id_row": "1",
            "ref_final": "0"
        }
        
        todas_las_propiedades = self.propiedades_base + self.propiedades_personalizadas
        
        for j, propiedad in enumerate(todas_las_propiedades):
            valor = valores_por_defecto.get(propiedad, "")
            item = QTableWidgetItem(str(valor))
            
            # TODAS las celdas son editables (igual que en el otro diálogo)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            
            # SIN color de fondo especial
            self.tabla.setItem(fila, j, item)
        
        # Seleccionar la nueva fila
        self.tabla.setCurrentCell(fila, 0)
    
    def eliminar_playa(self):
        """Elimina la fila seleccionada"""
        fila = self.tabla.currentRow()
        if fila >= 0:
            self.tabla.removeRow(fila)
        else:
            QMessageBox.warning(self, "Advertencia", "Seleccione una fila para eliminar.")
    
    def guardar_parametros(self):
        """Guarda todos los parámetros de la tabla"""
        todas_las_propiedades = self.propiedades_base + self.propiedades_personalizadas
        nuevos_parametros = []
        ids_vistos = set()
        
        for fila in range(self.tabla.rowCount()):
            playa = {}
            
            for j, propiedad in enumerate(todas_las_propiedades):
                item = self.tabla.item(fila, j)
                valor = item.text().strip() if item else ""
                
                if propiedad == "ID":
                    if not valor:
                        QMessageBox.warning(self, "Error", f"Fila {fila+1}: El ID es obligatorio.")
                        return
                    
                    try:
                        id_valor = int(valor)
                        if id_valor in ids_vistos:
                            QMessageBox.warning(self, "Error", f"El ID {id_valor} está duplicado.")
                            return
                        ids_vistos.add(id_valor)
                        playa[propiedad] = id_valor
                    except ValueError:
                        QMessageBox.warning(self, "Error", f"Fila {fila+1}: El ID debe ser un número entero.")
                        return
                elif propiedad in self.propiedades_base:
                    # Propiedades base
                    if valor:
                        # Convertir a número si es posible
                        try:
                            if propiedad in ["vertical", "Columnas", "Filas", "Pose_num", 
                                           "Detectar_con_lidar_seguridad", "id_col", "id_row", "ref_final"]:
                                playa[propiedad] = int(valor)
                            else:
                                playa[propiedad] = valor
                        except ValueError:
                            QMessageBox.warning(self, "Error", 
                                              f"Fila {fila+1}, Columna '{propiedad}': Valor inválido.")
                            return
                    else:
                        # Valor vacío, usar valor por defecto para propiedades base
                        if propiedad in ["Columnas", "Filas"]:
                            playa[propiedad] = 10
                        elif propiedad in ["id_col", "id_row"]:
                            playa[propiedad] = 1
                        elif propiedad in ["vertical", "Pose_num", "Detectar_con_lidar_seguridad", "ref_final"]:
                            playa[propiedad] = 0
                        else:
                            playa[propiedad] = ""  # Otras propiedades base vacías
                else:
                    # Propiedades personalizadas
                    if valor:
                        # Intentar convertir a número si es posible, mantener como string si no
                        try:
                            if '.' in valor:
                                playa[propiedad] = float(valor)
                            else:
                                playa[propiedad] = int(valor)
                        except ValueError:
                            playa[propiedad] = valor
                    else:
                        # Valor vacío para propiedades personalizadas - usar cadena vacía
                        playa[propiedad] = ""
            
            nuevos_parametros.append(playa)
        
        self.parametros_playa = nuevos_parametros
        self.accept()
    
    def obtener_parametros(self):
        """Retorna la lista de parámetros de playa"""
        return self.parametros_playa
    
    def obtener_propiedades(self):
        """Retorna todas las propiedades (base + personalizadas)"""
        return self.propiedades_base + self.propiedades_personalizadas