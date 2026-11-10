"""Gera o relatório mensal do cliente em Markdown a partir do SQLite.

Uso: python -m scripts.relatorio_mensal [--mes 2026-11] [--saida relatorios/]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import config, metricas  # noqa: E402


def gerar_markdown(m: metricas.Metricas) -> str:
    """Monta o texto do relatório (linguagem para o dono do negócio)."""
    cfg = config.obter()
    origens = ", ".join(f"{k}: {v}" for k, v in sorted(m.transferencias_por_origem.items())) or "nenhuma"
    linhas = [
        f"# Relatório do atendente virtual – {cfg.nome_negocio} – {m.inicio:%m/%Y}",
        "",
        "## Atendimento",
        "",
        f"- Conversas (sessões iniciadas): **{m.conversas}**",
        f"- Contatos diferentes: {m.contatos}",
        f"- Mensagens recebidas: {m.mensagens_recebidas}",
        f"- Recebidas fora do horário comercial: **{m.recebidas_fora_do_horario}**",
        f"- Resolvidas sem humano (aprox.): **{m.resolvidas_sem_humano_pct:.0f}%**",
        f"- Transferências para humano: {m.transferencias} ({origens})",
        f"- Agendamentos feitos pelo atendente: **{m.agendamentos}** · cancelamentos: {m.cancelamentos}",
        "",
        "## Custos estimados (conferir faturas oficiais)",
        "",
        f"- Claude API: {m.chamadas_api} chamadas · tokens de entrada {m.input_tokens:,} · "
        f"escrita de cache {m.cache_criacao_tokens:,} · leitura de cache {m.cache_leitura_tokens:,} · "
        f"saída {m.output_tokens:,}".replace(",", "."),
        f"- Custo Claude API: **US$ {m.custo_usd:.2f} (R$ {m.custo_brl:.2f})** com câmbio {cfg.cambio_brl:.2f}",
        f"- Mensagens WhatsApp enviadas: {m.mensagens_enviadas}",
        f"- Estimativa Meta: R$ {m.custo_meta_brl:.2f} (R$ {cfg.meta_preco_msg_brl:.3f} por mensagem acima de "
        f"{cfg.meta_franquia_msgs} no mês; parâmetro de configuração, confira a tabela vigente da Meta)",
        "",
        "## Perguntas que terminaram em \"não sei\" (candidatas para a base)",
        "",
    ]
    linhas += [f"- {p}" for p in m.perguntas_nao_sei] or ["- Nenhuma neste mês."]
    return "\n".join(linhas) + "\n"


def main() -> int:
    """Linha de comando."""
    parser = argparse.ArgumentParser(description="Relatório mensal do atendente.")
    parser.add_argument("--mes", help="AAAA-MM (padrão: mês atual)")
    parser.add_argument("--saida", type=Path, default=RAIZ / "relatorios")
    args = parser.parse_args()
    hoje = config.agora()
    ano, mes = (map(int, args.mes.split("-")) if args.mes else (hoje.year, hoje.month))
    texto = gerar_markdown(metricas.calcular(ano, mes))
    args.saida.mkdir(parents=True, exist_ok=True)
    arquivo = args.saida / f"relatorio_{ano}-{mes:02d}.md"
    arquivo.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Salvo em {arquivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
