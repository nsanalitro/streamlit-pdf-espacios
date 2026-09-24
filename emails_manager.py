"""Lectura de destinatarios y planificacion, y envio de correos a
entrenadores por SMTP, sin intervencion de un LLM."""

import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DESTINATARIOS_FILE_ID = "1hcd650lSeJ7MgyRVm7j6ZyFUlmIOYrUQ6YrJlIWRZrA"
PLANIFICACION_TAB = "Planificacion_Ejercicios"

# Categorias femeninas/juvenil: usan el contenido (ejercicios/videos) de su
# espejo masculino, pero se agrupan y envian como categoria propia.
CATEGORIA_ESPEJO = {
    "Infantil Femenino": "Alevín",
    "Cadete Femenino": "Infantil",
    "Juvenil Femenino": "Cadete",
}

# Categorias sin 3er entrenamiento semanal (no reciben envio de Dia3 el jueves).
SIN_TERCER_DIA = {"Escoleta", "Prebenjamín"}

# Categorias habilitadas para el envio automatico (GitHub Actions). Las que
# todavia tienen texto placeholder en Planificacion_Ejercicios quedan afuera
# a proposito hasta que Nico complete su contenido real.
CATEGORIAS_AUTOMATICO = ["Escoleta", "Prebenjamín"]

# Categorias con 3er entrenamiento semanal (reciben Dia3 el jueves). Fuera
# de CATEGORIAS_AUTOMATICO porque el envio de Dia3 hoy se hace a mano desde
# la app, categoria por categoria, hasta confirmar el flujo.
CATEGORIAS_DIA3 = [
    "Benjamín", "Alevín", "Infantil", "Cadete",
    "Infantil Femenino", "Cadete Femenino", "Juvenil Femenino",
]

MAX_SEMANAS_POR_CICLO = 3
MAX_CICLOS_POR_CM = 4
MAX_CM = 3

ESTADO_TAB = "Estado_Envios"


