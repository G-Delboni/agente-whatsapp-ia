"""Webhook da WhatsApp Cloud API: verificação, assinatura, deduplicação e fila em background."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app import config, db
from app.atendimento import Dependencias, dependencias_padrao, processar_mensagem
from app.whatsapp import extrair_mensagens

log = logging.getLogger("webhook")
router = APIRouter()


def assinatura_valida(corpo: bytes, cabecalho: str | None, app_secret: str) -> bool:
    """Confere X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(corpo, App Secret)."""
    if not cabecalho or not app_secret or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.removeprefix("sha256="))


@router.get("/webhook")
def verificar(
    modo: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    desafio: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    """A Meta chama este GET uma vez ao cadastrar o webhook e espera o challenge de volta."""
    esperado = config.obter().meta_verify_token
    if modo == "subscribe" and esperado and hmac.compare_digest(token, esperado):
        return PlainTextResponse(desafio)
    raise HTTPException(status_code=403, detail="token de verificação inválido")


@router.post("/webhook")
async def receber(
    request: Request,
    tarefas: BackgroundTasks,
    deps: Dependencias = Depends(dependencias_padrao),
) -> dict[str, int]:
    """Valida, deduplica e agenda o processamento; responde 200 rápido (a Meta reenvia se demorar)."""
    corpo = await request.body()
    if not assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256"), config.obter().meta_app_secret):
        raise HTTPException(status_code=401, detail="assinatura inválida")
    try:
        payload = json.loads(corpo)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    novas = 0
    for msg in extrair_mensagens(payload):
        if db.registrar_evento_unico(msg.id_meta):  # a Meta pode entregar o mesmo evento mais de uma vez
            tarefas.add_task(processar_mensagem, msg, deps)
            novas += 1
    return {"recebidas": novas}
