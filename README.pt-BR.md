# 💬 agente-whatsapp-ia

**Um atendente virtual para WhatsApp construído sobre a API da Anthropic, em Python e FastAPI.**

🌐 [English](README.md) · **Português**

Responde dúvidas a partir de uma base de conhecimento em Markdown, consulta e marca horários com ferramentas, e transfere a conversa para uma pessoa quando o assunto sai do escopo.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white) ![Claude API](https://img.shields.io/badge/Claude%20API-D97757?style=for-the-badge&logo=anthropic&logoColor=white) ![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)

---

## 📌 Sobre

O laço do agente é escrito à mão, sem framework de agentes, para deixar visível cada decisão de engenharia: cache de prompt, ferramentas em modo estrito, guardas de custo e de dados pessoais, e uma suíte de evals que roda sem rede.

> **Estado do projeto:** protótipo funcional. Os testes e os evals rodam em modo offline, com um cliente simulado, e validam o fluxo de ponta a ponta. Isso valida o pipeline, não a qualidade do modelo. Não há medição publicada com o modelo real, e o projeto não está em produção.

Todos os dados de exemplo (clínica, escritório de contabilidade, notas fiscais, telefones, CNPJs e CPFs) são fictícios.

A ideia central é uma separação de responsabilidades:

> 🧠 **O modelo interpreta a mensagem e propõe chamadas de ferramenta.**
> ⚙️ **O código Python valida e executa.**

O modelo nunca escreve no banco diretamente.

## 📑 Sumário

- [Tecnologias](#-tecnologias)
- [Funcionalidades](#-funcionalidades)
- [O processo](#-o-processo)
- [O que aprendi](#-o-que-aprendi)
- [Como pode melhorar](#-como-pode-melhorar)
- [Como rodar o projeto](#-como-rodar-o-projeto)
- [Licença](#-licença)

---

## 🛠 Tecnologias

| Área | Tecnologia |
| --- | --- |
| Linguagem | Python 3.12 ou mais novo (o CI roda em 3.12) |
| Web | FastAPI + Uvicorn |
| Modelo | Messages API da Anthropic pelo SDK oficial `anthropic`; modelo padrão `claude-haiku-5-5` (variável `MODELO`) |
| Mensagens | WhatsApp Cloud API (Graph API `v24.0`), chamada com `httpx` |
| Armazenamento | SQLite (`sqlite3` da biblioteca padrão) |
| Documentos | `openpyxl` (planilha), `validate-docbr` (CNPJ/CPF), `nfelib` (XML de NF-e) |
| Testes | pytest, mais dois executores de evals offline |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
| Arquivos de hospedagem | `Dockerfile`, `Procfile`, `railway.json` |

---

## 🚀 Funcionalidades

### 💬 Conversa

- Responde a partir da base de conhecimento em `kb/*.md`, que vai no prompt junto com as regras fixas de `prompts/system.md`.
- Guarda o histórico recente de cada conversa em SQLite (`HISTORICO_MAX_MENSAGENS`, `HISTORICO_HORAS`).
- Avisa o contato de que é uma IA na primeira mensagem e de novo após 24 horas (`HORAS_NOVA_CONVERSA`).
- Transcrição de áudio opcional, ativa só quando `TRANSCRICAO_URL` e `TRANSCRICAO_CHAVE` estão definidas.

### 🗓 Ferramentas de agenda

As quatro ferramentas usam `strict: true` e `additionalProperties: false`:

| Ferramenta | Finalidade |
| --- | --- |
| `consultar_horarios` | Listar horários livres numa data |
| `agendar` | Marcar um horário |
| `cancelar_agendamento` | Cancelar um agendamento |
| `transferir_para_humano` | Passar a conversa para a equipe |

Os agendamentos passam por uma interface `Agenda` com implementação em SQLite (`app/agenda_local.py`).

### 🙋 Humano no circuito

- A ferramenta `transferir_para_humano` e a palavra "HUMANO" pausam o bot e avisam o responsável (`NUMERO_RESPONSAVEL`).
- O painel `/admin`, protegido por `ADMIN_TOKEN`, permite a uma pessoa assumir a conversa, responder e devolvê-la.

### 🛡 Guardas

- Teto de gasto diário (`LIMITE_GASTO_DIARIO_USD`).
- Limite de mensagens por número por hora (`LIMITE_MSGS_POR_HORA`).
- Truncamento da entrada (`MAX_CARACTERES_ENTRADA`).
- CPF e número de cartão (o cartão conferido pelo dígito de Luhn) são mascarados antes de qualquer gravação em log ou no banco. Veja `app/guardas.py`.

### 💰 Custo por chamada

Cada resposta grava tokens de entrada, de cache e de saída, com o custo estimado por modelo. Veja `app/custos.py`.

### 📄 Módulo de documentos

Opcional e desligado por padrão (`MODO_DOCUMENTOS`). Extrai dados de notas fiscais, recibos, boletos e extratos enviados por foto ou PDF, e preenche uma planilha para revisão humana. Nada é lançado sem aprovação de uma pessoa. O código está em `app/documentos/`.

### 🧪 Provedor simulado

`app/cliente_falso.py` imita a API, o que permite rodar os testes e os evals sem rede e sem custo.

---

## 🔄 O processo

### 1. Da mensagem à resposta

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

### 2. Laço de ferramentas com limite

O agente roda até o modelo encerrar o turno ou atingir `MAX_ITERACOES_FERRAMENTAS`. Recusas, corte por `max_tokens` e o estouro do limite de iterações têm, cada um, uma resposta de reserva, para o contato nunca ficar sem resposta. Veja `app/agente.py`.

### 3. Cache de prompt

As regras e a base de conhecimento ficam num bloco estável com `cache_control`. O que muda a cada mensagem (data, hora, telefone) vai no fim da mensagem do usuário, para não invalidar o cache. Os arquivos da base são lidos em ordem alfabética e a lista de ferramentas tem ordem fixa pelo mesmo motivo.

### 4. Documentos

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

### 5. Estrutura do projeto

| Caminho | Conteúdo |
| --- | --- |
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

---

## 📚 O que aprendi

### O cache de prompt depende de estabilidade byte a byte

Qualquer byte diferente no bloco em cache o invalida. Por isso levei os dados de cada mensagem (data, hora, telefone) para o fim da mensagem do usuário e mantive a base de conhecimento e a lista de ferramentas em ordem fixa.

### Esquemas de ferramenta em modo estrito

Com `strict: true` e `additionalProperties: false` o modelo não consegue inventar campos, então o código que executa a ferramenta recebe o formato que espera.

### O modelo propõe, o código executa

Colocar os agendamentos atrás de uma interface `Agenda` mantém o modelo longe do banco e me deixa trocar a implementação sem mexer no agente.

### Mascarar dados pessoais antes de gravar

Mascaro CPF e número de cartão antes de qualquer gravação, e confiro o cartão pelo dígito de Luhn para não mascarar números longos comuns. Também aprendi o limite dessa abordagem: ela cobre só esses dois tipos de dado.

### Um provedor simulado para os testes

Imitar a API me permitiu testar o pipeline inteiro (banco, ferramentas, transferência, relatório) sem rede e sem custo. Também deixou claro o que esse tipo de teste não mostra: ele não diz nada sobre a qualidade das respostas do modelo real.

### Roteamento por custo no módulo de documentos

O XML de NF-e é lido de forma determinística, sem modelo. Para o resto, um modelo menor responde primeiro e um maior é chamado uma única vez, só quando um campo-chave volta com baixa confiança.

### Um laço de ferramentas precisa de limite e de reserva

Recusas, corte por `max_tokens` e o limite de iterações precisam, cada um, de uma resposta explícita e, quando o agente falha, de uma transferência para uma pessoa.

---

## 🔮 Como pode melhorar

| Melhoria | Descrição |
| --- | --- |
| **Medição com o modelo real** | Os relatórios publicados vêm do modo offline. Rodar os mesmos casos na API real, com o juiz por rubrica (`--juiz`), e publicar o resultado ainda está por fazer. |
| **Fila persistente** | A fila é em memória: se o servidor reiniciar durante o processamento, a mensagem em andamento se perde. |
| **Escala horizontal** | SQLite e as travas por telefone ficam em um único processo, então não há escala horizontal. |
| **Google Calendar** | A integração com Google Calendar é só um esqueleto (`app/agenda_google.py`). |
| **Busca na base de conhecimento** | A base de conhecimento vai inteira no prompt. Não há busca por embeddings. |
| **Máscara de dados mais ampla** | A máscara cobre apenas CPF e cartão. Outros dados pessoais ditos na conversa ficam no banco até a retenção configurada (`RETENCAO_DIAS`). |

---

## ▶ Como rodar o projeto

### Requisitos

- Python 3.12 ou mais novo
- Git
- Só para receber mensagens reais: uma chave da API da Anthropic e credenciais da WhatsApp Cloud API

### 1. Clonar o repositório

```bash
git clone <repository-url>
cd agente-whatsapp-ia
```

### 2. Criar o ambiente e instalar as dependências

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

No Linux ou macOS, use `.venv/bin/python` e `cp`.

### 3. Conversar com o agente no terminal

```powershell
.venv\Scripts\python -m scripts.conversar --offline
```

### 4. Rodar o servidor

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

A verificação de saúde fica em `http://localhost:8000/saude` e o painel em `/admin`, protegido por `ADMIN_TOKEN`.

### 5. Receber mensagens reais (opcional)

Preencha no `.env` as variáveis `ANTHROPIC_API_KEY`, `META_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET` e `META_VERIFY_TOKEN`, exponha a porta por um túnel HTTPS e cadastre `https://SEU-ENDERECO/webhook` no app da Meta. Nunca faça commit do arquivo `.env`.

### Rodando os testes

Os comandos abaixo rodam sem rede e sem chave de API.

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m evals.rodar --offline
.venv\Scripts\python -m evals.rodar_documentos --offline
```

- `pytest`: 74 testes, cobrindo agente, webhook, guardas, custos e documentos.
- `evals.rodar`: 25 casos de atendimento em `evals/casos.yaml`, incluindo tentativas de injeção de prompt, emergências e perguntas fora do escopo.
- `evals.rodar_documentos`: 12 casos de extração em `evals/casos_documentos.yaml`, incluindo arquivos ilegíveis e notas com soma divergente.

O modo `--offline` usa o cliente simulado: ele valida o pipeline (banco, ferramentas, transferência, relatório), não a qualidade do modelo. Sem `--offline` e com `ANTHROPIC_API_KEY` definida, os mesmos casos rodam na API real, e `--juiz` acrescenta uma avaliação por rubrica feita por um modelo.

---

## 📄 Licença

MIT. Veja [LICENSE](LICENSE).
