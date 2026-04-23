from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QCheckBox, QListWidget,
                             QListWidgetItem, QGroupBox, QFrame)
from PyQt5.QtCore import Qt


class DialogoImportarSeleccion(QDialog):
    """Diálogo para elegir qué elementos importar desde otro proyecto.

    Resultado (atributos tras Aceptar):
      - rutas_indices: set[int] con los índices de rutas seleccionadas
      - importar_nodos_sueltos: bool (nodos que no son referenciados por
        ninguna ruta seleccionada)
      - importar_todos_los_nodos: bool (todos los nodos del proyecto origen)
      - importar_parametros_playa: bool
      - importar_parametros_carga_descarga: bool
    """

    def __init__(self, parent, proyecto_src):
        super().__init__(parent)
        self.setWindowTitle("Importar proyecto — Seleccionar elementos")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #ffffff; }
            QGroupBox {
                background-color: #3c3c3c; border: 1px solid #555;
                border-radius: 4px; margin-top: 10px; padding-top: 10px;
                color: #ffffff; font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
            }
            QLabel, QCheckBox { color: #ffffff; }
            QListWidget {
                background-color: #3c3c3c; color: #ffffff;
                border: 1px solid #555;
            }
            QPushButton {
                background-color: #5a5a5a; color: #ffffff;
                border: 1px solid #555; border-radius: 3px;
                padding: 6px 14px; min-width: 90px;
            }
            QPushButton:hover { background-color: #6a6a6a; }
        """)

        self.rutas_indices = set()
        self.importar_nodos_sueltos = False
        self.importar_todos_los_nodos = False
        self.importar_parametros_playa = False
        self.importar_parametros_carga_descarga = False

        layout = QVBoxLayout()
        layout.addWidget(QLabel(
            "Seleccioná qué querés importar desde el proyecto origen.\n"
            "Los nodos referenciados por las rutas seleccionadas se importan "
            "automáticamente."
        ))

        # --- Grupo Rutas ---
        grp_rutas = QGroupBox("Rutas")
        lay_rutas = QVBoxLayout()

        botonera = QHBoxLayout()
        btn_sel_todas = QPushButton("Seleccionar todas")
        btn_sel_ninguna = QPushButton("Ninguna")
        btn_sel_todas.clicked.connect(self._seleccionar_todas)
        btn_sel_ninguna.clicked.connect(self._seleccionar_ninguna)
        botonera.addWidget(btn_sel_todas)
        botonera.addWidget(btn_sel_ninguna)
        botonera.addStretch()
        lay_rutas.addLayout(botonera)

        self.lst_rutas = QListWidget()
        self.lst_rutas.setSelectionMode(QListWidget.NoSelection)
        for idx, ruta in enumerate(proyecto_src.rutas or []):
            nombre = self._texto_ruta(ruta, idx)
            item = QListWidgetItem(nombre)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, idx)
            self.lst_rutas.addItem(item)
        lay_rutas.addWidget(self.lst_rutas)
        grp_rutas.setLayout(lay_rutas)
        layout.addWidget(grp_rutas)

        # --- Grupo Nodos ---
        grp_nodos = QGroupBox("Nodos")
        lay_nodos = QVBoxLayout()
        self.chk_todos_nodos = QCheckBox(
            f"Importar TODOS los nodos del proyecto origen "
            f"({len(proyecto_src.nodos or [])})"
        )
        self.chk_nodos_sueltos = QCheckBox(
            "Importar también los nodos no referenciados por las rutas seleccionadas"
        )
        # Si marco "todos", el otro queda redundante
        self.chk_todos_nodos.toggled.connect(
            lambda v: self.chk_nodos_sueltos.setEnabled(not v)
        )
        lay_nodos.addWidget(self.chk_todos_nodos)
        lay_nodos.addWidget(self.chk_nodos_sueltos)
        grp_nodos.setLayout(lay_nodos)
        layout.addWidget(grp_nodos)

        # --- Grupo Parámetros ---
        grp_params = QGroupBox("Parámetros")
        lay_params = QVBoxLayout()
        n_playa = len(getattr(proyecto_src, "parametros_playa", []) or [])
        n_cd = len(getattr(proyecto_src, "parametros_carga_descarga", []) or [])
        self.chk_playa = QCheckBox(f"Importar parámetros de playa ({n_playa})")
        self.chk_cd = QCheckBox(f"Importar parámetros de carga/descarga ({n_cd})")
        lay_params.addWidget(self.chk_playa)
        lay_params.addWidget(self.chk_cd)
        grp_params.setLayout(lay_params)
        layout.addWidget(grp_params)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # Botones
        botones = QHBoxLayout()
        botones.addStretch()
        self.btn_aceptar = QPushButton("Importar")
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_aceptar.setDefault(True)
        self.btn_aceptar.clicked.connect(self._aceptar)
        self.btn_cancelar.clicked.connect(self.reject)
        botones.addWidget(self.btn_aceptar)
        botones.addWidget(self.btn_cancelar)
        layout.addLayout(botones)

        self.setLayout(layout)

    def _texto_ruta(self, ruta, idx):
        def _id(ref):
            if ref is None:
                return "?"
            if isinstance(ref, dict):
                return str(ref.get("id", "?"))
            if isinstance(ref, int):
                return str(ref)
            try:
                return str(ref.get("id"))
            except Exception:
                return "?"
        nombre = ruta.get("nombre", "Ruta") if isinstance(ruta, dict) else "Ruta"
        o = _id(ruta.get("origen") if isinstance(ruta, dict) else None)
        d = _id(ruta.get("destino") if isinstance(ruta, dict) else None)
        vis = ruta.get("visita", []) if isinstance(ruta, dict) else []
        n_vis = len(vis) if vis else 0
        return f"[{idx+1}] {nombre}  —  origen {o} → destino {d}  (visitas: {n_vis})"

    def _seleccionar_todas(self):
        for i in range(self.lst_rutas.count()):
            self.lst_rutas.item(i).setCheckState(Qt.Checked)

    def _seleccionar_ninguna(self):
        for i in range(self.lst_rutas.count()):
            self.lst_rutas.item(i).setCheckState(Qt.Unchecked)

    def _aceptar(self):
        self.rutas_indices = set()
        for i in range(self.lst_rutas.count()):
            item = self.lst_rutas.item(i)
            if item.checkState() == Qt.Checked:
                self.rutas_indices.add(int(item.data(Qt.UserRole)))
        self.importar_todos_los_nodos = self.chk_todos_nodos.isChecked()
        self.importar_nodos_sueltos = (
            self.chk_nodos_sueltos.isChecked() and not self.importar_todos_los_nodos
        )
        self.importar_parametros_playa = self.chk_playa.isChecked()
        self.importar_parametros_carga_descarga = self.chk_cd.isChecked()
        self.accept()
