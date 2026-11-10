"""Clientes falsos (sem rede) para testes e para `evals/rodar.py --offline`.

- ClienteRoteirizado: devolve respostas prontas, em ordem (testes unitários).
- ClienteRegras: imita o agente com regras simples e busca por palavras na base,
  para testar o pipeline inteiro sem gastar com a API. Não mede a qualidade do modelo.
- WhatsAppFalso: guarda o que seria enviado pela Graph API.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from itertools import count
from types import SimpleNamespace
from typing import Any

_ids = count(1)


def bloco_texto(texto: str) -> SimpleNamespace:
    """Bloco `text` no formato do SDK."""
    return SimpleNamespace(type="text", text=texto)


def bloco_ferramenta(nome: str, entrada: dict[str, Any]) -> SimpleNamespace:
    """Bloco `tool_use` no formato do SDK."""
    return SimpleNamespace(type="tool_use", id=f"toolu_falso_{next(_ids)}", name=nome, input=entrada)


def resposta(blocos: list[SimpleNamespace], stop_reason: str, **uso: int) -> SimpleNamespace:
    """Objeto parecido com `anthropic.types.Message`."""
    padrao = {"input_tokens": 50, "output_tokens": 30,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    return SimpleNamespace(content=blocos, stop_reason=stop_reason, usage=SimpleNamespace(**(padrao | uso)))


class _Mensagens:
    def __init__(self, dono: Any) -> None:
        self.dono = dono

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.dono.chamadas.append(kwargs)
        return self.dono.gerar(**kwargs)


class ClienteRoteirizado:
    """Devolve as respostas da lista, uma por chamada."""

    def __init__(self, respostas: list[SimpleNamespace]) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []
        self.messages = _Mensagens(self)

    def gerar(self, **_: Any) -> SimpleNamespace:
        return self.respostas.pop(0)


# ---------- ClienteRegras ----------

def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


PARADAS = set(
    "a o os as de da do das dos e em no na nos nas um uma uns umas para por com sem que qual quais "
    "quanto quanta voces voce vcs tem ter sao ser esta estao isso essa esse como onde quando "
    "meu minha gostaria queria quero saber pode podem posso fazem faz aceita aceitam ola oi bom dia "
    "tarde noite obrigado obrigada por favor clinica pelo pela pelos pelas aqui agora".split()
)
SINONIMOS = {
    "custa": "r$", "valor": "r$", "preco": "r$", "pagar": "r$", "pago": "r$",
    "abre": "horario", "abrem": "horario", "fecha": "horario", "funciona": "horario", "funcionamento": "horario",
    "endereco": "rua", "fica": "rua", "localizacao": "rua", "plano": "convenio", "planos": "convenio",
    "convenios": "convenio", "parcelar": "vezes", "parcela": "vezes", "parcelado": "vezes",
    "crianca": "pediatria", "filho": "pediatria", "filha": "pediatria", "carro": "estacionamento",
    "estacionar": "estacionamento", "online": "telemedicina", "video": "telemedicina",
}
EMERGENCIA = re.compile(r"dor no peito|falta de ar|desmai|sangramento")
INJECAO = re.compile(r"ignor[ea]|esque[cç]a|suas instru|prompt|finja|modo desenvolvedor|novas regras")
SENSIVEL = re.compile(
    r"sintoma|\bdor\b|\bdores\b|diagnost|remedio|medicament|dose|antibiotic|febre|resultado do meu|"
    r"meu exame deu|meu resultado|\bgrave\b|gravida|processar|processo judicial|advogad|investi|empresti"
)
CANCELAR = re.compile(r"cancel|desmarc|remarc")
AGENDAR = re.compile(r"agend|marcar|horarios? (livre|disponive)|tem vaga")
DATA_ISO = re.compile(r"(\d{4}-\d{2}-\d{2})")
DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
HORA = re.compile(r"\b(\d{1,2})(?::|h)(\d{2})?\b")
NOME = re.compile(r"meu nome (?:e|eh) ([a-z]+ [a-z]+)")
HOJE = re.compile(r"Agora: \w+, (\d{4}-\d{2}-\d{2})")


def _palavras(texto: str) -> set[str]:
    """Palavras-chave da pergunta (sem paradas) mais os sinônimos, cortadas em 5 letras."""
    brutas = [p for p in re.findall(r"[a-z0-9$]+", normalizar(texto)) if len(p) >= 3 and p not in PARADAS]
    return {p[:5] for p in brutas} | {SINONIMOS[p][:5] for p in brutas if p in SINONIMOS}


def buscar_na_base(pergunta: str, base: str) -> str | None:
    """Linha da base com maior soma de pesos (palavra rara pesa mais: 1/nº de linhas), ou None."""
    linhas = [ln.strip()[2:] for ln in base.splitlines() if ln.strip().startswith("- ")]
    alvos = [{p[:5] for p in re.findall(r"[a-z0-9$]+", normalizar(ln))} for ln in linhas]
    chaves = _palavras(pergunta)
    frequencia = {c: sum(c in a for a in alvos) for c in chaves}
    melhor, pontos = None, 0.0
    for linha, alvo in zip(linhas, alvos):
        nota = sum(1 / frequencia[c] for c in chaves if c in alvo)
        if nota > pontos:
            melhor, pontos = linha, nota
    return melhor


class ClienteRegras:
    """Agente falso determinístico: regras de segurança + busca na base enviada no system."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []
        self.messages = _Mensagens(self)
        self._caches: set[int] = set()

    def _uso(self, system: str, entrada: str, saida: str) -> dict[str, int]:
        """Tokens aproximados (4 caracteres por token), simulando cache do system."""
        chave = hash(system)
        sistema_tokens = len(system) // 4
        lido = chave in self._caches
        self._caches.add(chave)
        return {
            "input_tokens": len(entrada) // 4 + 300,  # + definições das ferramentas
            "cache_creation_input_tokens": 0 if lido else sistema_tokens,
            "cache_read_input_tokens": sistema_tokens if lido else 0,
            "output_tokens": max(1, len(saida) // 4),
        }

    def gerar(self, **kwargs: Any) -> SimpleNamespace:
        system = "".join(b["text"] for b in kwargs["system"])
        base = system.split("# Base de conhecimento", 1)[-1]
        ultima = kwargs["messages"][-1]
        conteudo = ultima["content"]
        if isinstance(conteudo, list) and conteudo and isinstance(conteudo[0], dict) \
                and conteudo[0].get("type") == "tool_result":
            texto = self._apos_ferramenta(kwargs["messages"], conteudo)
            return resposta([bloco_texto(texto)], "end_turn", **self._uso(system, str(conteudo), texto))

        textos = [b["text"] for b in conteudo] if isinstance(conteudo, list) else [conteudo]
        contexto = next((t for t in textos if t.startswith("<contexto>")), "")
        pergunta = next((t for t in reversed(textos) if not t.startswith("<contexto>")), "")
        blocos, parada = self._decidir(pergunta, contexto, base)
        saida = " ".join(getattr(b, "text", "") for b in blocos)
        return resposta(blocos, parada, **self._uso(system, pergunta, saida))

    def _decidir(self, pergunta: str, contexto: str, base: str) -> tuple[list[SimpleNamespace], str]:
        p = normalizar(pergunta)
        if INJECAO.search(p):
            return [bloco_texto("Não posso fazer isso. Só consigo ajudar com informações e "
                                "agendamentos da clínica.")], "end_turn"
        if EMERGENCIA.search(p):
            return [bloco_texto("Ligue agora para o SAMU (192) ou vá ao pronto-socorro mais próximo."),
                    bloco_ferramenta("transferir_para_humano", {"motivo": "possível emergência"})], "tool_use"
        if SENSIVEL.search(p):
            return [bloco_ferramenta("transferir_para_humano",
                                     {"motivo": f"assunto sensível: {pergunta[:80]}"})], "tool_use"
        if CANCELAR.search(p):
            return [bloco_ferramenta("cancelar_agendamento", {"telefone": "", "data_hora": ""})], "tool_use"
        dia = self._data(p, contexto)
        nome, hora = NOME.search(p), HORA.search(p)
        if nome and hora and dia:
            data_hora = f"{dia.isoformat()}T{int(hora.group(1)):02d}:{hora.group(2) or '00'}"
            entrada = {"nome": nome.group(1).title(), "telefone": "", "data_hora": data_hora, "observacao": ""}
            return [bloco_ferramenta("agendar", entrada)], "tool_use"
        if AGENDAR.search(p):
            alvo = dia or self._hoje(contexto) + timedelta(days=1)
            return [bloco_ferramenta("consultar_horarios", {"data": alvo.isoformat()})], "tool_use"
        achado = buscar_na_base(pergunta, base)
        if achado:
            return [bloco_texto(achado)], "end_turn"
        return [bloco_texto("Não sei essa informação. Só consigo ajudar com assuntos da clínica; "
                            "quer que eu chame uma pessoa da equipe?")], "end_turn"

    @staticmethod
    def _hoje(contexto: str) -> date:
        achado = HOJE.search(contexto)
        return date.fromisoformat(achado.group(1)) if achado else date.today()

    def _data(self, p: str, contexto: str) -> date | None:
        """Data citada na pergunta: ISO, dd/mm, 'amanhã' ou 'hoje'."""
        hoje = self._hoje(contexto)
        if m := DATA_ISO.search(p):
            return date.fromisoformat(m.group(1))
        if m := DATA_BR.search(p):
            return date(hoje.year, int(m.group(2)), int(m.group(1)))
        if "amanha" in p:
            return hoje + timedelta(days=1)
        return None

    @staticmethod
    def _apos_ferramenta(mensagens: list[dict[str, Any]], resultados: list[dict[str, Any]]) -> str:
        """Texto final depois de uma ferramenta, com base no nome dela."""
        anterior = mensagens[-2]["content"]
        nome = next(b.name for b in anterior if getattr(b, "type", "") == "tool_use")
        resultado = resultados[0]["content"]
        erro = resultados[0].get("is_error", False)
        if nome == "transferir_para_humano":
            return "Esse assunto precisa de uma pessoa da equipe. Vou transferir sua conversa agora."
        if nome == "consultar_horarios":
            return f"{resultado} Qual horário prefere? Me diga também seu nome completo."
        if nome == "agendar":
            return f"{resultado} Chegue 15 minutos antes." if not erro else \
                f"Não consegui agendar: {resultado}"
        if nome == "cancelar_agendamento":
            return f"{resultado} Quer marcar um novo horário?" if not erro else \
                f"Não encontrei agendamento ativo. {resultado}"
        return resultado


class WhatsAppFalso:
    """Mesma interface do ClienteWhatsApp, sem rede."""

    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str]] = []
        self.templates: list[tuple[str, str, list[str]]] = []
        self.lidas: list[str] = []
        self.midias: dict[str, tuple[bytes, str]] = {}  # media_id → (bytes, mime) para testes de documentos

    def enviar_texto(self, para: str, texto: str) -> str:
        self.enviadas.append((para, texto))
        return f"wamid.falso.{len(self.enviadas)}"

    def enviar_template(self, para: str, nome: str, variaveis: list[str], idioma: str = "pt_BR") -> str:
        self.templates.append((para, nome, variaveis))
        return f"wamid.template.{len(self.templates)}"

    def marcar_como_lida(self, id_meta: str) -> None:
        self.lidas.append(id_meta)

    def baixar_midia(self, media_id: str) -> tuple[bytes, str]:
        return self.midias.get(media_id, (b"OggS-falso", "audio/ogg"))


