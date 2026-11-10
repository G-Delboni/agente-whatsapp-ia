"""Processa uma pasta de documentos de um cliente do escritório e preenche a planilha dele.

Uso (na raiz do projeto, com o venv):
    python -m scripts.processar_lote PASTA --cliente padaria-pao-bom --offline
    python -m scripts.processar_lote PASTA --cliente padaria-pao-bom                 # API real, um a um
    python -m scripts.processar_lote PASTA --cliente padaria-pao-bom --batch         # Batch API (metade do preço)
    python -m scripts.processar_lote PASTA --cliente padaria-pao-bom --resultado msgbatch_...  # lê o lote pronto

XML de NF-e é lido na hora, sem IA, em qualquer modo. No --batch, PDFs e imagens viram requisições da
Batch API (até 24 h, normalmente menos de 1 h); o mapa custom_id → arquivo fica em lote_<id>.json na pasta
de saída. No lote não há o segundo passe com Sonnet: campo duvidoso cai direto em revisão.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import config  # noqa: E402
from app.custos import Uso  # noqa: E402
from app.documentos import checklist, extrator, planilha, validacao  # noqa: E402
from app.documentos.recebimento import atualizar_pendencias  # noqa: E402

FATOR_LOTE = 0.5


def arquivos_da_pasta(pasta: Path) -> list[Path]:
    """Arquivos suportados, em ordem alfabética."""
    return sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in extrator.EXTENSOES)


def resumo(docs: list[extrator.DocumentoProcessado]) -> str:
    """Tabela curta para o terminal."""
    linhas = []
    for d in docs:
        e = d.extracao
        marca = "REVISAR" if d.revisar else "ok"
        linhas.append(f"{marca:8} {d.arquivo:40} {e.categoria:20} {validacao.reais(e.valor_total):>14}  "
                      f"{'; '.join(d.motivos_revisao)}")
    custo = sum(d.custo_usd for d in docs)
    linhas.append(f"{len(docs)} documentos · {sum(d.revisar for d in docs)} para revisar · "
                  f"custo estimado US$ {custo:.5f}")
    return "\n".join(linhas)


def lancar(docs: list[extrator.DocumentoProcessado], id_cliente: str, cfg: config.Config) -> Path:
    """Planilha do cliente + aba Pendências da competência mais frequente."""
    caminho = planilha.caminho_planilha(cfg.planilhas_dir, id_cliente)
    novos = planilha.adicionar_lancamentos(caminho, docs, config.agora())
    print(f"{novos} lançamentos novos em {caminho}")
    lista = checklist.carregar(cfg.checklist_documentos) if cfg.checklist_documentos.exists() else None
    cliente = lista.por_id(id_cliente) if lista else None
    datas = [d.extracao.data_emissao[:7] for d in docs if d.extracao.data_emissao]
    if cliente and datas:
        competencia = max(set(datas), key=datas.count)
        pendencias = atualizar_pendencias(caminho, cliente, competencia)
        print(checklist.resumo_painel(cliente, pendencias))
    return caminho


def processar_direto(arquivos: list[Path], llm: Any, cfg: config.Config) -> list[extrator.DocumentoProcessado]:
    """Um arquivo por vez (com o roteamento Haiku → Sonnet nos casos ambíguos)."""
    return [extrator.extrair_arquivo(a, llm, cfg=cfg) for a in arquivos]


def montar_lote(arquivos: list[Path], cfg: config.Config) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Requisições da Batch API para PDFs e imagens; devolve também custom_id → arquivo."""
    requisicoes, mapa = [], {}
    for caminho in arquivos:
        dados = caminho.read_bytes()
        tipo = extrator.tipo_do_arquivo(caminho.name)
        if tipo not in ("pdf", "imagem") or len(dados) > extrator.TAMANHO_MAXIMO:
            continue
        custom_id = extrator.id_para_lote(caminho.name, dados)
        mime = extrator.mime_do_arquivo(caminho.name)
        requisicoes.append({"custom_id": custom_id,
                            "params": extrator.montar_pedido(dados, mime, cfg.modelo_documentos)})
        mapa[custom_id] = str(caminho)
    return requisicoes, mapa


