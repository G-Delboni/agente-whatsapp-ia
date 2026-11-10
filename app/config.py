"""Configuração lida de variáveis de ambiente (e do arquivo .env, se existir)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent

# Preços da Claude API em US$ por milhão de tokens (conferir em
# https://platform.claude.com/docs/en/about-claude/pricing antes de usar).
# Ordem: entrada, escrita de cache 5 min, leitura de cache, saída.
# Haiku 5.5: vale para prompts até 100k tokens; acima disso a faixa é 5x mais cara.
PRECOS_USD_POR_MILHAO: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 2.50, 0.10, 10.00),
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
}


def _carregar_dotenv(caminho: Path) -> None:
    """Lê um .env simples (CHAVE=valor) sem sobrescrever o ambiente."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def _env(nome: str, padrao: str = "") -> str:
    """Lê uma variável de ambiente; vazia ou ausente usa o padrão."""
    return (os.environ.get(nome) or padrao).strip()


def _horario_comercial(texto: str) -> dict[int, tuple[str, str]]:
    """Converte '0-4=08:00-18:00;5=08:00-12:00' em {dia_da_semana: (início, fim)}."""
    resultado: dict[int, tuple[str, str]] = {}
    for parte in filter(None, (p.strip() for p in texto.split(";"))):
        dias, horas = parte.split("=")
        inicio, fim = horas.split("-")
        if "-" in dias:
            a, b = dias.split("-")
            faixa = range(int(a), int(b) + 1)
        else:
            faixa = [int(d) for d in dias.split(",")]
        for d in faixa:
            resultado[d] = (inicio, fim)
    return resultado


@dataclass(frozen=True)
class Config:
    """Todas as configurações do atendente (uma instância por cliente/deploy)."""

    nome_negocio: str = "Clínica Exemplo"
    # Modelo: Haiku é o mais barato e suficiente para atendimento com base fechada.
    modelo: str = "claude-haiku-5-5"
    max_tokens: int = 500
    esforco: str = "low"  # output_config.effort; "low" economiza raciocínio no Haiku
    max_iteracoes_ferramentas: int = 5
    historico_max_mensagens: int = 20
    historico_horas: int = 24

    meta_token: str = ""
    meta_phone_number_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    graph_api_versao: str = "v24.0"

    numero_responsavel: str = ""
    template_aviso_responsavel: str = ""
    pausa_humano_horas: int = 12
    horas_nova_conversa: int = 24
    fuso: str = "America/Sao_Paulo"
    horario_comercial: dict[int, tuple[str, str]] = field(
        default_factory=lambda: _horario_comercial("0-4=08:00-18:00;5=08:00-12:00")
    )
    duracao_consulta_min: int = 30

    limite_gasto_diario_usd: float = 2.0
    limite_msgs_por_hora: int = 30
    max_caracteres_entrada: int = 1500
    retencao_dias: int = 180

    cambio_brl: float = 5.53
    meta_preco_msg_brl: float = 0.035
    meta_franquia_msgs: int = 1000

    transcricao_url: str = ""
    transcricao_chave: str = ""
    transcricao_modelo: str = "whisper-1"

    # Nível 2 (documentos): desligado por padrão; ver app/documentos/.
    modo_documentos: bool = False
    modelo_documentos: str = "claude-haiku-5-5"
    modelo_documentos_ambiguo: str = "claude-sonnet-5-5"  # só para caso ambíguo (roteado no código)
    rotear_ambiguo: bool = True
    documentos_dir: Path = RAIZ / "dados" / "documentos"
    planilhas_dir: Path = RAIZ / "dados" / "planilhas"
    checklist_documentos: Path = RAIZ / "checklist_documentos.yaml"

    admin_token: str = ""
    db_caminho: Path = RAIZ / "dados" / "agente.db"
    kb_dir: Path = RAIZ / "kb"
    prompts_dir: Path = RAIZ / "prompts"

    @property
    def tz(self) -> ZoneInfo:
        """Fuso horário do negócio."""
        return ZoneInfo(self.fuso)


