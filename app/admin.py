"""Painel simples para a equipe do cliente: conversas, assumir/devolver, responder e custo do mês."""

from __future__ import annotations

import secrets
from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import config, conversas, db, metricas
from app.atendimento import Dependencias, dependencias_padrao

router = APIRouter(prefix="/admin")
_basic = HTTPBasic()

ESTILO = """<style>
body{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left}
.entrada{background:#f3f3f3}.saida{background:#e7f5ea}.msg{padding:8px;margin:6px 0;border-radius:6px;white-space:pre-wrap}
.humano{color:#b00;font-weight:600}button{padding:6px 12px;margin-right:6px}textarea{width:100%}
small{color:#666}
</style>"""


def autenticar(request: Request, cred: HTTPBasicCredentials = Depends(_basic)) -> None:
    """Login do navegador (usuário qualquer, senha = ADMIN_TOKEN) e trava simples contra CSRF."""
    token = config.obter().admin_token
    if not token:
        raise HTTPException(status_code=503, detail="Defina ADMIN_TOKEN para usar o painel.")
    if not secrets.compare_digest(cred.password.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Senha inválida", headers={"WWW-Authenticate": "Basic"})
    origem = request.headers.get("origin")
    if request.method == "POST" and origem and origem.split("://")[-1] != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Origem inválida")


def _pagina(titulo: str, corpo: str) -> HTMLResponse:
    """Envolve o conteúdo num HTML mínimo."""
    return HTMLResponse(
        f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width'><title>{escape(titulo)}</title>{ESTILO}</head>"
        f"<body><h1>{escape(titulo)}</h1>{corpo}</body></html>"
    )


@router.get("", dependencies=[Depends(autenticar)])
def inicio() -> HTMLResponse:
    """Resumo do mês e lista de conversas."""
    hoje = config.agora()
    m = metricas.calcular(hoje.year, hoje.month)
    resumo = (
        f"<p><b>{hoje:%m/%Y}</b>: {m.conversas} conversas, {m.transferencias} transferências, "
        f"{m.agendamentos} agendamentos, custo IA US$ {m.custo_usd:.2f} (R$ {m.custo_brl:.2f}), "
        f"{m.mensagens_enviadas} mensagens enviadas.</p>"
    )
    with db.conexao() as con:
        linhas = con.execute(
            "SELECT id, telefone, nome, estado, ultimo_contato FROM conversas ORDER BY ultimo_contato DESC LIMIT 200"
        ).fetchall()
    itens = "".join(
        f"<tr><td><a href='/admin/conversa/{c['id']}'>{escape(c['telefone'])}</a></td>"
        f"<td>{escape(c['nome'] or '')}</td>"
        f"<td class='{'humano' if c['estado'] == 'humano' else ''}'>{escape(c['estado'])}</td>"
        f"<td>{escape(c['ultimo_contato'][:16].replace('T', ' '))}</td></tr>"
        for c in linhas
    )
    tabela = f"<table><tr><th>Telefone</th><th>Nome</th><th>Estado</th><th>Último contato</th></tr>{itens}</table>"
    return _pagina(f"Atendimento – {config.obter().nome_negocio}", resumo + tabela)


@router.get("/conversa/{conversa_id}", dependencies=[Depends(autenticar)])
def ver_conversa(conversa_id: int) -> HTMLResponse:
    """Mensagens da conversa e botões de ação."""
    conversa = conversas.obter(conversa_id)
    if not conversa:
        raise HTTPException(status_code=404)
    with db.conexao() as con:
        msgs = con.execute(
            "SELECT direcao, autor, tipo, texto, criado_em FROM mensagens WHERE conversa_id = ?"
            " ORDER BY id DESC LIMIT 100", (conversa_id,)
        ).fetchall()
    blocos = "".join(
        f"<div class='msg {m['direcao']}'><small>{escape(m['criado_em'][:16].replace('T', ' '))} · "
        f"{escape(m['autor'])} · {escape(m['tipo'])}</small><br>{escape(m['texto'])}</div>"
        for m in reversed(msgs)
    )
    acao = "devolver" if conversa["estado"] == "humano" else "assumir"
    rotulo = "Devolver ao bot" if acao == "devolver" else "Assumir (pausa o bot)"
    pausa = f" até {escape(conversa['pausado_ate'][:16].replace('T', ' '))}" if conversa["pausado_ate"] else ""
    corpo = (
        f"<p><a href='/admin'>← voltar</a> · Estado: <b>{escape(conversa['estado'])}</b>{pausa}</p>"
        f"<form method='post' action='/admin/conversa/{conversa_id}/{acao}'><button>{rotulo}</button></form>"
        f"{blocos}"
        f"<form method='post' action='/admin/conversa/{conversa_id}/responder'>"
        f"<p><textarea name='texto' rows='3' required placeholder='Responder como atendente (pausa o bot)'></textarea></p>"
        f"<button>Enviar</button></form>"
    )
    return _pagina(conversa["telefone"], corpo)


@router.post("/conversa/{conversa_id}/assumir", dependencies=[Depends(autenticar)])
def assumir(conversa_id: int) -> RedirectResponse:
    """Humano assume: bot pausado por PAUSA_HUMANO_HORAS."""
    conversas.transferir_para_humano(conversa_id, "painel", "assumida pelo painel")
    return RedirectResponse(f"/admin/conversa/{conversa_id}", status_code=303)


@router.post("/conversa/{conversa_id}/devolver", dependencies=[Depends(autenticar)])
def devolver(conversa_id: int) -> RedirectResponse:
    """Devolve a conversa ao bot."""
    conversas.devolver_ao_bot(conversa_id)
    return RedirectResponse(f"/admin/conversa/{conversa_id}", status_code=303)


@router.post("/conversa/{conversa_id}/responder", dependencies=[Depends(autenticar)])
def responder(
    conversa_id: int, texto: str = Form(...), deps: Dependencias = Depends(dependencias_padrao)
) -> RedirectResponse:
    """Envia uma mensagem como atendente humano (dentro da janela de 24 h da Meta)."""
    conversa = conversas.obter(conversa_id)
    if not conversa:
        raise HTTPException(status_code=404)
    if conversa["estado"] != "humano":
        conversas.transferir_para_humano(conversa_id, "painel", "resposta manual pelo painel")
    id_meta = deps.whatsapp.enviar_texto(conversa["telefone"], texto)
    conversas.registrar_mensagem(conversa_id, "saida", "humano", texto, "texto", False, id_meta)
    return RedirectResponse(f"/admin/conversa/{conversa_id}", status_code=303)
