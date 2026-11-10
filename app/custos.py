"""Cálculo de custo da Claude API a partir do `usage` de cada resposta."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import PRECOS_USD_POR_MILHAO


@dataclass
class Uso:
    """Tokens de uma chamada, como vêm em `response.usage`."""

    modelo: str
    input_tokens: int = 0
    cache_criacao_tokens: int = 0
    cache_leitura_tokens: int = 0
    output_tokens: int = 0
    fator: float = 1.0  # 0.5 na Batch API (metade do preço)

    @classmethod
    def da_resposta(cls, modelo: str, usage: object) -> "Uso":
        """Lê os campos de `response.usage` (os de cache podem vir None)."""
        return cls(
            modelo=modelo,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            cache_criacao_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_leitura_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )

    @property
    def custo_usd(self) -> float:
        """Custo estimado em US$ (a cobrança oficial é a do Console da Anthropic)."""
        return calcular_custo_usd(self)


def calcular_custo_usd(uso: Uso) -> float:
    """Aplica a tabela de preços: entrada, escrita de cache (5 min), leitura de cache, saída."""
    entrada, escrita, leitura, saida = PRECOS_USD_POR_MILHAO.get(
        uso.modelo, PRECOS_USD_POR_MILHAO["claude-haiku-5-5"]
    )
    total = (
        uso.input_tokens * entrada
        + uso.cache_criacao_tokens * escrita
        + uso.cache_leitura_tokens * leitura
        + uso.output_tokens * saida
    )
    return total * uso.fator / 1_000_000


def usd_para_brl(valor_usd: float, cambio: float) -> float:
    """Converte US$ para R$ com o câmbio configurado."""
    return valor_usd * cambio
