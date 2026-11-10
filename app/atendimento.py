"""Fluxo de uma mensagem recebida: guardas, aviso de IA, humano no circuito, agente, resposta."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app import agente, config, conversas, db, guardas, horario
from app.agenda import Agenda
from app.transcricao import Transcritor, TranscritorDesligado
from app.whatsapp import MensagemRecebida

log = logging.getLogger("atendimento")

MSG_AVISO_IA = (
    "Olá! Sou o assistente virtual da {nome} e respondo automaticamente. "
    "Para falar com uma pessoa, escreva HUMANO."
)
MSG_PEDIR_TEXTO = "Ainda não consigo ouvir áudios ou abrir arquivos por aqui. Pode escrever sua dúvida em texto?"
MSG_TRANSFERENCIA = "Certo! Vou passar sua conversa para uma pessoa da equipe."


@dataclass
class Dependencias:
    """Serviços externos, injetados para facilitar testes (fakes) e trocas por cliente."""

    whatsapp: Any  # ClienteWhatsApp ou fake com a mesma interface
    llm: Any  # anthropic.Anthropic ou cliente falso
    agenda: Agenda
    transcritor: Transcritor


_travas: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_trava_global = threading.Lock()


def _trava(telefone: str) -> threading.Lock:
    """Uma trava por telefone: mensagens do mesmo cliente são processadas em ordem."""
    with _trava_global:
        return _travas[telefone]


def processar_mensagem(msg: MensagemRecebida, deps: Dependencias) -> None:
    """Ponto de entrada chamado em background pelo webhook."""
    with _trava(msg.telefone):
        try:
            _processar(msg, deps)
        except Exception:  # nunca derruba o worker; o erro fica no log da hospedagem
            log.exception("Falha ao processar mensagem %s", msg.id_meta)


def _processar(msg: MensagemRecebida, deps: Dependencias) -> None:
    """Regras do atendimento, na ordem em que se aplicam."""
    cfg = config.obter()
    if cfg.numero_responsavel and msg.telefone == cfg.numero_responsavel and msg.texto.lower().startswith("#bot"):
        _comando_responsavel(msg, deps)
        return
    _sem_falhar(deps.whatsapp.marcar_como_lida, msg.id_meta)
    if guardas.excedeu_mensagens_por_hora(msg.telefone):
        log.warning("Limite de mensagens por hora atingido para final %s", msg.telefone[-4:])
        return

    conversa = conversas.obter_ou_criar(msg.telefone, msg.nome)
    cid = conversa["id"]
    aviso = conversas.precisa_aviso_ia(conversa)
    historico = conversas.historico(cid)
    texto = _texto_da_mensagem(msg, deps)
    conversas.registrar_mensagem(
        cid, "entrada", "cliente", texto or f"[{msg.tipo} sem texto]",
        tipo="audio" if msg.tipo == "audio" else "texto", id_meta=msg.id_meta,
    )

    if conversas.bot_pausado(conversa):
        return  # um humano está atendendo esta conversa
    if cfg.modo_documentos and msg.tipo in ("image", "document") and msg.media_id:
        from app.documentos import recebimento  # import tardio: openpyxl só é exigido no nível 2

        resumo = recebimento.processar_midia(msg, deps.llm, deps.whatsapp, cid)
        _responder(deps, conversa, resumo, aviso, "documento")
        return
    if not texto:
        _responder(deps, conversa, MSG_PEDIR_TEXTO, aviso, "pedir_texto")
        return
    texto = guardas.truncar_entrada(texto)

    if conversas.quer_humano(texto):
        _transferir(deps, conversa, "cliente", "cliente pediu atendente")
        frase = f"{MSG_TRANSFERENCIA} {horario.quando_humano_responde(config.agora())}"
        _responder(deps, conversa, frase, aviso, "transferencia")
        return

    if guardas.limite_gasto_atingido():
        if db.registrar_evento_unico(f"limite-gasto-{config.agora():%Y-%m-%d}"):
            notificar_humano(deps, "SISTEMA", "limite diário de gasto da IA atingido")
        _responder(deps, conversa, guardas.MENSAGEM_LIMITE_GASTO, aviso, "limite")
        return

    try:
        resposta = agente.responder(historico, texto, msg.telefone, deps.llm, deps.agenda)
    except Exception:
        log.exception("Erro ao chamar a Claude API")
        _transferir(deps, conversa, "sistema", "erro técnico no agente")
        _responder(deps, conversa, agente.RESPOSTA_FALHA, aviso, "transferencia")
        return

    conversas.registrar_uso(cid, resposta.usos)
    conversas.registrar_chamadas(cid, resposta.chamadas)
    texto_final, tipo = resposta.texto, ("nao_sei" if resposta.nao_sei else "texto")
    if resposta.motivo_transferencia:
        _transferir(deps, conversa, "modelo", resposta.motivo_transferencia)
        if not horario.dentro_do_horario(config.agora()):
            texto_final += "\n\n" + horario.quando_humano_responde(config.agora())
        tipo = "transferencia"
    _responder(deps, conversa, texto_final, aviso, tipo)


def _texto_da_mensagem(msg: MensagemRecebida, deps: Dependencias) -> str:
    """Texto da mensagem; áudio passa pelo transcritor (vazio = pedir para escrever)."""
    if msg.tipo == "audio" and msg.media_id:
        if isinstance(deps.transcritor, TranscritorDesligado):
            return ""  # transcrição desligada: nem baixa o áudio
        try:
            audio, mime = deps.whatsapp.baixar_midia(msg.media_id)
            return deps.transcritor.transcrever(audio, mime) or ""
        except Exception:
            log.exception("Falha ao baixar/transcrever áudio")
            return ""
    return msg.texto


def _responder(deps: Dependencias, conversa: Any, texto: str, aviso: bool, tipo: str) -> None:
    """Envia UMA mensagem (aviso de IA junto, quando preciso) e grava no banco.

    Juntar aviso e resposta numa mensagem só reduz ruído e o número de mensagens
    contadas/cobradas pela Meta.
    """
    if aviso:
        texto = MSG_AVISO_IA.format(nome=config.obter().nome_negocio) + "\n\n" + texto
    id_meta = None
    try:
        id_meta = deps.whatsapp.enviar_texto(conversa["telefone"], texto)
    except Exception:
        log.exception("Falha ao enviar mensagem pelo WhatsApp")
        tipo = "erro_envio"
    conversas.registrar_mensagem(conversa["id"], "saida", "bot", texto, tipo, aviso, id_meta)


def _transferir(deps: Dependencias, conversa: Any, origem: str, motivo: str) -> None:
    """Muda a conversa para humano e avisa o responsável."""
    conversas.transferir_para_humano(conversa["id"], origem, motivo)
    notificar_humano(deps, conversa["telefone"], motivo)


def notificar_humano(deps: Dependencias, telefone: str, motivo: str) -> None:
    """Avisa o responsável no WhatsApp dele (template, se configurado; senão texto livre).

    Texto livre só chega se o responsável falou com o número nas últimas 24 h;
    para garantir a entrega, aprove um template na Meta e defina TEMPLATE_AVISO_RESPONSAVEL
    (corpo com 2 variáveis: {{1}} telefone, {{2}} motivo).
    """
    cfg = config.obter()
    if not cfg.numero_responsavel:
        log.warning("NUMERO_RESPONSAVEL vazio: transferência de final %s sem aviso", telefone[-4:])
        return
    motivo = guardas.mascarar_sensiveis(motivo)[:200]
    if cfg.template_aviso_responsavel:
        _sem_falhar(deps.whatsapp.enviar_template, cfg.numero_responsavel,
                    cfg.template_aviso_responsavel, [telefone, motivo])
    else:
        texto = (f"[{cfg.nome_negocio}] Atendimento humano pedido por {telefone}: {motivo}. "
                 f"Veja no painel /admin. Para devolver ao bot, envie: #bot {telefone}")
        _sem_falhar(deps.whatsapp.enviar_texto, cfg.numero_responsavel, texto)


def _comando_responsavel(msg: MensagemRecebida, deps: Dependencias) -> None:
    """Comando '#bot <telefone>' enviado pelo responsável devolve a conversa ao bot."""
    partes = msg.texto.split()
    alvo = "".join(ch for ch in (partes[1] if len(partes) > 1 else "") if ch.isdigit())
    ok = bool(alvo) and conversas.devolver_por_telefone(alvo)
    resposta = f"Bot retomado para {alvo}." if ok else "Use: #bot 5519999999999 (telefone com DDI e DDD)."
    _sem_falhar(deps.whatsapp.enviar_texto, msg.telefone, resposta)


def _sem_falhar(funcao: Any, *args: Any) -> Any:
    """Chama uma função de rede sem deixar a falha interromper o atendimento."""
    try:
        return funcao(*args)
    except Exception:
        log.exception("Falha em %s", getattr(funcao, "__name__", funcao))
        return None


_padrao: Dependencias | None = None


def dependencias_padrao() -> Dependencias:
    """Serviços reais (criados uma vez): WhatsApp, Claude API, agenda local e transcrição."""
    global _padrao
    if _padrao is None:
        from app.agenda_local import AgendaLocal
        from app.transcricao import criar_transcritor
        from app.whatsapp import ClienteWhatsApp

        _padrao = Dependencias(
            whatsapp=ClienteWhatsApp(),
            llm=agente.criar_cliente_anthropic(),
            agenda=AgendaLocal(),  # troque por AgendaGoogle.do_ambiente() quando ativar
            transcritor=criar_transcritor(),
        )
    return _padrao
