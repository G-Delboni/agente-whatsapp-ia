"""Estado das conversas: aviso de IA, histórico, transferência para humano."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app import config, db
from app.guardas import mascarar_sensiveis

PADRAO_QUER_HUMANO = re.compile(
    r"\b(humano|atendente|falar com (uma |um )?(pessoa|algu[eé]m))\b", re.IGNORECASE
)


def _dt(texto: str | None) -> datetime | None:
    """Converte ISO do banco em datetime."""
    return datetime.fromisoformat(texto) if texto else None


def obter_ou_criar(telefone: str, nome: str | None = None) -> sqlite3.Row:
    """Busca a conversa do telefone ou cria uma nova."""
    agora = config.agora().isoformat()
    with db.conexao() as con:
        con.execute(
            "INSERT OR IGNORE INTO conversas (telefone, nome, inicio, ultimo_contato)"
            " VALUES (?, ?, ?, ?)",
            (telefone, nome, agora, agora),
        )
        if nome:
            con.execute("UPDATE conversas SET nome = ? WHERE telefone = ?", (nome, telefone))
        return con.execute("SELECT * FROM conversas WHERE telefone = ?", (telefone,)).fetchone()


def obter(conversa_id: int) -> sqlite3.Row | None:
    """Lê uma conversa pelo id."""
    with db.conexao() as con:
        return con.execute("SELECT * FROM conversas WHERE id = ?", (conversa_id,)).fetchone()


def precisa_aviso_ia(conversa: sqlite3.Row) -> bool:
    """Aviso de IA na 1ª mensagem e de novo após N horas sem contato (Usage Policy da Anthropic)."""
    if not conversa["aviso_ia_enviado_em"]:
        return True
    limite = timedelta(hours=config.obter().horas_nova_conversa)
    return config.agora() - _dt(conversa["ultimo_contato"]) > limite


def registrar_mensagem(
    conversa_id: int,
    direcao: str,
    autor: str,
    texto: str,
    tipo: str = "texto",
    com_aviso_ia: bool = False,
    id_meta: str | None = None,
) -> None:
    """Grava a mensagem (com CPF e cartão mascarados) e atualiza o último contato."""
    agora = config.agora().isoformat()
    with db.conexao() as con:
        con.execute(
            "INSERT INTO mensagens (conversa_id, direcao, autor, tipo, texto, com_aviso_ia,"
            " criado_em, id_meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conversa_id, direcao, autor, tipo, mascarar_sensiveis(texto),
             int(com_aviso_ia), agora, id_meta),
        )
        if direcao == "entrada":
            con.execute("UPDATE conversas SET ultimo_contato = ? WHERE id = ?", (agora, conversa_id))
        if com_aviso_ia:
            con.execute(
                "UPDATE conversas SET aviso_ia_enviado_em = ? WHERE id = ?", (agora, conversa_id)
            )


def historico(conversa_id: int) -> list[dict[str, Any]]:
    """Últimas N mensagens das últimas X horas, no formato `messages` da API."""
    cfg = config.obter()
    desde = (config.agora() - timedelta(hours=cfg.historico_horas)).isoformat()
    with db.conexao() as con:
        linhas = con.execute(
            "SELECT direcao, autor, texto FROM mensagens WHERE conversa_id = ? AND criado_em >= ?"
            " ORDER BY id DESC LIMIT ?",
            (conversa_id, desde, cfg.historico_max_mensagens),
        ).fetchall()
    mensagens: list[dict[str, Any]] = []
    for linha in reversed(linhas):
        papel = "user" if linha["direcao"] == "entrada" else "assistant"
        texto = linha["texto"]
        if linha["autor"] == "humano":
            texto = f"[resposta de um atendente humano] {texto}"
        mensagens.append({"role": papel, "content": texto})
    while mensagens and mensagens[0]["role"] != "user":  # a API exige começar pelo usuário
        mensagens.pop(0)
    return mensagens


def bot_pausado(conversa: sqlite3.Row) -> bool:
    """True se um humano assumiu e a pausa ainda vale; pausa vencida devolve ao bot."""
    if conversa["estado"] != "humano":
        return False
    ate = _dt(conversa["pausado_ate"])
    if ate and ate > config.agora():
        return True
    devolver_ao_bot(conversa["id"])
    return False


def transferir_para_humano(conversa_id: int, origem: str, motivo: str) -> None:
    """Passa a conversa para humano e pausa o bot por N horas."""
    cfg = config.obter()
    agora = config.agora()
    ate = agora + timedelta(hours=cfg.pausa_humano_horas)
    with db.conexao() as con:
        con.execute(
            "UPDATE conversas SET estado = 'humano', pausado_ate = ? WHERE id = ?",
            (ate.isoformat(), conversa_id),
        )
        con.execute(
            "INSERT INTO transferencias (conversa_id, origem, motivo, criado_em) VALUES (?, ?, ?, ?)",
            (conversa_id, origem, mascarar_sensiveis(motivo), agora.isoformat()),
        )


def devolver_ao_bot(conversa_id: int) -> None:
    """Retoma o atendimento automático."""
    with db.conexao() as con:
        con.execute(
            "UPDATE conversas SET estado = 'bot', pausado_ate = NULL WHERE id = ?", (conversa_id,)
        )


def devolver_por_telefone(telefone: str) -> bool:
    """Retoma o bot pelo telefone (comando '#bot <telefone>' do responsável)."""
    with db.conexao() as con:
        linha = con.execute("SELECT id FROM conversas WHERE telefone = ?", (telefone,)).fetchone()
    if not linha:
        return False
    devolver_ao_bot(linha["id"])
    return True


def quer_humano(texto: str) -> bool:
    """Detecta pedido explícito de atendente ('HUMANO', 'atendente', 'falar com alguém')."""
    return bool(PADRAO_QUER_HUMANO.search(texto))


def registrar_uso(conversa_id: int | None, usos: list[Any], origem: str = "atendimento") -> None:
    """Grava tokens e custo estimado de cada chamada à Claude API."""
    agora = config.agora().isoformat()
    with db.conexao() as con:
        con.executemany(
            "INSERT INTO uso_tokens (conversa_id, origem, modelo, input_tokens, cache_criacao_tokens,"
            " cache_leitura_tokens, output_tokens, custo_usd, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(conversa_id, origem, u.modelo, u.input_tokens, u.cache_criacao_tokens,
              u.cache_leitura_tokens, u.output_tokens, u.custo_usd, agora) for u in usos],
        )


def registrar_chamadas(conversa_id: int, chamadas: list[Any]) -> None:
    """Grava as ferramentas executadas (entrada e resultado, mascarados)."""
    from app.ferramentas import serializar

    agora = config.agora().isoformat()
    with db.conexao() as con:
        con.executemany(
            "INSERT INTO chamadas_ferramenta (conversa_id, nome, entrada, resultado, erro, criado_em)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(conversa_id, c.nome, mascarar_sensiveis(serializar(c.entrada)),
              mascarar_sensiveis(c.resultado), int(c.erro), agora) for c in chamadas],
        )
