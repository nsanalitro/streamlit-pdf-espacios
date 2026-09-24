"""Interfaz Streamlit para generar el PDF de espacios de entrenamiento."""

import os

import streamlit as st

import pdf_generator as pg
import sheets_manager as sm

st.set_page_config(page_title="Espacios de Entrenamiento", page_icon="🗺️", layout="centered")

st.title("Generador de PDF de Espacios")
st.caption("AFA Internacional · UCF Santa Perpètua")


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
