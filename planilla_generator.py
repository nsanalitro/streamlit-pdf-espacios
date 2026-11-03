"""Planilla de impresion del dia: hojas A4 verticales con 2 categorias por hoja, cada una con
el esqueleto horario y la imagen inicial (primer cuadro del video) de sus ejercicios.
Todo determinista: textos del Sheet de planificacion, esqueletos de emails_manager e
imagenes de los videos de Drive; sin LLM."""

import io
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from difflib import SequenceMatcher
from xml.sax.saxutils import escape

from google.auth.transport.requests import AuthorizedSession
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

import emails_manager as em

AZUL_HEADER = colors.HexColor("#0B3D91")
BORDE = colors.HexColor("#8C8C8C")
GRIS_TEXTO = colors.HexColor("#555555")
COLOR_SEGMENTO = {
    "T0": colors.HexColor("#F6D9B8"),
    "T1": colors.HexColor("#CFE3F7"),
    "T2": colors.HexColor("#C9E7D0"),
    "T3": colors.HexColor("#F7E3A6"),
    "otro": colors.HexColor("#E8E8E8"),
}
COLOR_TAREA = {"1": colors.HexColor("#2F6DB5"), "2": colors.HexColor("#3E8E55"), "3": colors.HexColor("#B8860B")}

DIAS_NOMBRE = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES"]
_DIA_ABREV = {"lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4}
ORDEN_CATEGORIAS = [
    "Escoleta", "Prebenjamín", "Benjamín", "Alevín", "Infantil", "Cadete",
    "Infantil Femenino", "Cadete Femenino", "Juvenil Femenino",
]
# Dias de entrenamiento por defecto de cada categoria (0=lunes). Un equipo con otros dias
# los declara en la columna F ("Días entrena") de la hoja Entrenadores.
DIAS_ENTRENAMIENTO = {
    "Escoleta": [0, 2],
    "Prebenjamín": [1, 3],
    "Benjamín": [1, 3, 4],
    "Alevín": [0, 2, 4],
    "Infantil": [0, 2, 4],
    "Cadete": [0, 2, 4],
    "Infantil Femenino": [0, 2, 4],
    "Cadete Femenino": [0, 2, 4],
    "Juvenil Femenino": [0, 2, 4],
}
ABREVIATURAS = {"Tarea 0 (motricidad)": "T0", "Transición": "Trans.", "Explicación": "Explic."}
TIPO_TAREA = {"1": "ANALÍTICA", "2": "FACILITADORA", "3": "GLOBAL"}


def _pdf_text(texto):
    """Normaliza y deja solo caracteres que Helvetica (cp1252) dibuja bien."""
    texto = unicodedata.normalize("NFKC", texto or "")
    for origen, destino in (("→", "->"), ("≥", ">="), ("≤", "<="), ("×", "x")):
        texto = texto.replace(origen, destino)
    return texto.encode("cp1252", "replace").decode("cp1252")


def _separar_dif(texto):
    """(texto sin anotaciones, [anotaciones]) para las '(Dif V1: ...)' de CM2/CM3 (parentesis balanceados)."""
    notas = []
    while True:
        i = texto.find("(Dif")
        if i < 0:
            return texto.strip(), notas
        nivel, j = 0, i
        while j < len(texto):
            nivel += texto[j] == "("
            nivel -= texto[j] == ")"
            j += 1
            if nivel == 0:
                break
        notas.append(texto[i + 1 : j - 1].strip())
        texto = (texto[:i] + texto[j:]).strip()


# ----------------------------------------------------------------------------- equipos / paginas
def leer_filas_equipos(credentials_path="credenciales.json"):
    """Filas de la hoja Entrenadores (sin encabezado)."""
    return em._get_client(credentials_path).open_by_key(em.DESTINATARIOS_FILE_ID).sheet1.get_all_values()[1:]


def _parse_dias_semana(texto):
    dias = set()
    for tok in re.split(r"[,;/\s]+", unicodedata.normalize("NFKD", texto).lower()):
        tok = re.sub(r"[^a-z]", "", tok)[:3]
        if tok in _DIA_ABREV:
            dias.add(_DIA_ABREV[tok])
    if not dias:
        raise ValueError(f"Columna 'Días entrena' inválida en la hoja de entrenadores: '{texto}'")
    return sorted(dias)


def paginas_del_dia_semana(dia_semana, filas):
    """[{base, dia, cats, equipos}] de las categorias que entrenan ese dia (0=lunes).
    Cada fila de Entrenadores es un equipo: entrena en sus dias (columna F, o los de su
    categoria) y el N-esimo entrenamiento de la semana es el Dia N del plan; 'Solo días'
    (columna E) limita a que Dias aplica esa fila. Las femeninas comparten hoja con su
    categoria espejo (mismo contenido, esqueleto y videos)."""
    grupos = {}
    for f in filas:
        if len(f) < 3 or not f[0].strip() or not f[2].strip():
            continue
        cat_raw = f[0].strip()
        cat = em._categoria_base(cat_raw)
        if cat not in DIAS_ENTRENAMIENTO:
            continue
        solo = f[4].strip() if len(f) > 4 else ""
        entrena = f[5].strip() if len(f) > 5 else ""
        dias_sem = _parse_dias_semana(entrena) if entrena else DIAS_ENTRENAMIENTO[cat]
        if dia_semana not in dias_sem:
            continue
        dia = dias_sem.index(dia_semana) + 1
        if solo and dia not in {int(d) for d in re.findall(r"[123]", solo)}:
            continue
        base = em.CATEGORIA_ESPEJO.get(cat, cat)
        g = grupos.setdefault((base, dia), {"cats": [], "equipos": []})
        if cat not in g["cats"]:
            g["cats"].append(cat)
        m = re.search(r"\d.*$", cat_raw)
        if m and m.group() not in g["equipos"]:
            g["equipos"].append(m.group())
    paginas = []
    for base, dia in sorted(grupos, key=lambda k: (ORDEN_CATEGORIAS.index(k[0]), k[1])):
        g = grupos[(base, dia)]
        paginas.append({"base": base, "dia": dia, "cats": sorted(g["cats"], key=ORDEN_CATEGORIAS.index), "equipos": g["equipos"]})
    return paginas


# ----------------------------------------------------------------------------- imagenes de Drive
def _es_pasto(p):
    r, g, b = p
    return g > 80 and g > r + 25 and g > b + 20


def _quitar_franjas_oscuras(im):
    """Saca las filas casi negras que quedan arriba/abajo del recorte (el cuadro trae una barra oscura)."""
    w, h = im.size
    px = im.convert("L").load()
    def brillo(y):
        return sum(px[x, y] for x in range(0, w, 4)) / len(range(0, w, 4))
    arriba, abajo = 0, h
    while arriba < h * 0.15 and brillo(arriba) < 50:
        arriba += 1
    while abajo > h * 0.85 and brillo(abajo - 1) < 50:
        abajo -= 1
    return im.crop((0, arriba, w, abajo))


def _recortar_cancha(datos):
    """Recorta el cuadro del video a la cancha (saca encabezado y pie de FootballGPT).
    Si no encuentra la cancha devuelve el cuadro completo."""
    im = Image.open(io.BytesIO(datos)).convert("RGB")
    w, h = im.size
    f = 4
    chico = im.resize((max(1, w // f), max(1, h // f)))
    cw, ch = chico.size
    px = chico.load()
    filas = [sum(1 for x in range(cw) if _es_pasto(px[x, y])) for y in range(ch)]
    ys = [y for y, n in enumerate(filas) if n > cw * 0.4]
    xs = []
    if ys:
        cols = [sum(1 for y in range(ys[0], ys[-1] + 1) if _es_pasto(px[x, y])) for x in range(cw)]
        xs = [x for x, n in enumerate(cols) if n > (ys[-1] - ys[0] + 1) * 0.4]
    if ys and xs:
        m = 2
        im = im.crop((max(0, xs[0] * f - m), max(0, ys[0] * f - m), min(w, (xs[-1] + 1) * f + m), min(h, (ys[-1] + 1) * f + m)))
        im = _quitar_franjas_oscuras(im)
    salida = io.BytesIO()
    im.save(salida, "JPEG", quality=92)
    return salida.getvalue()


def _datos_video(file_id, creds):
    """(titulo, bytes de la imagen inicial recortada) de un video de Drive; (None, None) si falla."""
    try:
        drive = em._get_drive_service(creds=creds)
        meta = drive.files().get(fileId=file_id, fields="name,thumbnailLink").execute()
        titulo = unicodedata.normalize("NFKC", meta.get("name", ""))
        titulo = titulo.split(" — ", 1)[1] if " — " in titulo else titulo
        titulo = re.sub(r"\.(mp4|m4v|mov)$", "", titulo, flags=re.I).strip()
        link = meta.get("thumbnailLink")
        if not link:
            return titulo, None
        r = AuthorizedSession(creds).get(re.sub(r"=s\d+$", "=s1200", link), timeout=30)
        return titulo, (_recortar_cancha(r.content) if r.status_code == 200 else None)
    except Exception:
        return None, None


# ----------------------------------------------------------------------------- dibujo
def _repite_titulo(titulo, texto):
    """True si la descripcion no agrega nada al titulo (el titulo del video suele ser su primera frase)."""
    def norm(s):
        return re.sub(r"[^\w ]", "", unicodedata.normalize("NFKC", s or "").lower()).strip()
    t, d = norm(titulo), norm(texto)
    return bool(t) and len(d) <= len(t) + 12 and SequenceMatcher(None, t, d[: len(t) + 5]).ratio() >= 0.9


def _parrafo(c, texto, x, y_top, w, h_max, size_max=9, size_min=6.5, bold=False, color=colors.black):
    """Dibuja texto ajustando el tamano para que entre en h_max; devuelve el alto usado."""
    texto = escape(_pdf_text(texto)).replace("\n", "<br/>")
    size = size_max
    while True:
        estilo = ParagraphStyle(
            "p", fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size * 1.2, textColor=color
        )
        p = Paragraph(texto, estilo)
        _, h = p.wrap(w, 10000)
        if h <= h_max or size <= size_min:
            if h > h_max:
                partes = p.split(w, h_max)
                if partes:
                    p, h = partes[0], partes[0].wrap(w, h_max)[1]
            p.drawOn(c, x, y_top - h)
            return h
        size -= 0.5


def _segmentos(clave):
    segs = []
    for nombre, dur in em.ESQUELETOS[clave]:
        minutos = int(re.match(r"\d+", dur).group())
        detalle = re.search(r"\((.*)\)", dur)
        segs.append((nombre, minutos, detalle.group(1) if detalle else None))
    return segs


def _dibujar_esqueleto(c, x, y_top, w, clave):
    segs = _segmentos(clave)
    total = sum(m for _, m, _ in segs)
    c.setFillColor(AZUL_HEADER)
    c.setFont("Helvetica-Bold", 8)
    titulo = em.ESQUELETO_TITULO[clave].rstrip(":")
    c.drawString(x, y_top - 2.8 * mm, titulo)
    detalle = next((d for _, _, d in segs if d), None)
    if detalle:
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica", 7)
        c.drawString(x + stringWidth(titulo, "Helvetica-Bold", 8) + 2.5 * mm, y_top - 2.8 * mm, f"T2 = {_pdf_text(detalle)}")
    bar_h = 8 * mm
    bar_y = y_top - 4 * mm - bar_h
    px, acum = x, 0
    for nombre, minutos, _ in segs:
        sw = w * minutos / total
        clave_color = nombre if nombre in ("T1", "T2", "T3") else ("T0" if nombre.startswith("Tarea 0") else "otro")
        c.setFillColor(COLOR_SEGMENTO[clave_color])
        c.setStrokeColor(BORDE)
        c.setLineWidth(0.5)
        c.rect(px, bar_y, sw, bar_h, fill=1, stroke=1)
        etiqueta = ABREVIATURAS.get(nombre, nombre)
        size = 7.5 if clave_color != "otro" else 6.5
        while size > 4.5 and stringWidth(etiqueta, "Helvetica-Bold", size) > sw - 0.8 * mm:
            size -= 0.5
        c.setFillColor(colors.black)
        if stringWidth(etiqueta, "Helvetica-Bold", size) <= sw - 0.8 * mm:
            c.setFont("Helvetica-Bold", size)
            c.drawCentredString(px + sw / 2, bar_y + bar_h - 3.6 * mm, etiqueta)
        c.setFont("Helvetica", 6.5)
        minutos_txt = f"{minutos}'"
        if stringWidth(minutos_txt, "Helvetica", 6.5) <= sw - 0.4 * mm:
            c.drawCentredString(px + sw / 2, bar_y + 1.5 * mm, minutos_txt)
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica", 5.5)
        c.drawString(px + 0.3 * mm, bar_y - 2.4 * mm, f"{acum}'")
        px += sw
        acum += minutos
    c.drawRightString(x + w - 0.3 * mm, bar_y - 2.4 * mm, f"{total}'")
    return 4 * mm + bar_h + 3.5 * mm


def _dibujar_bloque(c, x, y_top, w, h, pagina, clave_esq, t0, ejercicios):
    """Una categoria dentro del rectangulo (x, y_top, w, h)."""
    es_f11 = pagina["base"] in em.CATEGORIAS_F11
    y = y_top
    # banda con titulo, Dia y equipos
    c.setFillColor(AZUL_HEADER)
    c.rect(x, y - 8 * mm, w, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11.5)
    titulo = _pdf_text(" + ".join(pagina["cats"]).upper())
    c.drawString(x + 2.5 * mm, y - 5.6 * mm, titulo)
    derecha = f"Día {pagina['dia']}" + (f"  ·  Equipos: {' · '.join(pagina['equipos'])}" if pagina["equipos"] else "")
    c.setFont("Helvetica", 8)
    c.drawRightString(x + w - 2.5 * mm, y - 5.4 * mm, _pdf_text(derecha))
    y -= 8 * mm + 2.5 * mm
    y -= _dibujar_esqueleto(c, x, y, w, clave_esq)

    if t0:
        linea = _pdf_text(t0.split("\n")[0].strip())
        c.setFillColor(COLOR_SEGMENTO["T0"])
        c.setStrokeColor(BORDE)
        c.setLineWidth(0.5)
        c.rect(x, y - 5.5 * mm, w, 5.5 * mm, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 2 * mm, y - 3.9 * mm, f"TAREA 0 - {linea}")
        y -= 5.5 * mm + 2.5 * mm
    else:
        y -= 1 * mm

    # notas "Dif" (CM2/CM3) al pie del bloque: se calcula su alto primero para reservarlo
    notas = [(n, nota) for n in ("1", "2", "3") for nota in ejercicios.get(n, {}).get("dif", [])]
    dif_h = 0
    if notas:
        dif_txt = "<br/>".join(f"<b>T{n}</b> · {escape(_pdf_text(nota))}" for n, nota in notas)
        size_dif = 7
        while True:
            estilo = ParagraphStyle("dif", fontName="Helvetica", fontSize=size_dif, leading=size_dif * 1.2, textColor=colors.HexColor("#333333"))
            p_dif = Paragraph(dif_txt, estilo)
            _, alto_txt = p_dif.wrap(w - 4 * mm, 10000)
            if alto_txt <= 34 * mm or size_dif <= 5.5:
                break
            size_dif -= 0.5
        dif_h = alto_txt + 7 * mm
    y_pie = y_top - h  # borde inferior del bloque
    if notas:
        c.setFillColor(colors.HexColor("#FFF8DC"))
        c.setStrokeColor(BORDE)
        c.setLineWidth(0.5)
        c.rect(x, y_pie, w, dif_h, fill=1, stroke=1)
        c.setFillColor(AZUL_HEADER)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(x + 2 * mm, y_pie + dif_h - 3.2 * mm, "DIFERENCIAS RESPECTO A LA VUELTA ANTERIOR")
        p_dif.drawOn(c, x + 2 * mm, y_pie + 1.5 * mm)

    gap = 4 * mm
    col_w = (w - 2 * gap) / 3
    segs = {n: m for n, m, _ in _segmentos(clave_esq)}
    resto = y - (y_pie + dif_h + (2 * mm if notas else 0))  # alto disponible para las 3 columnas
    texto_h = 30 * mm
    img_h = max(28 * mm, resto - 6.5 * mm - 2.5 * mm - texto_h)
    for i, n in enumerate(("1", "2", "3")):
        cx = x + i * (col_w + gap)
        datos = ejercicios.get(n, {})
        c.setFillColor(COLOR_TAREA[n])
        c.rect(cx, y - 5 * mm, col_w, 5 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        rotulo = f"T{n}" if es_f11 else f"T{n} - {TIPO_TAREA[n]}"
        c.drawString(cx + 1.5 * mm, y - 3.6 * mm, rotulo)
        c.drawRightString(cx + col_w - 1.5 * mm, y - 3.6 * mm, f"{segs.get(f'T{n}', '')}'")
        top_img = y - 5 * mm - 1.5 * mm
        c.setStrokeColor(BORDE)
        c.setLineWidth(0.6)
        if datos.get("img"):
            lector = ImageReader(io.BytesIO(datos["img"]))
            iw, ih = lector.getSize()
            esc = min(col_w / iw, img_h / ih)
            dw, dh = iw * esc, ih * esc
            c.drawImage(lector, cx + (col_w - dw) / 2, top_img - dh, dw, dh)
            c.rect(cx + (col_w - dw) / 2, top_img - dh, dw, dh, fill=0, stroke=1)
            usado = dh
        else:
            usado = min(img_h, col_w * 0.7)
            c.setDash(3, 2)
            c.rect(cx, top_img - usado, col_w, usado, fill=0, stroke=1)
            c.setDash()
            c.setFillColor(GRIS_TEXTO)
            c.setFont("Helvetica", 8)
            c.drawCentredString(cx + col_w / 2, top_img - usado / 2, "Video pendiente en Drive")
        yy = top_img - usado - 2 * mm
        limite = y_pie + dif_h + (2 * mm if notas else 0)  # el texto no pisa las notas Dif
        if datos.get("titulo"):
            yy -= _parrafo(c, datos["titulo"], cx, yy, col_w, 12 * mm, size_max=9.5, size_min=7.5, bold=True) + 1.5 * mm
        texto = datos.get("texto") or ""
        if texto and not _repite_titulo(datos.get("titulo"), texto):
            _parrafo(c, texto, cx, yy, col_w, max(8 * mm, yy - limite), size_max=9, size_min=6, color=colors.HexColor("#222222"))


def semana_sugerida(historial, dia):
    """(cm, ciclo, semana) del ultimo correo enviado para ese Dia del plan (el correo de un Dia sale
    el dia habil anterior a su primera sesion, asi que es la semana que se esta entrenando).
    Sin envios registrados: (1, 1, 1)."""
    envios = [h for h in historial if h["clave"][3] == dia and h.get("tipo") != "videos"]
    if not envios:
        return 1, 1, 1
    cm, ciclo, semana, _ = max(envios, key=lambda h: h["fecha"])["clave"]
    return cm, ciclo, semana


def generar_planilla_pdf(
    dia_semana, cm, ciclo, semana, salida, fecha=None, filas=None, plan=None,
    credentials_path="credenciales.json", progreso=None,
):
    """Genera el PDF de impresion del dia (dia_semana: 0=lunes ... 4=viernes), con 2 categorias por hoja.
    'salida' puede ser una ruta o un archivo en memoria (io.BytesIO). 'progreso(fraccion, texto)' se llama
    a medida que avanza. Devuelve {"hojas": n, "faltantes": [(titulo, [detalle, ...])]} con los videos o
    textos que no se encontraron (la hoja sale igual, con un recuadro en ese hueco)."""
    def avisar(frac, texto):
        if progreso:
            progreso(min(frac, 1.0), texto)

    filas = filas if filas is not None else leer_filas_equipos(credentials_path)
    paginas = paginas_del_dia_semana(dia_semana, filas)
    if not paginas:
        raise ValueError("Ese dia de la semana no entrena ninguna categoria")
    avisar(0.02, "Leyendo la planificación...")
    plan = plan or em.get_planificacion_completa(credentials_path)
    creds = em._get_credentials(credentials_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids_por_pagina = []
        for k, ids in enumerate(pool.map(
            lambda p: em._buscar_archivos_video_dia(p["base"], cm, ciclo, semana, p["dia"], credentials_path), paginas
        ), start=1):
            ids_por_pagina.append(ids)
            avisar(0.05 + 0.25 * k / len(paginas), f"Buscando videos en Drive... {k}/{len(paginas)}")
        pares = [(i, n, fid) for i, ids in enumerate(ids_por_pagina) for n, fid in ids.items()]
        resultados = []
        for k, r in enumerate(pool.map(lambda p: _datos_video(p[2], creds), pares), start=1):
            resultados.append(r)
            avisar(0.30 + 0.60 * k / max(len(pares), 1), f"Bajando imágenes de los diagramas... {k}/{len(pares)}")
    video = {(i, n): r for (i, n, _), r in zip(pares, resultados)}

    faltantes = []
    for i, p in enumerate(paginas):
        falta = []
        for n in ("1", "2", "3"):
            if not video.get((i, n), (None, None))[1]:
                falta.append(f"T{n}: video")
            if not em._es_real(plan.get((p["base"], str(cm), str(ciclo), str(semana), str(p["dia"]), f"T{n}")) or ""):
                falta.append(f"T{n}: ejercicio")
        if falta:
            faltantes.append((" + ".join(p["cats"]) + f" (Día {p['dia']})", falta))

    page_w, page_h = A4
    c = pdfcanvas.Canvas(salida, pagesize=A4)
    margen = 10 * mm
    ancho = page_w - 2 * margen
    nombre_dia = DIAS_NOMBRE[dia_semana]
    texto_dia = f"{nombre_dia} {fecha.strftime('%d/%m/%Y')}" if fecha else nombre_dia
    cabecera, pie = 10 * mm, 8 * mm
    util = page_h - cabecera - pie - 2 * margen / 2
    alto_bloque = (util - 5 * mm) / 2
    for inicio in range(0, len(paginas), 2):
        c.setFillColor(AZUL_HEADER)
        c.rect(0, page_h - cabecera, page_w, cabecera, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margen, page_h - 6.8 * mm, _pdf_text(texto_dia))
        c.setFont("Helvetica", 9)
        c.drawRightString(page_w - margen, page_h - 6.6 * mm, f"Ciclo Matriz {cm} · Ciclo {ciclo} · Semana {semana}")
        for k, i in enumerate(range(inicio, min(inicio + 2, len(paginas)))):
            p = paginas[i]
            ejercicios = {}
            for n in ("1", "2", "3"):
                titulo, img = video.get((i, n), (None, None))
                crudo = plan.get((p["base"], str(cm), str(ciclo), str(semana), str(p["dia"]), f"T{n}")) or ""
                texto, dif = _separar_dif(crudo if em._es_real(crudo) else "")
                ejercicios[n] = {"titulo": titulo, "img": img, "texto": texto or None, "dif": dif}
            t0 = plan.get((p["base"], str(cm), str(ciclo), str(semana), str(p["dia"]), "T0"))
            y_top = page_h - cabecera - margen / 2 - k * (alto_bloque + 5 * mm)
            _dibujar_bloque(
                c, margen, y_top, ancho, alto_bloque, p, em.CATEGORIA_ESQUELETO[p["cats"][0]],
                t0 if em._es_real(t0 or "") else None, ejercicios,
            )
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica", 6.5)
        c.drawString(margen, 5 * mm, "AFA INTERNACIONAL - UCF SANTA PERPETUA")
        c.drawRightString(page_w - margen, 5 * mm, f"Generado el {date.today().strftime('%d/%m/%Y')}")
        c.showPage()
        avisar(0.90 + 0.09 * min(inicio + 2, len(paginas)) / len(paginas), "Armando el PDF...")
    c.save()
    avisar(1.0, "Listo")
    return {"hojas": -(-len(paginas) // 2), "faltantes": faltantes}
