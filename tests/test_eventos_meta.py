"""Parsing dos eventos do webhook da Meta."""

from app.whatsapp import extrair_mensagens
from tests.conftest import TELEFONE, payload_texto


def _com_mensagem(msg: dict) -> dict:
    payload = payload_texto("x")
    payload["entry"][0]["changes"][0]["value"]["messages"] = [msg]
    return payload


def test_texto() -> None:
    [m] = extrair_mensagens(payload_texto("Olá, bom dia"))
    assert (m.tipo, m.texto, m.telefone, m.nome, m.id_meta) == ("text", "Olá, bom dia", TELEFONE, "Maria Teste", "wamid.TESTE1")


def test_botao_interativo() -> None:
    msg = {"from": TELEFONE, "id": "wamid.B1", "timestamp": "1762866000", "type": "interactive",
           "context": {"from": "15550000000", "id": "wamid.ORIGEM"},
           "interactive": {"type": "button_reply", "button_reply": {"id": "agendar", "title": "Agendar consulta"}}}
    [m] = extrair_mensagens(_com_mensagem(msg))
    assert (m.tipo, m.texto) == ("interactive", "Agendar consulta")


def test_lista_interativa() -> None:
    msg = {"from": TELEFONE, "id": "wamid.L1", "timestamp": "1762866000", "type": "interactive",
           "interactive": {"type": "list_reply", "list_reply": {"id": "p1", "title": "Pediatria", "description": "0 a 14"}}}
    assert extrair_mensagens(_com_mensagem(msg))[0].texto == "Pediatria"


def test_resposta_rapida_de_template() -> None:
    msg = {"from": TELEFONE, "id": "wamid.T1", "timestamp": "1762866000", "type": "button",
           "button": {"payload": "SIM", "text": "Confirmar"}}
    assert extrair_mensagens(_com_mensagem(msg))[0].texto == "Confirmar"


def test_audio() -> None:
    msg = {"from": TELEFONE, "id": "wamid.A1", "timestamp": "1762866000", "type": "audio",
           "audio": {"mime_type": "audio/ogg; codecs=opus", "sha256": "abc", "id": "300000000000000", "voice": True}}
    [m] = extrair_mensagens(_com_mensagem(msg))
    assert (m.tipo, m.media_id, m.texto) == ("audio", "300000000000000", "")


def test_status_ignorado() -> None:
    payload = payload_texto("x")
    valor = payload["entry"][0]["changes"][0]["value"]
    del valor["messages"], valor["contacts"]
    valor["statuses"] = [{"id": "wamid.S1", "status": "delivered", "timestamp": "1762866000",
                          "recipient_id": TELEFONE}]
    assert extrair_mensagens(payload) == []
