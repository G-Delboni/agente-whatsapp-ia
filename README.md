# agente-whatsapp-ia

Atendente virtual para WhatsApp construído sobre a API da Anthropic (Claude), em Python e FastAPI. Responde dúvidas a partir de uma base de conhecimento em Markdown, consulta e marca horários com ferramentas, e transfere a conversa para uma pessoa quando o assunto sai do escopo.

O laço do agente é escrito à mão, sem framework de agentes, para deixar visível cada decisão de engenharia: cache de prompt, ferramentas em modo estrito, guardas de custo e de dados pessoais, e uma suíte de evals que roda sem rede.

> **Estado do projeto:** protótipo funcional. Os testes e os evals rodam em modo offline, com um cliente simulado, e validam o fluxo de ponta a ponta. Ainda não há medição publicada com o modelo real, e o projeto não está em produção.

Todos os dados de exemplo (clínica, escritório, notas fiscais, telefones) são fictícios.

## Como funciona

```
Usuário (WhatsApp)
        │ mensagem
        ▼
WhatsApp Cloud API ──POST──▶ /webhook (FastAPI)
                              │ 1. confere a assinatura HMAC (X-Hub-Signature-256)
                              │ 2. descarta eventos repetidos pelo id da mensagem
                              │ 3. responde 200 e processa em segundo plano
                              ▼
                       guardas: volume por número, tamanho da entrada, teto de gasto diário
                              │ aviso de que é uma IA (1ª mensagem e após 24 h)
                              │ pediu "HUMANO"? pausa o bot e avisa o responsável
                              ▼
                       agente (Claude Haiku, Messages API)
                              │ prompt = regras + kb/*.md (em cache) + histórico (SQLite)
                              │ ferramentas strict: consultar_horarios, agendar,
                              │   cancelar_agendamento, transferir_para_humano
                              ▼
                       resposta (uma mensagem) ──▶ Graph API ──▶ usuário
                              │
                              └─ registro: mensagens, ferramentas, tokens e custo (SQLite)
```

## Decisões de engenharia

- **Laço de ferramentas com limite.** O agente roda até o modelo encerrar o turno ou atingir `MAX_ITERACOES_FERRAMENTAS`. Recusas e estouro de `max_tokens` têm resposta de reserva. Veja `app/agente.py`.
- **Ferramentas em modo estrito.** Todas usam `strict: true` e `additionalProperties: false`, então o modelo não pode inventar campos. Veja `app/ferramentas.py`.
- **Cache de prompt.** Regras e base de conhecimento ficam num bloco estável com `cache_control`. O que muda a cada mensagem (data, hora, telefone) vai no fim da mensagem do usuário, para não invalidar o cache.
- **O modelo propõe, o código executa.** Agendamentos passam por uma interface `Agenda` com implementação em SQLite. O modelo nunca escreve no banco diretamente.
- **Guardas.** Teto de gasto diário, limite de mensagens por hora por número, truncamento da entrada, e máscara de CPF e de cartão (com dígito verificador) antes de gravar qualquer log. Veja `app/guardas.py`.
- **Humano no circuito.** A ferramenta `transferir_para_humano` e a palavra "HUMANO" pausam o bot. Um painel `/admin` permite assumir e devolver a conversa.
- **Custo por chamada.** Cada resposta grava tokens de entrada, de cache e de saída, com o custo estimado por modelo. Veja `app/custos.py`.
- **Provedor simulado.** `app/cliente_falso.py` imita a API, o que permite testar e rodar os evals sem rede e sem custo.

## Módulo de documentos

Além do atendimento, há um módulo que extrai dados de notas fiscais, recibos, boletos e extratos enviados por foto ou PDF, e preenche uma planilha para revisão humana.

```
arquivo ─▶ é XML de NF-e? ── sim ──▶ leitura determinística, sem LLM
                │ não
                ▼
        modelo menor + saída estruturada (JSON Schema), com confiança por campo
                │ data, CNPJ/CPF ou valor com baixa confiança?
                ▼ sim
        modelo maior, uma única vez
                ▼
        validação: CNPJ/CPF, data, valor, soma dos itens
                ▼
        planilha .xlsx: linhas duvidosas marcadas para revisão
```

Nada é lançado sem aprovação de uma pessoa. O código está em `app/documentos/`.

## Instalação

Requer Python 3.12 ou mais novo.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

No Linux ou macOS, use `.venv/bin/python` e `cp`.

## Testes e evals

Os comandos abaixo rodam sem rede e sem chave de API.

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m evals.rodar --offline
.venv\Scripts\python -m evals.rodar_documentos --offline
.venv\Scripts\python -m scripts.conversar --offline
```

- `pytest`: 74 testes, cobrindo agente, webhook, guardas, custos e documentos.
- `evals.rodar`: 25 casos de atendimento em `evals/casos.yaml`, incluindo tentativas de injeção de prompt, emergências e perguntas fora do escopo.
- `evals.rodar_documentos`: 12 casos de extração em `evals/casos_documentos.yaml`, incluindo arquivos ilegíveis e notas com soma divergente.
- `scripts.conversar`: conversa com o agente no terminal.

O modo `--offline` usa o cliente simulado: ele valida o pipeline (banco, ferramentas, transferência, relatório), não a qualidade do modelo. Sem `--offline` e com `ANTHROPIC_API_KEY` definida, os mesmos casos rodam na API real, e `--juiz` acrescenta uma avaliação por rubrica feita por um modelo.

## Rodar o servidor

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Para receber mensagens reais, preencha no `.env` as credenciais da WhatsApp Cloud API e a chave da Anthropic, exponha a porta por um túnel HTTPS e cadastre `https://SEU-ENDERECO/webhook` no app da Meta. O painel fica em `/admin`, protegido por `ADMIN_TOKEN`. Há um `Dockerfile` e um `railway.json` para hospedagem.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `app/webhook.py` | Verificação da Meta, assinatura, deduplicação e fila em segundo plano |
| `app/atendimento.py` | Regras de uma mensagem: guardas, aviso de IA, humano no circuito, envio |
| `app/agente.py` | Montagem do prompt com cache, chamada ao modelo e laço de ferramentas |
| `app/ferramentas.py` | Definições e execução das ferramentas |
| `app/guardas.py`, `app/custos.py` | Limites, máscara de dados pessoais e custo por token |
| `app/documentos/` | Extração, validação, planilha e pendências |
| `app/cliente_falso.py` | Provedor simulado para testes e evals |
| `prompts/system.md` | Regras fixas do atendente |
| `kb/` | Base de conhecimento de exemplo |
| `evals/` | Casos, executores e relatórios |
| `tests/` | Testes com pytest, sem rede |

## Limitações conhecidas

- A fila é em memória: se o servidor reiniciar durante o processamento, a mensagem em andamento se perde.
- SQLite e as travas por telefone ficam em um único processo, então não há escala horizontal.
- A integração com Google Calendar é só um esqueleto (`app/agenda_google.py`).
- A base de conhecimento vai inteira no prompt. Não há busca por embeddings.
- A máscara de dados cobre apenas CPF e cartão. Outros dados pessoais ditos na conversa ficam no banco até a retenção configurada.

## Licença

MIT. Veja [LICENSE](LICENSE).
