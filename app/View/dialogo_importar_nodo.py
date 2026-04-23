from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QCheckBox, QFrame)
from PyQt5.QtCore import Qt


class DialogoImportarNodo(QDialog):
    """Diálogo para resolver una colisión de ID al importar un nodo.

    Resultado: atributo `accion` con valor:
      - "nuevo_id": asignar nuevo ID al nodo importado
      - "saltear":  no importar este nodo
      - "cancelar": cancelar toda la importación
    Y `aplicar_a_todos` (bool) indicando si usar la misma acción para los
    conflictos siguientes.
    """

    def __init__(self, parent, nodo_origen, nodo_actual, nuevo_id_sugerido,
                 restantes: int):
        super().__init__(parent)
        self.setWindowTitle("Conflicto de ID al importar")
        self.setMinimumWidth(520)
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #ffffff; }
            QPushButton {
                background-color: #5a5a5a; color: #ffffff;
                border: 1px solid #555; border-radius: 3px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #6a6a6a; }
            QCheckBox { color: #ffffff; }
            QFrame[frameShape="4"] { background-color: #555; }
        """)

        self.accion = "cancelar"
        self.aplicar_a_todos = False

        layout = QVBoxLayout()

        def _fmt(nodo):
            if hasattr(nodo, "to_dict"):
                nodo = nodo.to_dict()
            if not isinstance(nodo, dict):
                return str(nodo)
            objetivo_txt = {
                0: "Normal", 1: "Dejada", 2: "Cogida",
                3: "I/O", 4: "Cargador", 5: "Paso"
            }.get(int(nodo.get("objetivo", 0) or 0), "?")
            return (f"ID {nodo.get('id')} | X={nodo.get('X',0)} "
                    f"Y={nodo.get('Y',0)} | objetivo={objetivo_txt} | "
                    f"nombre=\"{nodo.get('Nombre','')}\"")

        titulo = QLabel(
            f"<b>El ID {nodo_origen.get('id') if hasattr(nodo_origen,'get') else '?'} "
            f"ya existe en el proyecto actual.</b>"
        )
        titulo.setStyleSheet("font-size: 14px;")
        layout.addWidget(titulo)

        layout.addWidget(QLabel(f"<b>Nodo a importar:</b><br>{_fmt(nodo_origen)}"))
        layout.addWidget(QLabel(f"<b>Nodo existente:</b><br>{_fmt(nodo_actual)}"))

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        info = QLabel(
            f"Si elige \"Asignar nuevo ID\", al nodo importado se le asignará "
            f"el ID <b>{nuevo_id_sugerido}</b> (o el siguiente libre).<br>"
            f"Si elige \"Saltear\", el nodo no se importará y las rutas que lo "
            f"usen también se descartarán."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.chk_aplicar_todos = QCheckBox(
            f"Aplicar esta acción a los {restantes} conflictos restantes"
        )
        if restantes <= 0:
            self.chk_aplicar_todos.setVisible(False)
        layout.addWidget(self.chk_aplicar_todos)

        botones = QHBoxLayout()
        botones.addStretch()

        btn_nuevo = QPushButton("Asignar nuevo ID")
        btn_nuevo.setDefault(True)
        btn_nuevo.clicked.connect(lambda: self._elegir("nuevo_id"))

        btn_saltear = QPushButton("Saltear")
        btn_saltear.clicked.connect(lambda: self._elegir("saltear"))

        btn_cancelar = QPushButton("Cancelar importación")
        btn_cancelar.clicked.connect(lambda: self._elegir("cancelar"))

        botones.addWidget(btn_nuevo)
        botones.addWidget(btn_saltear)
        botones.addWidget(btn_cancelar)
        layout.addLayout(botones)

        self.setLayout(layout)

    def _elegir(self, accion):
        self.accion = accion
        self.aplicar_a_todos = self.chk_aplicar_todos.isChecked()
        if accion == "cancelar":
            self.reject()
        else:
            self.accept()
