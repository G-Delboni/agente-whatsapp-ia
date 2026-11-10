"""WhatsApp Cloud API (Meta): leitura dos eventos do webhook e envio de mensagens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app import config


@dataclass
class MensagemRecebida:
    """Uma mensagem de cliente extraída do webhook."""

    id_meta: str
    telefone: str
    nome: str | None
    tipo: str  # 'text', 'interactive', 'button', 'audio', 'image', 'document' ou outro
    texto: str = ""
    media_id: str | None = None
    mime: str = ""  # imagem e documento (nível 2)
    nome_arquivo: str = ""


def extrair_mensagens(payload: dict[str, Any]) -> list[MensagemRecebida]:
    """Lê `entry[].changes[].value.messages[]`; ignora status (entregue/lida) e outros campos."""
    resultado: list[MensagemRecebida] = []
    for entrada in payload.get("entry", []):
        for mudanca in entrada.get("changes", []):
            valor = mudanca.get("value", {})
            nomes = {c.get("wa_id"): c.get("profile", {}).get("name") for c in valor.get("contacts", [])}
            for msg in valor.get("messages", []):
                tipo = msg.get("type", "")
                texto, media_id, mime, nome_arquivo = "", None, "", ""
                if tipo == "text":
                    texto = msg.get("text", {}).get("body", "")
                elif tipo == "interactive":
                    interativo = msg.get("interactive", {})
                    resposta = interativo.get("button_reply") or interativo.get("list_reply") or {}
                    texto = resposta.get("title", "")
                elif tipo == "button":  # resposta rápida de template
                    texto = msg.get("button", {}).get("text", "")
                elif tipo == "audio":
                    media_id = msg.get("audio", {}).get("id")
                elif tipo in ("image", "document"):  # usados só com MODO_DOCUMENTOS=1
                    midia = msg.get(tipo, {})
                    media_id, mime = midia.get("id"), midia.get("mime_type", "")
                    nome_arquivo = midia.get("filename", "")
                    texto = midia.get("caption", "")
                resultado.append(MensagemRecebida(
                    id_meta=msg["id"], telefone=msg["from"], nome=nomes.get(msg["from"]),
                    tipo=tipo, texto=texto.strip(), media_id=media_id, mime=mime, nome_arquivo=nome_arquivo,
                ))
    return resultado


class ClienteWhatsApp:
    """Cliente httpx da Graph API para um número (phone_number_id) do cliente."""

    def __init__(self, cfg: config.Config | None = None, http: httpx.Client | None = None) -> None:
        self.cfg = cfg or config.obter()
        self.base = f"https://graph.facebook.com/{self.cfg.graph_api_versao}"
        self.http = http or httpx.Client(timeout=20.0)
        self.cabecalhos = {"Authorization": f"Bearer {self.cfg.meta_token}"}

    def _enviar(self, corpo: dict[str, Any]) -> str | None:
        """POST em /messages; devolve o id da mensagem enviada."""
        url = f"{self.base}/{self.cfg.meta_phone_number_id}/messages"
        resp = self.http.post(url, json={"messaging_product": "whatsapp", **corpo}, headers=self.cabecalhos)
        resp.raise_for_status()
        mensagens = resp.json().get("messages", [])
        return mensagens[0].get("id") if mensagens else None

    def enviar_texto(self, para: str, texto: str) -> str | None:
        """Texto livre: só funciona até 24 h depois da última mensagem do cliente."""
        return self._enviar({"to": para, "type": "text", "text": {"body": texto[:4096]}})

    def enviar_template(self, para: str, nome: str, variaveis: list[str], idioma: str = "pt_BR") -> str | None:
        """Template aprovado na Meta (necessário fora da janela de 24 h)."""
        componentes = [{
            "type": "body",
            "parameters": [{"type": "text", "text": v} for v in variaveis],
        }] if variaveis else []
        return self._enviar({
            "to": para, "type": "template",
            "template": {"name": nome, "language": {"code": idioma}, "components": componentes},
        })

    def marcar_como_lida(self, id_meta: str) -> None:
        """Mostra os dois tiques azuis para o cliente."""
        url = f"{self.base}/{self.cfg.meta_phone_number_id}/messages"
        corpo = {"messaging_product": "whatsapp", "status": "read", "message_id": id_meta}
        self.http.post(url, json=corpo, headers=self.cabecalhos).raise_for_status()

    def baixar_midia(self, media_id: str) -> tuple[bytes, str]:
        """Busca a URL temporária da mídia e baixa o arquivo (bytes, mime_type)."""
        meta = self.http.get(f"{self.base}/{media_id}", headers=self.cabecalhos)
        meta.raise_for_status()
        dados = meta.json()
        arquivo = self.http.get(dados["url"], headers=self.cabecalhos)
        arquivo.raise_for_status()
        return arquivo.content, dados.get("mime_type", "audio/ogg")
