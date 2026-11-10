"""Documentos esperados por mês e por cliente do escritório (YAML) e o que ainda falta."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


@dataclass
class Esperado:
    """Um tipo de documento esperado no mês."""

    categoria: str
    descricao: str
    quantidade: int = 1


@dataclass
class ClienteEscritorio:
    """Cliente do escritório contábil (dados fictícios no exemplo)."""

    id: str
    nome: str
    contato: str
    telefone: str
    esperados: list[Esperado] = field(default_factory=list)


@dataclass
class Pendencia:
    """O que falta de um tipo de documento."""

    categoria: str
    descricao: str
    faltam: int
    quantidade: int = 1

    @property
    def texto(self) -> str:
        """'extrato do Banco Exemplo', '2 notas de compra' ou '1 de 2 notas de compra'."""
        if self.quantidade == 1:
            return self.descricao
        if self.faltam == self.quantidade:
            return f"{self.faltam} {self.descricao}"
        return f"{self.faltam} de {self.quantidade} {self.descricao}"


@dataclass
class Checklist:
    """Checklist do escritório: prazo e clientes."""

    escritorio: str
    prazo_dia: int
    clientes: list[ClienteEscritorio]

    def por_telefone(self, telefone: str) -> ClienteEscritorio | None:
        """Cliente cujo telefone (só dígitos) bate com o remetente."""
        return next((c for c in self.clientes if c.telefone == telefone), None)

    def por_id(self, id_cliente: str) -> ClienteEscritorio | None:
        """Cliente pelo identificador curto."""
        return next((c for c in self.clientes if c.id == id_cliente), None)


def carregar(caminho: Path) -> Checklist:
    """Lê o YAML do checklist."""
    dados: dict[str, Any] = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    clientes = [
        ClienteEscritorio(
            id=c["id"], nome=c["nome"], contato=c.get("contato", ""), telefone=str(c.get("telefone", "")),
            esperados=[Esperado(e["categoria"], e["descricao"], int(e.get("quantidade", 1)))
                       for e in c.get("esperados", [])],
        )
        for c in dados.get("clientes", [])
    ]
    return Checklist(dados.get("escritorio", ""), int(dados.get("prazo_dia", 10)), clientes)


def calcular_pendencias(cliente: ClienteEscritorio, categorias_recebidas: list[str]) -> list[Pendencia]:
    """Compara o esperado com as categorias recebidas na competência."""
    recebidos = Counter(categorias_recebidas)
    pendencias = []
    for esperado in cliente.esperados:
        usados = min(recebidos[esperado.categoria], esperado.quantidade)
        recebidos[esperado.categoria] -= usados
        if esperado.quantidade - usados > 0:
            pendencias.append(Pendencia(esperado.categoria, esperado.descricao,
                                        esperado.quantidade - usados, esperado.quantidade))
    return pendencias


def juntar(itens: list[str]) -> str:
    """['a', 'b', 'c'] → 'a, b e c'."""
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def resumo_painel(cliente: ClienteEscritorio, pendencias: list[Pendencia]) -> str:
    """Linha do painel: 'Padaria Pão Bom: faltam extrato e 2 notas de compra'."""
    if not pendencias:
        return f"{cliente.nome}: tudo recebido"
    return f"{cliente.nome}: faltam {juntar([p.texto for p in pendencias])}"


def nome_do_mes(competencia: str) -> str:
    """'2026-10' → 'outubro'."""
    return MESES[int(competencia[5:7]) - 1]
