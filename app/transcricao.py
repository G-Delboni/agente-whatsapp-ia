"""Transcrição de áudio: desligada por padrão; opcional via API compatível com Whisper."""

from __future__ import annotations

from typing import Protocol

import httpx

from app import config


class Transcritor(Protocol):
    """Converte áudio em texto; devolve None se não puder."""

    def transcrever(self, audio: bytes, mime: str) -> str | None:
        """Texto do áudio ou None."""
        ...


class TranscritorDesligado:
    """Padrão: não transcreve (o atendimento pede para o cliente escrever)."""

    def transcrever(self, audio: bytes, mime: str) -> str | None:
        """Sempre None."""
        return None


class TranscritorWhisperHTTP:
    """Endpoint `/audio/transcriptions` no formato da OpenAI (OpenAI, Groq e similares).

    Custo fica na conta do cliente. Exemplos de TRANSCRICAO_URL:
    https://api.openai.com/v1/audio/transcriptions (modelo whisper-1) ou
    https://api.groq.com/openai/v1/audio/transcriptions (modelo whisper-large-v3).
    Confira preço e termos de cada provedor antes de ativar.
    """

    def __init__(self, url: str, chave: str, modelo: str, http: httpx.Client | None = None) -> None:
        self.url, self.chave, self.modelo = url, chave, modelo
        self.http = http or httpx.Client(timeout=60.0)

    def transcrever(self, audio: bytes, mime: str) -> str | None:
        """Envia o áudio (multipart) e devolve o texto."""
        extensao = "ogg" if "ogg" in mime else mime.split("/")[-1]
        resp = self.http.post(
            self.url,
            headers={"Authorization": f"Bearer {self.chave}"},
            data={"model": self.modelo, "language": "pt"},
            files={"file": (f"audio.{extensao}", audio, mime)},
        )
        resp.raise_for_status()
        return (resp.json().get("text") or "").strip() or None


def criar_transcritor() -> Transcritor:
    """Ativa a transcrição só se TRANSCRICAO_URL e TRANSCRICAO_CHAVE estiverem no ambiente."""
    cfg = config.obter()
    if cfg.transcricao_url and cfg.transcricao_chave:
        return TranscritorWhisperHTTP(cfg.transcricao_url, cfg.transcricao_chave, cfg.transcricao_modelo)
    return TranscritorDesligado()
