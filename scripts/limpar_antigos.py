"""Apaga mensagens e logs mais antigos que RETENCAO_DIAS (LGPD). Rode 1x por mês.

Uso: python -m scripts.limpar_antigos [--dias 180]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, guardas  # noqa: E402


def main() -> int:
    """Linha de comando."""
    parser = argparse.ArgumentParser(description="Remove dados antigos do banco.")
    parser.add_argument("--dias", type=int, default=None, help="padrão: RETENCAO_DIAS")
    args = parser.parse_args()
    db.criar_tabelas()
    dias = args.dias if args.dias is not None else config.obter().retencao_dias
    apagadas = guardas.apagar_antigos(dias)
    print(f"{apagadas} mensagens com mais de {dias} dias apagadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
