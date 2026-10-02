import json
import time
import uuid
from datetime import datetime
from anthropic import Anthropic
from config import AGENT_MODEL, CONFIDENCE_THRESHOLD

client = Anthropic()


def log(agent: str, action: str, duration_ms: float):
    print(f"  [{agent}] {action} ({duration_ms:.0f}ms)")
    return {"timestamp": datetime.now().isoformat(),
            "agent": agent, "action": action, "duration_ms": round(duration_ms, 2)}


# ── Agent 1: Researcher ───────────────────────────────────────────────────────

def researcher_agent(ticket: str, customer_id: str, mcp_tools: dict) -> dict:
    """Fetches all context needed to resolve the ticket."""
    logs = []
    context = {}

    # classify
    t0 = time.perf_counter()
    r = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=100,
        system='Classify this support ticket. Reply with JSON only: {"category": "billing|technical|shipping|account|other", "confidence": 0.0-1.0}',
        messages=[{"role": "user", "content": ticket}]
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    classification = json.loads(raw.strip())
    logs.append(log("researcher", f"classify → {classification['category']}", (time.perf_counter()-t0)*1000))
    context["classification"] = classification

    # fetch customer
    t0 = time.perf_counter()
    customer = json.loads(mcp_tools["get_customer"](customer_id))
    logs.append(log("researcher", f"get_customer → {customer.get('name', 'unknown')}", (time.perf_counter()-t0)*1000))
    context["customer"] = customer

    # fetch orders
    t0 = time.perf_counter()
    orders = json.loads(mcp_tools["get_customer_orders"](customer_id))
    logs.append(log("researcher", f"get_orders → {len(orders.get('orders',[]))} orders", (time.perf_counter()-t0)*1000))
    context["orders"] = orders.get("orders", [])

    # fetch policy
    t0 = time.perf_counter()
    policy = json.loads(mcp_tools["get_policy"](classification["category"]))
    logs.append(log("researcher", f"get_policy → {len(policy.get('policies',[]))} policies", (time.perf_counter()-t0)*1000))
    context["policy"] = policy

    return {"context": context, "logs": logs}


# ── Agent 2: Writer ───────────────────────────────────────────────────────────

def writer_agent(ticket: str, context: dict) -> dict:
    """Drafts a support response from the context."""
    logs = []

    prompt = f"""Write a support response for this ticket.

Ticket: {ticket}
Customer: {json.dumps(context.get('customer', {}), indent=2)}
Orders: {json.dumps(context.get('orders', [])[:3], indent=2)}
Policy: {json.dumps(context.get('policy', {}), indent=2)}
Category: {context.get('classification', {}).get('category', 'unknown')}

Reply with JSON only, body under 150 words:
{{"subject": "...", "body": "...", "key_points": ["point1", "point2"]}}"""

    t0 = time.perf_counter()
    r = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        draft = json.loads(raw.strip())
    except Exception:
        draft = {"subject": "Support Request", "body": raw[:500], "key_points": []}
    logs.append(log("writer", f"draft → {len(draft.get('body',''))} chars", (time.perf_counter()-t0)*1000))

    return {"draft": draft, "logs": logs}


# ── Agent 3: Verifier ─────────────────────────────────────────────────────────

def verifier_agent(ticket: str, draft: dict, context: dict) -> dict:
    """Verifies draft quality and decides escalation."""
    logs = []

    prompt = f"""You are a QA verifier for customer support responses.

Original ticket: {ticket}
Customer plan: {context.get('customer', {}).get('plan', 'unknown')}
Category: {context.get('classification', {}).get('category', 'unknown')}

Draft response:
Subject: {draft.get('subject', '')}
Body: {draft.get('body', '')}

Evaluate and reply with JSON only:
{{
  "quality_score": 0.0-1.0,
  "issues": ["issue1"] or [],
  "escalate": true/false,
  "escalation_reason": "reason" or null,
  "approved": true/false
}}

Escalate if: quality < 0.6, account is suspended, or issue requires billing/engineering team."""

    t0 = time.perf_counter()
    r = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        verdict = json.loads(raw.strip())
    except Exception:
        verdict = {"quality_score": 0.5, "issues": [], "escalate": True,
                   "escalation_reason": "Verification failed", "approved": False}
    logs.append(log("verifier", f"verdict → quality={verdict.get('quality_score', 0):.2f} escalate={verdict.get('escalate')}", (time.perf_counter()-t0)*1000))

    return {"verdict": verdict, "logs": logs}


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_multi_agent(ticket: str, customer_id: str, mcp_tools: dict,
                    interactive: bool = True) -> dict:
    ticket_id = f"MA{uuid.uuid4().hex[:8].upper()}"
    start_time = time.time()
    all_logs = []

    print(f"\n{'='*60}")
    print(f"[MULTI-AGENT] Ticket {ticket_id}")
    print(f"Customer: {customer_id} | {ticket[:60]}...")
    print("="*60)

    # Agent 1: Research
    print("\n🔍 Researcher Agent")
    research = researcher_agent(ticket, customer_id, mcp_tools)
    all_logs.extend(research["logs"])
    context = research["context"]

    # Agent 2: Write
    print("\n✍️  Writer Agent")
    writing = writer_agent(ticket, context)
    all_logs.extend(writing["logs"])
    draft = writing["draft"]

    # Agent 3: Verify
    print("\n✅ Verifier Agent")
    verification = verifier_agent(ticket, draft, context)
    all_logs.extend(verification["logs"])
    verdict = verification["verdict"]

    # HITL if escalation needed
    final_action = "resolve"
    if verdict.get("escalate") and interactive:
        print(f"\n🔴 HITL CHECKPOINT")
        print(f"Reason: {verdict.get('escalation_reason')}")
        print(f"Quality score: {verdict.get('quality_score'):.2f}")
        choice = input("Escalate? (y/n): ").strip().lower()
        final_action = "escalate" if choice == "y" else "resolve"
    elif verdict.get("escalate"):
        final_action = "escalate"

    # update ticket
    t0 = time.perf_counter()
    status = "escalated" if final_action == "escalate" else "resolved"
    mcp_tools["update_ticket_status"](ticket_id, status, customer_id)
    all_logs.append(log("orchestrator", f"update_status → {status}", (time.perf_counter()-t0)*1000))

    total_ms = (time.time() - start_time) * 1000
    print(f"\n{'='*60}")
    print(f"✅ Done | Action: {final_action} | {total_ms:.0f}ms | {len(all_logs)} tool calls")
    print("="*60)

    return {
        "ticket_id": ticket_id,
        "ticket": ticket,
        "customer_id": customer_id,
        "context": context,
        "draft": draft,
        "verdict": verdict,
        "final_action": final_action,
        "logs": all_logs,
        "total_ms": round(total_ms, 2),
        "success": True,
    }