"""Mídia (PDF ou imagem) recebida no WhatsApp com MODO_DOCUMENTOS=1: baixa, extrai, lança e responde.

Tudo entra na planilha e no banco como 'aguardando_aprovacao'; o contador aprova antes de lançar.
O custo da extração vai para `uso_tokens` com origem 'documentos'.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app import config, conversas, db
from app.documentos import checklist, cobranca, extrator, planilha

log = logging.getLogger("documentos")

NAO_IDENTIFICADO = "nao-identificado"
RESPOSTA_FALHA = "Recebi seu arquivo, mas não consegui processar agora. A equipe vai conferir e te avisa."


def _checklist(cfg: config.Config) -> checklist.Checklist | None:
    """Checklist do escritório, se o arquivo existir."""
    return checklist.carregar(cfg.checklist_documentos) if cfg.checklist_documentos.exists() else None


def _guardar_arquivo(cfg: config.Config, id_cliente: str, doc: extrator.DocumentoProcessado, dados: bytes) -> Path:
    """Salva o original para a revisão do contador: documentos/<cliente>/<hash><extensão>."""
    extensao = Path(doc.arquivo).suffix.lower() or {"pdf": ".pdf", "imagem": ".jpg", "xml": ".xml"}.get(doc.tipo, "")
    destino = cfg.documentos_dir / planilha.nome_seguro(id_cliente) / f"{doc.hash}{extensao}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    return destino


def _registrar(conversa_id: int | None, id_cliente: str, doc: extrator.DocumentoProcessado) -> None:
    """Grava a extração no banco como aguardando aprovação."""
    with db.conexao() as con:
        con.execute(
            "INSERT INTO documentos_recebidos (conversa_id, cliente_id, arquivo, hash, categoria, valor, revisar,"
            " motivos, extracao, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (conversa_id, id_cliente, doc.arquivo, doc.hash, doc.extracao.categoria, doc.extracao.valor_total,
             int(doc.revisar), "; ".join(doc.motivos_revisao), doc.extracao.model_dump_json(),
             config.agora().isoformat()),
        )


def atualizar_pendencias(caminho: Path, cliente: checklist.ClienteEscritorio,
                         competencia: str) -> list[checklist.Pendencia]:
    """Recalcula o que falta na competência e reescreve a aba Pendências."""
    recebidas = planilha.categorias_da_competencia(planilha.ler_lancamentos(caminho), competencia)
    pendencias = checklist.calcular_pendencias(cliente, recebidas)
    planilha.escrever_pendencias(caminho, competencia, pendencias)
    return pendencias


def processar_midia(msg: Any, llm: Any, whatsapp: Any, conversa_id: int | None) -> str:
    """Baixa, extrai, lança na planilha do cliente e devolve o texto da resposta (uma mensagem)."""
    cfg = config.obter()
    try:
        dados, mime = whatsapp.baixar_midia(msg.media_id)
        nome = msg.nome_arquivo or f"{msg.media_id}{_extensao(msg.mime or mime)}"
        doc = extrator.extrair_bytes(dados, nome, msg.mime or mime, llm)
        conversas.registrar_uso(conversa_id, doc.usos, origem="documentos")
        lista = _checklist(cfg)
        cliente = lista.por_telefone(msg.telefone) if lista else None
        id_cliente = cliente.id if cliente else NAO_IDENTIFICADO
        _guardar_arquivo(cfg, id_cliente, doc, dados)
        caminho = planilha.caminho_planilha(cfg.planilhas_dir, id_cliente)
        planilha.adicionar_lancamentos(caminho, [doc], config.agora())
        _registrar(conversa_id, id_cliente, doc)
        competencia = (doc.extracao.data_emissao or config.agora().strftime("%Y-%m"))[:7]
        pendencias = atualizar_pendencias(caminho, cliente, competencia) if cliente else None
    except Exception:
        log.exception("Falha ao processar documento %s", getattr(msg, "media_id", "?"))
        return RESPOSTA_FALHA
    return cobranca.mensagem_recebido(doc, pendencias, checklist.nome_do_mes(competencia))


def _extensao(mime: str) -> str:
    """Extensão a partir do MIME ('image/jpeg' → '.jpg')."""
    mime = mime.split(";")[0].strip().lower()
    return next((ext for ext, m in extrator.MIME_POR_EXTENSAO.items() if m == mime), "")
