"""Punto de entrada para GitHub Actions: revisa el dia de la semana real
(Europe/Madrid) y, si corresponde segun la regla de negocio validada
(Viernes=Dia1, Martes=Dia2), envia los correos de las categorias en
CATEGORIAS_AUTOMATICO y avanza el estado en la pestaña Estado_Envios.

Modo prueba: con DRY_RUN=1 (default) arma todo pero no envia ni actualiza
el estado, solo lo deja registrado en envios_log.txt."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import emails_manager as em

DIAS_ES = {0: "LUNES", 1: "MARTES", 2: "MIERCOLES", 3: "JUEVES", 4: "VIERNES", 5: "SABADO", 6: "DOMINGO"}


def main():
    dry_run = os.environ.get("DRY_RUN", "1") == "1"
    ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    dia_semana = DIAS_ES[ahora.weekday()]

    log = [f"{ahora.isoformat()} - dia_semana={dia_semana} dry_run={dry_run}"]

    estado = em.leer_estado()
    log.append(f"Estado actual: CM{estado['cm']}-C{estado['ciclo']}-S{estado['semana']}-D{estado['dia']}")

    siguiente = em.calcular_siguiente_envio(dia_semana, estado)
    if siguiente is None:
        log.append("No corresponde ningún envío hoy.")
        _escribir_log(log)
        return

    cm, ciclo, semana, dia = siguiente
    log.append(f"A enviar: CM{cm}-C{ciclo}-S{semana}-D{dia} -> {em.CATEGORIAS_AUTOMATICO}")

    for categoria in em.CATEGORIAS_AUTOMATICO:
        emails, asunto, cuerpo = em.generar_preview(categoria, cm, ciclo, semana, dia)
        if not emails:
            log.append(f"  {categoria}: SIN DESTINATARIOS, se salteó.")
            continue
        if dry_run:
            log.append(f"  [DRY_RUN] {categoria} -> {emails} | {asunto}")
        else:
            em.enviar_correo(emails, asunto, cuerpo)
            log.append(f"  ENVIADO {categoria} -> {emails} | {asunto}")

    if dry_run:
        log.append("[DRY_RUN] Estado NO actualizado.")
    else:
        em.actualizar_estado(cm, ciclo, semana, dia)
        log.append(f"Estado actualizado a CM{cm}-C{ciclo}-S{semana}-D{dia}.")

    _escribir_log(log)


def _escribir_log(lineas):
    texto = "\n".join(lineas) + "\n\n"
    with open("envios_log.txt", "a", encoding="utf-8") as f:
        f.write(texto)
    print(texto)


if __name__ == "__main__":
    main()
