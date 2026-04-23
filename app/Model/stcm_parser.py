"""
Parser para archivos STCM (formato binario de mapas para sistemas de navegación AGV).

Estructura del archivo STCM:
- Magic bytes: "STCM" (4 bytes)
- Header de 18 bytes con metadatos del archivo, incluyendo el tamaño del primer layer
  como uint32 little-endian en la posición 0x12.
- Uno o más "layers" consecutivos. Cada layer contiene:
    - Items clave/valor con formato: name_len(2B LE) + name + value_len(2B LE) + value
    - Items conocidos: dimension_width, dimension_height, origin_x, origin_y,
      resolution_x, resolution_y, type, usage
    - Después de los items: datos de píxeles raw (width*height bytes) si es un grid-map
- Los archivos pueden tener un segundo layer (rectangle-area-map, etc.) después del
  grid-map. Por eso NO se puede asumir que los píxeles están al final del archivo:
  hay que usar el layer_size para encontrar el final del primer layer.
- Valores de píxel: 0 = negro (obstáculo), 127 = gris (espacio libre)
"""

import os
import struct


class STCMData:
    """Contenedor de datos extraídos de un archivo STCM."""

    def __init__(self):
        self.width = 0
        self.height = 0
        self.origin_x = 0.0
        self.origin_y = 0.0
        self.resolution_x = 0.05
        self.resolution_y = 0.05
        self.image_path = ""


def _find_key_value(data, key_name):
    """Busca una clave ASCII y extrae su valor usando el formato binario:
    [name_len(2B LE)] [name] [value_len(2B LE)] [value]

    El parser viejo hacía heurística por caracteres y fallaba con notación
    científica (ej: "2.67e-006" se cortaba en la 'e'). Este lee la longitud
    declarada en el archivo y devuelve el valor exacto.
    """
    key_bytes = key_name.encode("ascii")
    pos = data.find(key_bytes)
    if pos == -1:
        return None

    # Justo después del nombre vienen 2 bytes con la longitud del valor
    value_len_pos = pos + len(key_bytes)
    if value_len_pos + 2 > len(data):
        return None

    value_len = struct.unpack("<H", data[value_len_pos:value_len_pos + 2])[0]
    if value_len == 0 or value_len > 200:
        return None

    value_start = value_len_pos + 2
    if value_start + value_len > len(data):
        return None

    return data[value_start:value_start + value_len].decode("ascii", errors="ignore")


def parse_stcm(file_path):
    """Parsea un archivo STCM y extrae metadatos + imagen.

    Args:
        file_path: Ruta al archivo .stcm

    Returns:
        STCMData con los metadatos y ruta a la imagen PNG generada.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

    with open(file_path, "rb") as f:
        data = f.read()

    if data[:4] != b"STCM":
        raise ValueError(f"No es un archivo STCM válido (magic bytes: {data[:4]!r})")

    result = STCMData()

    keys_int = {"dimension_width": "width", "dimension_height": "height"}
    keys_float = {
        "origin_x": "origin_x",
        "origin_y": "origin_y",
        "resolution_x": "resolution_x",
        "resolution_y": "resolution_y",
    }

    for key_name, attr_name in keys_int.items():
        val = _find_key_value(data, key_name)
        if val is not None:
            try:
                setattr(result, attr_name, int(val))
            except ValueError:
                pass

    for key_name, attr_name in keys_float.items():
        val = _find_key_value(data, key_name)
        if val is not None:
            try:
                setattr(result, attr_name, float(val))
            except ValueError:
                pass

    if result.width <= 0 or result.height <= 0:
        raise ValueError(
            f"Dimensiones inválidas en STCM: {result.width}x{result.height}"
        )

    # Calcular dónde termina el primer layer.
    # En pos 0x12 hay un uint32 LE con el tamaño del primer layer.
    # El primer layer empieza en pos 0x16 (después del header del archivo).
    # Los píxeles del grid-map son los últimos width*height bytes DEL PRIMER LAYER,
    # no del archivo (un STCM puede tener layers adicionales después).
    pixel_count = result.width * result.height
    if len(data) < 0x16 + pixel_count:
        raise ValueError(
            f"Archivo demasiado pequeño: {len(data)} bytes, esperados al menos {0x16 + pixel_count}"
        )

    try:
        first_layer_size = struct.unpack("<I", data[0x12:0x16])[0]
        first_layer_end = 0x16 + first_layer_size
        if first_layer_end > len(data) or first_layer_end < 0x16 + pixel_count:
            # Tamaño de layer inválido: caer al método antiguo (final del archivo)
            first_layer_end = len(data)
    except Exception:
        first_layer_end = len(data)

    pixel_data = data[first_layer_end - pixel_count:first_layer_end]

    # Convertir a array de bytes y mapear valores
    import array
    pixels = array.array('B', pixel_data)

    # Mapeo STCM:
    #   0   = obstáculo (negro)
    #   127 = espacio libre (blanco)
    #   cualquier otro valor = "desconocido" / ruido → negro
    # (Antes se mapeaban todos los >=127 a blanco, lo que metía píxeles
    # sueltos con valores 128-255 en los bordes y producía franjas blancas
    # espurias en el mapa.)
    mapped = array.array('B', [0] * pixel_count)
    for i in range(pixel_count):
        raw = pixels[i]
        if raw == 127:
            mapped[i] = 255
        else:
            mapped[i] = 0

    # Crear imagen con PIL
    from PIL import Image
    img = Image.frombytes('L', (result.width, result.height), bytes(mapped))

    # Invertir verticalmente: en STCM el primer píxel es bottom-left
    img = img.transpose(Image.FLIP_TOP_BOTTOM)

    # Guardar como PNG junto al archivo STCM
    base_name = os.path.splitext(file_path)[0]
    png_path = base_name + ".png"
    img.save(png_path, "PNG")

    result.image_path = png_path
    print(
        f"STCM parseado: {result.width}x{result.height}, "
        f"origin=({result.origin_x}, {result.origin_y}), "
        f"resolution=({result.resolution_x}, {result.resolution_y}), "
        f"imagen guardada en: {png_path}"
    )

    return result
