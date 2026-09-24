"""Generador determinista del PDF de espacios de entrenamiento (Jaula,
Campo 1, Campo 2) a partir de los datos que entrega sheets_manager.
Motor de dibujo adaptado de la skill 'espacios-generar-pdf' (ya probada
contra datos reales)."""

import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas

import sheets_manager as sm

AZUL_HEADER = colors.HexColor("#0B3D91")
AZUL_ZONA = colors.HexColor("#7C96B8")
GRIS_ZONA = colors.HexColor("#D9D9D9")
NARANJA = colors.HexColor("#F2994A")
VACIO = colors.HexColor("#F2F2F2")
BORDE = colors.HexColor("#8C8C8C")
TEST_FILL = colors.HexColor("#FFE7A3")
FUERZA_VACIO = colors.HexColor("#FFF6DC")


def _wrap_lines(texto, max_w, font="Helvetica-Bold", start=26, min_size=14, max_lines=2):
    palabras = texto.split(" ")
    mejor = None
    for size in range(start, min_size - 1, -1):
        lineas, actual = [], ""
        for p in palabras:
            prueba = (actual + " " + p) if actual else p
            if stringWidth(prueba, font, size) <= max_w:
                actual = prueba
            else:
                if actual:
                    lineas.append(actual)
                actual = p
        if actual:
            lineas.append(actual)
        mejor = (lineas, size)
        if len(lineas) <= max_lines:
            return lineas, size
    return mejor


def celda(valor=None, tipo="campo"):
    if tipo == "vacio":
        return {"tipo": "vacio", "valor": ""}
    return {"tipo": "campo", "valor": valor}


def shape_campo(posiciones, base):
    """base=0 -> Campo 1 (posiciones 1-4); base=4 -> Campo 2 (posiciones 5-8).
    Devuelve una lista de filas de celdas para draw_zone, aplicando la
    convencion: 1 valor=entera, 2=mitad arriba/abajo (el numero mas bajo
    va arriba), 4=cuadrantes, 3=mixto (un lado cuadrantes, el otro entera)."""
    p = [base + 1, base + 2, base + 3, base + 4]
    vals = {k: posiciones.get(k) for k in p if posiciones.get(k)}
    count = len(vals)
    if count == 0:
        return [[celda(tipo="vacio")]]
    if count == 1:
        return [[celda(list(vals.values())[0])]]
    if count == 4:
        return [[celda(vals[p[0]]), celda(vals[p[1]])], [celda(vals[p[2]]), celda(vals[p[3]])]]
    if count == 2:
        k1, k2 = sorted(vals.keys())
        return [[celda(vals[k1])], [celda(vals[k2])]]
    top_full = p[0] in vals and p[1] in vals
    bottom_full = p[2] in vals and p[3] in vals
    if bottom_full:
        entera = vals[p[0]] if p[0] in vals else vals[p[1]]
        return [[celda(entera)], [celda(vals[p[2]]), celda(vals[p[3]])]]
    if top_full:
        entera = vals[p[2]] if p[2] in vals else vals[p[3]]
        return [[celda(vals[p[0]]), celda(vals[p[1]])], [celda(entera)]]
    ordered = [celda(vals[k]) for k in sorted(vals.keys())]
    return [ordered[:2], ordered[2:]]


def shape_jaula(jaula):
    v1, v2 = jaula
    if v1 and v2:
        return [[celda(v1)], [celda(v2)]]
    if v1 or v2:
        return [[celda(v1 or v2)]]
    return [[celda(tipo="vacio")]]


