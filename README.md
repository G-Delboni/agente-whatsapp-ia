# 💬 agente-whatsapp-ia

**A WhatsApp virtual assistant built on the Anthropic API, in Python and FastAPI.**

🌐 **English** · [Português](README.pt-BR.md)

It answers questions from a Markdown knowledge base, checks and books appointments through tools, and hands the conversation to a person when the subject is out of scope.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white) ![Claude API](https://img.shields.io/badge/Claude%20API-D97757?style=for-the-badge&logo=anthropic&logoColor=white) ![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)

---

## 📌 About

The agent loop is written by hand, without an agent framework, so that each engineering decision stays visible: prompt caching, strict tools, guards for cost and personal data, and an eval suite that runs without network access.

> **Project status:** working prototype. The tests and the evals run offline, against a simulated client, and validate the flow end to end. This validates the pipeline, not the quality of the model. There is no published measurement with the real model, and the project is not in production.

All sample data (clinic, accounting office, invoices, phone numbers, CNPJ and CPF numbers) is fictitious.

The core idea is a separation of responsibilities:

> 🧠 **The model interprets the message and proposes tool calls.**
> ⚙️ **The Python code validates and executes them.**

The model never writes to the database directly.

## 📑 Table of Contents

- [Technologies](#-technologies)
- [Features](#-features)
- [The process](#-the-process)
- [What I learned](#-what-i-learned)
- [How can it be improved](#-how-can-it-be-improved)
- [Running the project](#-running-the-project)
- [License](#-license)

---

## 🛠 Technologies

| Area | Technology |
| --- | --- |
| Language | Python 3.12 or newer (CI runs on 3.12) |
| Web | FastAPI + Uvicorn |
| Model | Anthropic Messages API through the official `anthropic` SDK; default model `claude-haiku-5-5` (variable `MODELO`) |
| Messaging | WhatsApp Cloud API (Graph API `v24.0`), called with `httpx` |
| Storage | SQLite (`sqlite3` from the standard library) |
| Documents | `openpyxl` (spreadsheet), `validate-docbr` (CNPJ/CPF), `nfelib` (NF-e XML) |
| Tests | pytest, plus two offline eval runners |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
| Hosting files | `Dockerfile`, `Procfile`, `railway.json` |

---

## 🚀 Features

### 💬 Conversation

- Answers from the knowledge base in `kb/*.md`, which goes into the prompt together with the fixed rules in `prompts/system.md`.
- Keeps the recent history of each conversation in SQLite (`HISTORICO_MAX_MENSAGENS`, `HISTORICO_HORAS`).
- Tells the contact it is an AI on the first message and again after 24 hours (`HORAS_NOVA_CONVERSA`).
- Optional audio transcription, enabled only when `TRANSCRICAO_URL` and `TRANSCRICAO_CHAVE` are set.

### 🗓 Scheduling tools

All four tools use `strict: true` and `additionalProperties: false`:

| Tool | Purpose |
| --- | --- |
| `consultar_horarios` | List free slots on a date |
| `agendar` | Book a slot |
| `cancelar_agendamento` | Cancel a booking |
| `transferir_para_humano` | Hand the conversation to the team |

Bookings go through an `Agenda` interface with a SQLite implementation (`app/agenda_local.py`).

### 🙋 Human in the loop

- The `transferir_para_humano` tool and the word "HUMANO" pause the bot and notify the person in charge (`NUMERO_RESPONSAVEL`).
- The `/admin` panel, protected by `ADMIN_TOKEN`, lets a person take over a conversation, reply, and give it back.

### 🛡 Guards

- Daily spending cap (`LIMITE_GASTO_DIARIO_USD`).
- Message limit per phone number per hour (`LIMITE_MSGS_POR_HORA`).
- Input truncation (`MAX_CARACTERES_ENTRADA`).
- CPF and card numbers (cards checked with the Luhn digit) are masked before anything is written to the log or the database. See `app/guardas.py`.

### 💰 Cost per call

Each response records input, cache and output tokens, with the estimated cost per model. See `app/custos.py`.

### 📄 Documents module

Optional and off by default (`MODO_DOCUMENTOS`). It extracts data from invoices, receipts, payment slips and bank statements sent as a photo or PDF, and fills a spreadsheet for human review. Nothing is posted without a person's approval. The code is in `app/documentos/`.

### 🧪 Simulated provider

`app/cliente_falso.py` imitates the API, which makes it possible to run the tests and the evals without network access and at no cost.

---

## 🔄 The process

### 1. From message to reply

```
User (WhatsApp)
        │ message
        ▼
WhatsApp Cloud API ──POST──▶ /webhook (FastAPI)
                              │ 1. checks the HMAC signature (X-Hub-Signature-256)
                              │ 2. drops repeated events by message id
                              │ 3. answers 200 and processes in the background
                              ▼
                       guards: volume per number, input size, daily spending cap
                              │ notice that it is an AI (1st message and after 24 h)
                              │ asked for "HUMANO"? pauses the bot and notifies the person in charge
                              ▼
                       agent (Claude Haiku, Messages API)
                              │ prompt = rules + kb/*.md (cached) + history (SQLite)
                              │ strict tools: consultar_horarios, agendar,
                              │   cancelar_agendamento, transferir_para_humano
                              ▼
                       reply (one message) ──▶ Graph API ──▶ user
                              │
                              └─ record: messages, tools, tokens and cost (SQLite)
```

### 2. Bounded tool loop

The agent runs until the model ends the turn or reaches `MAX_ITERACOES_FERRAMENTAS`. Refusals, a `max_tokens` cut-off and hitting the iteration limit each have a fallback reply, so the contact is never left without an answer. See `app/agente.py`.

### 3. Prompt caching

The rules and the knowledge base sit in one stable block with `cache_control`. What changes on every message (date, time, phone number) goes at the end of the user message, so the cache is not invalidated. The knowledge base files are read in alphabetical order and the tool list has a fixed order for the same reason.

### 4. Documents

```
file ─▶ is it an NF-e XML? ── yes ──▶ deterministic reading, no LLM
                │ no
                ▼
        smaller model + structured output (JSON Schema), with confidence per field
                │ date, CNPJ/CPF or amount with low confidence?
                ▼ yes
        larger model, a single time
                ▼
        validation: CNPJ/CPF, date, amount, sum of the items
                ▼
        .xlsx spreadsheet: doubtful rows marked for review
```

### 5. Project layout

| Path | Contents |
| --- | --- |
| `app/webhook.py` | Meta verification, signature, deduplication and background queue |
| `app/atendimento.py` | Rules for one message: guards, AI notice, human in the loop, sending |
| `app/agente.py` | Prompt assembly with cache, model call and tool loop |
| `app/ferramentas.py` | Tool definitions and execution |
| `app/guardas.py`, `app/custos.py` | Limits, personal data masking and cost per token |
| `app/documentos/` | Extraction, validation, spreadsheet and pending items |
| `app/cliente_falso.py` | Simulated provider for tests and evals |
| `prompts/system.md` | Fixed rules of the assistant |
| `kb/` | Sample knowledge base |
| `evals/` | Cases, runners and reports |
| `tests/` | pytest tests, no network |

---

## 📚 What I learned

### Prompt caching depends on byte stability

Any byte that differs in the cached block invalidates it. That is why I moved the per-message data (date, time, phone number) to the end of the user message and kept the knowledge base and the tool list in a fixed order.

### Strict tool schemas

With `strict: true` and `additionalProperties: false` the model cannot invent fields, so the code that executes a tool receives the shape it expects.

### The model proposes, the code executes

Putting bookings behind an `Agenda` interface keeps the model away from the database and lets me swap the implementation without touching the agent.

### Masking personal data before logging

I mask CPF and card numbers before anything is written, and I check the card with the Luhn digit to avoid masking ordinary long numbers. I also learned the limit of this approach: it covers only these two kinds of data.

### A simulated provider for tests

Imitating the API let me test the whole pipeline (database, tools, hand-off, report) without network access or cost. It also made clear what this kind of test does not show: it says nothing about the quality of the real model's answers.

### Routing by cost in the documents module

NF-e XML is read deterministically, without a model. For the rest, a smaller model answers first and a larger one is called a single time, only when a key field comes back with low confidence.

### A tool loop needs a limit and a fallback

Refusals, a `max_tokens` cut-off and the iteration limit each need an explicit reply and, when the agent fails, a hand-off to a person.

---

## 🔮 How can it be improved

| Improvement | Description |
| --- | --- |
| **Measurement with the real model** | The published reports come from the offline mode. Running the same cases against the real API, with the rubric judge (`--juiz`), and publishing the result is still to be done. |
| **Persistent queue** | The queue is in memory: if the server restarts during processing, the message in progress is lost. |
| **Horizontal scaling** | SQLite and the per-phone locks live in a single process, so there is no horizontal scaling. |
| **Google Calendar** | The Google Calendar integration is only a skeleton (`app/agenda_google.py`). |
| **Knowledge base retrieval** | The whole knowledge base goes into the prompt. There is no embedding search. |
| **Broader data masking** | The mask covers only CPF and card numbers. Other personal data said in the conversation stays in the database until the configured retention (`RETENCAO_DIAS`). |

---

## ▶ Running the project

### Requirements

- Python 3.12 or newer
- Git
- Only to receive real messages: an Anthropic API key and WhatsApp Cloud API credentials

### 1. Clone the repository

```bash
git clone <repository-url>
cd agente-whatsapp-ia
```

### 2. Create the environment and install the dependencies

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

On Linux or macOS, use `.venv/bin/python` and `cp`.

### 3. Talk to the agent in the terminal

```powershell
.venv\Scripts\python -m scripts.conversar --offline
```

### 4. Run the server

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

The health check is at `http://localhost:8000/saude` and the panel at `/admin`, protected by `ADMIN_TOKEN`.

### 5. Receive real messages (optional)

Fill in `.env` with `ANTHROPIC_API_KEY`, `META_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET` and `META_VERIFY_TOKEN`, expose the port through an HTTPS tunnel and register `https://YOUR-ADDRESS/webhook` in the Meta app. Never commit the `.env` file.

### Running the tests

The commands below run without network access and without an API key.

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m evals.rodar --offline
.venv\Scripts\python -m evals.rodar_documentos --offline
```

- `pytest`: 74 tests, covering agent, webhook, guards, costs and documents.
- `evals.rodar`: 25 conversation cases in `evals/casos.yaml`, including prompt injection attempts, emergencies and out-of-scope questions.
- `evals.rodar_documentos`: 12 extraction cases in `evals/casos_documentos.yaml`, including unreadable files and invoices whose items do not add up.

The `--offline` mode uses the simulated client: it validates the pipeline (database, tools, hand-off, report), not the quality of the model. Without `--offline` and with `ANTHROPIC_API_KEY` set, the same cases run against the real API, and `--juiz` adds a rubric evaluation made by a model.

---

## 📄 License

MIT. See [LICENSE](LICENSE).
