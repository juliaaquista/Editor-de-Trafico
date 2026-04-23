# Editor de Tráfico

Editor visual de mapas para robots AGV (Automated Guided Vehicles). Permite diseñar, gestionar y exportar rutas y nodos de navegación sobre planos reales de planta en formato **STCM** o imágenes estándar.

---

## Características principales

- **Carga de mapas**: soporte nativo para archivos **.stcm** (formato binario de mapas AGV) con extracción automática de origen, resolución y bitmap. También acepta PNG/JPG/BMP.
- **Gestión de nodos**: crear, mover, seleccionar, eliminar y **duplicar** (con selección múltiple). Coordenadas en metros en la UI.
- **Rutas**: origen → visitas → destino, con nombre personalizable y líneas discontinuas para `Tipo_curva != 0`. Los nodos de la ruta seleccionada se resaltan en **amarillo**.
- **Tipos de objetivo**: Normal, Dejada, Cogida, I/O, Cargador y Paso, cada uno con color distintivo.
- **Propiedades avanzadas por objetivo**: diálogo dedicado con validación de campos obligatorios (Pasillo, Estantería, Nombre, Pose final, etc.) y campo **Cargador (ID)** obligatorio cuando objetivo = Cargador.
- **Parámetros del sistema**: menús para parámetros globales del AGV, parámetros de playa y tipos de carga/descarga.
- **Visibilidad**: mostrar/ocultar nodos y rutas individualmente o en masa.
- **Undo/Redo**: historial de cambios con Ctrl+Z / Ctrl+Y (movimientos, creaciones, eliminaciones, cambios de propiedad).
- **Import / Export**:
  - Proyectos en formato JSON (incluye metadatos STCM para restaurar offsets exactos).
  - Exportación a **SQLite** (.db) y **CSV** con coordenadas en metros.
  - **Importar proyecto**: diálogo interactivo para traer rutas, nodos y/o parámetros desde otro `.json`, con resolución por caso de conflictos de ID y remapeo automático en rutas.
- **Ajuste automático de vista** (`fitInView`) al cargar un mapa nuevo.
- **Arquitectura MVC + patrón Observer** (señales Qt) para actualización eficiente entre modelo y vista.

---

## Requisitos

- Python 3.8+
- PyQt5
- Pillow (para manejo de bitmaps al parsear STCM)

Instalar dependencias:

```bash
pip install -r requeriments.txt
```

En Windows también podés usar el script incluido:

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
├── manual de usuario.pdf
│
├── Controller/
│   ├── editor_controller.py       # Controlador principal (UI, undo/redo, visibilidad, duplicar, importar)
│   ├── colocar_controller.py      # Modo: colocar nodos con clic
│   ├── mover_controller.py        # Modo: arrastrar nodos
│   └── ruta_controller.py         # Modo: crear rutas entre nodos
│
├── Model/
│   ├── Nodo.py                    # Modelo de nodo (wrapper dict con get/update/to_dict)
│   ├── Proyecto.py                # Modelo de proyecto con señales Qt (Observer)
│   ├── schema.py                  # Definición de campos / defaults del esquema de datos
│   ├── stcm_parser.py             # Parser binario de archivos .stcm (extrae metadatos + bitmap)
│   ├── ExportadorDB.py            # Exportación a SQLite
│   └── ExportadorCSV.py           # Exportación a CSV
│
├── View/
│   ├── editor.ui                  # Diseño de la ventana principal (Qt Designer)
│   ├── view.py                    # EditorView + widgets de lista (nodos/rutas)
│   ├── node_item.py               # QGraphicsObject visual para cada nodo
│   ├── zoom_view.py               # QGraphicsView con zoom (rueda) y pan (botón central)
│   ├── dialogo_parametros.py                  # Parámetros del sistema
│   ├── dialogo_parametros_playa.py            # Parámetros de playa
│   ├── dialogo_parametros_carga_descarga.py   # Parámetros carga/descarga
│   ├── dialogo_propiedades_objetivo.py        # Propiedades avanzadas de nodo
│   ├── dialogo_importar_seleccion.py          # Selección de elementos a importar
│   └── dialogo_importar_nodo.py               # Resolución de conflicto de ID al importar
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
| **Colocar vértice** | Botón | Clic en el mapa para crear un nuevo nodo |
| **Mover vértice** | Botón | Arrastra nodos; clic en fondo para desplazar el mapa |
| **Crear ruta** | Botón | Clic en nodos (o mapa) para encadenarlos en una ruta |
| **Duplicar nodo** | Botón | Clic marca un nodo, Ctrl+clic agrega más; al soltar Ctrl aparecen fantasmas verdes con coordenadas en vivo, clic en zona vacía los coloca |

### Atajos de teclado

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

## Tipos de objetivo

| Tipo | Valor `objetivo` | Color del nodo | Abre diálogo avanzado | Va a `objetivos.csv` |
|------|:----------------:|----------------|:---------------------:|:--------------------:|
| Normal | 0 | Azul | ❌ | ❌ |
| Dejada | 1 | Rojo | ✅ | ✅ |
| Cogida | 2 | Verde | ✅ | ✅ |
| I/O | 3 | Violeta | ✅ | ✅ |
| Cargador | 4 | Naranja | ✅ (pide ID de cargador) | ✅ |
| Paso | 5 | Negro | ❌ | ❌ (se escribe en `puntos.csv` con `objetivo=5`) |

