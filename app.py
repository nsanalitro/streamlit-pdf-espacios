"""Interfaz Streamlit: Mapas de Espacios + Envío de Correos a entrenadores."""

import os

import streamlit as st

import emails_manager as em
import pdf_generator as pg
import sheets_manager as sm

st.set_page_config(page_title="AFA Internacional", page_icon="🗺️", layout="centered")

st.title("AFA Internacional · UCF Santa Perpètua")

tab_espacios, tab_correos = st.tabs(["Mapas de Espacios", "Envío de Correos"])


with tab_espacios:
    st.header("Generador de PDF de Espacios")

    @st.cache_data(ttl=300)
    def _microciclos_disponibles():
        return sm.list_microciclos()

    try:
        microciclos = _microciclos_disponibles()
    except Exception as e:
        st.error(f"No se pudo conectar con Google Sheets: {e}")
        st.stop()

    if not microciclos:
        st.warning("No se encontraron microciclos en la hoja MICROCICLOS.")
        st.stop()

    col1, col2 = st.columns(2)
    with col1:
        microciclo_num = st.selectbox("MICROCICLO", microciclos, index=len(microciclos) - 1)
    with col2:
        dia = st.selectbox("DIA", sm.DIAS)

    st.divider()

    _, col_boton, _ = st.columns([1, 2, 1])
    with col_boton:
        generar = st.button(
            "Sincronizar y Generar PDF de Espacios",
            type="primary",
            use_container_width=True,
        )

    if generar:
        progress = st.progress(0, text="Sincronizando con Google Sheets...")
        try:
            data = sm.get_dia_completo(microciclo_num, dia)
            progress.progress(50, text="Generando PDF...")
            os.makedirs("output", exist_ok=True)
            nombre_archivo = f"Espacios {data['fecha_str']}.pdf"
            ruta = os.path.join("output", nombre_archivo)
            pg.dibujar_desde_datos(data, dia, ruta)
            progress.progress(100, text="Listo")
            with open(ruta, "rb") as f:
                st.session_state.pdf_bytes = f.read()
            st.session_state.pdf_nombre = nombre_archivo
            st.session_state.pdf_key = (microciclo_num, dia)
        except ValueError as e:
            st.session_state.pdf_bytes = None
            st.error(str(e))
        except Exception as e:
            st.session_state.pdf_bytes = None
            st.error(f"No se pudo generar el PDF: {e}")
        finally:
            progress.empty()

    if st.session_state.get("pdf_bytes") and st.session_state.get("pdf_key") == (microciclo_num, dia):
        st.success(f"PDF generado: MICROCICLO {microciclo_num} - {dia}")
        st.download_button(
            "Descargar PDF",
            data=st.session_state.pdf_bytes,
            file_name=st.session_state.pdf_nombre,
            mime="application/pdf",
            use_container_width=True,
        )


with tab_correos:
    st.header("Envío de Correos a Entrenadores")

    st.info(
        "**Planificador automático:** no configurado todavía en este entorno "
        "(pendiente: workflow de GitHub Actions para Martes/Jueves/Viernes 08:00). "
        "Por ahora, todo envío se hace con el botón manual de abajo, en modo prueba "
        "(arma la vista previa; no envía nada hasta que lo confirmes)."
    )

    c2, c3, c4, c5 = st.columns(4)
    with c2:
        cm = st.selectbox("Ciclo Matriz", [1, 2, 3])
    with c3:
        ciclo = st.selectbox("Ciclo", [1, 2, 3, 4])
    with c4:
        semana = st.selectbox("Semana", [1, 2, 3])
    with c5:
        dia_correo = st.selectbox("Día", [1, 2, 3], key="dia_correo")

    st.divider()

    _, col_boton_correo, _ = st.columns([1, 2, 1])
    with col_boton_correo:
        sincronizar = st.button(
            "Sincronizar y Armar Correos",
            type="primary",
            use_container_width=True,
            key="btn_correos",
        )

    clave_actual = (cm, ciclo, semana, dia_correo)

    if sincronizar:
        try:
            categorias = em.categorias_del_dia(dia_correo)
            previews = []
            for categoria in categorias:
                emails, asunto, cuerpo, videos_faltantes = em.generar_preview(categoria, cm, ciclo, semana, dia_correo)
                previews.append({
                    "categoria": categoria,
                    "emails": emails,
                    "asunto": asunto,
                    "cuerpo": cuerpo,
                    "videos_faltantes": videos_faltantes,
                })
            st.session_state.preview_correos = {"clave": clave_actual, "items": previews}
        except Exception as e:
            st.session_state.preview_correos = None
            st.error(f"No se pudo generar la vista previa: {e}")

    estado = st.session_state.get("preview_correos")
    if estado and estado["clave"] == clave_actual:
        items = estado["items"]
        st.subheader(f"Vista previa — {len(items)} categorías")

        for item in items:
            avisos = []
            if not item["emails"]:
                avisos.append("sin destinatarios")
            if item["videos_faltantes"]:
                avisos.append(f"falta video en {', '.join(item['videos_faltantes'])}")
            titulo = f"{item['categoria']}" + (f" ⚠️ {' | '.join(avisos)}" if avisos else "")
            with st.expander(titulo):
                if not item["emails"]:
                    st.warning(f"No hay entrenadores cargados para '{item['categoria']}'.")
                else:
                    st.write("**Para:** " + ", ".join(item["emails"]))
                if item["videos_faltantes"]:
                    st.warning(
                        f"No se encontró video en Drive para: {', '.join(item['videos_faltantes'])}. "
                        "El correo se puede mandar igual, sin ese link."
                    )
                st.write("**Asunto:** " + item["asunto"])
                st.text_area("Cuerpo del correo", item["cuerpo"], height=250, key=f"cuerpo_{item['categoria']}")

        enviables = [item for item in items if item["emails"]]
        _, col_confirmar, _ = st.columns([1, 2, 1])
        with col_confirmar:
            confirmar = st.button(
                f"Confirmar y Enviar a Todos ({len(enviables)})",
                type="secondary",
                use_container_width=True,
                disabled=not enviables,
            )
        if confirmar:
            resultados = []
            for item in enviables:
                try:
                    em.enviar_correo(item["emails"], item["asunto"], item["cuerpo"])
                    resultados.append((item["categoria"], True, None))
                except Exception as e:
                    resultados.append((item["categoria"], False, str(e)))
            for categoria, ok, error in resultados:
                if ok:
                    st.success(f"{categoria}: enviado.")
                else:
                    st.error(f"{categoria}: no se pudo enviar — {error}")
            st.session_state.preview_correos = None
