# Multi-Agent Customer Support System with MCP and A2A

**Multi-Agent Customer Support System with MCP and A2A** — a Python reference app where a **RouterAgent** classifies customer messages and delegates to specialists: **BillingAgent** and **SupportAgent** (data via Supabase, exposed through MCP-style tools), and **ReturnsRemoteAgent** (remote **Agent-to-Agent** protocol to a dedicated returns FastAPI service).

## Architecture

```text
                         +------------------+
                         |   RouterAgent    |
                         |  (intent route)  |
                         +--------+---------+
                                  |
          +-----------------------+----------------------+
          |                       |                      |
          v                       v                      v
+----------------+    +-------------------+    +----------------------+
|  BillingAgent  |    |   SupportAgent    |    | ReturnsRemoteAgent   |
|  ADK + tools   |    |  ADK + tickets    |    |  ADK RemoteA2aAgent  |
+-------+--------+    +---------+---------+    +----------+-----------+
        |                       |                         |
        |  MCP tool parity      |  MCP tool parity        |  A2A JSON-RPC
        |  (FunctionTool /      |  (get_support_tickets)  |  + agent card
        |   stdio MCP server)   |                         |
        v                       v                         v
+----------------+    +-------------------+    +----------------------+
|    Supabase    |    |     Supabase      |    |  Returns Service     |
|  customers,    |    |  support_tickets  |    |  (FastAPI, port 8081)  |
|  orders, ...   |    |                   |    |  eligibility + return  |
+----------------+    +-------------------+    +----------------------+
```

- **MCP → Supabase**: `src/mcp/supabase_mcp_server.py` exposes `get_billing_info` / `get_support_tickets` over stdio MCP; the same logic is called in-process from agents via `FunctionTool`.
- **A2A → Returns Service**: `servers/returns_service/main.py` serves an ADK agent over A2A; `ReturnsRemoteAgent` connects using the Agent Card URL.

## Tech Stack

- Google ADK (`google-adk`), A2A SDK (`a2a-sdk`), MCP (`mcp`), FastMCP, FastAPI, Uvicorn, Supabase (`supabase`), `httpx`, `python-dotenv`

## Project Structure

```text
multi_agent_customer_support/
  sql/
    schema_and_seed.sql    # DDL + seed data
    fix_rls_and_verify.sql # RLS policies + checks (run after schema if needed)
  src/
    main.py                 # FastAPI + CLI entry (`python -m src.main`)
    agents/
      router_agent.py
      billing_agent.py
      support_agent.py
      returns_remote_agent.py
    mcp/
      supabase_mcp_server.py
      supabase_mcp_connection.py
  servers/returns_service/main.py  # Returns A2A microservice
  tests/
  .env.example
  README.md
```

## Setup

### 1. Supabase: project, schema, and seed

1. Create a project in [Supabase](https://supabase.com).
2. In the SQL editor (or `psql`), run:
   - `sql/schema_and_seed.sql` — tables, seed rows, and dev-oriented RLS as provided.
   - If you hit RLS / permission issues with the anon key, run `sql/fix_rls_and_verify.sql` and re-check policies.

### 2. Environment variables

Copy and edit:

```bash
cp .env.example .env
```

Typical variables:

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_ANON_KEY` | Anon key (or `SUPABASE_KEY` legacy) |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | ADK / Gemini for router and agents |
| `RETURNS_SERVICE_URL` | Returns service base URL (default `http://127.0.0.1:8081`) |
| `RETURNS_A2A_AGENT_CARD_URL` | Optional full Agent Card URL override |

### 3. Install dependencies

Python **3.12** recommended.

```powershell
cd multi_agent_customer_support
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
pip install -e ".[dev]"   # optional: pytest + pytest-asyncio
```

### 4. Run the Supabase MCP server (separate process)

From `multi_agent_customer_support/`:

```powershell
python -m src.mcp.supabase_mcp_server
```

Uses stdio MCP; configure Cursor or other MCP hosts to launch this command with the same working directory and `.env` loaded.

### 5. Run the Returns FastAPI (A2A) service

```powershell
uvicorn servers.returns_service.main:app --host 127.0.0.1 --port 8081
```

Or: `python -m servers.returns_service.main`  
Agent card: `GET http://127.0.0.1:8081/.well-known/agent-card.json`

### 6. Run the main CLI

```powershell
python -m src.main
```

Optional: `CLI_CUSTOMER_ID` in `.env` to skip the customer-id prompt.  
Type `quit` or `exit` to stop.

### Run the HTTP API (optional)

```powershell
uvicorn src.main:app --reload --port 8000
```

Example:

```bash
curl -X POST http://127.0.0.1:8000/support/query \
  -H "Content-Type: application/json" \
  -d "{\"customer_id\":\"you@example.com\",\"message\":\"I was charged twice\"}"
```

Response includes `result`, `routed_to`, `escalated`, and `rationale`.

## Example conversations (CLI)

Use a **real seeded customer email** from Supabase when testing billing/support data.

### Billing

```text
> I was charged twice for my last order. Can you check my billing?
```

Expect routing to **billing** and a summary grounded in `get_billing_info` / orders.

### Returns

```text
> I want to return order ORD-123. Am I eligible for a refund?
```

Expect routing to **returns** and an answer from the remote **Returns** A2A agent (returns service must be running with `GEMINI_API_KEY`).

### Escalation

```text
> My account was hacked, all my orders are gone, and nobody is helping me.
```

For high-severity or ambiguous cases the router may return an **escalation** response (`[ESCALATE]`, `ESCALATE_FLAG`) so a human can take over; exact behavior may use the LLM router when API keys are set, or heuristics when not.

## Tests

```powershell
pytest tests/ -q
```

Scenario tests live in `tests/test_scenarios.py`.