def doc_do_resultado(caminho: Path, resposta: Any, modelo: str) -> extrator.DocumentoProcessado:
    """Resultado de uma requisição do lote → DocumentoProcessado validado (custo pela metade)."""
    dados = caminho.read_bytes()
    doc = extrator.DocumentoProcessado(
        arquivo=caminho.name, tipo=extrator.tipo_do_arquivo(caminho.name), hash=extrator.calcular_hash(dados),
        extracao=extrator.ler_resposta(resposta), origem="claude-lote", modelos=[modelo],
        usos=[Uso.da_resposta(modelo, resposta.usage)],
    )
    doc.usos[0].fator = FATOR_LOTE
    doc.motivos_revisao = validacao.motivos_de_revisao(doc, config.agora().date())
    return doc


def processar_lote(arquivos: list[Path], llm: Any, cfg: config.Config, offline: bool) -> list[extrator.DocumentoProcessado]:
    """XML na hora; PDF e imagem pela Batch API. Offline, o cliente falso responde cada requisição."""
    xmls = [extrator.extrair_arquivo(a, llm, cfg=cfg) for a in arquivos if extrator.tipo_do_arquivo(a.name) == "xml"]
    requisicoes, mapa = montar_lote(arquivos, cfg)
    cfg.planilhas_dir.mkdir(parents=True, exist_ok=True)
    if offline:
        docs = [doc_do_resultado(Path(mapa[r["custom_id"]]), llm.messages.create(**r["params"]),
                                 cfg.modelo_documentos) for r in requisicoes]
        print(f"Lote simulado: {len(requisicoes)} requisições (offline, cliente falso).")
        return xmls + docs
    lote = llm.messages.batches.create(requests=requisicoes)
    (cfg.planilhas_dir / f"lote_{lote.id}.json").write_text(json.dumps(mapa, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
    print(f"Lote enviado: {lote.id} ({len(requisicoes)} requisições). Rode de novo com --resultado {lote.id}.")
    return xmls


def ler_resultado(id_lote: str, llm: Any, cfg: config.Config) -> list[extrator.DocumentoProcessado]:
    """Busca os resultados de um lote encerrado e converte em documentos."""
    lote = llm.messages.batches.retrieve(id_lote)
    if lote.processing_status != "ended":
        print(f"Lote ainda em processamento ({lote.processing_status}). Tente mais tarde.")
        return []
    mapa = json.loads((cfg.planilhas_dir / f"lote_{id_lote}.json").read_text(encoding="utf-8"))
    docs = []
    for item in llm.messages.batches.results(id_lote):
        caminho = Path(mapa[item.custom_id])
        if item.result.type == "succeeded":
            docs.append(doc_do_resultado(caminho, item.result.message, cfg.modelo_documentos))
        else:
            print(f"Falhou no lote ({item.result.type}): {caminho.name}. Reenvie sem --batch.")
    return docs


def main() -> int:
    """Linha de comando."""
    parser = argparse.ArgumentParser(description="Processa uma pasta de documentos (nível 2).")
    parser.add_argument("pasta", type=Path, nargs="?", help="pasta com XML, PDF e imagens")
    parser.add_argument("--cliente", default="nao-identificado", help="id do cliente no checklist")
    parser.add_argument("--offline", action="store_true", help="cliente falso (sem rede, sem custo)")
    parser.add_argument("--batch", action="store_true", help="usa a Batch API (metade do preço, até 24 h)")
    parser.add_argument("--resultado", help="id de um lote enviado antes, para ler os resultados")
    parser.add_argument("--saida", type=Path, help="pasta das planilhas (padrão: PLANILHAS_DIR)")
    args = parser.parse_args()

    cfg = config.carregar_do_ambiente()
    if args.saida:
        from dataclasses import replace

        cfg = replace(cfg, planilhas_dir=args.saida)
    config.definir(cfg)

    if args.offline:
        from app.cliente_falso import ClienteDocumentosFalso

        llm: Any = ClienteDocumentosFalso()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Defina ANTHROPIC_API_KEY ou use --offline.")
            return 2
        from app.agente import criar_cliente_anthropic

        llm = criar_cliente_anthropic()

    if args.resultado:
        docs = ler_resultado(args.resultado, llm, cfg)
    elif args.pasta is None:
        parser.error("informe a PASTA ou --resultado")
    else:
        arquivos = arquivos_da_pasta(args.pasta)
        docs = processar_lote(arquivos, llm, cfg, args.offline) if args.batch else processar_direto(arquivos, llm, cfg)
    if docs:
        print(resumo(docs))
        lancar(docs, args.cliente, cfg)
    print(f"Feito em {datetime.now():%d/%m/%Y %H:%M}. Nada foi lançado no sistema contábil: revise a planilha.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
