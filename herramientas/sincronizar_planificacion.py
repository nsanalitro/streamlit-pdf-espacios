"""Sincroniza el texto de los Word de planificacion con la pestana Planificacion_Ejercicios del Sheet,
que es lo que lee la app (correos y planilla del dia).

    python herramientas/sincronizar_planificacion.py             -> simulacro: muestra que cambiaria
    python herramientas/sincronizar_planificacion.py --aplicar   -> respalda, escribe y verifica

Cubre T1/T2/T3 de Escoleta, Prebenjamin, Benjamin y Alevin, y Foco/T1/T2/T3 de Infantil y Cadete (si faltan
filas de esas dos categorias en el Sheet, las crea). No toca T0 ni Resumen. Respeta las celdas marcadas
"No se realiza". Requiere python-docx (uso local; la app online no lee Word)."""

import json
import os
import re
import sys
from datetime import datetime

import docx

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import emails_manager as em  # noqa: E402

CARPETA_WORD = r"C:\Users\nicol\Claude\Projects\Project A Futbol 7\ProyectoA_Futbol7\04_documentos_divididos"

# (categoria, CMs del Sheet que reciben ese texto, Word, quitar notas "(Dif Benj: ...)", lector)
FUENTES = [
    ("Escoleta", (1, 2, 3), "Escoleta - Introducción y Ciclo Único.docx", False, "f7"),
    ("Prebenjamín", (1, 2, 3), "Prebenjamín - Introducción y Ciclo Único.docx", False, "f7"),
    ("Benjamín", (1,), "Benjamín - Introducción y Ciclo Matriz 1.docx", False, "f7"),
    ("Benjamín", (2,), "Benjamín - Diferencias CM1-CM2 y Ciclo Matriz 2.docx", False, "f7"),
    ("Benjamín", (3,), "Benjamín - Diferencias CM2-CM3 y Ciclo Matriz 3.docx", False, "f7"),
    ("Alevín", (1,), "Alevín - Introducción y Ciclo Matriz 1.docx", True, "f7"),
    ("Alevín", (2,), "Alevín - Diferencias CM1-CM2 y Ciclo Matriz 2.docx", False, "f7"),
    ("Alevín", (3,), "Alevín - Diferencias CM2-CM3 y Ciclo Matriz 3.docx", False, "f7"),
    ("Infantil", (1,), "PROPUESTA - F11 Infantil - CM1 (Intro completa).docx", False, "f11"),
    ("Infantil", (2,), "PROPUESTA - F11 Infantil - CM2 (puente CM1-CM2).docx", False, "f11"),
    ("Infantil", (3,), "PROPUESTA - F11 Infantil - CM3 (puente CM2-CM3).docx", False, "f11"),
    ("Cadete", (1,), "PROPUESTA - F11 Cadete - CM1 (Intro completa).docx", False, "f11"),
    ("Cadete", (2,), "PROPUESTA - F11 Cadete - CM2 (puente CM1-CM2).docx", False, "f11"),
    ("Cadete", (3,), "PROPUESTA - F11 Cadete - CM3 (puente CM2-CM3).docx", False, "f11"),
]

_RE_CICLO = re.compile(r"CICLO\s+(\d)\s*:", re.I)
_RE_SEMANA = re.compile(r"SEMANA\s+(\d)", re.I)
_RE_DIA = re.compile(r"D[ií]a\s+(\d)\s*(\(.*\))?\s*:\s*$")
_RE_TAREA = re.compile(r"(Anal[ií]tica|Facilitadora|Bloque\s*2[^:]*?|Global)\s*:\s*(.*)$", re.S)


def _espacios(texto):
    return re.sub(r"\s+", " ", texto).strip()


def _limpiar_puntuacion(texto):
    """Arregla lo que deja quitar una nota: ' .', '. .', '?.'."""
    texto = re.sub(r"\s+([.,;:?!])", r"\1", texto)
    texto = re.sub(r"(?<!\.)\.\.(?!\.)", ".", texto)
    return re.sub(r"([?!])\.", r"\1", texto).strip()


def _quitar_notas_dif(texto):
    """Quita las '(Dif ...: ...)' (parentesis balanceados), como se hizo siempre con las de Alevin CM1."""
    while True:
        i = texto.find("(Dif")
        if i < 0:
            return _limpiar_puntuacion(texto)
        nivel, j = 0, i
        while j < len(texto):
            nivel += texto[j] == "("
            nivel -= texto[j] == ")"
            j += 1
            if nivel == 0:
                break
        texto = (texto[:i] + texto[j:]).strip()


def _tarea(etiqueta):
    e = etiqueta.lower()
    if e.startswith("anal"):
        return "T1"
    if e.startswith("global"):
        return "T3"
    return "T2"  # Facilitadora / "Bloque 2 ..."


