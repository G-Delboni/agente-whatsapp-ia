"""Cálculo de custo e guardas (dados sensíveis, tamanho, retenção)."""

from datetime import timedelta

import pytest

from app import conversas, db, guardas
from app.custos import Uso, calcular_custo_usd, usd_para_brl
from tests.conftest import TELEFONE


def test_custo_haiku_por_milhao() -> None:
    uso = Uso("claude-haiku-5-5", 1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert calcular_custo_usd(uso) == pytest.approx(0.10 + 0.125 + 0.01 + 0.50)


def test_custo_conversa_tipica_com_cache() -> None:
    # 15k de prefixo lido do cache + 150 de pergunta + 200 de resposta
    uso = Uso("claude-haiku-5-5", input_tokens=150, cache_leitura_tokens=15_000, output_tokens=200)
    assert uso.custo_usd == pytest.approx((150 * 0.10 + 15_000 * 0.01 + 200 * 0.50) / 1e6)


def test_custo_sonnet_e_conversao_brl() -> None:
    uso = Uso("claude-sonnet-5-5", input_tokens=1_000_000)
    assert uso.custo_usd == pytest.approx(2.0)
    assert usd_para_brl(uso.custo_usd, 5.53) == pytest.approx(11.06)


def test_uso_da_resposta_aceita_campos_nulos() -> None:
    class Usage:
        input_tokens, output_tokens = 10, 5
        cache_creation_input_tokens = None
        cache_read_input_tokens = None

    uso = Uso.da_resposta("claude-haiku-5-5", Usage())
    assert (uso.cache_criacao_tokens, uso.cache_leitura_tokens) == (0, 0)


def test_mascarar_cpf_e_cartao_mas_nao_telefone() -> None:
    texto = "CPF 123.456.789-09, cartão 4111 1111 1111 1111, fone 5519912345678"
    mascarado = guardas.mascarar_sensiveis(texto)
    assert "[CPF]" in mascarado and "[CARTAO]" in mascarado
    assert "5519912345678" in mascarado


def test_truncar_entrada(cfg) -> None:
    assert guardas.truncar_entrada("a" * 5000).endswith("[mensagem cortada]")
    assert guardas.truncar_entrada("curta") == "curta"


def test_gasto_hoje(cfg, relogio) -> None:
    conversas.registrar_uso(None, [Uso("claude-haiku-5-5", input_tokens=1_000_000)])
    assert guardas.gasto_hoje_usd() == pytest.approx(0.10)
    assert not guardas.limite_gasto_atingido()


def test_apagar_antigos(cfg, relogio) -> None:
    conversa = conversas.obter_ou_criar(TELEFONE)
    conversas.registrar_mensagem(conversa["id"], "entrada", "cliente", "antiga")
    relogio.atual += timedelta(days=200)
    conversas.registrar_mensagem(conversa["id"], "entrada", "cliente", "nova")
    assert guardas.apagar_antigos(180) == 1
    with db.conexao() as con:
        assert [r[0] for r in con.execute("SELECT texto FROM mensagens")] == ["nova"]