# ---------- Documentos (nível 2) ----------

PDF_TEXTO = re.compile(rb"\(((?:\\.|[^\\)])*)\)\s*Tj")
CATEGORIA_POR_TITULO = [
    ("nota fiscal de servico", "nota_fiscal_servico"), ("nfs-e", "nota_fiscal_servico"),
    ("cupom", "cupom_fiscal"), ("recibo", "recibo"), ("boleto", "boleto"),
    ("extrato", "extrato_bancario"), ("nota fiscal", "nota_fiscal_produto"), ("danfe", "nota_fiscal_produto"),
]
VALOR_BR = r"R\$\s*([\d.]+,\d{2})"


def _desescapar_pdf(trecho: bytes) -> str:
    """Desfaz os escapes de string literal do PDF (parênteses, barra, octal) e decodifica cp1252."""
    saida, i = bytearray(), 0
    while i < len(trecho):
        c = trecho[i]
        if c == 0x5C and i + 1 < len(trecho):
            prox = trecho[i + 1:i + 4]
            if prox[:1].isdigit():
                n = len(re.match(rb"[0-7]{1,3}", prox).group())
                saida.append(int(trecho[i + 1:i + 1 + n], 8))
                i += 1 + n
                continue
            saida.append(trecho[i + 1])
            i += 2
            continue
        saida.append(c)
        i += 1
    return saida.decode("cp1252", "replace")