def leer_word(nombre, quitar_dif=False):
    """F7: {(ciclo, semana, dia, 'T1'|'T2'|'T3'): texto} leyendo los encabezados CICLO / SEMANA / Día."""
    d = docx.Document(os.path.join(CARPETA_WORD, nombre))
    ps = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    inicio = next(i for i, t in enumerate(ps) if re.match(r"CICLO\s+1\s*:", t, re.I))
    tareas, ciclo, semana, dia = {}, None, None, None
    for t in ps[inicio:]:
        if re.match(r"ANEXO\b", t, re.I):
            break
        m = _RE_CICLO.match(t)
        if m:
            ciclo, semana, dia = int(m.group(1)), None, None
            continue
        m = _RE_SEMANA.match(t)
        if m:
            semana, dia = int(m.group(1)), None
            continue
        m = _RE_DIA.match(t)
        if m:
            dia = int(m.group(1))
            continue
        m = _RE_TAREA.match(t)
        if m and ciclo and semana and dia:
            texto = _espacios(m.group(2))
            tareas[(ciclo, semana, dia, _tarea(m.group(1)))] = _quitar_notas_dif(texto) if quitar_dif else texto
    return tareas


def _parentesis_balanceado(t, i):
    """Texto entre el '(' de la posicion i y su ')' de cierre, y la posicion siguiente."""
    nivel = 0
    for j in range(i, len(t)):
        nivel += t[j] == "("
        nivel -= t[j] == ")"
        if nivel == 0:
            return t[i + 1:j], j + 1
    return t[i + 1:], len(t)


def _mayus(s):
    return s[:1].upper() + s[1:]


def leer_word_f11(nombre, quitar_dif=False):
    """F11 (Infantil/Cadete): {(ciclo, semana, dia, 'Foco'|'T1'|'T2'|'T3'): texto}. Foco es '' si ese dia no
    tiene 'Foco de la semana'. T2 = 'Bloque A: ...\\nBloque B: ...'; en T3 el parentesis (menos los minutos) se
    une al texto. Cada campo empieza con mayuscula (asi se cargo CM1)."""
    d = docx.Document(os.path.join(CARPETA_WORD, nombre))
    ps = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    inicio = next(i for i, t in enumerate(ps) if re.match(r"CICLO\s+1\b", t))
    dias, ciclo, semana, cur = {}, None, None, None
    for t in ps[inicio:]:
        m = re.match(r"CICLO\s+(\d)\b", t)
        if m:
            ciclo, semana, cur = int(m.group(1)), None, None
            continue
        m = re.match(r"Semana\s+(\d)\b", t)
        if m:
            semana, cur = int(m.group(1)), None
            continue
        m = re.match(r"D[ií]a\s+(\d)\b", t)
        if m and ciclo and semana:
            cur = dias.setdefault((ciclo, semana, int(m.group(1))), {"Foco": "", "T1": "", "T2A": "", "T2B": "", "T3": ""})
            continue
        if cur is None:
            continue
        m = re.match(r"Foco de la semana\s*:\s*(.*)$", t, re.S)
        if m:
            cur["Foco"] = _espacios(m.group(1))
            continue
        m = re.match(r"T1\s*\([^)]*\)\s*:\s*(.*)$", t, re.S)
        if m:
            cur["T1"] = _espacios(m.group(1))
            continue
        m = re.match(r"T2\s*A\s*\([^)]*\)\s*:\s*(.*)$", t, re.S)
        if m:
            cur["T2A"] = _espacios(m.group(1))
            continue
        m = re.match(r"T2\s*B\s*\([^)]*\)\s*:\s*(.*)$", t, re.S)
        if m:
            cur["T2B"] = _espacios(m.group(1))
            continue
        if re.match(r"T3\s*\(", t):
            dentro, fin = _parentesis_balanceado(t, t.index("("))
            resto = re.sub(r"^\s*:\s*", "", t[fin:])
            extra = re.sub(r"^\s*\d+\s*'\s*,?\s*", "", dentro).strip()
            if extra and not resto.strip(" .:;"):
                cur["T3"] = _espacios(extra.rstrip(".") + ".")  # el T3 es solo el parentesis
            else:
                cur["T3"] = _espacios(f"{extra}: {resto}" if extra and resto else (resto or extra))
    tareas = {}
    for (c, s, dia), v in dias.items():
        a, b = _mayus(v["T2A"]), _mayus(v["T2B"])
        tareas[(c, s, dia, "Foco")] = _mayus(v["Foco"])
        tareas[(c, s, dia, "T1")] = _mayus(v["T1"])
        tareas[(c, s, dia, "T2")] = f"Bloque A: {a}\nBloque B: {b}" if a and b else (a or b)
        tareas[(c, s, dia, "T3")] = _mayus(v["T3"])
    return tareas


