"""Interfaz Streamlit: Mapas de Espacios + Envío de Correos a entrenadores."""

import os

import streamlit as st

import emails_manager as em
import pdf_generator as pg
import sheets_manager as sm

st.set_page_config(page_title="AFA Internacional", page_icon="🗺️", layout="centered")

# Cuando la app esta procesando (el indicador nativo de Streamlit aparece
# arriba a la derecha), se tapa la pantalla con un vidrio esmerilado y se
# muestra un indicador propio centrado, para que quede claro que hay que
# esperar y no tocar nada. El indicador nativo de Streamlit vive en un
# contenedor con su propio sistema de coordenadas (no se puede recentrar
# de forma confiable con CSS), por eso se oculta y se reemplaza por este.
# Requiere navegador con soporte de :has() (todos los actuales).
st.markdown(
    """
    <style>
    [data-testid="stStatusWidget"] {
        opacity: 0 !important;
    }
    [data-testid="stApp"]:has([data-testid="stStatusWidget"])::before {
        content: "";
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.25);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        z-index: 999998;
    }
    [data-testid="stApp"]:has([data-testid="stStatusWidget"])::after {
        content: "⏳\\A Procesando…\\A no cierres ni recargues la página";
        white-space: pre;
        text-align: center;
        position: fixed;
        top: calc(50% - 40px);
        left: 50%;
        z-index: 999999;
        color: white;
        font-size: 0.95rem;
        font-weight: 600;
        line-height: 1.8;
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
        animation: afa-pulso 1.4s ease-in-out infinite;
    }
    @keyframes afa-pulso {
        0%, 100% { transform: translate(-50%, -50%) scale(0.96); opacity: 0.7; }
        50% { transform: translate(-50%, -50%) scale(1.05); opacity: 1; }
    }
    /* Barra de progreso real (st.progress) centrada dentro del overlay,
    encima del icono/texto. Solo existe en el DOM mientras hay un progreso
    en curso, asi que no hace falta condicionarla con :has(). */
    [data-testid="stProgress"] {
        position: fixed !important;
        top: calc(50% + 45px) !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        width: min(320px, 80vw) !important;
        z-index: 999999 !important;
    }
    [data-testid="stProgress"] [data-testid="stCaptionContainer"],
    [data-testid="stProgress"] div[class*="caption"] {
        color: white !important;
        text-align: center !important;
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
        categorias = em.categorias_del_dia(dia_correo)
        total = len(categorias)
        progress = st.progress(0, text=f"Armando vista previa... 0/{total}")
        try:
            previews = []
            for i, categoria in enumerate(categorias):
                emails, asunto, cuerpo, videos_faltantes, contenido_faltante = em.generar_preview(
                    categoria, cm, ciclo, semana, dia_correo
                )
                previews.append({
                    "categoria": categoria,
                    "emails": emails,
                    "asunto": asunto,
                    "cuerpo": cuerpo,
                    "videos_faltantes": videos_faltantes,
                    "contenido_faltante": contenido_faltante,
                })
                pct = int((i + 1) / total * 100)
                progress.progress(pct, text=f"Armando vista previa... {i + 1}/{total} ({pct}%)")
            st.session_state.preview_correos = {"clave": clave_actual, "items": previews}
        except Exception as e:
            st.session_state.preview_correos = None
            st.error(f"No se pudo generar la vista previa: {e}")
        finally:
            progress.empty()

    estado = st.session_state.get("preview_correos")
    if estado and estado["clave"] == clave_actual:
        items = estado["items"]
        st.subheader(f"Vista previa — {len(items)} categorías")

        for item in items:
            avisos = []
            if not item["emails"]:
                avisos.append("sin destinatarios")
            if item["contenido_faltante"]:
                avisos.append("FALTAN LOS EJERCICIOS")
            if item["videos_faltantes"]:
                avisos.append(f"falta video en {', '.join(item['videos_faltantes'])}")
            titulo = f"{item['categoria']}" + (f" ⚠️ {' | '.join(avisos)}" if avisos else "")
            with st.expander(titulo):
                if not item["emails"]:
                    st.warning(f"No hay entrenadores cargados para '{item['categoria']}'.")
                else:
                    st.write("**Para:** " + ", ".join(item["emails"]))
                if item["contenido_faltante"]:
                    st.error(
                        f"⚠️ No hay ejercicios cargados (T1/T2/T3) para '{item['categoria']}' en este Ciclo/"
                        "Semana/Día — el correo saldría con el esqueleto vacío. No se puede enviar hasta "
                        "completar la planificación en el Sheet."
                    )
                if item["videos_faltantes"]:
                    st.error(
                        f"⚠️ Todavía no está en Drive el video de: {', '.join(item['videos_faltantes'])}. "
                        "No se puede enviar hasta que esté — esperá a que termine de subirse/procesarse "
                        "y volvé a sincronizar."
                    )
                st.write("**Asunto:** " + item["asunto"])
                st.text_area("Cuerpo del correo", item["cuerpo"], height=250, key=f"cuerpo_{item['categoria']}")

        enviables = [
            item for item in items
            if item["emails"] and not item["contenido_faltante"] and not item["videos_faltantes"]
        ]
        excluidas_contenido = [item["categoria"] for item in items if item["contenido_faltante"]]
        excluidas_video = [
            item["categoria"] for item in items
            if item["videos_faltantes"] and not item["contenido_faltante"]
        ]
        if excluidas_contenido:
            st.error(
                f"No se van a enviar (faltan ejercicios): {', '.join(excluidas_contenido)}. "
                "Completá esa planificación en el Sheet y volvé a sincronizar."
            )
        if excluidas_video:
            st.error(
                f"No se van a enviar (falta video en Drive): {', '.join(excluidas_video)}. "
                "Esperá a que terminen de subirse y volvé a sincronizar — o usá "
                "\"Reenviar solo videos\" más abajo una vez que estén."
            )
        _, col_confirmar, _ = st.columns([1, 2, 1])
        with col_confirmar:
            confirmar = st.button(
                f"Confirmar y Enviar a Todos ({len(enviables)})",
                type="secondary",
                use_container_width=True,
                disabled=not enviables,
            )
        if confirmar:
            total_enviables = len(enviables)
            progress_envio = st.progress(0, text=f"Enviando... 0/{total_enviables}")
            resultados = []
            for i, item in enumerate(enviables):
                try:
                    try:
                        em.compartir_videos_con_destinatarios(
                            item["categoria"], cm, ciclo, semana, dia_correo, item["emails"]
                        )
                    except Exception:
                        pass  # si falla el permiso, igual se manda el correo
                    em.enviar_correo(item["emails"], item["asunto"], item["cuerpo"])
                    resultados.append((item["categoria"], True, None))
                except Exception as e:
                    resultados.append((item["categoria"], False, str(e)))
                pct = int((i + 1) / total_enviables * 100)
                progress_envio.progress(pct, text=f"Enviando... {i + 1}/{total_enviables} ({pct}%)")
            progress_envio.empty()
            for categoria, ok, error in resultados:
                if ok:
                    st.success(f"{categoria}: enviado.")
                else:
                    st.error(f"{categoria}: no se pudo enviar — {error}")
            st.session_state.preview_correos = None

    st.divider()
    st.subheader("Reenviar solo videos")
    st.caption(
        "Para cuando el video llega después del correo principal (que ya salió sin ese link). "
        "No hace falta que haya texto de ejercicios cargado."
    )

    try:
        categorias_video = sorted(em.get_destinatarios().keys())
    except Exception as e:
        categorias_video = []
        st.error(f"No se pudo conectar con el Sheet de entrenadores: {e}")

    if categorias_video:
        vc1, vc2, vc3, vc4, vc5 = st.columns(5)
        with vc1:
            categoria_video = st.selectbox("Categoría", categorias_video, key="categoria_video")
        with vc2:
            cm_v = st.selectbox("Ciclo Matriz", [1, 2, 3], key="cm_video")
        with vc3:
            ciclo_v = st.selectbox("Ciclo", [1, 2, 3, 4], key="ciclo_video")
        with vc4:
            semana_v = st.selectbox("Semana", [1, 2, 3], key="semana_video")
        with vc5:
            dia_v = st.selectbox("Día", [1, 2, 3], key="dia_video")

        clave_video = (categoria_video, cm_v, ciclo_v, semana_v, dia_v)

        if st.button("Buscar videos", key="btn_buscar_video"):
            emails_v, asunto_v, cuerpo_v = em.generar_preview_videos(categoria_video, cm_v, ciclo_v, semana_v, dia_v)
            st.session_state.preview_video = {"clave": clave_video, "emails": emails_v, "asunto": asunto_v, "cuerpo": cuerpo_v}

        preview_v = st.session_state.get("preview_video")
        if preview_v and preview_v["clave"] == clave_video:
            if not preview_v["cuerpo"]:
                st.warning("No se encontró ningún video en Drive para esta combinación.")
            elif not preview_v["emails"]:
                st.warning(f"No hay entrenadores cargados para '{categoria_video}'.")
            else:
                st.write("**Para:** " + ", ".join(preview_v["emails"]))
                st.write("**Asunto:** " + preview_v["asunto"])
                st.text_area("Cuerpo del correo", preview_v["cuerpo"], height=180, key="cuerpo_video_preview")
                if st.button("Confirmar y Enviar Video", key="btn_confirmar_video"):
                    try:
                        em.compartir_videos_con_destinatarios(categoria_video, cm_v, ciclo_v, semana_v, dia_v, preview_v["emails"])
                    except Exception:
                        pass
                    try:
                        em.enviar_correo(preview_v["emails"], preview_v["asunto"], preview_v["cuerpo"])
                        st.success(f"{categoria_video}: video enviado.")
                        st.session_state.preview_video = None
                    except Exception as e:
                        st.error(f"No se pudo enviar: {e}")
