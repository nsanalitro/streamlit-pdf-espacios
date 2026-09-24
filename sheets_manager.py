"""Conexion a Google Sheets (service account) y parseo determinista de la
hoja MICROCICLOS a un diccionario limpio por horario, sin intervencion de un LLM."""

from datetime import date

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

MICROCICLOS_FILE_ID = "1QDRC6rt97EgsNAXuy0yjgg120K1U60UVI4nfTzXkRd8"
FUERZA_FILE_ID = "1o8gDig9JGKBkaTlNvPGyLyR1Nx4tF26FkM-Iw9p3Xvw"
GYM_FILE_ID = "15eaPdFjKCup40eiJJS4-GVbKcLJASqdojFQDaREH3jI"

DIAS = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES"]
DAY_BLOCK_WIDTH = 9
DATE_COL = {dia: 2 + (i + 1) * DAY_BLOCK_WIDTH - 1 for i, dia in enumerate(DIAS)}
GYM_HORARIO_MAP = {"16": "16:00", "18": "17:30", "19": "19:00", "20": "20:00"}


def _get_client(credentials_path="credenciales.json"):
    # En Streamlit Cloud las credenciales viven en st.secrets (nunca se sube
    # credenciales.json al repo); en local se usa el archivo tal cual.
    try:
        import streamlit as st
        info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _fetch_rows(client, file_id):
    return client.open_by_key(file_id).sheet1.get_all_values()


def _cell(row, idx):
    return row[idx] if idx < len(row) else ""


def _find_microciclo_block(rows, microciclo_num):
    starts = [i for i, r in enumerate(rows) if r and r[0].strip().startswith("MICROCICLO ")]
    target = f"MICROCICLO {microciclo_num}"
    for pos, start in enumerate(starts):
        if rows[start][0].strip() == target:
            end = starts[pos + 1] if pos + 1 < len(starts) else len(rows)
            return start, end
    raise ValueError(f"No se encontro el bloque '{target}' en la hoja MICROCICLOS")


def _day_col_start(dia):
    return 2 + DIAS.index(dia) * DAY_BLOCK_WIDTH


def _extract_day_slice(row, dia):
    start = _day_col_start(dia)
    return [_cell(row, start + i) for i in range(DAY_BLOCK_WIDTH)]


def _markers_from_slice(slice_):
    # El numero de posicion puede estar en cualquier lugar fisico de la fila;
    # se agrupa siempre por el numero explicito, nunca por orden secuencial
    # (leer un valor por posicion secuencial fue la causa de un error real).
    markers, jaula = {}, None
    i, n = 0, len(slice_)
    while i < n:
        tok = slice_[i]
        if tok.isdigit():
            val = slice_[i + 1] if i + 1 < n else ""
            if val:
                markers[int(tok)] = val
            i += 2
        elif tok:
            jaula = tok
            i += 1
        else:
            i += 1
    return markers, jaula


def _parse_dia(rows, start, end, dia):
    # Cada franja horaria abarca varias filas fisicas (datos + filas 100%
    # vacias de separacion visual, sin celdas combinadas). No hace falta
    # forward-fill: se acumulan los pares numero->valor de todas las filas
    # hasta que aparece el proximo HORARIO no vacio.
    horario_actual = None
    fila_en_franja = 0
    resultado = {}
    for i in range(start + 2, end):
        row = rows[i] if i < len(rows) else []
        if len(row) < 2:
            continue
        horario_tok = _cell(row, 1).strip()
        if horario_tok:
            horario_actual = horario_tok
            fila_en_franja = 0
        if horario_actual is None:
            continue
        slice_ = _extract_day_slice(row, dia)
        markers, jaula = _markers_from_slice(slice_)
        franja = resultado.setdefault(horario_actual, {"posiciones": {}, "jaula": [None, None]})
        franja["posiciones"].update(markers)
        if jaula and fila_en_franja < 2:
            franja["jaula"][fila_en_franja] = jaula
        fila_en_franja += 1
    return resultado


def _resolver_fecha(header, dia, hoy=None):
    # El Sheet solo guarda el dia del mes (sin mes/anio), asi que se ancla
    # al mes/anio real mas cercano a hoy para el LUNES del bloque, y se
    # detecta un cruce de mes dentro de la semana si algun dia de la
    # secuencia LUNES->VIERNES es menor al anterior (ej. 29,30,1,2,3).
    hoy = hoy or date.today()
    dias_semana = [int(_cell(header, DATE_COL[d])) for d in DIAS]

    mes, anio, mejor_dist = None, None, None
    for delta in (-1, 0, 1):
        m, a = hoy.month + delta, hoy.year
        if m == 0:
            m, a = 12, a - 1
        elif m == 13:
            m, a = 1, a + 1
        try:
            candidato = date(a, m, dias_semana[0])
        except ValueError:
            continue
        dist = abs((candidato - hoy).days)
        if mejor_dist is None or dist < mejor_dist:
            mes, anio, mejor_dist = m, a, dist

    anterior = None
    for i, d in enumerate(dias_semana):
        if anterior is not None and d < anterior:
            mes += 1
            if mes == 13:
                mes, anio = 1, anio + 1
        if DIAS[i] == dia:
            return date(anio, mes, d)
        anterior = d
    raise ValueError(f"dia invalido: {dia!r}")