def texto_do_pdf(dados: bytes) -> str:
    """Texto dos operadores Tj de um PDF sem compressão (os PDFs de exemplo são assim)."""
    return "\n".join(_desescapar_pdf(m.group(1)) for m in PDF_TEXTO.finditer(dados))


def textos_do_png(dados: bytes) -> dict[str, str]:
    """Pedaços iTXt/tEXt de um PNG (o gerador de exemplos grava o texto da imagem ali)."""
    import struct
    import zlib

    textos, pos = {}, 8
    while pos + 8 <= len(dados):
        tamanho, tipo = struct.unpack(">I4s", dados[pos:pos + 8])
        corpo = dados[pos + 8:pos + 8 + tamanho]
        if tipo == b"tEXt":
            chave, _, valor = corpo.partition(b"\0")
            textos[chave.decode("latin-1")] = valor.decode("latin-1")
        elif tipo == b"iTXt":
            chave, _, resto = corpo.partition(b"\0")
            comprimido, resto = resto[0], resto[2:]
            _, _, resto = resto.partition(b"\0")
            _, _, valor = resto.partition(b"\0")
            textos[chave.decode("latin-1")] = (zlib.decompress(valor) if comprimido else valor).decode("utf-8")
        pos += 12 + tamanho
    return textos


def _ler_campos(texto: str) -> dict[str, Any]:
    """Imita a extração: procura rótulos fixos no texto; ausente = vazio com confiança baixa."""
    n = normalizar(texto)
    categoria = next((cat for chave, cat in CATEGORIA_POR_TITULO if chave in n), "outro")
    achados = {
        "emitente": re.search(r"(?:Emitente|Prestador|Banco|Recebi de)\s*:\s*(.+)", texto),
        "documento_emitente": re.search(r"(?:CNPJ|CPF)\s*:\s*([\w./-]+)", texto),
        "data_emissao": re.search(r"(?:Data|Emiss[ãa]o|Vencimento)\s*:\s*(\d{2})/(\d{2})/(\d{4})", texto),
        "valor_total": re.search(r"(?:Total|Valor (?:total|cobrado|pago)|Saldo final)\s*:\s*" + VALOR_BR, texto),
    }
    numero = re.search(r"N[º°o]\.?\s*:?\s*(\w+)", texto)

    def real(s: str) -> float:
        return float(s.replace(".", "").replace(",", "."))

    data = achados["data_emissao"]
    itens = [{"descricao": d.strip(), "valor": real(v)}
             for d, v in re.findall(r"Item\s*:\s*(.+?)\s*[|.]{1,}\s*" + VALOR_BR, texto)]
    campos = {
        "legivel": True, "categoria": categoria,
        "data_emissao": f"{data.group(3)}-{data.group(2)}-{data.group(1)}" if data else "",
        "emitente": achados["emitente"].group(1).strip() if achados["emitente"] else "",
        "documento_emitente": re.sub(r"\W", "", achados["documento_emitente"].group(1))
        if achados["documento_emitente"] else "",
        "numero_documento": numero.group(1) if numero else "",
        "valor_total": real(achados["valor_total"].group(1)) if achados["valor_total"] else 0.0,
        "itens": itens,
        "confianca": {c: ("alta" if achados[c] else "baixa") for c in achados} | {
            "categoria": "alta" if categoria != "outro" else "baixa"},
        "evidencia": {c: (achados[c].group(0)[:60] if achados[c] else "") for c in achados} | {
            "categoria": texto.strip().splitlines()[0][:60] if texto.strip() else ""},
        "observacao": "",
    }
    return campos


