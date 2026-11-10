"""Regras do atendimento: aviso de IA, humano no circuito, guardas e áudio."""

from datetime import timedelta

from app import conversas, db
from app.atendimento import MSG_PEDIR_TEXTO, processar_mensagem
from app.cliente_falso import ClienteRoteirizado, bloco_ferramenta, bloco_texto, resposta
from app.guardas import MENSAGEM_LIMITE_GASTO
from app.whatsapp import MensagemRecebida
from tests.conftest import RESPONSAVEL, TELEFONE

_n = iter(range(1, 10_000))


def msg(texto: str, telefone: str = TELEFONE, tipo: str = "text", media_id: str | None = None) -> MensagemRecebida:
    return MensagemRecebida(id_meta=f"wamid.{next(_n)}", telefone=telefone, nome="Maria",
                            tipo=tipo, texto=texto, media_id=media_id)


def _estado() -> str:
    return conversas.obter_ou_criar(TELEFONE)["estado"]


def _para_cliente(deps) -> list[str]:
    return [t for para, t in deps.whatsapp.enviadas if para == TELEFONE]


def test_aviso_ia_so_na_primeira_mensagem(deps) -> None:
    processar_mensagem(msg("Qual o endereço?"), deps)
    processar_mensagem(msg("E o horário de sábado?"), deps)
    primeira, segunda = _para_cliente(deps)
    assert "assistente virtual" in primeira
    assert "assistente virtual" not in segunda


def test_aviso_ia_de_novo_apos_24h(deps, relogio) -> None:
    processar_mensagem(msg("Qual o endereço?"), deps)
    relogio.atual += timedelta(hours=25)
    processar_mensagem(msg("Qual o endereço?"), deps)
    assert all("assistente virtual" in t for t in _para_cliente(deps))


def test_pedido_humano_pausa_bot_e_avisa_responsavel(deps) -> None:
    processar_mensagem(msg("Quero falar com um HUMANO"), deps)
    assert _estado() == "humano"
    avisos = [t for para, t in deps.whatsapp.enviadas if para == RESPONSAVEL]
    assert avisos and TELEFONE in avisos[0]
    antes = len(deps.whatsapp.enviadas)
    processar_mensagem(msg("Alô?"), deps)
    assert len(deps.whatsapp.enviadas) == antes  # bot pausado não responde


def test_modelo_transfere_com_ferramenta(deps) -> None:
    deps.llm = ClienteRoteirizado([
        resposta([bloco_ferramenta("transferir_para_humano", {"motivo": "sintoma"})], "tool_use"),
        resposta([bloco_texto("Vou chamar uma pessoa da equipe.")], "end_turn"),
    ])
    processar_mensagem(msg("Estou com febre"), deps)
    assert _estado() == "humano"
    with db.conexao() as con:
        assert tuple(con.execute("SELECT origem, motivo FROM transferencias").fetchone()) == ("modelo", "sintoma")
        assert con.execute("SELECT COUNT(*) FROM uso_tokens").fetchone()[0] == 2
        assert con.execute("SELECT nome FROM chamadas_ferramenta").fetchone()[0] == "transferir_para_humano"


def test_pausa_vence_e_bot_volta(deps, relogio) -> None:
    processar_mensagem(msg("atendente por favor"), deps)
    relogio.atual += timedelta(hours=13)  # pausa padrão: 12 h
    processar_mensagem(msg("Qual o endereço?"), deps)
    assert _estado() == "bot"
    assert "Acácias" in _para_cliente(deps)[-1]


def test_comando_do_responsavel_retoma_bot(deps) -> None:
    processar_mensagem(msg("HUMANO"), deps)
    processar_mensagem(msg(f"#bot {TELEFONE}", telefone=RESPONSAVEL), deps)
    assert _estado() == "bot"
    assert deps.whatsapp.enviadas[-1] == (RESPONSAVEL, f"Bot retomado para {TELEFONE}.")


def test_fora_do_horario_informa_quando_humano_responde(deps, relogio) -> None:
    relogio.atual = relogio.atual.replace(hour=20)  # quarta, 20:00
    processar_mensagem(msg("HUMANO"), deps)
    assert "amanhã a partir das 08:00" in _para_cliente(deps)[-1]


def test_guarda_de_gasto_diario(deps, cfg, relogio) -> None:
    with db.conexao() as con:
        con.execute(
            "INSERT INTO uso_tokens (modelo, input_tokens, cache_criacao_tokens, cache_leitura_tokens,"
            " output_tokens, custo_usd, criado_em) VALUES ('claude-haiku-5-5', 0, 0, 0, 0, ?, ?)",
            (cfg.limite_gasto_diario_usd, relogio.atual.isoformat()),
        )
    deps.llm = ClienteRoteirizado([])  # não pode ser chamado
    processar_mensagem(msg("Qual o endereço?"), deps)
    processar_mensagem(msg("Oi?"), deps)
    respostas = _para_cliente(deps)
    assert len(respostas) == 2 and all(MENSAGEM_LIMITE_GASTO in t for t in respostas)
    assert sum(para == RESPONSAVEL for para, _ in deps.whatsapp.enviadas) == 1  # avisa 1x por dia
    assert deps.llm.chamadas == []


def test_limite_de_mensagens_por_hora(deps, cfg) -> None:
    for _ in range(cfg.limite_msgs_por_hora + 3):
        processar_mensagem(msg("Qual o endereço?"), deps)
    assert len(_para_cliente(deps)) == cfg.limite_msgs_por_hora


def test_audio_sem_transcricao_pede_texto(deps) -> None:
    processar_mensagem(msg("", tipo="audio", media_id="300"), deps)
    assert MSG_PEDIR_TEXTO in _para_cliente(deps)[-1]


def test_audio_com_transcritor(deps) -> None:
    class TranscritorFalso:
        def transcrever(self, audio: bytes, mime: str) -> str:
            return "Qual o endereço?"

    deps.transcritor = TranscritorFalso()
    processar_mensagem(msg("", tipo="audio", media_id="300"), deps)
    assert "Acácias" in _para_cliente(deps)[-1]


def test_cpf_mascarado_no_banco(deps) -> None:
    processar_mensagem(msg("Meu CPF é 123.456.789-09, qual o endereço?"), deps)
    with db.conexao() as con:
        texto = con.execute("SELECT texto FROM mensagens WHERE direcao = 'entrada'").fetchone()[0]
    assert "[CPF]" in texto and "123.456" not in texto
