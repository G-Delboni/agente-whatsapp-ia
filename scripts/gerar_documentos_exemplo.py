"""Gera os 12 documentos FICTÍCIOS de evals/documentos_exemplo/ (3 XML, 4 PDF, 3 imagens, 2 ilegíveis).

Nomes inventados; CNPJ e CPF com dígitos verificadores calculados aqui (válidos no formato, de
empresas e pessoas inventadas). As imagens precisam do Pillow (só para gerar; o atendente não usa).
O texto de cada PNG também vai num pedaço iTXt 'conteudo', que o cliente falso lê no modo offline.

Uso: python -m scripts.gerar_documentos_exemplo
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.documentos.validacao import _dv  # noqa: E402

DESTINO = RAIZ / "evals" / "documentos_exemplo"
PESOS_CNPJ = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def cnpj(base12: str, valido: bool = True) -> str:
    """Completa 12 posições com os 2 dígitos verificadores (ou com dígitos errados de propósito)."""
    d1 = _dv(base12, PESOS_CNPJ)
    d2 = _dv(base12 + str(d1), [6] + PESOS_CNPJ)
    dv = f"{d1}{d2}" if valido else f"{(d1 + 1) % 10}{d2}"
    return base12 + dv


def cpf(base9: str) -> str:
    """Completa 9 dígitos com os verificadores."""
    d1 = _dv(base9, list(range(10, 1, -1)))
    return base9 + str(d1) + str(_dv(base9 + str(d1), list(range(11, 1, -1))))


def mascara_cnpj(c: str) -> str:
    """00.000.000/0000-00"""
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def mascara_cpf(c: str) -> str:
    """000.000.000-00"""
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


PAPELARIA = cnpj("905123450001")
ATACADO = cnpj("907654320001")
MERCADINHO_ERRADO = cnpj("903141590001", valido=False)
ESTUDIO = cnpj("908642000001")
BANCO = cnpj("909999990001")
DISTRIBUIDORA = cnpj("906060600001")
FORNECEDOR = cnpj("904444440001")
LOJA_MATERIAL = cnpj("902222220001")
PADARIA = cnpj("901111110001")
LOCADORA_CPF = cpf("900123456")
DIARISTA_CPF = cpf("900654321")


# ---------- XML de NF-e ----------

def chave_acesso(cnpj_emit: str, modelo: str, numero: int, aamm: str = "2610") -> str:
    """Chave de 44 dígitos com DV módulo 11 (pesos 2 a 9 da direita para a esquerda)."""
    base = f"35{aamm}{cnpj_emit}{modelo}001{numero:09d}1{numero * 7:08d}"[:43]
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(base)))
    resto = soma % 11
    return base + str(0 if resto < 2 else 11 - resto)


def nfe_xml(emit: tuple[str, str], numero: int, data: str, itens: list[tuple[str, float]],
            modelo: str = "55", frete: float = 0.0) -> str:
    """procNFe 4.00 mínimo (sem assinatura), suficiente para a leitura."""
    chave = chave_acesso(emit[1], modelo, numero)
    vprod = round(sum(v for _, v in itens), 2)
    det = "".join(
        f'<det nItem="{i}"><prod><cProd>{i}</cProd><xProd>{d}</xProd><qCom>1.0000</qCom>'
        f"<vUnCom>{v:.2f}</vUnCom><vProd>{v:.2f}</vProd></prod></det>"
        for i, (d, v) in enumerate(itens, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        f'<NFe><infNFe Id="NFe{chave}" versao="4.00">'
        f"<ide><cUF>35</cUF><nNF>{numero}</nNF><dhEmi>{data}T10:30:00-03:00</dhEmi><mod>{modelo}</mod>"
        f"<serie>1</serie></ide>"
        f"<emit><CNPJ>{emit[1]}</CNPJ><xNome>{emit[0]}</xNome></emit>"
        f"<dest><CNPJ>{PADARIA}</CNPJ><xNome>Padaria Pão Bom (fictícia)</xNome></dest>{det}"
        f"<total><ICMSTot><vProd>{vprod:.2f}</vProd><vFrete>{frete:.2f}</vFrete>"
        f"<vNF>{vprod + frete:.2f}</vNF></ICMSTot></total>"
        f"</infNFe></NFe><protNFe versao=\"4.00\"><infProt><chNFe>{chave}</chNFe></infProt></protNFe></nfeProc>\n"
    )


# ---------- PDF sem dependências ----------

def _escapar_pdf(texto: str) -> bytes:
    """String literal do PDF em WinAnsi (cp1252), com escapes."""
    saida = bytearray()
    for b in texto.encode("cp1252"):
        if b in b"()\\":
            saida += b"\\" + bytes([b])
        elif b > 126:
            saida += f"\\{b:03o}".encode()
        else:
            saida.append(b)
    return bytes(saida)


def pdf(linhas: list[str], so_desenho: bool = False) -> bytes:
    """PDF de 1 página A4 com Helvetica (texto real, sem compressão) ou só retângulos (escaneado ruim)."""
    if so_desenho:
        conteudo = b"".join(f"0.{7 + i % 2} g 60 {700 - i * 40} {300 + (i * 37) % 160} 18 re f\n".encode()
                            for i in range(14))
    else:
        partes = []
        for i, linha in enumerate(linhas):
            tamanho = 16 if i == 0 else 11
            partes.append(b"BT /F1 %d Tf 60 %d Td (" % (tamanho, 780 - i * 22) + _escapar_pdf(linha) + b") Tj ET\n")
        conteudo = b"".join(partes)
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> "
        b"/Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posicoes = []
    for n, obj in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    saida += b"".join(b"%010d 00000 n \n" % p for p in posicoes)
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
    return bytes(saida)


# ---------- Imagens (Pillow) ----------

def imagem(linhas: list[str], destino: Path, estilo: str = "normal", simulacao: str = "") -> None:
    """Foto simulada de papel: 'normal', 'amassado' (inclinado, vincos) ou 'borrado' (ilegível, JPEG)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from PIL.PngImagePlugin import PngInfo

    rnd = random.Random(destino.name)
    fonte = ImageFont.truetype("arial.ttf", 30) if Path("C:/Windows/Fonts/arial.ttf").exists() \
        else ImageFont.load_default(size=30)
    papel = Image.new("RGB", (900, 120 + 48 * len(linhas)), (250, 248, 240))
    desenho = ImageDraw.Draw(papel)
    for i, linha in enumerate(linhas):
        cor = (40, 40, 40) if not (simulacao and linha.startswith("Total")) else (150, 150, 150)
        desenho.text((50, 50 + i * 48), linha, fill=cor, font=fonte)
    if estilo == "amassado":
        for _ in range(6):
            x = rnd.randint(0, 900)
            desenho.line([(x, 0), (x + rnd.randint(-200, 200), papel.height)], fill=(200, 196, 185), width=3)
        papel = papel.rotate(4, expand=True, fillcolor=(90, 80, 70))
    fundo = Image.new("RGB", (papel.width + 80, papel.height + 80), (120, 105, 90))
    fundo.paste(papel, (40, 40))
    if estilo == "borrado":
        fundo.filter(ImageFilter.GaussianBlur(9)).save(destino, "JPEG", quality=35)
        return
    info = PngInfo()
    info.add_itxt("conteudo", "\n".join(linhas))
    if simulacao:
        info.add_itxt("simulacao", simulacao)
    fundo.save(destino, "PNG", pnginfo=info)