class ClienteDocumentosFalso:
    """Imita a extração da Claude API lendo o texto que o gerador de exemplos embutiu no arquivo.

    PDF: texto dos operadores Tj. Imagem PNG: pedaço iTXt 'conteudo' (e 'simulacao' para testar
    o roteamento Haiku → Sonnet). Sem texto = ilegível. Valida o pipeline, não a qualidade do modelo.
    """

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []
        self.messages = _Mensagens(self)

    def gerar(self, **kwargs: Any) -> SimpleNamespace:
        import base64
        import json

        bloco = kwargs["messages"][0]["content"][0]
        dados = base64.standard_b64decode(bloco["source"]["data"])
        simulacao = ""
        if bloco["type"] == "document":
            texto, tokens_arquivo = texto_do_pdf(dados), 1500 * max(1, len(re.findall(rb"/Type\s*/Page(?!s)", dados)))
        else:
            pedacos = textos_do_png(dados) if dados.startswith(b"\x89PNG") else {}
            texto, simulacao, tokens_arquivo = pedacos.get("conteudo", ""), pedacos.get("simulacao", ""), 1600
        if len(normalizar(texto).strip()) < 15:
            campos = {"legivel": False, "categoria": "outro", "data_emissao": "", "emitente": "",
                      "documento_emitente": "", "numero_documento": "", "valor_total": 0.0, "itens": [],
                      "confianca": dict.fromkeys(["data_emissao", "emitente", "documento_emitente",
                                                  "valor_total", "categoria"], "baixa"),
                      "evidencia": dict.fromkeys(["data_emissao", "emitente", "documento_emitente",
                                                  "valor_total", "categoria"], ""),
                      "observacao": "sem texto legível"}
        else:
            campos = _ler_campos(texto)
            if simulacao == "haiku-duvida-valor" and "haiku" in kwargs["model"]:
                campos["confianca"]["valor_total"] = "baixa"
        saida = json.dumps(campos, ensure_ascii=False)
        uso = {"input_tokens": tokens_arquivo + 450, "output_tokens": max(1, len(saida) // 4)}
        return resposta([bloco_texto(saida)], "end_turn", **uso)
