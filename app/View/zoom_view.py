from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtCore import Qt, QPoint, QPointF
from PyQt5.QtGui import QPainter, QWheelEvent, QCursor, QTransform

class ZoomGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.TextAntialiasing)

        # Configuración para mejor rendimiento en Windows
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)

        # No usar anchor automático, lo hacemos manual con scrollbars
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        # Scrollbars visibles siempre
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Mejorar la respuesta al ratón en Windows
        self.setMouseTracking(True)

        # Variables para zoom
        self.zoom_level = 0
        self.zoom_factor = 1.25
        self.min_zoom = 0.1
        self.max_zoom = 10.0

        # Variables para pan con botón central
        self._pan = False
        self._pan_start_pos = QPoint()

    def wheelEvent(self, event: QWheelEvent):
        # Posición del cursor en el viewport
        view_pos = event.pos()
        # Convertir a coordenadas de escena ANTES del zoom
        scene_pos = self.mapToScene(view_pos)

        # Calcular factor
        if event.angleDelta().y() > 0:
            factor = self.zoom_factor
        else:
            factor = 1 / self.zoom_factor

        # Limitar zoom
        current_scale = self.transform().m11()
        new_scale = current_scale * factor

        if self.min_zoom <= new_scale <= self.max_zoom:
            # Crear nueva transformación centrada en el punto del cursor
            # 1. Mover el origen al punto de la escena bajo el cursor
            # 2. Escalar
            # 3. Mover el origen de vuelta
            old_transform = self.transform()
            new_transform = QTransform()
            new_transform.translate(scene_pos.x(), scene_pos.y())
            new_transform.scale(factor, factor)
            new_transform.translate(-scene_pos.x(), -scene_pos.y())

            # Combinar con la transformación existente
            self.setTransform(old_transform * new_transform)

            # Asegurar que el punto de la escena siga bajo el cursor
            # ajustando las scrollbars
            new_scene_pos = self.mapToScene(view_pos)
            delta_x = scene_pos.x() - new_scene_pos.x()
            delta_y = scene_pos.y() - new_scene_pos.y()

            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(int(h_bar.value() + delta_x * new_scale))
            v_bar.setValue(int(v_bar.value() + delta_y * new_scale))

        event.accept()

    # --- MÉTODOS PARA NAVEGACIÓN CON BOTÓN CENTRAL ---

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan:
            delta = self._pan_start_pos - event.pos()
            self._pan_start_pos = event.pos()

            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() + delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() + delta.y()
            )
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan:
            self._pan = False
            self.unsetCursor()
            event.accept()
            return

        super().mouseReleaseEvent(event)
