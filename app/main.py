"""Aplicação FastAPI: `uvicorn app.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import admin, db, webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    """Cria as tabelas ao subir o servidor."""
    db.criar_tabelas()
    yield


app = FastAPI(title="Atendente virtual", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)
app.include_router(webhook.router)
app.include_router(admin.router)


@app.get("/saude")
def saude() -> dict[str, str]:
    """Verificação simples para a hospedagem (health check)."""
    return {"status": "ok"}