El **Cargador** (objetivo = 4) requiere un campo obligatorio **Cargador (ID)** ≠ 0 que se persiste en `es_cargador`.

---

## Propiedades de un nodo

| Propiedad | Descripción |
|-----------|-------------|
| `X`, `Y` | Posición en metros (internamente en píxeles; escala por defecto: 1 px = 0.05 m, o lo que indique el STCM) |
| `A` | Ángulo de orientación (grados) |
| `Vmax` | Velocidad máxima |
| `Seguridad`, `Seg_alto`, `Seg_horq`, `Seg_tresD`, `seg_2d_tras` | Zonas de seguridad |
| `Tipo_curva` | 0 = línea sólida, ≠0 = línea discontinua |
| `QR`, `Reloc` | Flags de ubicación |
| `objetivo` | Tipo de objetivo (0-5) |
| `es_cargador` | ID del cargador (cuando objetivo=4) |
| `decision`, `timeout` | Control de comportamiento |
| `Puerta_Abrir`, `Puerta_Cerrar`, `Punto_espera` | Control de puertas/espera |
| `Punto_encarar` | ID del nodo al que encarar (autorreferencia por defecto) |

Los nodos con `objetivo ∈ {1,2,3,4}` tienen además **propiedades avanzadas**: pasillo, estantería, altura, altura en mm, punto pasillo, pose final, punto desaproximar, FIFO, nombre, precisión, número de playa, tipo carga/descarga, distancia horquilla-pallet.

---

## Mapas STCM

El editor incluye un parser propio para archivos `.stcm` (formato binario común en sistemas de navegación AGV). Extrae:

- **dimension_width / dimension_height**: tamaño del bitmap.
- **origin_x / origin_y**: origen físico del mapa (el 0,0 real).
- **resolution_x / resolution_y**: metros por píxel (define la escala de toda la app).
- **Píxeles**: `0 = obstáculo` (negro), `127 = espacio libre` (blanco). Cualquier otro valor se considera desconocido / ruido y se pinta negro (evita artefactos en los bordes).

Al guardar un proyecto se persisten los metadatos STCM (origin + resolution) en el JSON, de modo que al reabrirlo los offsets y coordenadas quedan idénticos.

El (0,0) coordenado queda en la esquina inferior izquierda del bitmap completo.

---

## Import / Export

### Proyecto JSON

```json
{
  "mapa": "ruta/al/mapa.png",
  "nodos": [ { "id": 1, "X": 200, "Y": 300, "objetivo": 0, ... } ],
  "rutas": [
    {
      "nombre": "Ruta",
      "origen":  { "id": 1, ... },
      "visita":  [ { "id": 2, ... } ],
      "destino": { "id": 3, ... }
    }
  ],
  "parametros": [...],
  "parametros_playa": [...],
  "parametros_carga_descarga": [...],
  "stcm": { "origin_x": 0, "origin_y": 0, "resolution_x": 0.05, "resolution_y": 0.05 }
}
```

### Importar proyecto

Permite traer elementos de otro proyecto al actual. El flujo:

1. **Seleccionar qué importar**: diálogo con checkboxes para cada ruta, opciones para traer también nodos sueltos (o todos) y los parámetros de playa / carga-descarga.
2. **Nodos referenciados**: los nodos usados por las rutas seleccionadas se importan automáticamente.
3. **Conflictos de ID**: si un ID de nodo ya existe en el proyecto destino, aparece un diálogo por caso con opciones (*Asignar nuevo ID* / *Saltear* / *Cancelar*) y checkbox *"Aplicar a los N restantes"*.
4. **Remapeo**: las rutas importadas se reconstruyen usando los nuevos IDs; si una ruta referencia un nodo salteado, se descarta con aviso en el resumen final.
5. **Parámetros**: si hay colisión de ID en playa o carga/descarga, se renumera automáticamente.

### Exportación a SQLite (`.db`) y CSV

Genera hasta 6 archivos en la carpeta seleccionada:

| Archivo | Contenido |
|---------|-----------|
| `puntos.*`             | Todos los nodos con sus propiedades básicas |
| `objetivos.*`          | Propiedades avanzadas de nodos con `objetivo ∈ {1,2,3,4}` (Paso no va) |
| `rutas.*`              | Rutas: `origen_id`, `destino_id`, `visitados` (lista de IDs) |
| `playas.*`             | Parámetros de playa |
| `parametros.*`         | Parámetros globales del sistema |
| `tipo_carga_descarga.*`| Tipos de carga/descarga |

Las coordenadas siempre se exportan en **metros**.

---

## Arquitectura

Proyecto con patrón **MVC** + **Observer** (señales Qt):

- **Model** (`Proyecto`, `Nodo`): emite señales (`nodo_modificado`, `nodo_agregado`, `ruta_agregada`, `ruta_modificada`, `proyecto_cambiado`, etc.) al cambiar estado.
- **View** (`EditorView`, `NodoItem`, widgets de lista): renderiza el estado visual sin lógica de negocio.
- **Controller** (`EditorController` + subcontroladores): recibe eventos de UI, actualiza el modelo y reacciona a las señales del modelo para refrescar la vista.

El `EditorController` delega los modos de interacción a subcontroladores independientes (`ColocarController`, `MoverController`, `RutaController`) que instalan/desinstalan filtros de eventos según el modo activo. El modo **Duplicar** y el **Import** se manejan directamente desde el controlador principal usando el mismo patrón de filtro de eventos.

---
