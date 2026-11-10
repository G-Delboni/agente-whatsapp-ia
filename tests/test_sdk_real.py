"""Agente com o SDK oficial da Anthropic, mas com transporte HTTP simulado (sem rede).

Garante que os parâmetros que montamos (strict, cache_control, output_config) passam pela
validação do SDK e que a resposta real (objetos do SDK) é lida corretamente.
"""

import json

import anthropic
import httpx2

from app import agente
from app.agenda_local import AgendaLocal
from tests.conftest import TELEFONE

USO = {"input_tokens": 120, "output_tokens": 40, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1800}


def _mensagem(conteudo: list[dict], stop_reason: str) -> dict:
    return {"id": "msg_teste", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": conteudo, "stop_reason": stop_reason, "stop_sequence": None, "usage": USO}


def test_loop_com_sdk_e_transporte_simulado(cfg) -> None:
    pedidos: list[dict] = []
    respostas = [
        _mensagem([{"type": "tool_use", "id": "toolu_01", "name": "consultar_horarios",
                    "input": {"data": "2026-11-12"}}], "tool_use"),
        _mensagem([{"type": "text", "text": "Tenho 08:00 livre amanhã. Qual seu nome completo?"}], "end_turn"),
    ]

    def responder(request: httpx2.Request) -> httpx2.Response:
        pedidos.append(json.loads(request.content))
        return httpx2.Response(200, json=respostas.pop(0))

    cliente = anthropic.Anthropic(
        api_key="chave-falsa-de-teste", max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(responder)),
    )
    r = agente.responder([], "Quero agendar amanhã", TELEFONE, cliente, AgendaLocal())

    assert r.texto.startswith("Tenho 08:00") and r.stop_reason == "end_turn"
    assert r.usos[0].cache_leitura_tokens == 1800
    primeiro, segundo = pedidos
    assert primeiro["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert primeiro["output_config"] == {"effort": "low"}
    assert all(t["strict"] is True for t in primeiro["tools"])
    assert segundo["messages"][1]["content"][0]["type"] == "tool_use"  # bloco do SDK reenviado
    assert segundo["messages"][2]["content"][0]["tool_use_id"] == "toolu_01"
