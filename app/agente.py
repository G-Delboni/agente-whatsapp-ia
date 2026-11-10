"""Agente de atendimento: monta o prompt, chama a Claude API e roda o loop de ferramentas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import config, horario
from app.agenda import Agenda
from app.custos import Uso
from app.ferramentas import FERRAMENTAS, ContextoFerramentas, executar

RESPOSTA_RECUSA = "Não consigo ajudar com isso por aqui. Quer que eu chame uma pessoa da equipe?"
RESPOSTA_FALHA = "Desculpe, não consegui concluir sua solicitação. Vou chamar uma pessoa da equipe."
PADRAO_NAO_SEI = re.compile(r"n[ãa]o sei|n[ãa]o tenho (essa|esta|essas) informa", re.IGNORECASE)
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@dataclass
class ChamadaFerramenta:
    """Registro de uma ferramenta executada."""

    nome: str
    entrada: dict[str, Any]
    resultado: str
    erro: bool


@dataclass
class Resposta:
    """Resultado de um turno do agente."""

    texto: str
    stop_reason: str
    motivo_transferencia: str | None = None
    usos: list[Uso] = field(default_factory=list)
    chamadas: list[ChamadaFerramenta] = field(default_factory=list)

    @property
    def nao_sei(self) -> bool:
        """True se o agente disse que não sabe (pergunta a levar para a base)."""
        return bool(PADRAO_NAO_SEI.search(self.texto))

    @property
    def custo_usd(self) -> float:
        """Custo somado de todas as chamadas do turno."""
        return sum(u.custo_usd for u in self.usos)


def carregar_kb(kb_dir: Path) -> str:
    """Concatena kb/*.md em ordem alfabética (ordem fixa = cache estável). Ignora README.md."""
    partes = []
    for arquivo in sorted(kb_dir.glob("*.md")):
        if arquivo.name.lower() == "readme.md":
            continue
        partes.append(f"<arquivo nome=\"{arquivo.name}\">\n{config.ler_texto(arquivo).strip()}\n</arquivo>")
    return "\n\n".join(partes)


def montar_system(cfg: config.Config) -> list[dict[str, Any]]:
    """Regras fixas + base de conhecimento num bloco único com cache no fim.

    Nada que muda por mensagem (data, telefone) entra aqui: qualquer byte diferente
    invalida o cache. Com cache, as leituras seguintes custam 10% da entrada no Haiku.
    """
    regras = config.ler_texto(cfg.prompts_dir / "system.md").replace("{NOME_NEGOCIO}", cfg.nome_negocio)
    texto = f"{regras.strip()}\n\n# Base de conhecimento\n\n{carregar_kb(cfg.kb_dir)}"
    return [{"type": "text", "text": texto, "cache_control": {"type": "ephemeral"}}]


def contexto_do_turno(telefone: str) -> str:
    """Dados que mudam a cada mensagem; vão no fim (depois do cache), na mensagem do usuário."""
    agora = config.agora()
    humano = "sim" if horario.dentro_do_horario(agora) else "não"
    return (
        f"<contexto>Agora: {DIAS[agora.weekday()]}, {agora:%Y-%m-%d %H:%M} (horário de Brasília). "
        f"Telefone do contato: {telefone}. Equipe humana trabalhando agora: {humano}.</contexto>"
    )


def _texto(conteudo: list[Any]) -> str:
    """Junta os blocos de texto da resposta."""
    return "\n".join(b.text for b in conteudo if b.type == "text").strip()


def responder(
    historico: list[dict[str, Any]],
    texto_usuario: str,
    telefone: str,
    cliente: Any,
    agenda: Agenda,
) -> Resposta:
    """Roda um turno: chama o modelo, executa ferramentas até `end_turn` ou limite."""
    cfg = config.obter()
    mensagens = list(historico) + [{
        "role": "user",
        "content": [
            {"type": "text", "text": contexto_do_turno(telefone)},
            {"type": "text", "text": texto_usuario},
        ],
    }]
    parametros: dict[str, Any] = {
        "model": cfg.modelo,
        "max_tokens": cfg.max_tokens,  # respostas curtas: 1 mensagem de WhatsApp
        "system": montar_system(cfg),
        "tools": FERRAMENTAS,
    }
    if cfg.esforco and cfg.esforco != "padrao":
        parametros["output_config"] = {"effort": cfg.esforco}

    ctx = ContextoFerramentas(agenda=agenda, telefone=telefone)
    resultado = Resposta(texto="", stop_reason="")
    partes: list[str] = []  # texto de todas as iterações (ex.: aviso do 192 antes de transferir)
    for _ in range(cfg.max_iteracoes_ferramentas):
        resposta = cliente.messages.create(messages=mensagens, **parametros)
        resultado.usos.append(Uso.da_resposta(cfg.modelo, resposta.usage))
        resultado.stop_reason = resposta.stop_reason
        if (parte := _texto(resposta.content)) and parte not in partes:
            partes.append(parte)

        if resposta.stop_reason == "tool_use":
            mensagens.append({"role": "assistant", "content": resposta.content})
            retornos = []
            for bloco in resposta.content:
                if bloco.type != "tool_use":
                    continue
                saida, erro = executar(bloco.name, dict(bloco.input), ctx)
                resultado.chamadas.append(ChamadaFerramenta(bloco.name, dict(bloco.input), saida, erro))
                retorno: dict[str, Any] = {"type": "tool_result", "tool_use_id": bloco.id, "content": saida}
                if erro:
                    retorno["is_error"] = True
                retornos.append(retorno)
            mensagens.append({"role": "user", "content": retornos})
            continue

        if resposta.stop_reason == "pause_turn":  # só ocorre com ferramentas de servidor
            mensagens.append({"role": "assistant", "content": resposta.content})
            continue

        if resposta.stop_reason == "refusal":
            resultado.texto = RESPOSTA_RECUSA
        else:  # end_turn, stop_sequence ou max_tokens (usa o texto parcial, se houver)
            resultado.texto = "\n\n".join(partes) or RESPOSTA_FALHA
        break
    else:
        # Estourou o limite de iterações: não deixa o cliente sem resposta.
        resultado.texto = RESPOSTA_FALHA
        ctx.motivo_transferencia = ctx.motivo_transferencia or "limite de iterações do agente"

    if resultado.texto == RESPOSTA_FALHA and not ctx.motivo_transferencia:
        ctx.motivo_transferencia = f"falha do agente ({resultado.stop_reason})"
    resultado.motivo_transferencia = ctx.motivo_transferencia
    return resultado


def criar_cliente_anthropic() -> Any:
    """Cliente real da Claude API (lê ANTHROPIC_API_KEY do ambiente)."""
    import anthropic

    return anthropic.Anthropic(timeout=30.0, max_retries=2)