def draw_zone(c, x, y, w, h, label, filas):
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(colors.black)
    c.drawCentredString(x + w / 2, y + h + 8 * mm, label)

    n_rows = len(filas)
    cell_h = h / n_rows
    for row, fila in enumerate(filas):
        n_cols = len(fila)
        cell_w = w / n_cols
        for col, cell in enumerate(fila):
            cx = x + col * cell_w
            cy = y + h - (row + 1) * cell_h

            valor_up = cell.get("valor", "").upper()
            es_test = cell["tipo"] == "campo" and "TEST" in valor_up
            es_intermitente = cell["tipo"] == "campo" and bool(re.search(r"INTERMITENTE|\bINT\b", valor_up))

            if cell["tipo"] == "vacio":
                fill = VACIO
            elif es_intermitente:
                fill = NARANJA
            elif es_test:
                fill = TEST_FILL
            else:
                fill = GRIS_ZONA if (row + col) % 2 == 0 else AZUL_ZONA

            c.setFillColor(fill)
            c.setStrokeColor(BORDE)
            c.setLineWidth(1)
            c.rect(cx + 1, cy + 1, cell_w - 2, cell_h - 2, fill=1, stroke=1)

            if cell["tipo"] == "vacio":
                continue

            c.setFillColor(colors.black)
            texto = cell["valor"]
            max_w = cell_w - 14
            if es_intermitente:
                lineas, fsize = _wrap_lines(texto, max_w, start=min(26, int(cell_h / 3.2)), min_size=14, max_lines=2)
                line_h = fsize * 1.25
                ty = cy + cell_h / 2 + (len(lineas) - 1) * line_h / 2 - fsize * 0.35
                c.setFont("Helvetica-Bold", fsize)
                for ln in lineas:
                    c.drawCentredString(cx + cell_w / 2, ty, ln)
                    ty -= line_h
            else:
                fsize = min(36, int(cell_h / 2.2))
                while stringWidth(texto, "Helvetica-Bold", fsize) > cell_w - 12 and fsize > 11:
                    fsize -= 1
                c.setFont("Helvetica-Bold", fsize)
                c.drawCentredString(cx + cell_w / 2, cy + cell_h / 2 - fsize * 0.35, texto)


def draw_fuerza_box(c, x, y, w, h, cell):
    ocupado = cell is not None and cell.get("valor")
    c.setFillColor(TEST_FILL if ocupado else FUERZA_VACIO)
    c.setStrokeColor(BORDE)
    c.setLineWidth(1)
    c.rect(x + 1, y + 1, w - 2, h - 2, fill=1, stroke=1)
    if ocupado:
        c.setFillColor(colors.black)
        texto = cell["valor"]
        fsize = 15
        while stringWidth(texto, "Helvetica-Bold", fsize) > w - 8 and fsize > 8:
            fsize -= 1
        c.setFont("Helvetica-Bold", fsize)
        c.drawCentredString(x + w / 2, y + h / 2 - fsize * 0.35, texto)


def draw_fuerza(c, x_campo1, x_campo2, w_campo, gap, top, band_h, grid_top, zone_h, fuerza):
    """9,10 = banda arriba de Campo 1; 12,13 = banda arriba de Campo 2;
    11,14 = par central, a la altura de medio campo, montado levemente
    encima del limite entre la fila de arriba y la de abajo de cada campo."""
    sub_w = w_campo / 2
    band_y = top - band_h
    draw_fuerza_box(c, x_campo1, band_y, sub_w, band_h, fuerza.get(9))
    draw_fuerza_box(c, x_campo1 + sub_w, band_y, sub_w, band_h, fuerza.get(10))
    draw_fuerza_box(c, x_campo2, band_y, sub_w, band_h, fuerza.get(12))
    draw_fuerza_box(c, x_campo2 + sub_w, band_y, sub_w, band_h, fuerza.get(13))

    mid_w = gap + 24 * mm
    mid_x = x_campo1 + w_campo - 12 * mm
    mid_h = 32 * mm
    fila_media_y = grid_top - zone_h / 2
    mid_y = fila_media_y - mid_h / 2
    c.saveState()
    c.setFillAlpha(0.82)
    draw_fuerza_box(c, mid_x, mid_y, mid_w / 2, mid_h, fuerza.get(11))
    draw_fuerza_box(c, mid_x + mid_w / 2, mid_y, mid_w / 2, mid_h, fuerza.get(14))
    c.restoreState()


