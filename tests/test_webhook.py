"""Webhook: verificação da Meta, assinatura, deduplicação, processamento em background e admin."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.atendimento import dependencias_padrao
from app.main import app
from tests.conftest import payload_texto


@pytest.fixture
def cliente_http(cfg, deps):
    app.dependency_overrides[dependencias_padrao] = lambda: deps
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _assinar(corpo: bytes, segredo: str = "segredo-de-teste") -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


def _post(cliente_http, payload, assinatura=None):
    corpo = json.dumps(payload).encode()
    cabecalhos = {"Content-Type": "application/json", "X-Hub-Signature-256": assinatura or _assinar(corpo)}
    return cliente_http.post("/webhook", content=corpo, headers=cabecalhos)


def test_verificacao_ok(cliente_http) -> None:
    r = cliente_http.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "token-de-teste",
                                             "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"


def test_verificacao_token_errado(cliente_http) -> None:
    r = cliente_http.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "errado",
                                             "hub.challenge": "12345"})
    assert r.status_code == 403


def test_assinatura_invalida_rejeitada(cliente_http, deps) -> None:
    r = _post(cliente_http, payload_texto("Oi"), assinatura="sha256=" + "0" * 64)
    assert r.status_code == 401
    assert deps.whatsapp.enviadas == []


def test_sem_assinatura_rejeitada(cliente_http) -> None:
    corpo = json.dumps(payload_texto("Oi")).encode()
    assert cliente_http.post("/webhook", content=corpo).status_code == 401


def test_mensagem_processada_em_background(cliente_http, deps) -> None:
    r = _post(cliente_http, payload_texto("Qual o endereço?"))
    assert r.status_code == 200 and r.json() == {"recebidas": 1}
    [(_, texto)] = deps.whatsapp.enviadas
    assert "assistente virtual" in texto and "Acácias" in texto
    assert deps.whatsapp.lidas == ["wamid.TESTE1"]


def test_dedupe_por_id_da_mensagem(cliente_http, deps) -> None:
    payload = payload_texto("Qual o endereço?", id_meta="wamid.REPETIDA")
    assert _post(cliente_http, payload).json() == {"recebidas": 1}
    assert _post(cliente_http, payload).json() == {"recebidas": 0}
    assert len(deps.whatsapp.enviadas) == 1


def test_saude(cliente_http) -> None:
    assert cliente_http.get("/saude").json() == {"status": "ok"}


def test_admin_exige_senha(cliente_http) -> None:
    assert cliente_http.get("/admin").status_code == 401
    assert cliente_http.get("/admin", auth=("equipe", "errada")).status_code == 401
    assert cliente_http.get("/admin", auth=("equipe", "admin-teste")).status_code == 200


def test_admin_assumir_responder_devolver(cliente_http, deps) -> None:
    _post(cliente_http, payload_texto("Oi"))
    auth = ("equipe", "admin-teste")
    assert cliente_http.post("/admin/conversa/1/assumir", auth=auth).status_code == 200  # segue o redirect
    assert "Devolver ao bot" in cliente_http.get("/admin/conversa/1", auth=auth).text
    cliente_http.post("/admin/conversa/1/responder", data={"texto": "Olá, aqui é a Júlia"}, auth=auth)
    assert deps.whatsapp.enviadas[-1][1] == "Olá, aqui é a Júlia"
    cliente_http.post("/admin/conversa/1/devolver", auth=auth)
    assert "Assumir" in cliente_http.get("/admin/conversa/1", auth=auth).text
