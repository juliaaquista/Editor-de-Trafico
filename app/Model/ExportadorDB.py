# -*- coding: utf-8 -*-
import sqlite3
import os
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from .schema import NODO_FIELDS, OBJETIVO_FIELDS, PARAMETROS_FIELDS

class ExportadorDB:
    @staticmethod
    def exportar(proyecto, view, escala=0.05):
        """
        Exporta el proyecto a seis bases de datos SQLite:
        - puntos.db: propiedades básicas de todos los nodos
        - objetivos.db: propiedades avanzadas de nodos con objetivo != 0
        - rutas.db: información de las rutas
        - playas.db: parámetros de playa
        - parametros.db: parámetros generales del sistema
        - tipo_carga_descarga.db: parámetros de carga/descarga
        Las coordenadas se exportan en metros usando la escala proporcionada.
        """
        if not proyecto:
            QMessageBox.warning(view, "Error", "No hay proyecto cargado.")
            return

        # Preguntar al usuario dónde guardar los archivos
        carpeta = QFileDialog.getExistingDirectory(
            view,
            "Seleccionar carpeta para exportar bases de datos"
        )
        if not carpeta:
            return  # El usuario canceló

        # --- VERIFICAR ARCHIVOS EXISTENTES ---
        rutas_a_generar = []
        # Archivos que se generan siempre
        rutas_a_generar.append(os.path.join(carpeta, "puntos.db"))
        rutas_a_generar.append(os.path.join(carpeta, "rutas.db"))

        # Objetivos (solo si hay nodos con objetivo real: 1..4).
        # "Paso" (5) no genera línea en objetivos.db.
        if any(n.get("objetivo", 0) not in (0, 5) for n in proyecto.nodos):
            rutas_a_generar.append(os.path.join(carpeta, "objetivos.db"))

        # Parámetros de playa
        if getattr(proyecto, 'parametros_playa', []):
            rutas_a_generar.append(os.path.join(carpeta, "playas.db"))

        # Parámetros generales
        if getattr(proyecto, 'parametros', {}):
            rutas_a_generar.append(os.path.join(carpeta, "parametros.db"))

        # Parámetros de carga/descarga
        if getattr(proyecto, 'parametros_carga_descarga', []):
            rutas_a_generar.append(os.path.join(carpeta, "tipo_carga_descarga.db"))

        # Filtrar los que ya existen
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
            # --- Exportar nodos (puntos básicos) usando esquema ---
            conn_nodos = sqlite3.connect(os.path.join(carpeta, "puntos.db"))
            cursor_nodos = conn_nodos.cursor()

            # Eliminar tabla si existe
            cursor_nodos.execute("DROP TABLE IF EXISTS nodos")

            # Construir CREATE TABLE dinámico según NODO_FIELDS
            column_defs = []
            for key, info in NODO_FIELDS.items():
                col_name = info.get('csv_name', key)
                db_type = info.get('db_type', 'TEXT')
                # Ajustar PRIMARY KEY si es id
                if key == 'id':
                    # Quitar 'PRIMARY KEY' si ya está incluido en db_type y añadirlo al final
                    if 'PRIMARY KEY' in db_type:
                        db_type = db_type.replace('PRIMARY KEY', '').strip()
                    column_defs.append(f"{col_name} {db_type} PRIMARY KEY")
                else:
                    column_defs.append(f"{col_name} {db_type}")
            create_sql = f"CREATE TABLE nodos ({', '.join(column_defs)})"
            cursor_nodos.execute(create_sql)

            # Insertar datos
            for nodo in proyecto.nodos:
                if hasattr(nodo, 'to_dict'):
                    datos = nodo.to_dict()
                else:
                    datos = nodo

                valores = []
                for key, info in NODO_FIELDS.items():
                    col_name = info.get('csv_name', key)
                    valor = datos.get(key, info['default'])
                    if key == 'X' or key == 'Y':
                        valor = valor * escala
                    valores.append(valor)

                placeholders = ','.join(['?' for _ in NODO_FIELDS])
                insert_sql = f"INSERT INTO nodos VALUES ({placeholders})"
                cursor_nodos.execute(insert_sql, valores)

            conn_nodos.commit()
            conn_nodos.close()

            # --- Exportar objetivos (nodos con objetivo != 0) ---
            if os.path.join(carpeta, "objetivos.db") in rutas_a_generar:
                conn_objetivos = sqlite3.connect(os.path.join(carpeta, "objetivos.db"))
                cursor_objetivos = conn_objetivos.cursor()

                cursor_objetivos.execute("DROP TABLE IF EXISTS objetivos")

                # Construir tabla con campo nodo_id y los campos de OBJETIVO_FIELDS
                column_defs = ["nodo_id INTEGER PRIMARY KEY"]
                for key, info in OBJETIVO_FIELDS.items():
                    col_name = info.get('csv_name', key)
                    db_type = info.get('db_type', 'TEXT')
                    column_defs.append(f"{col_name} {db_type}")
                create_sql = f"CREATE TABLE objetivos ({', '.join(column_defs)})"
                cursor_objetivos.execute(create_sql)

                for nodo in proyecto.nodos:
                    if hasattr(nodo, 'to_dict'):
                        datos = nodo.to_dict()
                    else:
                        datos = nodo

                    # "Paso" (5) no genera línea en objetivos.db
                    if datos.get('objetivo', 0) not in (0, 5):
                        valores = [datos.get('id')]
                        for key, info in OBJETIVO_FIELDS.items():
                            valor = datos.get(key, info['default'])
                            valores.append(valor)
                        placeholders = ','.join(['?' for _ in range(len(valores))])
                        insert_sql = f"INSERT INTO objetivos VALUES ({placeholders})"
                        cursor_objetivos.execute(insert_sql, valores)

                conn_objetivos.commit()
                conn_objetivos.close()

            # --- Exportar rutas (estructura fija, no usa esquema) ---
            conn_rutas = sqlite3.connect(os.path.join(carpeta, "rutas.db"))
            cursor_rutas = conn_rutas.cursor()

            cursor_rutas.execute("DROP TABLE IF EXISTS rutas")
            cursor_rutas.execute("""
                CREATE TABLE rutas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origen_id INTEGER,
                    destino_id INTEGER,
                    visitados TEXT
                )
            """)

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

                cursor_rutas.execute("""
                    INSERT INTO rutas (origen_id, destino_id, visitados)
                    VALUES (?, ?, ?)
                """, (origen_id, destino_id, visitados_str))

            conn_rutas.commit()
            conn_rutas.close()

            # --- Exportar parámetros de playa (dinámico, igual que antes) ---
            if os.path.join(carpeta, "playas.db") in rutas_a_generar:
                parametros_playa = getattr(proyecto, 'parametros_playa', [])
                if parametros_playa:
                    conn_playa = sqlite3.connect(os.path.join(carpeta, "playas.db"))
                    cursor_playa = conn_playa.cursor()

                    cursor_playa.execute("DROP TABLE IF EXISTS parametros_playa")

                    # Obtener todas las propiedades únicas de todos los registros
                    todas_las_propiedades = set()
                    for playa in parametros_playa:
                        todas_las_propiedades.update(playa.keys())

                    propiedades_ordenadas = sorted(todas_las_propiedades)
                    if 'ID' in propiedades_ordenadas:
                        propiedades_ordenadas.remove('ID')
                        propiedades_ordenadas = ['ID'] + propiedades_ordenadas

                    # Construir CREATE TABLE dinámico
                    create_table_sql = f"""
                        CREATE TABLE parametros_playa (
                            {propiedades_ordenadas[0]} INTEGER PRIMARY KEY,
                    """
                    for i, prop in enumerate(propiedades_ordenadas[1:], 1):
                        create_table_sql += f"\n    {prop} TEXT"
                        if i < len(propiedades_ordenadas) - 1:
                            create_table_sql += ","
                    create_table_sql += "\n)"
                    cursor_playa.execute(create_table_sql)

                    for playa in parametros_playa:
                        valores = []
                        placeholders = []
                        for prop in propiedades_ordenadas:
                            placeholders.append("?")
                            valor = playa.get(prop, "")
                            valores.append(str(valor) if valor is not None else "")
                        insert_sql = f"""
                            INSERT INTO parametros_playa ({', '.join(propiedades_ordenadas)})
                            VALUES ({', '.join(placeholders)})
                        """
                        cursor_playa.execute(insert_sql, tuple(valores))

                    conn_playa.commit()
                    conn_playa.close()

            # --- Exportar parámetros generales (usando esquema, pero simple clave-valor) ---
            if os.path.join(carpeta, "parametros.db") in rutas_a_generar:
                parametros = getattr(proyecto, 'parametros', {})
                if parametros:
                    conn_param = sqlite3.connect(os.path.join(carpeta, "parametros.db"))
                    cursor_param = conn_param.cursor()

                    cursor_param.execute("DROP TABLE IF EXISTS parametros")
                    cursor_param.execute("""
                        CREATE TABLE parametros (
                            clave TEXT PRIMARY KEY,
                            valor TEXT
                        )
                    """)

                    for clave, valor in parametros.items():
                        cursor_param.execute("""
                            INSERT OR REPLACE INTO parametros (clave, valor)
                            VALUES (?, ?)
                        """, (clave, str(valor)))

                    conn_param.commit()
                    conn_param.close()

            # --- Exportar tipo_carga_descarga (dinámico, igual que antes) ---
            if os.path.join(carpeta, "tipo_carga_descarga.db") in rutas_a_generar:
                parametros_carga_descarga = getattr(proyecto, 'parametros_carga_descarga', [])
                if parametros_carga_descarga:
                    conn_carga = sqlite3.connect(os.path.join(carpeta, "tipo_carga_descarga.db"))
                    cursor_carga = conn_carga.cursor()

                    cursor_carga.execute("DROP TABLE IF EXISTS tipo_carga_descarga")

                    # Obtener todas las propiedades únicas de todos los registros
                    todas_las_propiedades = set()
                    for item in parametros_carga_descarga:
                        todas_las_propiedades.update(item.keys())

                    propiedades_ordenadas = sorted(todas_las_propiedades)
                    if 'ID' in propiedades_ordenadas:
                        propiedades_ordenadas.remove('ID')
                        propiedades_ordenadas = ['ID'] + propiedades_ordenadas

                    # Construir CREATE TABLE dinámico
                    create_table_sql = f"""
                        CREATE TABLE tipo_carga_descarga (
                            {propiedades_ordenadas[0]} INTEGER PRIMARY KEY,
                    """
                    for i, prop in enumerate(propiedades_ordenadas[1:], 1):
                        create_table_sql += f"\n    {prop} TEXT"
                        if i < len(propiedades_ordenadas) - 1:
                            create_table_sql += ","
                    create_table_sql += "\n)"
                    cursor_carga.execute(create_table_sql)

                    for item in parametros_carga_descarga:
                        valores = []
                        placeholders = []
                        for prop in propiedades_ordenadas:
                            placeholders.append("?")
                            valor = item.get(prop, "")
                            valores.append(str(valor) if valor is not None else "")
                        insert_sql = f"""
                            INSERT INTO tipo_carga_descarga ({', '.join(propiedades_ordenadas)})
                            VALUES ({', '.join(placeholders)})
                        """
                        cursor_carga.execute(insert_sql, tuple(valores))

                    conn_carga.commit()
                    conn_carga.close()

            # Mostrar mensaje de éxito
            nodos_con_objetivo = sum(1 for n in proyecto.nodos if n.get("objetivo", 0) not in (0, 5))
            archivos_creados = [
                f"• {os.path.basename(rutas_a_generar[0])} ({len(proyecto.nodos)} nodos)",
                f"• {os.path.basename(rutas_a_generar[1])} ({len(proyecto.rutas)} rutas)"
            ]
            if os.path.join(carpeta, "objetivos.db") in rutas_a_generar:
                archivos_creados.append(f"• objetivos.db ({nodos_con_objetivo} nodos con objetivo)")
            if os.path.join(carpeta, "playas.db") in rutas_a_generar:
                archivos_creados.append(f"• playas.db ({len(getattr(proyecto, 'parametros_playa', []))} playas)")
            if os.path.join(carpeta, "parametros.db") in rutas_a_generar:
                archivos_creados.append(f"• parametros.db ({len(getattr(proyecto, 'parametros', {}))} parámetros)")
            if os.path.join(carpeta, "tipo_carga_descarga.db") in rutas_a_generar:
                archivos_creados.append(f"• tipo_carga_descarga.db ({len(getattr(proyecto, 'parametros_carga_descarga', []))} tipos)")

            QMessageBox.information(
                view,
                "Exportación completada",
                f"Se han exportado:\n"
                f"• Nodos: {len(proyecto.nodos)}\n"
                f"• Rutas: {len(proyecto.rutas)}\n"
                f"• Nodos con objetivo: {nodos_con_objetivo}\n"
                f"• Playas: {len(getattr(proyecto, 'parametros_playa', []))}\n"
                f"• Parámetros generales: {len(getattr(proyecto, 'parametros', {}))}\n"
                f"• Tipos carga/descarga: {len(getattr(proyecto, 'parametros_carga_descarga', []))}\n\n"
                f"Archivos creados en:\n{carpeta}\n" + "\n".join(archivos_creados) + f"\n\n"
                f"Coordenadas exportadas en METROS (escala: {escala})"
            )

        except Exception as e:
            QMessageBox.critical(
                view,
                "Error en la exportación",
                f"Ocurrió un error al exportar: {str(e)}"
            )