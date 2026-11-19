"""Sincroniza el texto de los Word de planificacion (T1/T2/T3) con la pestana Planificacion_Ejercicios
del Sheet, que es lo que lee la app (correos y planilla del dia).

    python herramientas/sincronizar_planificacion.py             -> simulacro: muestra que cambiaria
    python herramientas/sincronizar_planificacion.py --aplicar   -> respalda, escribe y verifica

Solo toca el texto de T1/T2/T3 de Escoleta, Prebenjamin, Benjamin y Alevin; no toca T0, Foco ni Resumen,
ni Infantil/Cadete. Requiere python-docx (uso local; la app online no lee Word)."""

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

# (categoria, CMs del Sheet que reciben ese texto, Word, quitar notas "(Dif Benj: ...)")
FUENTES = [
    ("Escoleta", (1, 2, 3), "Escoleta - Introducción y Ciclo Único.docx", False),
    ("Prebenjamín", (1, 2, 3), "Prebenjamín - Introducción y Ciclo Único.docx", False),
    ("Benjamín", (1,), "Benjamín - Introducción y Ciclo Matriz 1.docx", False),
    ("Benjamín", (2,), "Benjamín - Diferencias CM1-CM2 y Ciclo Matriz 2.docx", False),
    ("Benjamín", (3,), "Benjamín - Diferencias CM2-CM3 y Ciclo Matriz 3.docx", False),
    ("Alevín", (1,), "Alevín - Introducción y Ciclo Matriz 1.docx", True),
    ("Alevín", (2,), "Alevín - Diferencias CM1-CM2 y Ciclo Matriz 2.docx", False),
    ("Alevín", (3,), "Alevín - Diferencias CM2-CM3 y Ciclo Matriz 3.docx", False),
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
    """{(ciclo, semana, dia, 'T1'|'T2'|'T3'): texto} leyendo los encabezados CICLO / SEMANA / Día."""
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


def calcular_cambios(filas):
    """Devuelve (cambios, resumen): cambios = [(fila, clave, texto_viejo, texto_nuevo)]."""
    indice = {}
    for n, r in enumerate(filas[1:], start=2):
        indice[tuple(r[:6])] = (n, r[6] if len(r) > 6 else "")
    cambios, resumen, respetadas = [], [], []
    for cat, cms, nombre, quitar_dif in FUENTES:
        tareas = leer_word(nombre, quitar_dif)
        for cm in cms:
            claves_sheet = [k for k in indice if k[0] == str(cm) and k[4] == cat and k[5] in ("T1", "T2", "T3")]
            ausentes = [k for k in tareas if (str(cm), str(k[0]), str(k[1]), str(k[2]), cat, k[3]) not in indice]
            sobrantes = len(claves_sheet) - len(tareas)
            distintos = 0
            for (ciclo, semana, dia, t), nuevo in tareas.items():
                clave = (str(cm), str(ciclo), str(semana), str(dia), cat, t)
                if clave not in indice:
                    continue
                n, viejo = indice[clave]
                if em.no_se_realiza(viejo) and not em.no_se_realiza(nuevo):
                    respetadas.append(clave)  # marcada a mano como 'No se realiza': no se pisa
                    continue
                if _espacios(viejo) != _espacios(nuevo):
                    distintos += 1
                    cambios.append((n, clave, viejo, nuevo))
            resumen.append((cat, cm, nombre, len(tareas), distintos, len(ausentes), sobrantes))
    return cambios, resumen, respetadas


def main():
    aplicar = "--aplicar" in sys.argv
    ws = em._get_client().open_by_key(em.DESTINATARIOS_FILE_ID).worksheet(em.PLANIFICACION_TAB)
    filas = ws.get_all_values()
    cambios, resumen, respetadas = calcular_cambios(filas)
    if respetadas:
        print(f"Celdas marcadas 'No se realiza' que se respetan (no se pisan con el Word): {len(respetadas)} {respetadas[:6]}\n")
    print(f"{'categoría':<12}{'CM':<4}{'tareas Word':>12}{'a cambiar':>11}{'no están en Sheet':>19}{'Sheet sin Word':>16}")
    for cat, cm, nombre, n_word, distintos, ausentes, sobrantes in resumen:
        print(f"{cat:<12}{cm:<4}{n_word:>12}{distintos:>11}{ausentes:>19}{sobrantes:>16}")
    problemas = [r for r in resumen if r[5] or r[6]]
    if problemas:
        print("\nHAY TAREAS QUE NO COINCIDEN ENTRE EL WORD Y EL SHEET (no se escribe nada hasta revisarlo):", problemas)
        sys.exit(1)
    print(f"\nTotal de celdas a actualizar: {len(cambios)}")
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
    despues = ws.get_all_values()
    mal = [(n, k) for n, k, _, nuevo in cambios if _espacios(despues[n - 1][6]) != _espacios(nuevo)]
    cambiadas_de_mas = [n for n in range(2, len(filas) + 1) if n not in {c[0] for c in cambios} and despues[n - 1] != filas[n - 1]]
    print(f"VERIFICACIÓN: celdas que no coinciden={len(mal)} | filas no objetivo modificadas={len(cambiadas_de_mas)} | filas antes/después={len(filas)}/{len(despues)}")


if __name__ == "__main__":
    main()