def draw_gym_box(c, x, y, w, h, texto):
    c.setFillColor(colors.white)
    c.setStrokeColor(BORDE)
    c.setLineWidth(1)
    c.rect(x + 1, y + 1, w - 2, h - 2, fill=1, stroke=1)

    c.setFillColor(AZUL_HEADER)
    c.rect(x + 1, y + h - 11 * mm, w - 2, 11 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(x + w / 2, y + h - 8 * mm, "GYM")

    c.setFillColor(colors.black)
    if texto:
        lineas, fsize = _wrap_lines(texto, w - 10, start=16, min_size=10, max_lines=3)
        line_h = fsize * 1.2
        ty = y + (h - 11 * mm) / 2 + (len(lineas) - 1) * line_h / 2 - fsize * 0.35
        c.setFont("Helvetica-Bold", fsize)
        for ln in lineas:
            c.drawCentredString(x + w / 2, ty, ln)
            ty -= line_h
    else:
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#9A9A9A"))
        c.drawCentredString(x + w / 2, y + (h - 11 * mm) / 2 - 3, "—")


def draw_page(c, page_w, page_h, dia, horario, jaula_filas, campo1_filas, campo2_filas, fuerza, gym_texto):
    c.setFillColor(AZUL_HEADER)
    c.rect(0, page_h - 22 * mm, page_w, 22 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(12 * mm, page_h - 14 * mm, f"{dia.upper()}  {horario}")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(page_w - 12 * mm, page_h - 14 * mm, "AFA INTERNACIONAL - UCF SANTA PERPETUA")

    top = page_h - 40 * mm
    band_h = 15 * mm
    band_gap = 16 * mm
    reserva = band_h + band_gap
    zone_h = 138 * mm - reserva
    grid_top = top - reserva
    margin = 14 * mm
    gap = 8 * mm
    usable_w = page_w - 2 * margin - 2 * gap
    w_jaula = usable_w * 0.16
    w_campo = usable_w * 0.42

    x = margin
    jaula_h = zone_h / 2 - 4 * mm
    draw_zone(c, x, grid_top - jaula_h, w_jaula, jaula_h, "JAULA", jaula_filas)
    draw_gym_box(c, x, grid_top - zone_h, w_jaula, zone_h - jaula_h - 8 * mm, gym_texto)
    x += w_jaula + gap
    x_campo1 = x
    draw_zone(c, x, grid_top - zone_h, w_campo, zone_h, "CAMPO 1", campo1_filas)
    x += w_campo + gap
    x_campo2 = x
    draw_zone(c, x, grid_top - zone_h, w_campo, zone_h, "CAMPO 2", campo2_filas)

    draw_fuerza(c, x_campo1, x_campo2, w_campo, gap, top, band_h, grid_top, zone_h, fuerza)


def dibujar_desde_datos(data, dia, salida):
    """Dibuja el PDF a partir de un dict ya obtenido con sm.get_dia_completo().
    Separado de generar_pdf() para que un caller (ej. app.py) pueda mostrar
    progreso real entre el paso de sincronizar y el de dibujar."""
    page_w, page_h = landscape(A4)
    c = pdfcanvas.Canvas(salida, pagesize=landscape(A4))
    horarios = sorted(data["franjas"], key=lambda h: [int(x) for x in h.split(":")])
    for horario in horarios:
        franja = data["franjas"][horario]
        posiciones = franja["posiciones"]
        campo1 = shape_campo(posiciones, base=0)
        campo2 = shape_campo(posiciones, base=4)
        jaula = shape_jaula(franja["jaula"])
        fuerza = {p: (celda(posiciones[p]) if posiciones.get(p) else None) for p in (9, 10, 11, 12, 13, 14)}
        draw_page(c, page_w, page_h, dia, horario, jaula, campo1, campo2, fuerza, franja["gym"])
        c.showPage()
    c.save()
    return salida


def generar_pdf(microciclo_num, dia, salida, credentials_path="credenciales.json"):
    data = sm.get_dia_completo(microciclo_num, dia, credentials_path)
    return dibujar_desde_datos(data, dia, salida)
