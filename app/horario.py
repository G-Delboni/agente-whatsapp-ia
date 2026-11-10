"""Horário comercial do negócio: dentro/fora e quando um humano volta."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from app import config

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def faixa_do_dia(dia_semana: int) -> tuple[time, time] | None:
    """Início e fim do expediente no dia da semana (0 = segunda), ou None se fechado."""
    faixa = config.obter().horario_comercial.get(dia_semana)
    if not faixa:
        return None
    return time.fromisoformat(faixa[0]), time.fromisoformat(faixa[1])


def dentro_do_horario(momento: datetime) -> bool:
    """True se há equipe humana trabalhando neste momento."""
    faixa = faixa_do_dia(momento.weekday())
    return bool(faixa) and faixa[0] <= momento.time() < faixa[1]


def proximo_inicio(momento: datetime) -> datetime:
    """Próximo momento em que o expediente começa (ou o próprio momento, se aberto)."""
    if dentro_do_horario(momento):
        return momento
    for i in range(8):
        dia = (momento + timedelta(days=i)).date()
        faixa = faixa_do_dia(dia.weekday())
        if not faixa:
            continue
        inicio = datetime.combine(dia, faixa[0], tzinfo=momento.tzinfo)
        if inicio > momento:
            return inicio
    return momento  # sem horário configurado


def quando_humano_responde(momento: datetime) -> str:
    """Frase curta dizendo quando a equipe responde."""
    if dentro_do_horario(momento):
        return "Nossa equipe responde aqui em breve."
    inicio = proximo_inicio(momento)
    if inicio.date() == momento.date():
        dia = "hoje"
    elif inicio.date() == (momento + timedelta(days=1)).date():
        dia = "amanhã"
    else:
        dia = DIAS[inicio.weekday()]
    return f"Estamos fora do horário de atendimento; a equipe responde {dia} a partir das {inicio:%H:%M}."
