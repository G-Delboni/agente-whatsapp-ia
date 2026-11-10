"""Nível 2 (documentos): extrator, validação, planilha, checklist, cobrança, webhook e lote. Sem rede."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from openpyxl import load_workbook

from app import config, db, metricas
from app.atendimento import MSG_PEDIR_TEXTO, processar_mensagem
from app.cliente_falso import ClienteDocumentosFalso, ClienteRoteirizado, bloco_texto, resposta
from app.documentos import checklist, cobranca, extrator, planilha, validacao
from app.whatsapp import MensagemRecebida, extrair_mensagens
from scripts import processar_lote

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "evals" / "documentos_exemplo"
HOJE = date(2026, 11, 11)
TELEFONE_PADARIA = "5500900000101"


def _doc(nome: str, llm=None, cfg: config.Config | None = None) -> extrator.DocumentoProcessado:
    return extrator.extrair_arquivo(EXEMPLOS / nome, llm or ClienteDocumentosFalso(), HOJE, cfg or config.Config())


def _json_extracao(**mudancas) -> str:
    base = json.loads(extrator.extracao_vazia("").model_dump_json())
    base.update(legivel=True, categoria="recibo", data_emissao="2026-10-05", emitente="Fulano Fictício",
                documento_emitente="52998224725", valor_total=100.0,
                confianca=dict.fromkeys(extrator.CAMPOS_CONFIANCA, "alta"))
    base.update(mudancas)
    return json.dumps(base)


# ---------- extrator ----------

def test_esquema_bate_com_o_modelo_pydantic() -> None:
    assert set(extrator.ESQUEMA_EXTRACAO["properties"]) == set(extrator.Extracao.model_fields)
    assert set(extrator.ESQUEMA_EXTRACAO["required"]) == set(extrator.Extracao.model_fields)
    assert extrator.ESQUEMA_EXTRACAO["additionalProperties"] is False


@pytest.mark.parametrize("usar_nfelib", [True, False])
def test_xml_nfe_sem_ia_com_e_sem_nfelib(usar_nfelib: bool) -> None:
    dados = (EXEMPLOS / "nfe_02_atacado_com_frete.xml").read_bytes()
    ext, vprod, origem = extrator.ler_nfe_xml(dados, usar_nfelib=usar_nfelib)
    assert origem == ("xml-nfelib" if usar_nfelib and extrator.NFELIB_DISPONIVEL else "xml-simples")
    assert ext.valor_total == 320.0 and vprod == 300.0 and ext.data_emissao == "2026-10-21"
    assert ext.categoria == "nota_fiscal_produto" and len(ext.itens) == 2
    assert ext.observacao.startswith("chave 35")


def test_xml_nao_nfe_vai_para_revisao() -> None:
    doc = extrator.extrair_bytes(b"<?xml version='1.0'?><outro/>", "x.xml", "", None, HOJE, config.Config())
    assert doc.revisar and not doc.extracao.legivel and doc.custo_usd == 0


def test_xml_nao_chama_a_api() -> None:
    llm = ClienteDocumentosFalso()
    doc = _doc("nfe_01_papelaria.xml", llm)
    assert llm.chamadas == [] and doc.modelos == [] and not doc.revisar


def test_pdf_vai_ao_haiku_com_saida_estruturada() -> None:
    llm = ClienteDocumentosFalso()
    doc = _doc("pdf_01_recibo_aluguel.pdf", llm)
    pedido = llm.chamadas[0]
    assert pedido["model"] == "claude-haiku-5-5"
    assert pedido["messages"][0]["content"][0]["type"] == "document"
    assert pedido["output_config"]["format"]["type"] == "json_schema"
    assert doc.extracao.valor_total == 1800.0 and doc.extracao.documento_emitente == "90012345695"
    assert not doc.revisar and doc.usos[0].custo_usd > 0


def test_caso_ambiguo_roteia_para_sonnet_e_pode_ser_desligado() -> None:
    doc = _doc("img_03_boleto_valor_apagado.png")
    assert doc.modelos == ["claude-haiku-5-5", "claude-sonnet-5-5"] and not doc.revisar
    sem_rota = _doc("img_03_boleto_valor_apagado.png", cfg=replace(config.Config(), rotear_ambiguo=False))
    assert sem_rota.modelos == ["claude-haiku-5-5"]
    assert "baixa confiança em valor_total" in sem_rota.motivos_revisao


def test_ilegivel_nao_tenta_sonnet() -> None:
    doc = _doc("ilegivel_01_foto_borrada.jpg")
    assert doc.revisar and doc.modelos == ["claude-haiku-5-5"]


def test_recusa_e_json_invalido_viram_revisao() -> None:
    recusa = ClienteRoteirizado([resposta([], "refusal")])
    doc = extrator.extrair_bytes(b"%PDF-1.4", "a.pdf", "application/pdf", recusa, HOJE,
                                 replace(config.Config(), rotear_ambiguo=False))
    assert doc.revisar and "refusal" in doc.extracao.observacao
    lixo = ClienteRoteirizado([resposta([bloco_texto("não é json")], "end_turn")])
    doc = extrator.extrair_bytes(b"%PDF-1.4", "a.pdf", "application/pdf", lixo, HOJE,
                                 replace(config.Config(), rotear_ambiguo=False))
    assert doc.revisar


def test_formato_nao_suportado_e_arquivo_grande() -> None:
    doc = extrator.extrair_bytes(b"heic", "foto.heic", "image/heic", None, HOJE, config.Config())
    assert doc.revisar and "não suportado" in doc.extracao.observacao
    grande = extrator.extrair_bytes(b"0" * (extrator.TAMANHO_MAXIMO + 1), "a.pdf", "", None, HOJE, config.Config())
    assert "10 MB" in grande.extracao.observacao


def test_pedido_passa_pela_validacao_do_sdk() -> None:
    """Parâmetros reais do SDK (output_config.format, document base64) com transporte simulado."""
    pedidos: list[dict] = []
    corpo = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
             "content": [{"type": "text", "text": _json_extracao()}], "stop_reason": "end_turn",
             "stop_sequence": None, "usage": {"input_tokens": 3000, "output_tokens": 200}}

    def responder(request: httpx2.Request) -> httpx2.Response:
        pedidos.append(json.loads(request.content))
        return httpx2.Response(200, json=corpo)

    cliente = anthropic.Anthropic(api_key="chave-falsa-de-teste", max_retries=0,
                                  http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(responder)))
    doc = extrator.extrair_arquivo(EXEMPLOS / "pdf_01_recibo_aluguel.pdf", cliente, HOJE, config.Config())
    assert doc.extracao.valor_total == 100.0 and not doc.revisar
    enviado = pedidos[0]
    assert enviado["messages"][0]["content"][0]["source"]["media_type"] == "application/pdf"
    assert enviado["output_config"]["format"]["schema"]["required"]
    assert round(doc.custo_usd, 6) == round((3000 * 0.10 + 200 * 0.50) / 1e6, 6)


# ---------- validação ----------

def test_cpf_e_cnpj() -> None:
    assert validacao.cpf_valido("529.982.247-25") and not validacao.cpf_valido("111.111.111-11")
    assert validacao.cnpj_valido("11.222.333/0001-81") and not validacao.cnpj_valido("11.222.333/0001-82")
    assert validacao.cnpj_valido("12.ABC.345/01DE-35")  # CNPJ alfanumérico (Receita, 2026)
    assert validacao.validar_documento("") == "CNPJ/CPF do emitente ausente"
    assert "tamanho" in validacao.validar_documento("123")


def test_datas_e_soma() -> None:
    assert validacao.validar_data("2026-10-15", HOJE) is None
    assert "futuro" in validacao.validar_data("2026-12-01", HOJE)
    assert "antiga" in validacao.validar_data("2020-01-01", HOJE)
    assert "formato" in validacao.validar_data("15/10/2026", HOJE)
    assert validacao.validar_soma([50.0, 20.0], 70.0) is None
    assert validacao.validar_soma([50.0, 20.0], 70.01) is None  # arredondamento
    assert "R$ 70,00" in validacao.validar_soma([50.0, 20.0], 80.0)
    assert validacao.validar_soma([], 80.0) is None


def test_baixa_confianca_sempre_pede_revisao() -> None:
    llm = ClienteRoteirizado([resposta([bloco_texto(_json_extracao(
        confianca=dict.fromkeys(extrator.CAMPOS_CONFIANCA, "alta") | {"emitente": "baixa"}))], "end_turn")])
    doc = extrator.extrair_bytes(b"%PDF", "a.pdf", "application/pdf", llm, HOJE, config.Config())
    assert doc.motivos_revisao == ["baixa confiança em emitente"]


# ---------- checklist, planilha e cobrança ----------

def _checklist() -> checklist.Checklist:
    return checklist.carregar(RAIZ / "checklist_documentos.yaml")


def test_checklist_calcula_o_que_falta() -> None:
    padaria = _checklist().por_id("padaria-pao-bom")
    falta = checklist.calcular_pendencias(padaria, ["nota_fiscal_produto", "outro"])
    assert [p.texto for p in falta] == ["extrato do Banco Exemplo", "1 de 2 notas de compra", "recibo do aluguel"]
    assert checklist.resumo_painel(padaria, falta).startswith("Padaria Pão Bom (fictícia): faltam extrato")
    tudo = ["extrato_bancario", "nota_fiscal_produto", "nota_fiscal_produto", "recibo"]
    assert checklist.calcular_pendencias(padaria, tudo) == []
    assert _checklist().por_telefone(TELEFONE_PADARIA).id == "padaria-pao-bom"


def test_planilha_revisar_dedupe_e_pendencias(tmp_path: Path) -> None:
    caminho = planilha.caminho_planilha(tmp_path, "Padaria Pão Bom")
    assert caminho.name == "padaria-pao-bom.xlsx"
    docs = [_doc("nfe_01_papelaria.xml"), _doc("nfe_03_cupom_cnpj_invalido.xml")]
    agora = datetime(2026, 11, 11, 10, 0)
    assert planilha.adicionar_lancamentos(caminho, docs, agora) == 2
    assert planilha.adicionar_lancamentos(caminho, docs, agora) == 0  # mesmo arquivo não entra duas vezes
    linhas = planilha.ler_lancamentos(caminho)
    assert [l["Revisar"] for l in linhas] == ["não", "SIM"]
    assert linhas[1]["Motivos da revisão"].startswith("CNPJ inválido")
    aba = load_workbook(caminho)[planilha.ABA_LANCAMENTOS]
    assert aba.cell(row=3, column=1).fill.start_color.rgb.endswith("FFF2CC")  # amarelo = revisar
    assert planilha.categorias_da_competencia(linhas, "2026-10") == ["nota_fiscal_produto", "cupom_fiscal"]
    pend = [checklist.Pendencia("extrato_bancario", "extrato", 1)]
    planilha.escrever_pendencias(caminho, "2026-09", pend)
    planilha.escrever_pendencias(caminho, "2026-10", pend)
    planilha.escrever_pendencias(caminho, "2026-10", [])
    pendencias = list(load_workbook(caminho)[planilha.ABA_PENDENCIAS].iter_rows(min_row=2, values_only=True))
    assert pendencias == [("2026-09", "extrato", 1)]


def test_ilegivel_nao_conta_como_recebido() -> None:
    linhas = [{"Categoria": "recibo", "Data emissão": "2026-10-01", "Motivos da revisão": "ilegível: x"}]
    assert planilha.categorias_da_competencia(linhas, "2026-10") == []


def test_cobranca_texto_e_variaveis() -> None:
    pend = [checklist.Pendencia("extrato_bancario", "extrato do Itaú", 1),
            checklist.Pendencia("nota_fiscal_produto", "notas de compra", 2, 2)]
    texto = cobranca.mensagem_cobranca("João", "outubro", "Padaria Pão Bom", pend, "10/11")
    assert texto.startswith("Olá, João! Para fecharmos a contabilidade de outubro da Padaria Pão Bom")
    assert "extrato do Itaú e 2 notas de compra" in texto and "{{" not in texto
    assert cobranca.variaveis_cobranca("João", "outubro", "P", pend, "10/11")[3] == "extrato do Itaú e 2 notas de compra"


def test_mensagem_recebido() -> None:
    doc = _doc("nfe_01_papelaria.xml")
    texto = cobranca.mensagem_recebido(doc, [checklist.Pendencia("extrato_bancario", "extrato", 1)], "outubro")
    assert texto == ("Recebi a nota fiscal de Papelaria Ponto Fictício Ltda (R$ 70,00, 15/10/2026). Obrigado! "
                     "Ainda falta: extrato.")
    assert cobranca.mensagem_recebido(doc, [], "outubro").endswith("Está tudo certo para outubro.")
    assert cobranca.mensagem_recebido(_doc("ilegivel_01_foto_borrada.jpg"), [], "x") == cobranca.ILEGIVEL


# ---------- webhook com MODO_DOCUMENTOS ----------

def _payload_imagem(media_id: str, telefone: str) -> dict:
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"profile": {"name": "João"}, "wa_id": telefone}],
        "messages": [{"from": telefone, "id": "wamid.IMG1", "timestamp": "1", "type": "image",
                      "image": {"id": media_id, "mime_type": "image/png", "caption": "nota"}}]}}]}]}


def test_webhook_le_imagem_e_documento() -> None:
    msg = extrair_mensagens(_payload_imagem("MID1", TELEFONE_PADARIA))[0]
    assert (msg.tipo, msg.media_id, msg.mime, msg.texto) == ("image", "MID1", "image/png", "nota")


def test_modo_documentos_extrai_lanca_e_responde(deps, cfg, tmp_path: Path) -> None:
    config.definir(replace(cfg, modo_documentos=True, planilhas_dir=tmp_path / "planilhas",
                           documentos_dir=tmp_path / "docs", checklist_documentos=RAIZ / "checklist_documentos.yaml"))
    deps.llm = ClienteDocumentosFalso()
    deps.whatsapp.midias["MID1"] = ((EXEMPLOS / "pdf_01_recibo_aluguel.pdf").read_bytes(), "application/pdf")
    msg = MensagemRecebida("wamid.D1", TELEFONE_PADARIA, "João", "document", media_id="MID1",
                           mime="application/pdf", nome_arquivo="recibo.pdf")
    processar_mensagem(msg, deps)
    _, enviado = deps.whatsapp.enviadas[-1]
    assert "Recebi o recibo de Maria Locadora Fictícia (R$ 1.800,00, 05/10/2026)" in enviado
    assert "Ainda falta: extrato do Banco Exemplo e 2 notas de compra." in enviado
    linhas = planilha.ler_lancamentos(tmp_path / "planilhas" / "padaria-pao-bom.xlsx")
    assert len(linhas) == 1 and linhas[0]["Valor (R$)"] == 1800.0
    assert len(list((tmp_path / "docs" / "padaria-pao-bom").iterdir())) == 1
    with db.conexao() as con:
        registro = con.execute("SELECT status, revisar FROM documentos_recebidos").fetchone()
        origem = con.execute("SELECT origem FROM uso_tokens").fetchone()[0]
    assert tuple(registro) == ("aguardando_aprovacao", 0) and origem == "documentos"
    assert metricas.calcular(2026, 11).custo_usd > 0  # entra no relatório mensal


def test_modo_documentos_desligado_pede_texto(deps) -> None:
    msg = MensagemRecebida("wamid.D2", "5500900000555", None, "image", media_id="MID9", mime="image/jpeg")
    processar_mensagem(msg, deps)
    assert MSG_PEDIR_TEXTO in deps.whatsapp.enviadas[-1][1]


def test_falha_no_download_responde_sem_quebrar(deps, cfg, tmp_path: Path) -> None:
    config.definir(replace(cfg, modo_documentos=True, planilhas_dir=tmp_path, documentos_dir=tmp_path))

    def falhar(_):
        raise RuntimeError("rede")

    deps.whatsapp.baixar_midia = falhar
    processar_mensagem(MensagemRecebida("wamid.D3", "5500900000556", None, "image", media_id="X"), deps)
    assert "não consegui processar" in deps.whatsapp.enviadas[-1][1]


# ---------- lote ----------

def test_lote_monta_requisicoes_validas_e_custa_metade() -> None:
    arquivos = processar_lote.arquivos_da_pasta(EXEMPLOS)
    requisicoes, mapa = processar_lote.montar_lote(arquivos, config.Config())
    assert len(requisicoes) == 9  # 4 PDF + 3 imagens + 2 ilegíveis; XML fica fora do lote
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", r["custom_id"]) for r in requisicoes)
    assert set(mapa) == {r["custom_id"] for r in requisicoes}
    llm = ClienteDocumentosFalso()
    r = requisicoes[0]
    doc = processar_lote.doc_do_resultado(Path(mapa[r["custom_id"]]), llm.messages.create(**r["params"]),
                                          "claude-haiku-5-5")
    inteiro = replace(doc.usos[0], fator=1.0).custo_usd
    assert doc.custo_usd == pytest.approx(inteiro / 2)


def test_evals_de_documentos_offline_passam(cfg, tmp_path: Path) -> None:
    import yaml

    from evals import rodar_documentos

    config.definir(replace(cfg, checklist_documentos=RAIZ / "checklist_documentos.yaml"))
    casos = yaml.safe_load((RAIZ / "evals" / "casos_documentos.yaml").read_text(encoding="utf-8"))
    assert len(casos) == 12
    resultados = rodar_documentos.rodar(casos, ClienteDocumentosFalso())
    assert [r.id for r in resultados if not r.aprovado] == []
    painel = rodar_documentos.montar_planilhas(resultados, tmp_path / "saida")
    assert any("faltam extrato do Banco Exemplo" in linha for linha in painel)


def test_resposta_falsa_tem_formato_do_sdk() -> None:
    r = ClienteDocumentosFalso().messages.create(**extrator.montar_pedido(
        (EXEMPLOS / "pdf_02_nfse_estudio.pdf").read_bytes(), "application/pdf", "claude-haiku-5-5"))
    assert isinstance(r, SimpleNamespace) and r.stop_reason == "end_turn"
    assert extrator.Extracao.model_validate_json(r.content[0].text).categoria == "nota_fiscal_servico"