def _get_client(credentials_path="credenciales.json"):
    # Orden: Streamlit Cloud (secrets) -> GitHub Actions (variable de
    # entorno con el JSON completo) -> archivo local (dev).
    try:
        import streamlit as st
        info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        import json
        import os
        env_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if env_json:
            creds = Credentials.from_service_account_info(json.loads(env_json), scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _categoria_base(categoria_raw):
    # "Benjamin 9a" -> "Benjamin"; "Infantil Femenino" no tiene subgrupo
    # numerico, queda igual.
    return re.sub(r"\s+\d.*$", "", categoria_raw).strip()


def get_destinatarios(credentials_path="credenciales.json"):
    """Devuelve {categoria_base: [(nombre, email), ...]}, consolidando
    subgrupos (Benjamin 9a/9b/10a/10b -> Benjamin) y sin emails duplicados
    dentro de una misma categoria base."""
    client = _get_client(credentials_path)
    rows = client.open_by_key(DESTINATARIOS_FILE_ID).sheet1.get_all_values()
    grupos = {}
    for row in rows[1:]:
        if len(row) < 3 or not row[0].strip():
            continue
        categoria_raw, nombre, email = row[0].strip(), row[1].strip(), row[2].strip()
        if not email:
            continue
        base = _categoria_base(categoria_raw)
        entrenadores = grupos.setdefault(base, [])
        if email.lower() not in {e.lower() for _, e in entrenadores}:
            entrenadores.append((nombre, email))
    return grupos


# Esqueletos horarios por tipo de sesion. F7 (Escoleta/Prebenjamin/Benjamin/
# Alevin) confirmado por Nico: estructura real de 90' que se viene enviando
# (Explicacion inicial + T1-15'/T2-25'/T3-30', segun el Word maestro vigente),
# no la de 60' de la skill vieja.
ESQUELETOS = {
    "f7_90": [
        ("Tarea 0 (motricidad)", "15' (Explicación 2', Desarrollo 10', Feedback 3')"),
        ("Explicación inicial", "5'"),
        ("T1", "15'"),
        ("Transición", "5'"),
        ("T2", "25'"),
        ("Transición", "5'"),
        ("T3", "30'"),
        ("Cierre", "5'"),
    ],
    "f11_60": [
        ("Explicación", "3'"),
        ("T1", "5'"),
        ("Transición", "2'"),
        ("T2", "25' (Bloque A 12', cambio 1', Bloque B 12')"),
        ("Transición", "2'"),
        ("T3", "20'"),
        ("Cierre", "3'"),
    ],
    "f11_70": [
        ("Explicación", "3'"),
        ("T1", "5'"),
        ("Transición", "2'"),
        ("T2", "25' (Bloque A 12', cambio 1', Bloque B 12')"),
        ("Transición", "2'"),
        ("T3", "30'"),
        ("Cierre", "3'"),
    ],
}

CATEGORIA_ESQUELETO = {
    "Escoleta": "f7_90",
    "Prebenjamín": "f7_90",
    "Benjamín": "f7_90",
    "Alevín": "f7_90",
    "Infantil Femenino": "f7_90",
    "Infantil": "f11_60",
    "Cadete Femenino": "f11_60",
    "Cadete": "f11_70",
    "Juvenil Femenino": "f11_70",
}


def get_planificacion_completa(credentials_path="credenciales.json"):
    """Devuelve {(categoria, cm, ciclo, semana, dia, tarea): texto}."""
    client = _get_client(credentials_path)
    rows = client.open_by_key(DESTINATARIOS_FILE_ID).worksheet(PLANIFICACION_TAB).get_all_values()
    tabla = {}
    for r in rows[1:]:
        if len(r) < 7:
            continue
        cm, ciclo, semana, dia, categoria, tarea, texto = r[:7]
        tabla[(categoria, cm, ciclo, semana, dia, tarea)] = texto
    return tabla


def armar_cuerpo_email(categoria, cm, ciclo, semana, dia, planificacion=None, credentials_path="credenciales.json"):
    """Arma el asunto y el cuerpo (texto plano) para categoria/cm/ciclo/
    semana/dia. Usa el contenido de la categoria espejo si corresponde
    (Infantil Femenino -> Alevín, etc). Los links de video no estan
    incluidos todavia (pendiente Etapa 3)."""
    if planificacion is None:
        planificacion = get_planificacion_completa(credentials_path)
    categoria_contenido = CATEGORIA_ESPEJO.get(categoria, categoria)
    esqueleto = ESQUELETOS[CATEGORIA_ESQUELETO[categoria]]

    def buscar(tarea):
        return planificacion.get((categoria_contenido, str(cm), str(ciclo), str(semana), str(dia), tarea))

    asunto = f"{categoria} - Ciclo {ciclo}, Semana {semana}, Día {dia}"

    lineas = ["Esqueleto de la sesión:"]
    for nombre, duracion in esqueleto:
        lineas.append(f"- {nombre}: {duracion}")
    lineas.append("")

    for tarea in ("Foco", "T0", "T1", "T2", "T3"):
        texto = buscar(tarea)
        if texto:
            lineas.append(f"{tarea}:")
            lineas.append(texto)
            lineas.append("")

    cuerpo = "\n".join(lineas).strip()
    return asunto, cuerpo


def generar_preview(categoria, cm, ciclo, semana, dia, credentials_path="credenciales.json"):
    """Arma (destinatarios, asunto, cuerpo) sin enviar nada."""
    destinatarios = get_destinatarios(credentials_path)
    entrenadores = destinatarios.get(categoria, [])
    emails = [email for _, email in entrenadores]
    asunto, cuerpo = armar_cuerpo_email(categoria, cm, ciclo, semana, dia, credentials_path=credentials_path)
    return emails, asunto, cuerpo


def _smtp_credenciales():
    try:
        import streamlit as st
        smtp = st.secrets["smtp"]
        return smtp["email"], smtp["app_password"]
    except Exception:
        import os
        email, clave = os.environ.get("SMTP_EMAIL"), os.environ.get("SMTP_APP_PASSWORD")
        if email and clave:
            return email, clave
        raise RuntimeError(
            "Faltan las credenciales SMTP: st.secrets['smtp'] o las variables "
            "de entorno SMTP_EMAIL / SMTP_APP_PASSWORD"
        )


def enviar_correo(destinatarios, asunto, cuerpo):
    """Envia un correo por SMTP (Gmail, con contraseña de aplicación) a la
    lista de destinatarios, todos juntos en 'To'."""
    if not destinatarios:
        raise ValueError("No hay destinatarios para este envío")
    remitente, clave = _smtp_credenciales()
    msg = MIMEMultipart()
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = ", ".join(destinatarios)
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(remitente, clave)
        server.sendmail(remitente, destinatarios, msg.as_string())


def leer_estado(credentials_path="credenciales.json"):
    """Devuelve {"cm":1, "ciclo":2, "semana":1, "dia":2} = ultimo Dia
    confirmado como enviado a las categorias de CATEGORIAS_AUTOMATICO."""
    client = _get_client(credentials_path)
    ws = client.open_by_key(DESTINATARIOS_FILE_ID).worksheet(ESTADO_TAB)
    fila = ws.get_all_values()[1]
    return {"cm": int(fila[0]), "ciclo": int(fila[1]), "semana": int(fila[2]), "dia": int(fila[3])}


def actualizar_estado(cm, ciclo, semana, dia, credentials_path="credenciales.json"):
    client = _get_client(credentials_path)
    ws = client.open_by_key(DESTINATARIOS_FILE_ID).worksheet(ESTADO_TAB)
    ws.update("A2", [[cm, ciclo, semana, dia]], value_input_option="RAW")


def _avanzar_semana(cm, ciclo, semana):
    """Primer Dia de la proxima semana (rotando Ciclo/CM si corresponde)."""
    if semana < MAX_SEMANAS_POR_CICLO:
        return cm, ciclo, semana + 1
    if ciclo < MAX_CICLOS_POR_CM:
        return cm, ciclo + 1, 1
    if cm < MAX_CM:
        return cm + 1, 1, 1
    raise ValueError("Temporada completa: no hay mas CM/Ciclo/Semana para avanzar")


def calcular_siguiente_envio(dia_semana, estado):
    """dia_semana: 'VIERNES'/'MARTES'/'JUEVES'/etc. estado: el dict de
    leer_estado(). Devuelve (cm, ciclo, semana, dia) a enviar, o None si
    ese dia de la semana no corresponde ningun envio (segun la regla de
    negocio ya validada) o si ya se envio y no hay nada nuevo que hacer."""
    cm, ciclo, semana, ultimo_dia = estado["cm"], estado["ciclo"], estado["semana"], estado["dia"]
    if dia_semana == "VIERNES":
        if ultimo_dia < 2:
            return None  # la semana anterior no se completo, no avanzar solo
        cm2, ciclo2, semana2 = _avanzar_semana(cm, ciclo, semana)
        return (cm2, ciclo2, semana2, 1)
    if dia_semana == "MARTES":
        if ultimo_dia != 1:
            return None  # ya se mando el Dia2 de esta semana, o el Dia1 no salio
        return (cm, ciclo, semana, 2)
    if dia_semana == "JUEVES":
        if ultimo_dia != 2:
            return None  # el Dia2 de esta semana todavia no salio, o el Dia3 ya salio
        return (cm, ciclo, semana, 3)  # aplica solo a CATEGORIAS_DIA3, no a Escoleta/Prebenjamin
    return None  # Lunes/Miercoles/Sabado/Domingo: nunca corresponde nada