def gerar(destino: Path = DESTINO) -> list[Path]:
    """Cria os 12 arquivos e devolve os caminhos."""
    destino.mkdir(parents=True, exist_ok=True)
    arquivos: dict[str, bytes | None] = {
        "nfe_01_papelaria.xml": nfe_xml(("Papelaria Ponto Fictício Ltda", PAPELARIA), 1234, "2026-10-15",
                                        [("Resma papel A4", 50.0), ("Caneta azul cx 10", 20.0)]).encode(),
        "nfe_02_atacado_com_frete.xml": nfe_xml(("Atacado Exemplo Distribuição Ltda", ATACADO), 88,
                                                "2026-10-21", [("Farinha de trigo 25 kg", 180.0),
                                                               ("Açúcar 5 kg", 120.0)], frete=20.0).encode(),
        "nfe_03_cupom_cnpj_invalido.xml": nfe_xml(("Mercadinho Inventado ME", MERCADINHO_ERRADO), 5512,
                                                  "2026-10-09", [("Produtos de limpeza", 45.9)],
                                                  modelo="65").encode(),
        "pdf_01_recibo_aluguel.pdf": pdf([
            "RECIBO DE ALUGUEL", "Nº 10/2026", "Emitente: Maria Locadora Fictícia",
            f"CPF: {mascara_cpf(LOCADORA_CPF)}", "Data: 05/10/2026",
            "Referente ao aluguel do imóvel da Rua Inventada, 100 - outubro/2026",
            "Valor pago: R$ 1.800,00", "Assinatura: Maria Locadora Fictícia"]),
        "pdf_02_nfse_estudio.pdf": pdf([
            "NOTA FISCAL DE SERVIÇO ELETRÔNICA - NFS-e", "Nº 341", "Prestador: Studio Bela Forma (fictício)",
            f"CNPJ: {mascara_cnpj(ESTUDIO)}", "Emissão: 18/10/2026",
            "Item: Pacote de 10 sessões de pilates | R$ 650,00", "Item: Avaliação física | R$ 120,00",
            "Valor total: R$ 770,00", "ISS retido: não"]),
        "pdf_03_extrato_banco.pdf": pdf([
            "EXTRATO BANCÁRIO - CONTA CORRENTE", "Banco: Banco Exemplo S.A. (fictício)",
            f"CNPJ: {mascara_cnpj(BANCO)}", "Data: 31/10/2026", "Período: 01/10/2026 a 31/10/2026",
            "Agência 0001  Conta 12345-6  Titular: Studio Bela Forma (fictício)",
            "Saldo anterior: R$ 8.200,00", "Créditos: R$ 6.145,67   Débitos: R$ 2.000,00",
            "Saldo final: R$ 12.345,67"]),
        "pdf_04_danfe_soma_divergente.pdf": pdf([
            "DANFE - NOTA FISCAL ELETRÔNICA (representação simplificada)", "Nº 777",
            "Emitente: Distribuidora Imaginária Ltda", f"CNPJ: {mascara_cnpj(DISTRIBUIDORA)}",
            "Data: 12/10/2026", "Item: Toalhas descartáveis | R$ 100,00", "Item: Luvas nitrílicas | R$ 50,00",
            "Total: R$ 160,00"]),
        "img_01_cupom_material.png": None,
        "img_02_recibo_amassado.png": None,
        "img_03_boleto_valor_apagado.png": None,
        "ilegivel_01_foto_borrada.jpg": None,
        "ilegivel_02_pdf_escaneado_sem_texto.pdf": pdf([], so_desenho=True),
    }
    for nome, dados in arquivos.items():
        if dados is not None:
            (destino / nome).write_bytes(dados)
    imagem(["CUPOM FISCAL ELETRÔNICO - SAT", "Emitente: Loja de Materiais Faz de Conta",
            f"CNPJ: {mascara_cnpj(LOJA_MATERIAL)}", "Data: 22/10/2026", "Item: Elásticos de treino | R$ 89,90",
            "Item: Colchonete | R$ 59,90", "Total: R$ 149,80"], destino / "img_01_cupom_material.png")
    imagem(["RECIBO", "Emitente: Joana Diarista Inventada", "Recebi de Studio Bela Forma (fictício)", "a quantia de cento e vinte reais",
            "referente a limpeza do salão", f"CPF: {mascara_cpf(DIARISTA_CPF)}", "Valor total: R$ 120,00",
            "Assinatura: Joana Diarista Inventada"], destino / "img_02_recibo_amassado.png", "amassado")
    imagem(["BOLETO DE COBRANÇA", "Emitente: Fornecedor Modelo de Embalagens Ltda",
            f"CNPJ: {mascara_cnpj(FORNECEDOR)}", "Vencimento: 25/10/2026", "Nº 000981",
            "Total: R$ 389,40"], destino / "img_03_boleto_valor_apagado.png", simulacao="haiku-duvida-valor")
    imagem(["RECIBO", "Emitente: Pessoa Inventada", "Data: 03/10/2026", "Valor total: R$ 75,00"],
           destino / "ilegivel_01_foto_borrada.jpg", "borrado")
    return sorted(destino.iterdir())


if __name__ == "__main__":
    for caminho in gerar():
        print(caminho.relative_to(RAIZ))
