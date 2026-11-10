"""Validações sem IA: CNPJ e CPF, datas, valor e soma dos itens contra o total."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.documentos.extrator import DocumentoProcessado

try:  # opcional do nível 2; sem ela, o cálculo próprio abaixo assume (só CNPJ numérico)
    from validate_docbr import CNPJ, CPF

    _CNPJ, _CPF = CNPJ(), CPF()
except Exception:  # pragma: no cover - depende do ambiente
    _CNPJ = _CPF = None

TOLERANCIA_SOMA = 0.02  # R$ 0,02 de arredondamento
MESES_PASSADO = 18  # documento mais velho que isso é suspeito


def reais(valor: float) -> str:
    """1234.5 → 'R$ 1.234,50'."""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def so_digitos(texto: str) -> str:
    """Remove pontuação; mantém letras maiúsculas (CNPJ alfanumérico)."""
    return re.sub(r"[^0-9A-Z]", "", (texto or "").upper())


def _dv(base: str, pesos: list[int]) -> int:
    """Dígito verificador módulo 11 (valor de cada caractere = ASCII - 48, regra da Receita)."""
    soma = sum((ord(c) - 48) * p for c, p in zip(base, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def cpf_valido(cpf: str) -> bool:
    """CPF com 11 dígitos e dígitos verificadores corretos."""
    cpf = so_digitos(cpf)
    if _CPF is not None:
        return len(cpf) == 11 and _CPF.validate(cpf)
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    d1 = _dv(cpf[:9], list(range(10, 1, -1)))
    d2 = _dv(cpf[:10], list(range(11, 1, -1)))
    return cpf[-2:] == f"{d1}{d2}"


def cnpj_valido(cnpj: str) -> bool:
    """CNPJ com 14 posições (numérico ou alfanumérico) e dígitos verificadores corretos."""
    cnpj = so_digitos(cnpj)
    if len(cnpj) != 14 or not cnpj[-2:].isdigit() or len(set(cnpj)) == 1:
        return False
    if _CNPJ is not None and cnpj.isdigit():
        return _CNPJ.validate(cnpj)
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _dv(cnpj[:12], pesos)
    d2 = _dv(cnpj[:12] + str(d1), [6] + pesos)
    return cnpj[-2:] == f"{d1}{d2}"


def validar_documento(documento: str) -> str | None:
    """Motivo de revisão para o CNPJ/CPF do emitente, ou None se válido."""
    doc = so_digitos(documento)
    if not doc:
        return "CNPJ/CPF do emitente ausente"
    if len(doc) == 11:
        return None if cpf_valido(doc) else f"CPF inválido ({doc})"
    if len(doc) == 14:
        return None if cnpj_valido(doc) else f"CNPJ inválido ({doc})"
    return f"CNPJ/CPF com tamanho errado ({doc})"


def validar_data(texto: str, hoje: date) -> str | None:
    """Data AAAA-MM-DD, não futura e não mais velha que MESES_PASSADO."""
    if not texto:
        return "data de emissão ausente"
    try:
        dia = date.fromisoformat(texto)
    except ValueError:
        return f"data em formato inválido ({texto})"
    if dia > hoje + timedelta(days=1):
        return f"data no futuro ({dia:%d/%m/%Y})"
    if dia < hoje - timedelta(days=30 * MESES_PASSADO):
        return f"data muito antiga ({dia:%d/%m/%Y})"
    return None


def validar_soma(valores: list[float], total: float, tolerancia: float = TOLERANCIA_SOMA) -> str | None:
    """Soma dos itens contra o total (sem itens, não há o que conferir)."""
    if not valores:
        return None
    soma = round(sum(valores), 2)
    if abs(soma - total) > tolerancia:
        return f"soma dos itens ({reais(soma)}) diferente do total ({reais(total)})"
    return None


def motivos_de_revisao(doc: DocumentoProcessado, hoje: date) -> list[str]:
    """Tudo o que impede lançar sem olhar: ilegível, baixa confiança e validações."""
    ext = doc.extracao
    if not ext.legivel:
        return [f"ilegível ou não reconhecido: {ext.observacao}".rstrip(": ")]
    motivos = [f"baixa confiança em {campo}" for campo, nivel in ext.confianca.model_dump().items()
               if nivel == "baixa"]
    motivos.append(validar_documento(ext.documento_emitente))
    motivos.append(validar_data(ext.data_emissao, hoje))
    if ext.valor_total <= 0:
        motivos.append("valor total zerado ou ausente")
    referencia = doc.total_itens_declarado if doc.total_itens_declarado is not None else ext.valor_total
    motivos.append(validar_soma([i.valor for i in ext.itens], referencia))
    return [m for m in motivos if m]
