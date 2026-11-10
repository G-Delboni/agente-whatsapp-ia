"""Agenda guardada no próprio SQLite: boa para protótipo e piloto."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app import config, db
from app.agenda import ErroAgenda
from app.horario import faixa_do_dia

FORMATO = "%Y-%m-%dT%H:%M"


class AgendaLocal:
    """Agenda simples: horários em blocos fixos dentro do expediente configurado."""

    def _slots(self, dia: date) -> list[datetime]:
        """Todos os horários possíveis do dia, ignorando ocupação."""
        faixa = faixa_do_dia(dia.weekday())
        if not faixa:
            return []
        tz = config.obter().tz
        passo = timedelta(minutes=config.obter().duracao_consulta_min)
        atual = datetime.combine(dia, faixa[0], tzinfo=tz)
        fim = datetime.combine(dia, faixa[1], tzinfo=tz)
        slots = []
        while atual + passo <= fim:
            slots.append(atual)
            atual += passo
        return slots

    def _ocupados(self, dia: date) -> set[str]:
        """Horários 'HH:MM' já marcados no dia."""
        with db.conexao() as con:
            linhas = con.execute(
                "SELECT data_hora FROM agendamentos WHERE status = 'ativo' AND data_hora LIKE ?",
                (f"{dia.isoformat()}T%",),
            ).fetchall()
        return {linha["data_hora"][11:16] for linha in linhas}

    def horarios_livres(self, dia: date) -> list[str]:
        """Horários livres e futuros no dia."""
        agora = config.agora()
        ocupados = self._ocupados(dia)
        return [
            s.strftime("%H:%M") for s in self._slots(dia)
            if s > agora and s.strftime("%H:%M") not in ocupados
        ]

    def agendar(self, nome: str, telefone: str, data_hora: datetime, observacao: str) -> str:
        """Marca se o horário estiver livre."""
        if data_hora.strftime("%H:%M") not in self.horarios_livres(data_hora.date()):
            raise ErroAgenda("Horário indisponível. Consulte os horários livres e ofereça outro.")
        with db.conexao() as con:
            cur = con.execute(
                "INSERT INTO agendamentos (nome, telefone, data_hora, observacao, criado_em)"
                " VALUES (?, ?, ?, ?, ?)",
                (nome, telefone, data_hora.strftime(FORMATO), observacao, config.agora().isoformat()),
            )
        return f"Agendamento #{cur.lastrowid} confirmado para {data_hora:%d/%m/%Y às %H:%M}."

    def cancelar(self, telefone: str, data_hora: datetime | None) -> str:
        """Cancela o agendamento indicado ou o próximo do telefone."""
        sql = "SELECT id, data_hora FROM agendamentos WHERE status = 'ativo' AND telefone = ?"
        params: list[str] = [telefone]
        if data_hora:
            sql += " AND data_hora = ?"
            params.append(data_hora.strftime(FORMATO))
        else:
            sql += " AND data_hora >= ?"
            params.append(config.agora().strftime(FORMATO))
        with db.conexao() as con:
            linha = con.execute(sql + " ORDER BY data_hora LIMIT 1", params).fetchone()
            if not linha:
                raise ErroAgenda("Nenhum agendamento ativo encontrado para este telefone.")
            con.execute("UPDATE agendamentos SET status = 'cancelado' WHERE id = ?", (linha["id"],))
        quando = datetime.strptime(linha["data_hora"], FORMATO)
        return f"Agendamento de {quando:%d/%m/%Y às %H:%M} cancelado."
