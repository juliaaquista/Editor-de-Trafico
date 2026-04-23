# -*- coding: utf-8 -*-
import csv
import os
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from .schema import NODO_FIELDS, OBJETIVO_FIELDS

class ExportadorCSV:
    @staticmethod
    def exportar(proyecto, view, escala=0.05):
        """
        Exporta el proyecto a archivos CSV.
        """
        if not proyecto:
            QMessageBox.warning(view, "Error", "No hay proyecto cargado.")
            return

        # Preguntar al usuario dónde guardar los archivos
        carpeta = QFileDialog.getExistingDirectory(
            view,
            "Seleccionar carpeta para exportar archivos CSV"
        )
        if not carpeta:
            return  # El usuario canceló

        # --- VERIFICAR ARCHIVOS EXISTENTES ---
        rutas_a_generar = []
        # Archivos que se generan siempre
        rutas_a_generar.append(os.path.join(carpeta, "puntos.csv"))
        rutas_a_generar.append(os.path.join(carpeta, "rutas.csv"))

        # Objetivos (solo si hay nodos con objetivo real: 1..4).
        # "Paso" (5) se escribe en puntos.csv pero NO genera línea en objetivos.csv.
        if any(n.get("objetivo", 0) not in (0, 5) for n in proyecto.nodos):
            rutas_a_generar.append(os.path.join(carpeta, "objetivos.csv"))

        # Parámetros de playa
        if getattr(proyecto, 'parametros_playa', []):
            rutas_a_generar.append(os.path.join(carpeta, "playas.csv"))

        # Parámetros generales
        if getattr(proyecto, 'parametros', {}):
            rutas_a_generar.append(os.path.join(carpeta, "parametros.csv"))

        # Parámetros de carga/descarga
        if getattr(proyecto, 'parametros_carga_descarga', []):
            rutas_a_generar.append(os.path.join(carpeta, "tipo_carga_descarga.csv"))

        existentes = [r for r in rutas_a_generar if os.path.exists(r)]
        if existentes:
            msg = "Los siguientes archivos ya existen en la carpeta seleccionada:\n\n"
            msg += "\n".join(f"  • {os.path.basename(r)}" for r in existentes)
            msg += "\n\n¿Deseas sobrescribirlos?"
            respuesta = QMessageBox.question(
                view,
                "Confirmar sobrescritura",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if respuesta != QMessageBox.Yes:
                return

        # --- CONTINUAR CON LA EXPORTACIÓN NORMAL ---
        try:
            # --- Exportar puntos (nodos básicos) usando el esquema ---
            with open(os.path.join(carpeta, "puntos.csv"), 'w', newline='', encoding='utf-8') as f:
                # Obtener los nombres de columna según el esquema
                column_names = [info.get('csv_name', key) for key, info in NODO_FIELDS.items()]
                writer = csv.DictWriter(f, fieldnames=column_names)
                writer.writeheader()

                for nodo in proyecto.nodos:
                    if hasattr(nodo, 'to_dict'):
                        datos = nodo.to_dict()
                    else:
                        datos = nodo

                    fila = {}
                    for key, info in NODO_FIELDS.items():
                        col_name = info.get('csv_name', key)
                        valor = datos.get(key, info['default'])
                        # Convertir coordenadas a metros
                        if key == 'X':
                            valor = valor * escala
                        elif key == 'Y':
                            valor = valor * escala
                        fila[col_name] = valor
                    writer.writerow(fila)

            # --- Exportar objetivos (solo nodos con objetivo != 0) ---
            if os.path.join(carpeta, "objetivos.csv") in rutas_a_generar:
                with open(os.path.join(carpeta, "objetivos.csv"), 'w', newline='', encoding='utf-8') as f:
                    column_names = [info.get('csv_name', key) for key, info in OBJETIVO_FIELDS.items()]
                    # Asegurarse de que 'nodo_id' esté al principio (lo añadimos manualmente)
                    column_names = ['nodo_id'] + column_names
                    writer = csv.DictWriter(f, fieldnames=column_names)
                    writer.writeheader()

                    for nodo in proyecto.nodos:
                        if hasattr(nodo, 'to_dict'):
                            datos = nodo.to_dict()
                        else:
                            datos = nodo

                        # "Paso" (5) no genera línea en objetivos.csv
                        if datos.get('objetivo', 0) not in (0, 5):
                            fila = {'nodo_id': datos.get('id')}
                            for key, info in OBJETIVO_FIELDS.items():
                                col_name = info.get('csv_name', key)
                                valor = datos.get(key, info['default'])
                                fila[col_name] = valor
                            writer.writerow(fila)

            # --- Exportar rutas (estructura fija, no usa esquema) ---
            with open(os.path.join(carpeta, "rutas.csv"), 'w', newline='', encoding='utf-8') as f:
                campos_rutas = ['origen_id', 'destino_id', 'visitados']
                writer = csv.DictWriter(f, fieldnames=campos_rutas)
                writer.writeheader()

                for ruta in proyecto.rutas:
                    if hasattr(ruta, 'to_dict'):
                        ruta_dict = ruta.to_dict()
                    else:
                        ruta_dict = ruta

                    origen = ruta_dict.get('origen', {})
                    destino = ruta_dict.get('destino', {})
                    visita = ruta_dict.get('visita', [])

                    origen_id = origen.get('id') if isinstance(origen, dict) else None
                    destino_id = destino.get('id') if isinstance(destino, dict) else None

                    visitados_ids = []
                    if origen_id is not None:
                        visitados_ids.append(str(origen_id))
                    for v in visita:
                        if isinstance(v, dict):
                            visitados_ids.append(str(v.get('id', '')))
                        else:
                            visitados_ids.append(str(v))
                    if destino_id is not None:
                        visitados_ids.append(str(destino_id))

                    visitados_str = ','.join(visitados_ids)

                    writer.writerow({
                        'origen_id': origen_id,
                        'destino_id': destino_id,
                        'visitados': visitados_str
                    })

            # --- Exportar parámetros de playa (dinámico, igual que antes) ---
            if os.path.join(carpeta, "playas.csv") in rutas_a_generar:
                parametros_playa = getattr(proyecto, 'parametros_playa', [])
                if parametros_playa:
                    with open(os.path.join(carpeta, "playas.csv"), 'w', newline='', encoding='utf-8') as f:
                        todas_las_propiedades = set()
                        for playa in parametros_playa:
                            todas_las_propiedades.update(playa.keys())
                        propiedades_ordenadas = sorted(todas_las_propiedades)
                        if 'ID' in propiedades_ordenadas:
                            propiedades_ordenadas.remove('ID')
                            propiedades_ordenadas = ['ID'] + propiedades_ordenadas

                        writer = csv.DictWriter(f, fieldnames=propiedades_ordenadas)
                        writer.writeheader()

                        for playa in parametros_playa:
                            fila = {prop: playa.get(prop, "") for prop in propiedades_ordenadas}
                            writer.writerow(fila)

            # --- Exportar parámetros generales ---
            if os.path.join(carpeta, "parametros.csv") in rutas_a_generar:
                parametros = getattr(proyecto, 'parametros', {})
                if parametros:
                    with open(os.path.join(carpeta, "parametros.csv"), 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=['clave', 'valor'])
                        writer.writeheader()
                        for clave, valor in parametros.items():
                            writer.writerow({'clave': clave, 'valor': str(valor)})

            # --- Exportar tipo_carga_descarga (dinámico, igual que antes) ---
            if os.path.join(carpeta, "tipo_carga_descarga.csv") in rutas_a_generar:
                parametros_carga_descarga = getattr(proyecto, 'parametros_carga_descarga', [])
                if parametros_carga_descarga:
                    with open(os.path.join(carpeta, "tipo_carga_descarga.csv"), 'w', newline='', encoding='utf-8') as f:
                        todas_las_propiedades = set()
                        for item in parametros_carga_descarga:
                            todas_las_propiedades.update(item.keys())
                        propiedades_ordenadas = sorted(todas_las_propiedades)
                        if 'ID' in propiedades_ordenadas:
                            propiedades_ordenadas.remove('ID')
                            propiedades_ordenadas = ['ID'] + propiedades_ordenadas

                        writer = csv.DictWriter(f, fieldnames=propiedades_ordenadas)
                        writer.writeheader()

                        for item in parametros_carga_descarga:
                            fila = {prop: item.get(prop, "") for prop in propiedades_ordenadas}
                            writer.writerow(fila)

            # Mostrar mensaje de éxito
            nodos_con_objetivo = sum(1 for n in proyecto.nodos if n.get("objetivo", 0) not in (0, 5))
            archivos_creados = [
                f"• puntos.csv ({len(proyecto.nodos)} nodos)",
                f"• rutas.csv ({len(proyecto.rutas)} rutas)"
            ]
            if os.path.join(carpeta, "objetivos.csv") in rutas_a_generar:
                archivos_creados.append(f"• objetivos.csv ({nodos_con_objetivo} nodos con objetivo)")
            if os.path.join(carpeta, "playas.csv") in rutas_a_generar:
                archivos_creados.append(f"• playas.csv ({len(parametros_playa)} playas)")
            if os.path.join(carpeta, "parametros.csv") in rutas_a_generar:
                archivos_creados.append(f"• parametros.csv ({len(parametros)} parámetros)")
            if os.path.join(carpeta, "tipo_carga_descarga.csv") in rutas_a_generar:
                archivos_creados.append(f"• tipo_carga_descarga.csv ({len(parametros_carga_descarga)} tipos)")

            QMessageBox.information(
                view,
                "Exportación a CSV completada",
                f"Se han exportado:\n"
                f"• Nodos: {len(proyecto.nodos)}\n"
                f"• Rutas: {len(proyecto.rutas)}\n"
                f"• Nodos con objetivo: {nodos_con_objetivo}\n"
                f"• Playas: {len(parametros_playa)}\n"
                f"• Parámetros generales: {len(parametros)}\n"
                f"• Tipos carga/descarga: {len(parametros_carga_descarga)}\n\n"
                f"Archivos creados en:\n{carpeta}\n" + "\n".join(archivos_creados) + f"\n\n"
                f"Coordenadas exportadas en METROS (escala: {escala})"
            )

        except Exception as e:
            QMessageBox.critical(
                view,
                "Error en la exportación a CSV",
                f"Ocurrió un error al exportar: {str(e)}"
            )