def get_microciclo_dia(microciclo_num, dia, credentials_path="credenciales.json"):
    """Devuelve {"fecha": "23", "franjas": {"17:30": {"posiciones": {1: "12A", ..., 8: None}, "jaula": [v1, v2]}, ...}}.
    Posiciones 1-4 = Campo 1, 5-8 = Campo 2. Franjas totalmente vacias (sin
    ninguna posicion ni jaula) no se incluyen."""
    if dia not in DIAS:
        raise ValueError(f"dia invalido: {dia!r} (debe ser uno de {DIAS})")
    client = _get_client(credentials_path)
    rows = _fetch_rows(client, MICROCICLOS_FILE_ID)
    start, end = _find_microciclo_block(rows, microciclo_num)
    fecha = _cell(rows[start], DATE_COL[dia])
    fecha_str = _resolver_fecha(rows[start], dia).strftime("%d-%m-%y")
    franjas_raw = _parse_dia(rows, start, end, dia)
    franjas = {}
    for horario, datos in franjas_raw.items():
        posiciones = {p: datos["posiciones"].get(p) for p in range(1, 9)}
        if any(posiciones.values()) or any(datos["jaula"]):
            franjas[horario] = {"posiciones": posiciones, "jaula": datos["jaula"]}
    return {"fecha": fecha, "fecha_str": fecha_str, "franjas": franjas}


def list_microciclos(credentials_path="credenciales.json"):
    """Numeros de MICROCICLO disponibles en la hoja, para poblar el selector."""
    client = _get_client(credentials_path)
    rows = _fetch_rows(client, MICROCICLOS_FILE_ID)
    disponibles = []
    for r in rows:
        if r and r[0].strip().startswith("MICROCICLO "):
            try:
                disponibles.append(int(r[0].strip().split()[1]))
            except (IndexError, ValueError):
                continue
    return sorted(set(disponibles))


def get_fuerza_dia(microciclo_num, dia, credentials_path="credenciales.json"):
    """Devuelve {"17:30": {9: "14B", 10: "CBF", 11: None, 12: "16B", 13: "CAF", 14: None}, ...}.
    Mismo layout de bloques que MICROCICLOS (mismo find/day-slice), pero las
    posiciones son 9-14 (bandas de fuerza) en vez de 1-8. Si el microciclo
    todavia no esta cargado en esta hoja (semana nueva sin cargar), no es un
    error: se devuelve {} en vez de propagar la excepcion."""
    if dia not in DIAS:
        raise ValueError(f"dia invalido: {dia!r} (debe ser uno de {DIAS})")
    client = _get_client(credentials_path)
    rows = _fetch_rows(client, FUERZA_FILE_ID)
    try:
        start, end = _find_microciclo_block(rows, microciclo_num)
    except ValueError:
        return {}
    franjas_raw = _parse_dia(rows, start, end, dia)
    franjas = {}
    for horario, datos in franjas_raw.items():
        posiciones = {p: datos["posiciones"].get(p) for p in (9, 10, 11, 12, 13, 14)}
        if any(posiciones.values()):
            franjas[horario] = posiciones
    return franjas


def _parse_gym_dia(rows, start, end, dia):
    # Estructura plana: 1 fila = 1 horario + su valor, sin filas para
    # acumular ni celdas combinadas. Las filas separadoras (sin HORARIO)
    # se saltean solas al no aportar nada.
    col = 2 + DIAS.index(dia) * 2
    resultado = {}
    for i in range(start + 2, end):
        row = rows[i] if i < len(rows) else []
        horario_tok = _cell(row, 1).strip()
        if not horario_tok:
            continue
        valor = _cell(row, col).strip()
        if valor:
            resultado[horario_tok] = valor
    return resultado


def get_gym_dia(microciclo_num, dia, credentials_path="credenciales.json"):
    """Devuelve {"17:30": "13A", "19:00": "16A", ...} (solo horarios con dato).
    Igual que fuerza, un microciclo no cargado todavia devuelve {}."""
    if dia not in DIAS:
        raise ValueError(f"dia invalido: {dia!r} (debe ser uno de {DIAS})")
    client = _get_client(credentials_path)
    rows = _fetch_rows(client, GYM_FILE_ID)
    try:
        start, end = _find_microciclo_block(rows, microciclo_num)
    except ValueError:
        return {}
    raw = _parse_gym_dia(rows, start, end, dia)
    return {GYM_HORARIO_MAP.get(h, h): v for h, v in raw.items()}


def get_dia_completo(microciclo_num, dia, credentials_path="credenciales.json"):
    """Diccionario unico por horario, combinando las 3 hojas:
    {"fecha": "23", "franjas": {"17:30": {"posiciones": {1..14: val|None},
    "jaula": [v1, v2], "gym": val|None}, ...}}."""
    base = get_microciclo_dia(microciclo_num, dia, credentials_path)
    fuerza = get_fuerza_dia(microciclo_num, dia, credentials_path)
    gym = get_gym_dia(microciclo_num, dia, credentials_path)
    franjas = {}
    for horario in set(base["franjas"]) | set(fuerza) | set(gym):
        campo = base["franjas"].get(horario, {"posiciones": {}, "jaula": [None, None]})
        posiciones = {p: campo["posiciones"].get(p) for p in range(1, 9)}
        posiciones.update({p: fuerza.get(horario, {}).get(p) for p in (9, 10, 11, 12, 13, 14)})
        franjas[horario] = {
            "posiciones": posiciones,
            "jaula": campo["jaula"],
            "gym": gym.get(horario),
        }
    return {"fecha": base["fecha"], "fecha_str": base["fecha_str"], "franjas": franjas}
