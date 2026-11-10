"""ESQUELETO: agenda no Google Calendar do cliente (não usado por padrão).

Como ativar (por cliente):
1. No Google Cloud Console do CLIENTE (conta dele, não a sua), crie um projeto,
   ative a "Google Calendar API" e crie credenciais OAuth (tipo "App para computador").
2. Rode uma vez, na sua máquina, o fluxo OAuth com a conta do cliente para gerar um
   refresh token com escopo `https://www.googleapis.com/auth/calendar.events`.
3. Guarde GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN e GOOGLE_CALENDAR_ID
   só nas variáveis de ambiente da hospedagem (nunca no Git).
4. Instale no venv: `google-api-python-client google-auth` (gratuito; a API do Calendar não
   cobra no volume de uma clínica pequena, mas confira as cotas).
5. Em app/main.py, troque `AgendaLocal()` por `AgendaGoogle.do_ambiente()`.

Endpoints usados (Calendar API v3):
- consultar: `freebusy.query` com timeMin/timeMax do dia -> horários ocupados.
- agendar:  `events.insert` com summary, description (telefone e observação), start/end.
- cancelar: `events.list` com q=<telefone> e `events.delete` (ou status 'cancelled').
"""

from __future__ import annotations

import os
from datetime import date, datetime


class AgendaGoogle:
    """Implementação da interface Agenda sobre o Google Calendar (a completar por cliente)."""

    def __init__(self, calendar_id: str, credenciais: object) -> None:
        self.calendar_id = calendar_id
        self.credenciais = credenciais  # google.oauth2.credentials.Credentials

    @classmethod
    def do_ambiente(cls) -> "AgendaGoogle":
        """Monta a partir das variáveis GOOGLE_* (exige as bibliotecas do Google instaladas)."""
        from google.oauth2.credentials import Credentials  # type: ignore[import-not-found]

        cred = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/calendar.events"],
        )
        return cls(os.environ["GOOGLE_CALENDAR_ID"], cred)

    def horarios_livres(self, dia: date) -> list[str]:
        """TODO: freebusy.query e subtrair dos blocos do expediente (veja AgendaLocal._slots)."""
        raise NotImplementedError("Complete agenda_google.py para este cliente.")

    def agendar(self, nome: str, telefone: str, data_hora: datetime, observacao: str) -> str:
        """TODO: conferir livre e chamar events.insert."""
        raise NotImplementedError("Complete agenda_google.py para este cliente.")

    def cancelar(self, telefone: str, data_hora: datetime | None) -> str:
        """TODO: events.list(q=telefone) e events.delete."""
        raise NotImplementedError("Complete agenda_google.py para este cliente.")
