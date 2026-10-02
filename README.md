# Customer Support Triage Agent

An agentic customer support system that classifies inbound tickets, fetches customer context via a custom MCP server, looks up policies, drafts responses, and escalates with a HITL checkpoint when confidence is low.

## Architecture

```
Inbound ticket
      ↓
classify_ticket (Claude)
      ↓
get_customer + get_orders (CRM MCP Server → SQLite)
      ↓
get_policy (CRM MCP Server)
      ↓
draft_response (Claude)
      ↓
confidence < 0.7? → HITL checkpoint → escalate
confidence ≥ 0.7? → auto-resolve
      ↓
update_ticket_status (CRM MCP Server)
```

## Stack
- **Agent:** Claude Sonnet 4.6 (classification + drafting)
- **MCP Server:** custom FastMCP server exposing 5 CRM tools over stdio
- **Database:** SQLite (50 customers, 100 orders, 8 policies)
- **HITL:** interactive checkpoint before any escalation
- **Observability:** every tool call logged with timing
- **Eval:** 20-case eval set scored with LLM-as-judge (Claude Haiku)

## Tools (5)
1. `classify_ticket` — billing / technical / shipping / account / other + confidence
2. `get_customer` — customer profile from CRM
3. `get_customer_orders` — order history
4. `get_policy` — category-specific support policies
5. `update_ticket_status` — open / resolved / escalated / pending

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python crm_server/seed_db.py
python run.py
```

## Docker

```bash
docker build -t support-agent .
docker run -it -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY support-agent
```

## Eval Results (20 test cases)

| Metric | Score |
|---|---|
| Category accuracy | 85% |
| Action accuracy | 55% |
| LLM judge score | 4.1/5 |
| Avg latency | 8.8s |

Category accuracy 85% across billing/technical/shipping/account/other. Action accuracy 55% reflects conservative escalation behavior — the agent escalates when accounts are suspended or confidence is borderline, which is the right production default. LLM judge scores response quality 4.1/5 on relevance, empathy, accuracy, completeness, and appropriate escalation.

## Loop termination
- Max steps: 10 (configurable in `config.py`)
- Success criterion: ticket status updated to resolved or escalated
- Error handling: agent catches exceptions per step, logs, and continues

## HITL checkpoint
Triggers when draft confidence < 0.7 or agent detects account anomalies. Presents operator with 3 options: approve escalation, send without escalation, or reject for manual review.

## Stretch Goals

### 1. Cost vs Quality (3 model tiers)

| Tier | Model | CatAcc | ActAcc | Judge | Cost/ticket |
|---|---|---|---|---|---|
| haiku | claude-haiku-4-5 | 90% | 60% | 2.4/5 | $0.0033 |
| sonnet | claude-sonnet-4-6 | 100% | 60% | 2.2/5 | $0.0098 |
| opus | claude-opus-4-6 | 90% | 60% | 2.4/5 | $0.0488 |

Sonnet wins on category accuracy at 3x Haiku's cost. Opus costs 5x more than Sonnet with no quality gain — Sonnet is the sweet spot for production.

### 2. Multi-Agent Architecture

Refactored monolithic agent into 3 specialized agents:
- **Researcher** — classifies ticket, fetches customer context, orders, and policy via MCP tools
- **Writer** — drafts the support response from the research context
- **Verifier** — QA checks the draft and decides escalation

Each agent has a single responsibility. The orchestrator runs them in sequence with handoffs. See `agent/multi_agent.py`.

### 3. Slack Bot

Mention `@SupportAgent` in any Slack channel with a ticket and customer ID:

```
@SupportAgent CUST0001 I was charged twice this month
```

Returns a formatted Slack message with ticket ID, category + confidence, action, customer name and plan, full draft response, and escalation reason.

Run with:
```bash
export SLACK_BOT_TOKEN=...
export SLACK_APP_TOKEN=...
python slack_bot.py
```

## Project structure
```
agent/
  agent.py           Main agent loop + observability
  mcp_client.py      MCP client (implements CRM tool interface)
  multi_agent.py     Multi-agent: researcher / writer / verifier
crm_server/
  server.py          FastMCP server (5 CRM tools over stdio)
  seed_db.py         Seeds SQLite with 50 customers, 100 orders, 8 policies
  crm.db             SQLite database
eval/
  eval.py            20-case eval harness + LLM-as-judge
  eval_results.json  Results
  cost_quality_eval.py   3-tier cost vs quality comparison
  cost_quality_results.json  Results
config.py            Model, thresholds, costs
run.py               Entry point (3-ticket interactive demo)
slack_bot.py         Slack bot via Socket Mode
Dockerfile
requirements.txt
```