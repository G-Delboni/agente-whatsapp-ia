"""Interface de agenda usada pelas ferramentas do agente."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol


class ErroAgenda(Exception):
    """Erro de regra de agenda (horário ocupado, fora do expediente, não encontrado)."""


class Agenda(Protocol):
    """O que o agente precisa de uma agenda: consultar, marcar e cancelar."""

    def horarios_livres(self, dia: date) -> list[str]:
        """Horários livres no dia, como 'HH:MM'."""
        ...

    def agendar(self, nome: str, telefone: str, data_hora: datetime, observacao: str) -> str:
        """Marca e devolve um código/descrição do agendamento; levanta ErroAgenda se não puder."""
        ...

    def cancelar(self, telefone: str, data_hora: datetime | None) -> str:
        """Cancela o agendamento do telefone (o da data/hora, ou o próximo); levanta ErroAgenda."""
        ...
