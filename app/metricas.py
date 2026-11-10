"""Métricas do mês lidas do SQLite (usadas no relatório mensal e no painel admin)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app import config, db, horario


@dataclass
class Metricas:
    """Números de um mês de atendimento."""

    inicio: date
    fim: date
    contatos: int = 0
    conversas: int = 0
    mensagens_recebidas: int = 0
    recebidas_fora_do_horario: int = 0
    transferencias: int = 0
    transferencias_por_origem: dict[str, int] = field(default_factory=dict)
    agendamentos: int = 0
    cancelamentos: int = 0
    chamadas_api: int = 0
    input_tokens: int = 0
    cache_criacao_tokens: int = 0
    cache_leitura_tokens: int = 0
    output_tokens: int = 0
    custo_usd: float = 0.0
    mensagens_enviadas: int = 0
    perguntas_nao_sei: list[str] = field(default_factory=list)

    @property
    def resolvidas_sem_humano_pct(self) -> float:
        """% aproximada de conversas sem transferência (transferências / conversas)."""
        if not self.conversas:
            return 0.0
        return max(0.0, (self.conversas - self.transferencias) / self.conversas * 100)

    @property
    def custo_brl(self) -> float:
        """Custo da Claude API em R$ pelo câmbio configurado."""
        return self.custo_usd * config.obter().cambio_brl

    @property
    def custo_meta_brl(self) -> float:
        """Estimativa simples da Meta: preço por mensagem acima da franquia mensal (config)."""
        cfg = config.obter()
        return max(0, self.mensagens_enviadas - cfg.meta_franquia_msgs) * cfg.meta_preco_msg_brl


def periodo_do_mes(ano: int, mes: int) -> tuple[date, date]:
    """Primeiro dia do mês e primeiro dia do mês seguinte."""
    inicio = date(ano, mes, 1)
    fim = date(ano + (mes == 12), mes % 12 + 1, 1)
    return inicio, fim


def calcular(ano: int, mes: int) -> Metricas:
    """Lê o banco e calcula as métricas do mês."""
    inicio, fim = periodo_do_mes(ano, mes)
    m = Metricas(inicio=inicio, fim=fim)
    faixa = (inicio.isoformat(), fim.isoformat())
    with db.conexao() as con:
        def um(sql: str, *extra: object) -> int:
            return con.execute(sql, (*faixa, *extra)).fetchone()[0] or 0

        entre = "criado_em >= ? AND criado_em < ?"
        m.contatos = um(f"SELECT COUNT(DISTINCT conversa_id) FROM mensagens WHERE {entre} AND direcao = 'entrada'")
        m.conversas = um(f"SELECT COUNT(*) FROM mensagens WHERE {entre} AND com_aviso_ia = 1")
        m.mensagens_enviadas = um(
            f"SELECT COUNT(*) FROM mensagens WHERE {entre} AND direcao = 'saida' AND tipo != 'erro_envio'"
        )
        recebidas = con.execute(
            f"SELECT criado_em FROM mensagens WHERE {entre} AND direcao = 'entrada'", faixa
        ).fetchall()
        m.mensagens_recebidas = len(recebidas)
        m.recebidas_fora_do_horario = sum(
            not horario.dentro_do_horario(datetime.fromisoformat(r[0])) for r in recebidas
        )
        for origem, n in con.execute(
            f"SELECT origem, COUNT(*) FROM transferencias WHERE {entre} GROUP BY origem", faixa
        ):
            m.transferencias_por_origem[origem] = n
        m.transferencias = sum(m.transferencias_por_origem.values())
        m.agendamentos = um(f"SELECT COUNT(*) FROM chamadas_ferramenta WHERE {entre} AND nome = 'agendar' AND erro = 0")
        m.cancelamentos = um(
            f"SELECT COUNT(*) FROM chamadas_ferramenta WHERE {entre} AND nome = 'cancelar_agendamento' AND erro = 0"
        )
        uso = con.execute(
            "SELECT COUNT(*), SUM(input_tokens), SUM(cache_criacao_tokens), SUM(cache_leitura_tokens),"
            f" SUM(output_tokens), SUM(custo_usd) FROM uso_tokens WHERE {entre} AND origem IN ('atendimento', 'documentos')",
            faixa,
        ).fetchone()
        (m.chamadas_api, m.input_tokens, m.cache_criacao_tokens,
         m.cache_leitura_tokens, m.output_tokens) = (int(v or 0) for v in uso[:5])
        m.custo_usd = float(uso[5] or 0)
        m.perguntas_nao_sei = [
            linha[0] for linha in con.execute(
                "SELECT (SELECT e.texto FROM mensagens e WHERE e.conversa_id = s.conversa_id"
                "  AND e.direcao = 'entrada' AND e.id < s.id ORDER BY e.id DESC LIMIT 1)"
                " FROM mensagens s WHERE s.criado_em >= ? AND s.criado_em < ? AND s.tipo = 'nao_sei'"
                " ORDER BY s.id",
                faixa,
            ) if linha[0]
        ]
    return m
