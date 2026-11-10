"""Loop do agente, montagem do prompt, stop_reason e agenda."""

from datetime import date, datetime

import pytest

from app import agente, config
from app.agenda import ErroAgenda
from app.agenda_local import AgendaLocal
from app.cliente_falso import ClienteRoteirizado, bloco_ferramenta, bloco_texto, resposta
from app.ferramentas import FERRAMENTAS
from tests.conftest import TELEFONE


def _responder(cliente, texto="Oi", historico=None):
    return agente.responder(historico or [], texto, TELEFONE, cliente, AgendaLocal())


def test_loop_de_ferramentas_ate_end_turn(cfg) -> None:
    cliente = ClienteRoteirizado([
        resposta([bloco_texto("Vou consultar."), bloco_ferramenta("consultar_horarios", {"data": "2026-11-12"})],
                 "tool_use", cache_creation_input_tokens=1500),
        resposta([bloco_texto("Tenho 08:00 e 08:30. Qual prefere?")], "end_turn", cache_read_input_tokens=1500),
    ])
    r = _responder(cliente, "Quero agendar amanhã")
    assert r.stop_reason == "end_turn"
    assert [c.nome for c in r.chamadas] == ["consultar_horarios"]
    assert "08:00" in r.chamadas[0].resultado and not r.chamadas[0].erro
    assert "Qual prefere?" in r.texto
    assert len(r.usos) == 2 and r.usos[0].cache_criacao_tokens == 1500
    segunda = cliente.chamadas[1]["messages"]
    assert segunda[-1]["content"][0]["type"] == "tool_result"
    assert segunda[-1]["content"][0]["tool_use_id"] == segunda[-2]["content"][1].id


def test_prompt_com_cache_e_ferramentas_estritas(cfg) -> None:
    cliente = ClienteRoteirizado([resposta([bloco_texto("a")], "end_turn"), resposta([bloco_texto("b")], "end_turn")])
    _responder(cliente, "primeira")
    _responder(cliente, "segunda", historico=[{"role": "user", "content": "x"}])
    um, dois = cliente.chamadas
    assert um["system"] == dois["system"]  # prefixo idêntico = cache reaproveitado
    assert um["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "Clínica Exemplo" in um["system"][0]["text"] and "Acácias" in um["system"][0]["text"]
    assert "README" not in um["system"][0]["text"]
    assert um["model"] == "claude-haiku-5-5" and um["max_tokens"] == 500
    assert um["output_config"] == {"effort": "low"}
    assert all(f["strict"] and f["input_schema"]["additionalProperties"] is False for f in FERRAMENTAS)
    assert um["tools"] is dois["tools"]
    contexto = um["messages"][-1]["content"][0]["text"]
    assert contexto.startswith("<contexto>") and "2026-11-11 10:00" in contexto and TELEFONE in contexto


def test_max_tokens_usa_texto_parcial(cfg) -> None:
    r = _responder(ClienteRoteirizado([resposta([bloco_texto("Resposta cortada")], "max_tokens")]))
    assert r.texto == "Resposta cortada" and r.motivo_transferencia is None


def test_max_tokens_sem_texto_transfere(cfg) -> None:
    r = _responder(ClienteRoteirizado([resposta([], "max_tokens")]))
    assert r.texto == agente.RESPOSTA_FALHA and r.motivo_transferencia


def test_refusal(cfg) -> None:
    r = _responder(ClienteRoteirizado([resposta([], "refusal")]))
    assert r.texto == agente.RESPOSTA_RECUSA


def test_limite_de_iteracoes(cfg) -> None:
    ferramenta = lambda: resposta([bloco_ferramenta("consultar_horarios", {"data": "2026-11-12"})], "tool_use")  # noqa: E731
    cliente = ClienteRoteirizado([ferramenta() for _ in range(cfg.max_iteracoes_ferramentas)])
    r = _responder(cliente)
    assert r.texto == agente.RESPOSTA_FALHA
    assert r.motivo_transferencia == "limite de iterações do agente"
    assert len(cliente.chamadas) == cfg.max_iteracoes_ferramentas


def test_nao_sei_detectado(cfg) -> None:
    r = _responder(ClienteRoteirizado([resposta([bloco_texto("Não sei essa informação.")], "end_turn")]))
    assert r.nao_sei


def test_erro_de_ferramenta_volta_como_is_error(cfg) -> None:
    cliente = ClienteRoteirizado([
        resposta([bloco_ferramenta("agendar", {"nome": "Ana", "telefone": "", "data_hora": "2026-11-15T09:00",
                                               "observacao": ""})], "tool_use"),  # domingo: fechado
        resposta([bloco_texto("Esse horário não está disponível.")], "end_turn"),
    ])
    r = _responder(cliente)
    assert r.chamadas[0].erro
    assert cliente.chamadas[1]["messages"][-1]["content"][0]["is_error"] is True


def test_agenda_local(cfg) -> None:
    agenda = AgendaLocal()
    livres = agenda.horarios_livres(date(2026, 11, 12))
    assert livres[0] == "08:00" and livres[-1] == "17:30"
    assert agenda.horarios_livres(date(2026, 11, 14))[-1] == "11:30"  # sábado até 12:00
    assert agenda.horarios_livres(date(2026, 11, 15)) == []  # domingo
    quando = datetime(2026, 11, 12, 9, 0, tzinfo=config.obter().tz)
    assert "confirmado" in agenda.agendar("Ana Souza", TELEFONE, quando, "")
    assert "09:00" not in agenda.horarios_livres(date(2026, 11, 12))
    with pytest.raises(ErroAgenda):
        agenda.agendar("Outra", "5500900000002", quando, "")
    assert "cancelado" in agenda.cancelar(TELEFONE, None)
    assert "09:00" in agenda.horarios_livres(date(2026, 11, 12))
