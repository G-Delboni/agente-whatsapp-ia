"""Relatório mensal com dados de exemplo e evals em modo offline."""

from app import metricas
from app.atendimento import processar_mensagem
from app.cliente_falso import ClienteRegras
from app.whatsapp import MensagemRecebida
from evals import rodar as evals
from scripts.relatorio_mensal import gerar_markdown


def _msg(i: int, texto: str, telefone: str) -> MensagemRecebida:
    return MensagemRecebida(id_meta=f"wamid.R{i}", telefone=telefone, nome=None, tipo="text", texto=texto)


def test_relatorio_mensal(deps, relogio, tmp_path) -> None:
    conversa_a, conversa_b, conversa_c = "5500900000011", "5500900000012", "5500900000013"
    processar_mensagem(_msg(1, "Qual o endereço?", conversa_a), deps)
    processar_mensagem(_msg(2, "Vocês vendem vacina da gripe?", conversa_a), deps)
    processar_mensagem(_msg(3, "Estou com febre, que remédio tomo?", conversa_b), deps)
    relogio.atual = relogio.atual.replace(hour=21)  # fora do horário comercial
    processar_mensagem(_msg(4, "Meu nome é Ana Souza, quero marcar dia 12/11 às 09:00", conversa_c), deps)

    m = metricas.calcular(2026, 11)
    assert (m.conversas, m.contatos, m.mensagens_recebidas) == (3, 3, 4)
    assert m.recebidas_fora_do_horario == 1
    assert m.transferencias == 1 and m.transferencias_por_origem == {"modelo": 1}
    assert m.agendamentos == 1
    assert m.perguntas_nao_sei == ["Vocês vendem vacina da gripe?"]
    assert m.custo_usd > 0 and m.input_tokens > 0
    assert m.mensagens_enviadas >= 4 and m.custo_meta_brl == 0  # abaixo da franquia
    assert round(m.resolvidas_sem_humano_pct) == 67

    texto = gerar_markdown(m)
    assert "Relatório do atendente virtual – Clínica Exemplo – 11/2026" in texto
    assert "- Vocês vendem vacina da gripe?" in texto
    assert "Agendamentos feitos pelo atendente: **1**" in texto

    vazio = metricas.calcular(2026, 12)
    assert vazio.conversas == 0 and "Nenhuma neste mês" in gerar_markdown(vazio)


def test_evals_offline_passam(cfg, tmp_path) -> None:
    casos = evals.carregar_casos(evals.RAIZ / "evals" / "casos.yaml")
    assert len(casos) == 25
    resultados = evals.rodar(casos, ClienteRegras())
    reprovados = {r.id: r.falhas for r in resultados if not r.aprovado}
    assert reprovados == {}
    arquivo = evals.escrever_relatorio(resultados, "offline", tmp_path)
    conteudo = arquivo.read_text(encoding="utf-8")
    assert "25/25 aprovados" in conteudo and "cliente falso" in conteudo


def test_eval_detecta_falha(cfg) -> None:
    caso = {"id": "x", "entrada": "Qual a capital da França?", "deve_conter": ["Paris"], "deve_transferir": True}
    [r] = evals.rodar([caso], ClienteRegras())
    assert not r.aprovado and "faltou 'Paris'" in r.falhas and "deveria transferir" in r.falhas
