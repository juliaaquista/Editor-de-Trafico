# Editor de Tráfico 

Editor gráfico de mapas para robots AGV (Automated Guided Vehicles). Permite diseñar, gestionar y exportar rutas y nodos de navegación sobre imágenes de planta.

---

## Características principales

- **Carga de mapas**: Importa imágenes PNG/JPG como fondo de trabajo
- **Gestión de nodos**: Crea, mueve, selecciona y elimina nodos de navegación sobre el mapa
- **Rutas**: Define rutas entre nodos con origen, destino y nodos intermedios (visita)
- **Tipos de nodo**: Nodos normales, de carga (IN), descarga (OUT), bidireccionales (I/O) y cargadores de batería
- **Propiedades avanzadas**: Configura parámetros detallados por nodo (velocidad, seguridad, ángulo, tipo de curva, etc.)
- **Parámetros del sistema**: Configura parámetros globales del AGV, parámetros de playa y tipos de carga/descarga
- **Visibilidad**: Muestra u oculta nodos y rutas de forma individual o global
- **Undo/Redo**: Historial de cambios con Ctrl+Z / Ctrl+Y (movimientos, creaciones, eliminaciones, cambios de propiedad)
- **Exportación**: Exporta a SQLite (.db) y CSV con coordenadas en metros
- **Guardado de proyectos**: Serialización completa en formato JSON

---

## Requisitos

- Python 3.8+
- PyQt5

Instalar dependencias:

```bash
pip install -r requeriments.txt
```

En Windows puedes usar el script de configuración incluido:

```bash
set_up_windows.bat
```

---

## Ejecución

```bash
python main.py
```

---

## Estructura del proyecto

```
app/
├── main.py                        # Punto de entrada
├── requeriments.txt
├── set_up_windows.bat
│
├── Controller/
│   ├── editor_controller.py       # Controlador principal (lógica de UI, undo/redo, visibilidad)
│   ├── colocar_controller.py      # Modo: colocar nodos con clic
│   ├── mover_controller.py        # Modo: arrastrar nodos
│   └── ruta_controller.py         # Modo: crear rutas entre nodos
│
├── Model/
│   ├── Nodo.py                    # Modelo de nodo (wrapper dict con get/update/to_dict)
│   ├── Proyecto.py                # Modelo de proyecto con señales Qt (Observer)
│   ├── ExportadorDB.py            # Exportación a SQLite
│   └── ExportadorCSV.py           # Exportación a CSV
│
├── View/
│   ├── editor.ui                  # Diseño de la ventana principal (Qt Designer)
│   ├── view.py                    # EditorView + widgets NodoListItemWidget / RutaListItemWidget
│   ├── node_item.py               # QGraphicsObject visual para cada nodo
│   ├── zoom_view.py               # QGraphicsView con zoom (rueda) y pan (botón central)
│   ├── dialogo_parametros.py               # Diálogo de parámetros del sistema
│   ├── dialogo_parametros_playa.py         # Diálogo de parámetros de playa
│   ├── dialogo_parametros_carga_descarga.py # Diálogo de parámetros carga/descarga
│   └── dialogo_propiedades_objetivo.py     # Diálogo de propiedades avanzadas de nodo
│
└── Static/
    ├── Icons/
    │   ├── bateria.png
    │   ├── cargadorIO.png
    │   ├── cargar.png
    │   └── descargar.png
    └── Scripts/
        └── estilos.qss
```

---

## Modos de edición

| Modo | Activación | Descripción |
|------|-----------|-------------|
| **Navegación** | Por defecto | Desplaza el mapa con el ratón; selecciona nodos con clic |
| **Colocar** | Botón "Colocar vértice" | Clic en el mapa para crear un nuevo nodo |
| **Mover** | Botón "Mover" | Arrastra nodos; clic en fondo para desplazar el mapa |
| **Ruta** | Botón "Crear ruta" | Clic en nodos (o mapa) para encadenarlos en una ruta |

**Atajos de teclado:**

