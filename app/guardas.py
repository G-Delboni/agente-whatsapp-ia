"""Travas de segurança e custo: gasto diário, volume por número, tamanho, dados sensíveis."""

from __future__ import annotations

import re
from datetime import timedelta

from app import config, db

MENSAGEM_LIMITE_GASTO = (
    "No momento nosso atendimento automático está indisponível. "
    "Uma pessoa da equipe vai responder assim que possível."
)

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CARTAO = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn_valido(numero: str) -> bool:
    """Confere o dígito verificador de cartão (evita mascarar telefones por engano)."""
    digitos = [int(d) for d in numero][::-1]
    soma = sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digitos))
    return soma % 10 == 0


def mascarar_sensiveis(texto: str) -> str:
    """Troca CPF e número de cartão por marcadores antes de gravar em log/banco."""
    def _cartao(m: re.Match[str]) -> str:
        so_digitos = re.sub(r"\D", "", m.group())
        return "[CARTAO]" if 13 <= len(so_digitos) <= 19 and _luhn_valido(so_digitos) else m.group()

    texto = _CARTAO.sub(_cartao, texto)
    return _CPF.sub("[CPF]", texto)


def truncar_entrada(texto: str) -> str:
    """Corta textos enormes (evita custo e abuso)."""
    limite = config.obter().max_caracteres_entrada
    return texto if len(texto) <= limite else texto[:limite] + " [mensagem cortada]"


def gasto_hoje_usd() -> float:
    """Soma o custo estimado da Claude API desde 00:00 de hoje."""
    inicio = config.agora().replace(hour=0, minute=0, second=0).isoformat()
    with db.conexao() as con:
        linha = con.execute(
            "SELECT COALESCE(SUM(custo_usd), 0) AS total FROM uso_tokens WHERE criado_em >= ?",
            (inicio,),
        ).fetchone()
    return float(linha["total"])


def limite_gasto_atingido() -> bool:
    """True se o gasto de hoje chegou ao teto diário do cliente."""
    return gasto_hoje_usd() >= config.obter().limite_gasto_diario_usd


def excedeu_mensagens_por_hora(telefone: str) -> bool:
    """True se o número mandou mais mensagens na última hora do que o permitido."""
    desde = (config.agora() - timedelta(hours=1)).isoformat()
    with db.conexao() as con:
        linha = con.execute(
            "SELECT COUNT(*) AS n FROM mensagens m JOIN conversas c ON c.id = m.conversa_id"
            " WHERE c.telefone = ? AND m.direcao = 'entrada' AND m.criado_em >= ?",
            (telefone, desde),
        ).fetchone()
    return linha["n"] >= config.obter().limite_msgs_por_hora


def apagar_antigos(dias: int | None = None) -> int:
    """Apaga mensagens e logs com mais de N dias (retenção da LGPD). Devolve quantas mensagens."""
    dias = dias if dias is not None else config.obter().retencao_dias
    corte = (config.agora() - timedelta(days=dias)).isoformat()
    with db.conexao() as con:
        n = con.execute("DELETE FROM mensagens WHERE criado_em < ?", (corte,)).rowcount
        con.execute("DELETE FROM chamadas_ferramenta WHERE criado_em < ?", (corte,))
        con.execute("DELETE FROM eventos_webhook WHERE recebido_em < ?", (corte,))
        con.execute(
            "DELETE FROM conversas WHERE ultimo_contato < ?"
            " AND id NOT IN (SELECT DISTINCT conversa_id FROM mensagens)",
            (corte,),
        )
    return n
