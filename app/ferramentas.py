"""Ferramentas do agente: definições (strict) e execução no nosso código."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app import config
from app.agenda import Agenda, ErroAgenda


def _ferramenta(nome: str, descricao: str, propriedades: dict[str, Any]) -> dict[str, Any]:
    """Monta uma ferramenta com `strict: true` (a API garante nome e entrada válidos)."""
    return {
        "name": nome,
        "description": descricao,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propriedades,
            "required": list(propriedades),
            "additionalProperties": False,
        },
    }


_TEXTO = {"type": "string"}

# Lista fixa e em ordem estável: ferramentas entram no início do prompt,
# então mudar a lista invalida o cache (e encarece todas as chamadas).
FERRAMENTAS: list[dict[str, Any]] = [
    _ferramenta(
        "agendar",
        "Marca um horário. Use só depois de consultar_horarios e de o cliente confirmar "
        "nome, data e hora. data_hora no formato AAAA-MM-DDTHH:MM (horário de Brasília). "
        "telefone vazio usa o número do WhatsApp. observacao pode ser vazia.",
        {"nome": _TEXTO, "telefone": _TEXTO, "data_hora": _TEXTO, "observacao": _TEXTO},
    ),
    _ferramenta(
        "cancelar_agendamento",
        "Cancela um agendamento do cliente após ele confirmar. data_hora AAAA-MM-DDTHH:MM, "
        "ou vazia para o próximo agendamento. telefone vazio usa o número do WhatsApp. "
        "Para remarcar: cancele e depois agende o novo horário.",
        {"telefone": _TEXTO, "data_hora": _TEXTO},
    ),
    _ferramenta(
        "consultar_horarios",
        "Lista horários livres para consulta numa data (AAAA-MM-DD).",
        {"data": {"type": "string", "format": "date"}},
    ),
    _ferramenta(
        "transferir_para_humano",
        "Passa a conversa para a equipe. Use quando: o cliente pedir uma pessoa; o assunto "
        "for sintoma, diagnóstico, remédio, resultado de exame, questão jurídica ou financeira "
        "pessoal; reclamação; ou quando você não souber responder e o cliente quiser ajuda.",
        {"motivo": _TEXTO},
    ),
]


@dataclass
class ContextoFerramentas:
    """Dados da conversa que as ferramentas precisam (e o que elas decidiram)."""

    agenda: Agenda
    telefone: str
    motivo_transferencia: str | None = None


def _data_hora(texto: str) -> datetime:
    """Lê 'AAAA-MM-DDTHH:MM' no fuso do negócio."""
    return datetime.strptime(texto.strip()[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=config.obter().tz)


def executar(nome: str, entrada: dict[str, Any], ctx: ContextoFerramentas) -> tuple[str, bool]:
    """Executa a ferramenta e devolve (texto do resultado, houve_erro)."""
    try:
        if nome == "consultar_horarios":
            dia = date.fromisoformat(entrada["data"])
            livres = ctx.agenda.horarios_livres(dia)
            if not livres:
                return f"Sem horários livres em {dia:%d/%m/%Y}.", False
            return f"Horários livres em {dia:%d/%m/%Y}: {', '.join(livres)}.", False
        if nome == "agendar":
            telefone = entrada["telefone"].strip() or ctx.telefone
            resultado = ctx.agenda.agendar(
                entrada["nome"], telefone, _data_hora(entrada["data_hora"]), entrada["observacao"]
            )
            return resultado, False
        if nome == "cancelar_agendamento":
            telefone = entrada["telefone"].strip() or ctx.telefone
            quando = _data_hora(entrada["data_hora"]) if entrada["data_hora"].strip() else None
            return ctx.agenda.cancelar(telefone, quando), False
        if nome == "transferir_para_humano":
            ctx.motivo_transferencia = entrada["motivo"] or "sem motivo informado"
            return "Transferência registrada. Avise o cliente que uma pessoa da equipe vai responder.", False
        return f"Ferramenta desconhecida: {nome}", True
    except ErroAgenda as erro:
        return str(erro), True
    except (ValueError, KeyError) as erro:
        return f"Entrada inválida: {erro}", True


def serializar(entrada: dict[str, Any]) -> str:
    """JSON estável para log."""
    return json.dumps(entrada, ensure_ascii=False, sort_keys=True)
