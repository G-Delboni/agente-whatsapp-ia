"""Conversa com o atendente no terminal, sem WhatsApp (demonstração e testes manuais).

Uso:
    python -m scripts.conversar --offline     # cliente falso, sem custo
    python -m scripts.conversar               # API real (ANTHROPIC_API_KEY no ambiente)
O banco usado fica em dados/conversa_terminal.db (separado da produção).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from itertools import count
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import agente, config, db  # noqa: E402
from app.agenda_local import AgendaLocal  # noqa: E402
from app.atendimento import Dependencias, processar_mensagem  # noqa: E402
from app.cliente_falso import ClienteRegras, WhatsAppFalso  # noqa: E402
from app.transcricao import TranscritorDesligado  # noqa: E402
from app.whatsapp import MensagemRecebida  # noqa: E402

TELEFONE = "5500000000001"


def main() -> int:
    """Lê mensagens do teclado e mostra as respostas."""
    parser = argparse.ArgumentParser(description="Conversa com o atendente no terminal.")
    parser.add_argument("--offline", action="store_true", help="usa o cliente falso (sem custo)")
    args = parser.parse_args()
    config.definir(replace(config.carregar_do_ambiente(), db_caminho=RAIZ / "dados" / "conversa_terminal.db"))
    db.criar_tabelas()
    whatsapp = WhatsAppFalso()
    deps = Dependencias(
        whatsapp=whatsapp,
        llm=ClienteRegras() if args.offline else agente.criar_cliente_anthropic(),
        agenda=AgendaLocal(),
        transcritor=TranscritorDesligado(),
    )
    print("Digite sua mensagem (vazio para sair).")
    for n in count(1):
        texto = input("você> ").strip()
        if not texto:
            return 0
        antes = len(whatsapp.enviadas)
        processar_mensagem(MensagemRecebida(f"terminal.{n}", TELEFONE, "Terminal", "text", texto), deps)
        for para, resposta in whatsapp.enviadas[antes:]:
            quem = "atendente" if para == TELEFONE else f"aviso p/ {para}"
            print(f"{quem}> {resposta}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