def carregar_do_ambiente() -> Config:
    """Monta a Config a partir do ambiente (.env opcional na raiz)."""
    _carregar_dotenv(RAIZ / ".env")
    base = Config()
    return Config(
        nome_negocio=_env("NOME_NEGOCIO", base.nome_negocio),
        modelo=_env("MODELO", base.modelo),
        max_tokens=int(_env("MAX_TOKENS", str(base.max_tokens))),
        esforco=_env("ESFORCO", base.esforco),
        max_iteracoes_ferramentas=int(_env("MAX_ITERACOES_FERRAMENTAS", "5")),
        historico_max_mensagens=int(_env("HISTORICO_MAX_MENSAGENS", "20")),
        historico_horas=int(_env("HISTORICO_HORAS", "24")),
        meta_token=_env("META_TOKEN"),
        meta_phone_number_id=_env("META_PHONE_NUMBER_ID"),
        meta_app_secret=_env("META_APP_SECRET"),
        meta_verify_token=_env("META_VERIFY_TOKEN"),
        graph_api_versao=_env("GRAPH_API_VERSAO", base.graph_api_versao),
        numero_responsavel=_env("NUMERO_RESPONSAVEL"),
        template_aviso_responsavel=_env("TEMPLATE_AVISO_RESPONSAVEL"),
        pausa_humano_horas=int(_env("PAUSA_HUMANO_HORAS", "12")),
        horas_nova_conversa=int(_env("HORAS_NOVA_CONVERSA", "24")),
        fuso=_env("FUSO", base.fuso),
        horario_comercial=_horario_comercial(
            _env("HORARIO_COMERCIAL", "0-4=08:00-18:00;5=08:00-12:00")
        ),
        duracao_consulta_min=int(_env("DURACAO_CONSULTA_MIN", "30")),
        limite_gasto_diario_usd=float(_env("LIMITE_GASTO_DIARIO_USD", "2.0")),
        limite_msgs_por_hora=int(_env("LIMITE_MSGS_POR_HORA", "30")),
        max_caracteres_entrada=int(_env("MAX_CARACTERES_ENTRADA", "1500")),
        retencao_dias=int(_env("RETENCAO_DIAS", "180")),
        cambio_brl=float(_env("CAMBIO_BRL", "5.53")),
        meta_preco_msg_brl=float(_env("META_PRECO_MSG_BRL", "0.035")),
        meta_franquia_msgs=int(_env("META_FRANQUIA_MSGS", "1000")),
        transcricao_url=_env("TRANSCRICAO_URL"),
        transcricao_chave=_env("TRANSCRICAO_CHAVE"),
        transcricao_modelo=_env("TRANSCRICAO_MODELO", base.transcricao_modelo),
        modo_documentos=_env("MODO_DOCUMENTOS", "0") == "1",
        modelo_documentos=_env("MODELO_DOCUMENTOS", base.modelo_documentos),
        modelo_documentos_ambiguo=_env("MODELO_DOCUMENTOS_AMBIGUO", base.modelo_documentos_ambiguo),
        rotear_ambiguo=_env("ROTEAR_AMBIGUO", "1") == "1",
        documentos_dir=Path(_env("DOCUMENTOS_DIR", str(base.documentos_dir))),
        planilhas_dir=Path(_env("PLANILHAS_DIR", str(base.planilhas_dir))),
        checklist_documentos=Path(_env("CHECKLIST_DOCUMENTOS", str(base.checklist_documentos))),
        admin_token=_env("ADMIN_TOKEN"),
        db_caminho=Path(_env("DB_CAMINHO", str(base.db_caminho))),
        kb_dir=Path(_env("KB_DIR", str(base.kb_dir))),
        prompts_dir=Path(_env("PROMPTS_DIR", str(base.prompts_dir))),
    )


_atual: Config | None = None


def obter() -> Config:
    """Devolve a configuração ativa (carrega do ambiente na primeira vez)."""
    global _atual
    if _atual is None:
        _atual = carregar_do_ambiente()
    return _atual


def definir(cfg: Config) -> None:
    """Troca a configuração ativa (usado em testes e evals)."""
    global _atual
    _atual = cfg
    ler_texto.cache_clear()


def agora() -> datetime:
    """Data e hora atuais no fuso do negócio (substituível em testes)."""
    return datetime.now(obter().tz).replace(microsecond=0)


@lru_cache(maxsize=8)
def ler_texto(caminho: Path) -> str:
    """Lê um arquivo de texto uma vez e guarda em memória."""
    return caminho.read_text(encoding="utf-8")
