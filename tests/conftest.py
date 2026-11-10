"""Fixtures: banco temporário, relógio fixo e dependências falsas (sem rede)."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402
from app.agenda_local import AgendaLocal  # noqa: E402
from app.atendimento import Dependencias  # noqa: E402
from app.cliente_falso import ClienteRegras, WhatsAppFalso  # noqa: E402
from app.transcricao import TranscritorDesligado  # noqa: E402

TELEFONE = "5500900000001"
RESPONSAVEL = "5500900000099"


class Relogio:
    """Relógio controlável nos testes."""

    def __init__(self, inicio: str) -> None:
        self.atual = datetime.fromisoformat(inicio).replace(tzinfo=config.Config().tz)

    def __call__(self) -> datetime:
        return self.atual


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> Relogio:
    """Quarta-feira, 11/11/2026, 10:00 (dentro do horário comercial)."""
    r = Relogio("2026-11-11T10:00")
    monkeypatch.setattr(config, "agora", r)
    return r


@pytest.fixture
def cfg(tmp_path: Path, relogio: Relogio) -> config.Config:
    """Config de teste com banco temporário e segredos fictícios."""
    c = replace(
        config.Config(),
        db_caminho=tmp_path / "teste.db",
        meta_app_secret="segredo-de-teste",
        meta_verify_token="token-de-teste",
        numero_responsavel=RESPONSAVEL,
        admin_token="admin-teste",
    )
    config.definir(c)
    db.criar_tabelas()
    yield c
    config.definir(config.Config())


@pytest.fixture
def deps(cfg: config.Config) -> Dependencias:
    """Dependências falsas: WhatsApp, Claude (regras) e agenda local."""
    return Dependencias(
        whatsapp=WhatsAppFalso(), llm=ClienteRegras(), agenda=AgendaLocal(), transcritor=TranscritorDesligado()
    )


def payload_texto(texto: str, id_meta: str = "wamid.TESTE1", telefone: str = TELEFONE) -> dict[str, Any]:
    """Webhook real da Cloud API (v21+) para uma mensagem de texto."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "100000000000000",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15550000000", "phone_number_id": "200000000000000"},
                    "contacts": [{"profile": {"name": "Maria Teste"}, "wa_id": telefone}],
                    "messages": [{
                        "from": telefone, "id": id_meta, "timestamp": "1762866000",
                        "type": "text", "text": {"body": texto},
                    }],
                },
            }],
        }],
    }
