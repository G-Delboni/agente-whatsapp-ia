"""Textos de cobrança e de recebimento de documentos. Só gera o texto; quem envia é o atendimento.

A cobrança que o escritório inicia fora da janela de 24 h precisa ser o template aprovado na Meta
(`documentos_pendentes`, categoria Utilidade) e só vai para quem aceitou receber.
"""

from __future__ import annotations

from app.documentos.checklist import Pendencia, juntar
from app.documentos.extrator import DocumentoProcessado
from app.documentos.validacao import reais

TEMPLATE_COBRANCA = "documentos_pendentes"
COBRANCA = (
    "Olá, {{1}}! Para fecharmos a contabilidade de {{2}} da {{3}}, ainda faltam: {{4}}.\n"
    "Você pode enviar foto ou PDF por aqui até {{5}}. Obrigado!"
)
SEGUNDO_LEMBRETE = (
    "Olá, {{1}}! Só lembrando: ainda faltam {{2}} de {{3}}. "
    "Se já enviou por outro canal, me avise que eu atualizo aqui."
)
RECEBIDO = "Recebi {documento}. Obrigado!"
AINDA_FALTA = " Ainda falta: {lista}."
TUDO_CERTO = " Está tudo certo para {mes}."
ILEGIVEL = (
    "Não consegui ler bem esse arquivo. Pode mandar de novo, com a foto mais de perto e com boa luz, ou em PDF?"
)
NOMES_CATEGORIA = {
    "nota_fiscal_produto": "a nota fiscal", "nota_fiscal_servico": "a nota de serviço",
    "cupom_fiscal": "o cupom fiscal", "recibo": "o recibo", "boleto": "o boleto",
    "extrato_bancario": "o extrato", "outro": "o documento",
}


def _preencher(modelo: str, valores: list[str]) -> str:
    """Troca {{1}}, {{2}}... pelos valores, na ordem."""
    for i, valor in enumerate(valores, start=1):
        modelo = modelo.replace(f"{{{{{i}}}}}", valor)
    return modelo


def lista_pendencias(pendencias: list[Pendencia]) -> str:
    """'extrato do Banco Exemplo e 2 notas de compra'."""
    return juntar([p.texto for p in pendencias])


def variaveis_cobranca(contato: str, mes: str, empresa: str, pendencias: list[Pendencia], prazo: str) -> list[str]:
    """Variáveis {{1}}..{{5}} do template `documentos_pendentes`, na ordem da Meta."""
    return [contato, mes, empresa, lista_pendencias(pendencias), prazo]


def mensagem_cobranca(contato: str, mes: str, empresa: str, pendencias: list[Pendencia], prazo: str) -> str:
    """Texto da cobrança educada (prévia do template, para o contador conferir)."""
    return _preencher(COBRANCA, variaveis_cobranca(contato, mes, empresa, pendencias, prazo))


def mensagem_segundo_lembrete(contato: str, pendencias: list[Pendencia], mes: str) -> str:
    """Segundo lembrete (só para quem aceitou receber)."""
    return _preencher(SEGUNDO_LEMBRETE, [contato, lista_pendencias(pendencias), mes])


def descrever_documento(doc: DocumentoProcessado) -> str:
    """'a nota fiscal da Papelaria X (R$ 70,00, 15/10/2026)'."""
    e = doc.extracao
    partes = [NOMES_CATEGORIA.get(e.categoria, "o documento")]
    if e.emitente:
        partes.append(f"de {e.emitente}")
    detalhes = []
    if e.valor_total > 0:
        detalhes.append(reais(e.valor_total))
    if len(e.data_emissao) == 10:
        detalhes.append(f"{e.data_emissao[8:10]}/{e.data_emissao[5:7]}/{e.data_emissao[:4]}")
    texto = " ".join(partes)
    return f"{texto} ({', '.join(detalhes)})" if detalhes else texto


def mensagem_recebido(doc: DocumentoProcessado, pendencias: list[Pendencia] | None, mes: str) -> str:
    """Resposta ao receber um arquivo: resumo + o que falta (ou pedido de reenvio se ilegível)."""
    if not doc.extracao.legivel:
        return ILEGIVEL
    texto = RECEBIDO.format(documento=descrever_documento(doc))
    if pendencias is None:  # remetente fora do checklist: só confirma
        return texto
    if pendencias:
        return texto + AINDA_FALTA.format(lista=lista_pendencias(pendencias))
    return texto + TUDO_CERTO.format(mes=mes)