| Tecla | Acción |
|-------|--------|
| `Enter` | Finalizar ruta en creación |
| `Escape` | Cancelar modo activo |
| `Delete` | Eliminar nodo seleccionado (con confirmación) |
| `Ctrl+Z` | Deshacer |
| `Ctrl+Y` | Rehacer |
| Rueda del ratón | Zoom in/out |
| Botón central (scroll) | Pan del mapa |

---

## Tipos de nodo

| Tipo | Icono | Valor `objetivo` |
|------|-------|-----------------|
| Normal | Círculo azul con ID | `0` |
| Carga (IN) | `cargar.png` | `1` |
| Descarga (OUT) | `descargar.png` | `2` |
| Carga/Descarga (I/O) | `cargadorIO.png` | `3` |
| Cargador de batería | `bateria.png` | `es_cargador != 0` |

---

## Propiedades de un nodo

| Propiedad | Descripción |
|-----------|-------------|
| `X`, `Y` | Posición en metros (se almacena en píxeles internamente; escala: 1 px = 0.05 m) |
| `A` | Ángulo de orientación (grados) |
| `Vmax` | Velocidad máxima |
| `Seguridad`, `Seg_alto`, `Seg_tresD` | Zonas de seguridad |
| `Tipo_curva` | Tipo de curva (0 = línea sólida, ≠0 = línea discontinua) |
| `objetivo` | Tipo de nodo (0-3) |
| `es_cargador` | Si actúa como estación de carga |
| `decision`, `timeout`, `ultimo_metro` | Control de comportamiento |
| `Puerta_Abrir`, `Puerta_Cerrar`, `Punto_espera` | Control de puertas/espera |

Los nodos con `objetivo != 0` tienen además **propiedades avanzadas** (pasillo, estantería, altura, FIFO, playa, tipo de carga/descarga, etc.) editables desde un diálogo dedicado.

---

## Exportación

### SQLite (`.db`)
Genera hasta 6 archivos en la carpeta seleccionada:

| Archivo | Contenido |
|---------|-----------|
| `puntos.db` | Todos los nodos con sus propiedades básicas |
| `objetivos.db` | Propiedades avanzadas de nodos con objetivo |
| `rutas.db` | Rutas: `origen_id`, `destino_id`, `visitados` (lista de IDs) |
| `playas.db` | Parámetros de playa |
| `parametros.db` | Parámetros globales del sistema |
| `tipo_carga_descarga.db` | Tipos de carga/descarga |

### CSV
Misma estructura que SQLite pero en archivos `.csv`.

Las coordenadas siempre se exportan en **metros** (escala `0.05 m/px` por defecto).

---

## Formato de proyecto (JSON)

```json
{
  "mapa": "ruta/al/mapa.png",
  "nodos": [ { "id": 1, "X": 200, "Y": 300, "objetivo": 0, ... } ],
  "rutas": [
    {
      "nombre": "Ruta",
      "origen": { "id": 1, ... },
      "visita": [ { "id": 2, ... } ],
      "destino": { "id": 3, ... }
    }
  ],
  "parametros": { "G_AGV_ID": 2, ... },
  "parametros_playa": [ { "ID": 1, "Columnas": 10, ... } ],
  "parametros_carga_descarga": [ { "ID": 0, "p_a": 100, ... } ]
}
```

---

## Arquitectura

El proyecto sigue un patrón **MVC** con **Observer** mediante señales Qt:

- **Model** (`Proyecto`, `Nodo`): emite señales (`nodo_modificado`, `ruta_agregada`, etc.) al cambiar estado
- **View** (`EditorView`, `NodoItem`, widgets de lista): renderiza el estado visual
- **Controller** (`EditorController` + subcontroladores): recibe eventos de UI, actualiza el modelo y reacciona a las señales del modelo para refrescar la vista

El `EditorController` delega los modos de interacción a tres subcontroladores independientes (`ColocarController`, `MoverController`, `RutaController`) que instalan/desinstalan filtros de eventos según el modo activo.

---

