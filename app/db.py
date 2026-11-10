"""Banco SQLite: esquema e conexão. Um arquivo por cliente, sem servidor."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS conversas (
    id INTEGER PRIMARY KEY,
    telefone TEXT NOT NULL UNIQUE,
    nome TEXT,
    inicio TEXT NOT NULL,
    ultimo_contato TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'bot',          -- 'bot' ou 'humano'
    pausado_ate TEXT,                             -- bot pausado até esta data/hora
    aviso_ia_enviado_em TEXT
);
CREATE TABLE IF NOT EXISTS mensagens (
    id INTEGER PRIMARY KEY,
    conversa_id INTEGER NOT NULL REFERENCES conversas(id),
    direcao TEXT NOT NULL,                        -- 'entrada' ou 'saida'
    autor TEXT NOT NULL,                          -- 'cliente', 'bot', 'humano', 'sistema'
    tipo TEXT NOT NULL DEFAULT 'texto',           -- 'texto', 'audio', 'nao_sei', 'transferencia', 'limite'...
    texto TEXT NOT NULL,
    com_aviso_ia INTEGER NOT NULL DEFAULT 0,      -- 1 = abriu uma conversa nova (sessão)
    criado_em TEXT NOT NULL,
    id_meta TEXT
);
CREATE INDEX IF NOT EXISTS ix_mensagens_conversa ON mensagens(conversa_id, criado_em);
CREATE TABLE IF NOT EXISTS chamadas_ferramenta (
    id INTEGER PRIMARY KEY,
    conversa_id INTEGER,
    nome TEXT NOT NULL,
    entrada TEXT NOT NULL,
    resultado TEXT NOT NULL,
    erro INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uso_tokens (
    id INTEGER PRIMARY KEY,
    conversa_id INTEGER,
    origem TEXT NOT NULL DEFAULT 'atendimento',   -- 'atendimento', 'eval', 'juiz'
    modelo TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    cache_criacao_tokens INTEGER NOT NULL,
    cache_leitura_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    custo_usd REAL NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transferencias (
    id INTEGER PRIMARY KEY,
    conversa_id INTEGER NOT NULL,
    origem TEXT NOT NULL,                         -- 'cliente', 'modelo', 'sistema'
    motivo TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos_webhook (
    chave TEXT PRIMARY KEY,                       -- id da mensagem na Meta (ou chave interna)
    recebido_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documentos_recebidos (  -- nível 2 (MODO_DOCUMENTOS=1)
    id INTEGER PRIMARY KEY,
    conversa_id INTEGER,
    cliente_id TEXT NOT NULL,                     -- id do checklist ou 'nao-identificado'
    arquivo TEXT NOT NULL,
    hash TEXT NOT NULL,
    categoria TEXT NOT NULL,
    valor REAL NOT NULL,
    revisar INTEGER NOT NULL,                     -- 1 = campo duvidoso ou validação falhou
    motivos TEXT NOT NULL DEFAULT '',
    extracao TEXT NOT NULL,                       -- JSON completo da extração
    status TEXT NOT NULL DEFAULT 'aguardando_aprovacao',  -- nada é lançado sem o contador aprovar
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agendamentos (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    telefone TEXT NOT NULL,
    data_hora TEXT NOT NULL,                      -- 'AAAA-MM-DDTHH:MM' no fuso do negócio
    observacao TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ativo',         -- 'ativo' ou 'cancelado'
    criado_em TEXT NOT NULL
);
"""


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    """Abre uma conexão, faz commit no fim e fecha (uma por operação, segura entre threads)."""
    caminho = config.obter().db_caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def criar_tabelas() -> None:
    """Cria as tabelas se ainda não existirem."""
    with conexao() as con:
        con.executescript(ESQUEMA)


def registrar_evento_unico(chave: str) -> bool:
    """Grava a chave e devolve True só na primeira vez (deduplicação)."""
    with conexao() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO eventos_webhook (chave, recebido_em) VALUES (?, ?)",
            (chave, config.agora().isoformat()),
        )
        return cur.rowcount == 1
