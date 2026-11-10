"""Planilha .xlsx por cliente do escritório: aba Lançamentos (com coluna "revisar") e aba Pendências."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.documentos.checklist import Pendencia
from app.documentos.extrator import DocumentoProcessado

ABA_LANCAMENTOS = "Lançamentos"
ABA_PENDENCIAS = "Pendências"
COLUNAS = [
    ("Recebido em", 17), ("Arquivo", 28), ("Categoria", 20), ("Data emissão", 12), ("Emitente", 32),
    ("CNPJ/CPF", 18), ("Nº documento", 14), ("Valor (R$)", 13), ("Confiança", 10), ("Origem", 12),
    ("Revisar", 9), ("Motivos da revisão", 48), ("Aprovado por", 14), ("Evidência do valor", 32), ("Hash", 18),
]
AMARELO = PatternFill("solid", start_color="FFF2CC")
CINZA = PatternFill("solid", start_color="D9D9D9")
FORMATO_REAL = '"R$" #,##0.00'


def nome_seguro(texto: str) -> str:
    """'Padaria Pão Bom' → 'padaria-pao-bom' (nome de arquivo)."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "sem-nome"


def caminho_planilha(pasta: Path, id_cliente: str) -> Path:
    """dados/planilhas/<cliente>.xlsx"""
    return pasta / f"{nome_seguro(id_cliente)}.xlsx"


def _cabecalho(aba: Any, colunas: list[tuple[str, int]]) -> None:
    """Primeira linha em negrito, congelada e com filtro."""
    for i, (titulo, largura) in enumerate(colunas, start=1):
        celula = aba.cell(row=1, column=i, value=titulo)
        celula.font, celula.fill = Font(bold=True), CINZA
        aba.column_dimensions[get_column_letter(i)].width = largura
    aba.freeze_panes = "A2"
    aba.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}1"


def abrir(caminho: Path) -> Workbook:
    """Abre a planilha ou cria uma nova com as duas abas."""
    if caminho.exists():
        return load_workbook(caminho)
    livro = Workbook()
    aba = livro.active
    aba.title = ABA_LANCAMENTOS
    _cabecalho(aba, COLUNAS)
    _cabecalho(livro.create_sheet(ABA_PENDENCIAS), [("Competência", 12), ("Documento", 40), ("Faltam", 8)])
    return livro


def hashes_existentes(livro: Workbook) -> set[str]:
    """Hashes já lançados (para não duplicar se o arquivo chegar duas vezes)."""
    aba = livro[ABA_LANCAMENTOS]
    return {str(linha[-1]) for linha in aba.iter_rows(min_row=2, values_only=True) if linha[-1]}


def _linha(doc: DocumentoProcessado, recebido_em: datetime) -> list[Any]:
    """Valores de uma linha de lançamento."""
    e = doc.extracao
    return [
        recebido_em.strftime("%d/%m/%Y %H:%M"), doc.arquivo, e.categoria, e.data_emissao, e.emitente,
        e.documento_emitente, e.numero_documento, e.valor_total, doc.menor_confianca, doc.origem,
        "SIM" if doc.revisar else "não", "; ".join(doc.motivos_revisao), "", e.evidencia.valor_total, doc.hash,
    ]


def adicionar_lancamentos(caminho: Path, docs: list[DocumentoProcessado], recebido_em: datetime) -> int:
    """Acrescenta os documentos novos; linhas a revisar ficam em amarelo. Devolve quantos entraram."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    livro = abrir(caminho)
    aba = livro[ABA_LANCAMENTOS]
    vistos = hashes_existentes(livro)
    novos = 0
    for doc in docs:
        if doc.hash in vistos:
            continue
        aba.append(_linha(doc, recebido_em))
        linha = aba.max_row
        aba.cell(row=linha, column=8).number_format = FORMATO_REAL
        if doc.revisar:
            for coluna in range(1, len(COLUNAS) + 1):
                aba.cell(row=linha, column=coluna).fill = AMARELO
        vistos.add(doc.hash)
        novos += 1
    livro.save(caminho)
    return novos


def ler_lancamentos(caminho: Path) -> list[dict[str, Any]]:
    """Linhas da aba Lançamentos como dicionários (título da coluna → valor)."""
    if not caminho.exists():
        return []
    aba = load_workbook(caminho, read_only=True)[ABA_LANCAMENTOS]
    titulos = [t for t, _ in COLUNAS]
    return [dict(zip(titulos, linha)) for linha in aba.iter_rows(min_row=2, values_only=True)]


def categorias_da_competencia(lancamentos: list[dict[str, Any]], competencia: str) -> list[str]:
    """Categorias recebidas no mês 'AAAA-MM' (pela data de emissão), sem contar os ilegíveis."""
    return [
        l["Categoria"] for l in lancamentos
        if str(l["Data emissão"] or "").startswith(competencia)
        and not str(l["Motivos da revisão"] or "").startswith("ilegível")
    ]


def escrever_pendencias(caminho: Path, competencia: str, pendencias: list[Pendencia]) -> None:
    """Reescreve a aba Pendências da competência (as de outros meses ficam)."""
    livro = abrir(caminho)
    aba = livro[ABA_PENDENCIAS]
    outras = [l for l in aba.iter_rows(min_row=2, values_only=True) if l[0] and l[0] != competencia]
    aba.delete_rows(2, aba.max_row)
    for linha in outras:
        aba.append(list(linha))
    for p in pendencias:
        aba.append([competencia, p.descricao, p.faltam])
    livro.save(caminho)
