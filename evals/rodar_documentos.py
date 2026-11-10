"""Roda os casos de evals/casos_documentos.yaml e gera evals/relatorio_documentos_AAAA-MM-DD.md.

Uso (na raiz do projeto, com o venv):
    python -m evals.rodar_documentos --offline   # cliente falso, sem custo (testa o pipeline)
    python -m evals.rodar_documentos             # API real (precisa de ANTHROPIC_API_KEY de um workspace de testes)

Também monta as planilhas de demonstração em evals/saida_documentos/ (uma por cliente fictício),
com a aba Pendências e a prévia da cobrança.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import config  # noqa: E402
from app.documentos import checklist, cobranca, extrator, planilha  # noqa: E402
from app.documentos.recebimento import atualizar_pendencias  # noqa: E402

PASTA_EXEMPLOS = RAIZ / "evals" / "documentos_exemplo"
AGORA_PADRAO = "2026-11-11T10:00"
COMPETENCIA = "2026-10"


@dataclass
class ResultadoDoc:
    """Resultado de um caso de documento."""

    id: str
    cliente: str
    doc: extrator.DocumentoProcessado
    falhas: list[str] = field(default_factory=list)

    @property
    def aprovado(self) -> bool:
        """Sem nenhuma divergência do esperado."""
        return not self.falhas


def checar(esperado: dict[str, Any], doc: extrator.DocumentoProcessado) -> list[str]:
    """Compara campo a campo com o esperado do caso."""
    e, falhas = doc.extracao, []
    for campo in ("origem", "legivel", "categoria", "data_emissao", "documento_emitente", "revisar"):
        if campo not in esperado:
            continue
        obtido = getattr(doc, campo) if campo in ("origem", "revisar") else getattr(e, campo)
        if obtido != esperado[campo]:
            falhas.append(f"{campo}: esperado {esperado[campo]!r}, veio {obtido!r}")
    if "valor_total" in esperado and abs(e.valor_total - float(esperado["valor_total"])) > 0.01:
        falhas.append(f"valor_total: esperado {esperado['valor_total']}, veio {e.valor_total}")
    trecho = esperado.get("motivo_contem")
    if trecho and not any(trecho.lower() in m.lower() for m in doc.motivos_revisao):
        falhas.append(f"motivos sem '{trecho}': {doc.motivos_revisao}")
    if "usou_sonnet" in esperado:
        usou = any("sonnet" in m for m in doc.modelos)
        if usou != esperado["usou_sonnet"]:
            falhas.append("deveria usar o Sonnet" if esperado["usou_sonnet"] else "usou o Sonnet sem precisar")
    return falhas


def rodar(casos: list[dict[str, Any]], llm: Any, pasta: Path = PASTA_EXEMPLOS) -> list[ResultadoDoc]:
    """Extrai e confere cada caso (a Config e o relógio já devem estar definidos)."""
    resultados = []
    for caso in casos:
        doc = extrator.extrair_arquivo(pasta / caso["arquivo"], llm)
        resultados.append(ResultadoDoc(caso["id"], caso.get("cliente", "nao-identificado"), doc,
                                       checar(caso.get("esperado") or {}, doc)))
    return resultados


def _relativo(caminho: Path) -> str:
    """Caminho relativo à raiz do projeto, quando possível (com barras normais)."""
    try:
        return caminho.relative_to(RAIZ).as_posix()
    except ValueError:
        return caminho.as_posix()


def montar_planilhas(resultados: list[ResultadoDoc], saida: Path) -> list[str]:
    """Uma planilha por cliente + pendências; devolve as linhas do painel e das cobranças."""
    cfg = config.obter()
    lista = checklist.carregar(cfg.checklist_documentos)
    if saida.exists():
        shutil.rmtree(saida)
    linhas = []
    for cliente in lista.clientes:
        docs = [r.doc for r in resultados if r.cliente == cliente.id]
        caminho = planilha.caminho_planilha(saida, cliente.id)
        planilha.adicionar_lancamentos(caminho, docs, config.agora())
        pendencias = atualizar_pendencias(caminho, cliente, COMPETENCIA)
        linhas.append(f"- **{checklist.resumo_painel(cliente, pendencias)}** · planilha `{_relativo(caminho)}`")
        if pendencias:
            texto = cobranca.mensagem_cobranca(cliente.contato, checklist.nome_do_mes(COMPETENCIA), cliente.nome,
                                               pendencias, f"{lista.prazo_dia:02d}/11")
            linhas.append("  - Prévia da cobrança (template `documentos_pendentes`, só texto, não enviada):")
            linhas.append("    > " + texto.replace("\n", "\n    > "))
    return linhas


def escrever_relatorio(resultados: list[ResultadoDoc], painel: list[str], modo: str, destino: Path) -> Path:
    """Markdown com resultado por caso, custo, painel e cobranças."""
    cfg = config.obter()
    aprovados = sum(r.aprovado for r in resultados)
    custo = sum(r.doc.custo_usd for r in resultados)
    revisar = sum(r.doc.revisar for r in resultados)
    linhas = [
        f"# Relatório de evals de documentos – {date.today():%d/%m/%Y}",
        "",
        f"- Modo: **{modo}** · modelo: `{cfg.modelo_documentos}` · ambíguo: "
        f"`{cfg.modelo_documentos_ambiguo if cfg.rotear_ambiguo else 'desligado'}`",
        f"- Resultado: **{aprovados}/{len(resultados)} aprovados** · {revisar} documentos na coluna \"revisar\"",
        f"- Custo estimado: US$ {custo:.4f} (R$ {custo * cfg.cambio_brl:.4f}); XML de NF-e não usa IA",
        f"- nfelib disponível: {'sim' if extrator.NFELIB_DISPONIVEL else 'não (leitor simples)'}",
    ]
    if modo == "offline":
        linhas.append("- Atenção: modo offline usa um cliente falso que lê o texto embutido nos arquivos de "
                      "exemplo; valida o pipeline, não a qualidade do modelo.")
    linhas += ["", "| Caso | Resultado | Origem | Categoria | Valor | Revisar | Modelos | Falhas | Custo US$ |",
               "|---|---|---|---|---|---|---|---|---|"]
    for r in resultados:
        d, e = r.doc, r.doc.extracao
        modelos = ", ".join(m.replace("claude-", "") for m in d.modelos) or "-"
        linhas.append(
            f"| {r.id} | {'OK' if r.aprovado else 'FALHOU'} | {d.origem} | {e.categoria} | "
            f"{e.valor_total:.2f} | {'sim' if d.revisar else 'não'} | {modelos} | "
            f"{'; '.join(r.falhas) or '-'} | {d.custo_usd:.5f} |"
        )
    linhas += ["", "## Motivos de revisão", ""]
    linhas += [f"- {r.id}: {'; '.join(r.doc.motivos_revisao)}" for r in resultados if r.doc.revisar]
    linhas += ["", f"## Painel da competência {COMPETENCIA}", ""] + painel + [""]
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"relatorio_documentos_{date.today():%Y-%m-%d}.md"
    arquivo.write_text("\n".join(linhas), encoding="utf-8")
    return arquivo


def main() -> int:
    """Linha de comando."""
    parser = argparse.ArgumentParser(description="Roda os evals do assistente de documentos.")
    parser.add_argument("--offline", action="store_true", help="usa o cliente falso (sem rede, sem custo)")
    parser.add_argument("--casos", type=Path, default=RAIZ / "evals" / "casos_documentos.yaml")
    parser.add_argument("--saida", type=Path, default=RAIZ / "evals")
    parser.add_argument("--apenas", help="roda só o caso com este id")
    parser.add_argument("--agora", default=AGORA_PADRAO, help="relógio fixo AAAA-MM-DDTHH:MM")
    args = parser.parse_args()

    base = config.carregar_do_ambiente()
    config.definir(replace(base, checklist_documentos=RAIZ / "checklist_documentos.yaml"))
    momento = datetime.fromisoformat(args.agora).replace(tzinfo=base.tz)
    config.agora = lambda: momento

    casos = yaml.safe_load(args.casos.read_text(encoding="utf-8"))
    if args.apenas:
        casos = [c for c in casos if c["id"] == args.apenas]
    if args.offline:
        from app.cliente_falso import ClienteDocumentosFalso

        llm: Any = ClienteDocumentosFalso()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Defina ANTHROPIC_API_KEY (chave de um workspace de testes) ou use --offline.")
            return 2
        from app.agente import criar_cliente_anthropic

        llm = criar_cliente_anthropic()

    resultados = rodar(casos, llm)
    painel = montar_planilhas(resultados, args.saida / "saida_documentos")
    arquivo = escrever_relatorio(resultados, painel, "offline" if args.offline else "API real", args.saida)
    for r in resultados:
        if not r.aprovado:
            print(f"FALHOU {r.id}: {'; '.join(r.falhas)}")
    aprovados = sum(r.aprovado for r in resultados)
    print(f"{aprovados}/{len(resultados)} aprovados · custo US$ {sum(r.doc.custo_usd for r in resultados):.4f}")
    print(f"Relatório: {arquivo}")
    return 0 if aprovados == len(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