def calcular_cambios(filas):
    """Devuelve (cambios, resumen, respetadas, nuevas).
    cambios = [(fila, clave, texto_viejo, texto_nuevo)]; nuevas = [(clave, texto)] filas que hay que crear (solo F11)."""
    indice = {}
    for n, r in enumerate(filas[1:], start=2):
        indice[tuple(r[:6])] = (n, r[6] if len(r) > 6 else "")
    cambios, resumen, respetadas, nuevas = [], [], [], []
    for cat, cms, nombre, quitar_dif, lector in FUENTES:
        tareas = (leer_word_f11 if lector == "f11" else leer_word)(nombre, quitar_dif)
        tipos = ("Foco", "T1", "T2", "T3") if lector == "f11" else ("T1", "T2", "T3")
        for cm in cms:
            claves_word = {(str(cm), str(c), str(s), str(d), cat, t) for (c, s, d, t) in tareas}
            sobrantes = len([k for k in indice if k[0] == str(cm) and k[4] == cat and k[5] in tipos and k not in claves_word])
            ausentes = 0
            distintos = 0
            for (ciclo, semana, dia, t), nuevo in tareas.items():
                clave = (str(cm), str(ciclo), str(semana), str(dia), cat, t)
                if clave not in indice:
                    if lector == "f11":
                        nuevas.append((clave, nuevo))
                    ausentes += 1
                    continue
                n, viejo = indice[clave]
                if em.no_se_realiza(viejo) and not em.no_se_realiza(nuevo):
                    respetadas.append(clave)  # marcada a mano como 'No se realiza': no se pisa
                    continue
                if _espacios(viejo) != _espacios(nuevo):
                    distintos += 1
                    cambios.append((n, clave, viejo, nuevo))
            resumen.append((cat, cm, nombre, len(tareas), distintos, ausentes, sobrantes, lector))
    return cambios, resumen, respetadas, nuevas


def main():
    aplicar = "--aplicar" in sys.argv
    ws = em._get_client().open_by_key(em.DESTINATARIOS_FILE_ID).worksheet(em.PLANIFICACION_TAB)
    filas = ws.get_all_values()
    cambios, resumen, respetadas, nuevas = calcular_cambios(filas)
    if respetadas:
        print(f"Celdas marcadas 'No se realiza' que se respetan (no se pisan con el Word): {len(respetadas)} {respetadas[:6]}\n")
    print(f"{'categoría':<12}{'CM':<4}{'tareas Word':>12}{'a cambiar':>11}{'filas nuevas':>14}{'Sheet sin Word':>16}")
    for cat, cm, nombre, n_word, distintos, ausentes, sobrantes, lector in resumen:
        nuevas_cat = ausentes if lector == "f11" else 0
        print(f"{cat:<12}{cm:<4}{n_word:>12}{distintos:>11}{nuevas_cat:>14}{sobrantes:>16}")
    problemas = [r for r in resumen if r[6] or (r[5] and r[7] != "f11")]
    if problemas:
        print("\nHAY TAREAS QUE NO COINCIDEN ENTRE EL WORD Y EL SHEET (no se escribe nada hasta revisarlo):", problemas)
        sys.exit(1)
    print(f"\nTotal de celdas a actualizar: {len(cambios)} | filas nuevas a crear: {len(nuevas)}")
    if not aplicar:
        print("(simulacro; correr con --aplicar para escribir)")
        return
    os.makedirs(os.path.join(RAIZ, "output"), exist_ok=True)
    respaldo = os.path.join(RAIZ, "output", f"respaldo_planificacion_{datetime.now():%Y%m%d_%H%M}.json")
    with open(respaldo, "w", encoding="utf-8") as fh:
        json.dump(filas, fh, ensure_ascii=False)
    print("respaldo:", respaldo)
    for i in range(0, len(cambios), 150):
        ws.batch_update(
            [{"range": f"G{n}", "values": [[nuevo]]} for n, _, _, nuevo in cambios[i:i + 150]],
            value_input_option="RAW",
        )
    for i in range(0, len(nuevas), 300):
        ws.append_rows(
            [[int(c[0]), int(c[1]), int(c[2]), int(c[3]), c[4], c[5], texto] for c, texto in nuevas[i:i + 300]],
            value_input_option="RAW",
        )
    despues = ws.get_all_values()
    mal = [(n, k) for n, k, _, nuevo in cambios if _espacios(despues[n - 1][6]) != _espacios(nuevo)]
    idx = {tuple(r[:6]): (r[6] if len(r) > 6 else "") for r in despues[1:]}
    mal_nuevas = [c for c, texto in nuevas if _espacios(idx.get(c, "\0")) != _espacios(texto)]
    tocadas = {c[0] for c in cambios}
    ajenas = [n for n in range(2, len(filas) + 1) if n not in tocadas and despues[n - 1] != filas[n - 1]]
    print(
        f"VERIFICACIÓN: celdas que no coinciden={len(mal)} | filas nuevas que no coinciden={len(mal_nuevas)} | "
        f"filas previas modificadas sin querer={len(ajenas)} | filas antes/después={len(filas)}/{len(despues)} (esperadas {len(filas) + len(nuevas)})"
    )


if __name__ == "__main__":
    main()
