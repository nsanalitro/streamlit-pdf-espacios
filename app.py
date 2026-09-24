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

    try:
        categorias_disponibles = sorted(em.get_destinatarios().keys())
    except Exception as e:
        st.error(f"No se pudo conectar con el Sheet de entrenadores: {e}")
        st.stop()

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        categoria = st.selectbox("Categoría", categorias_disponibles)
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
            "Sincronizar y Enviar Correos Ahora",
            type="primary",
            use_container_width=True,
            key="btn_correos",
        )

    if sincronizar:
        try:
            emails, asunto, cuerpo = em.generar_preview(categoria, cm, ciclo, semana, dia_correo)
            st.session_state.preview_correo = {
                "emails": emails,
                "asunto": asunto,
                "cuerpo": cuerpo,
                "clave": (categoria, cm, ciclo, semana, dia_correo),
            }
        except Exception as e:
            st.session_state.preview_correo = None
            st.error(f"No se pudo generar la vista previa: {e}")

    preview = st.session_state.get("preview_correo")
    if preview and preview["clave"] == (categoria, cm, ciclo, semana, dia_correo):
        st.subheader("Vista previa")
        if not preview["emails"]:
            st.warning(f"No hay entrenadores cargados para la categoría '{categoria}'.")
        else:
            st.write("**Para:** " + ", ".join(preview["emails"]))
            st.write("**Asunto:** " + preview["asunto"])
            st.text_area("Cuerpo del correo", preview["cuerpo"], height=300)

            _, col_confirmar, _ = st.columns([1, 2, 1])
            with col_confirmar:
                confirmar = st.button(
                    "Confirmar y Enviar",
                    type="secondary",
                    use_container_width=True,
                    disabled=not preview["emails"],
                )
            if confirmar:
                try:
                    em.enviar_correo(preview["emails"], preview["asunto"], preview["cuerpo"])
                    st.success("Correo enviado.")
                    st.session_state.preview_correo = None
                except Exception as e:
                    st.error(f"No se pudo enviar el correo: {e}")
