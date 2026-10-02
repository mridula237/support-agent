import json
import time
import uuid
from datetime import datetime
from anthropic import Anthropic
from config import AGENT_MODEL, MAX_STEPS, CONFIDENCE_THRESHOLD, COSTS

client = Anthropic()


# ── Observability ─────────────────────────────────────────────────────────────

def log_tool_call(tool_name: str, input_data: dict, output: str, duration_ms: float):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "input": input_data,
        "output_preview": output[:200],
        "duration_ms": round(duration_ms, 2),
    }
    print(f"  [TOOL] {tool_name} ({duration_ms:.0f}ms)")
    return entry


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = COSTS.get(model, (0, 0))
    return input_tokens / 1e6 * p_in + output_tokens / 1e6 * p_out


# ── Tools (non-MCP) ───────────────────────────────────────────────────────────

def classify_ticket(text: str) -> dict:
    """Classify ticket into category + confidence."""
    r = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=100,
        system="Classify this support ticket. Reply with JSON only: {\"category\": \"billing|technical|shipping|account|other\", \"confidence\": 0.0-1.0, \"reason\": \"one sentence\"}",
        messages=[{"role": "user", "content": text}]
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def draft_response(ticket: str, customer_info: dict, policy: dict, category: str) -> dict:
    """Draft a support response."""
    context = f"""
Ticket: {ticket}
Customer: {json.dumps(customer_info, indent=2)}
Relevant Policy: {json.dumps(policy, indent=2)}
Category: {category}
"""
    r = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=800,
        system="""Draft a professional, empathetic support response.
Reply with JSON only, no markdown. Keep the body under 200 words.
Format: {"subject": "...", "body": "...", "confidence": 0.0-1.0, "escalate": true/false, "escalation_reason": "..." or null}""",
        messages=[{"role": "user", "content": context}]
    )
    raw = r.content[0].text.strip()
    # strip markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    # try to fix truncated JSON
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # truncation fix: find last complete field
        try:
            # try to close the JSON object
            raw = raw.rstrip().rstrip(",")
            if not raw.endswith("}"):
                raw = raw + '"}'  # close last string + object
            result = json.loads(raw)
        except Exception:
            # fallback: return safe default
            result = {
                "subject": "Support Request Received",
                "body": "Thank you for contacting us. We have received your request and will respond shortly.",
                "confidence": 0.3,
                "escalate": True,
                "escalation_reason": "Response generation failed — manual review required"
            }

    # force escalation if confidence below threshold
    if result.get("confidence", 1.0) < CONFIDENCE_THRESHOLD:
        result["escalate"] = True
        if not result.get("escalation_reason"):
            result["escalation_reason"] = f"Low confidence: {result['confidence']:.2f}"
    return result


# ── HITL checkpoint ───────────────────────────────────────────────────────────

def hitl_escalation_check(ticket: str, draft: dict, customer_id: str) -> dict:
    """Human-in-the-loop: pause and ask for human approval before escalating."""
    print("\n" + "="*60)
    print("HITL CHECKPOINT — ESCALATION REQUIRED")
    print("="*60)
    print(f"Customer: {customer_id}")
    print(f"Reason: {draft.get('escalation_reason', 'Low confidence')}")
    print(f"\nDraft response:\n{draft.get('body', '')[:300]}")
    print("\nOptions:")
    print("  [1] Approve draft and escalate to human agent")
    print("  [2] Send draft without escalation")
    print("  [3] Reject and mark for manual review")

    choice = input("\nYour choice (1/2/3): ").strip()

    if choice == "1":
        return {"action": "escalate", "approved": True, "draft": draft}
    elif choice == "2":
        draft["escalate"] = False
        return {"action": "send", "approved": True, "draft": draft}
    else:
        return {"action": "manual_review", "approved": False, "draft": draft}


# ── Main agent loop ───────────────────────────────────────────────────────────

def run_agent(ticket: str, customer_id: str, mcp_tools: dict, interactive: bool = True) -> dict:
    """
    Main agent loop.
    mcp_tools: dict of tool_name -> callable (injected from MCP client)
    """
    ticket_id = f"TKT{uuid.uuid4().hex[:8].upper()}"
    start_time = time.time()
    tool_logs = []
    steps = 0

    print(f"\n{'='*60}")
    print(f"Processing ticket {ticket_id}")
    print(f"Customer: {customer_id}")
    print(f"Ticket: {ticket[:100]}...")
    print("="*60)

    result = {
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "ticket": ticket,
        "steps": 0,
        "tool_logs": [],
        "classification": None,
        "customer_info": None,
        "policy": None,
        "draft": None,
        "final_action": None,
        "total_cost": 0.0,
        "total_duration_ms": 0.0,
        "success": False,
        "error": None,
    }

    try:
        # Step 1: classify
        steps += 1
        print(f"\nStep {steps}: Classifying ticket...")
        t0 = time.perf_counter()
        classification = classify_ticket(ticket)
        duration = (time.perf_counter() - t0) * 1000
        tool_logs.append(log_tool_call("classify_ticket", {"text": ticket[:100]},
                                        json.dumps(classification), duration))
        result["classification"] = classification
        category = classification["category"]
        print(f"  → {category} (confidence: {classification['confidence']:.2f})")

        if steps >= MAX_STEPS:
            raise Exception("Max steps reached after classification")

        # Step 2: fetch customer context (MCP)
        steps += 1
        print(f"\nStep {steps}: Fetching customer context...")
        t0 = time.perf_counter()
        customer_info = json.loads(mcp_tools["get_customer"](customer_id))
        duration = (time.perf_counter() - t0) * 1000
        tool_logs.append(log_tool_call("get_customer", {"customer_id": customer_id},
                                        json.dumps(customer_info), duration))
        result["customer_info"] = customer_info
        print(f"  → {customer_info.get('name', 'Unknown')} ({customer_info.get('plan', 'unknown')} plan)")

        if steps >= MAX_STEPS:
            raise Exception("Max steps reached after customer fetch")

        # Step 3: fetch order history (MCP)
        steps += 1
        print(f"\nStep {steps}: Fetching order history...")
        t0 = time.perf_counter()
        orders = json.loads(mcp_tools["get_customer_orders"](customer_id))
        duration = (time.perf_counter() - t0) * 1000
        tool_logs.append(log_tool_call("get_customer_orders", {"customer_id": customer_id},
                                        json.dumps(orders), duration))
        customer_info["orders"] = orders.get("orders", [])
        print(f"  → {len(customer_info['orders'])} orders found")

        if steps >= MAX_STEPS:
            raise Exception("Max steps reached after order fetch")

        # Step 4: fetch policy (MCP)
        steps += 1
        print(f"\nStep {steps}: Fetching policy for '{category}'...")
        t0 = time.perf_counter()
        policy = json.loads(mcp_tools["get_policy"](category))
        duration = (time.perf_counter() - t0) * 1000
        tool_logs.append(log_tool_call("get_policy", {"category": category},
                                        json.dumps(policy), duration))
        result["policy"] = policy
        policies = policy.get("policies", [])
        print(f"  → {len(policies)} policies found")

        if steps >= MAX_STEPS:
            raise Exception("Max steps reached after policy fetch")

        # Step 5: draft response
        steps += 1
        print(f"\nStep {steps}: Drafting response...")
        t0 = time.perf_counter()
        draft = draft_response(ticket, customer_info, policy, category)
        duration = (time.perf_counter() - t0) * 1000
        tool_logs.append(log_tool_call("draft_response", {"category": category},
                                        json.dumps(draft), duration))
        result["draft"] = draft
        print(f"  → Confidence: {draft.get('confidence', 0):.2f}")
        print(f"  → Escalate: {draft.get('escalate', False)}")

        if steps >= MAX_STEPS:
            raise Exception("Max steps reached after draft")

        # Step 6: HITL or auto-resolve
        steps += 1
        if draft.get("escalate") and interactive:
            print(f"\nStep {steps}: HITL checkpoint...")
            hitl_result = hitl_escalation_check(ticket, draft, customer_id)
            result["final_action"] = hitl_result["action"]

            # update ticket status via MCP
            status = "escalated" if hitl_result["action"] == "escalate" else "resolved"
            t0 = time.perf_counter()
            update_result = json.loads(mcp_tools["update_ticket_status"](
                ticket_id, status, customer_id
            ))
            duration = (time.perf_counter() - t0) * 1000
            tool_logs.append(log_tool_call("update_ticket_status",
                                            {"ticket_id": ticket_id, "status": status},
                                            json.dumps(update_result), duration))
        else:
            # auto-resolve (non-interactive mode for eval)
            result["final_action"] = "escalate" if draft.get("escalate") else "resolve"
            t0 = time.perf_counter()
            status = "escalated" if draft.get("escalate") else "resolved"
            update_result = json.loads(mcp_tools["update_ticket_status"](
                ticket_id, status, customer_id
            ))
            duration = (time.perf_counter() - t0) * 1000
            tool_logs.append(log_tool_call("update_ticket_status",
                                            {"ticket_id": ticket_id, "status": status},
                                            json.dumps(update_result), duration))

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        result["success"] = False
        print(f"\n Agent error: {e}")

    total_duration = (time.time() - start_time) * 1000
    result["steps"] = steps
    result["tool_logs"] = tool_logs
    result["total_duration_ms"] = round(total_duration, 2)

    print(f"\n{'='*60}")
    print(f"Done in {steps} steps ({total_duration:.0f}ms)")
    print(f"Final action: {result['final_action']}")
    print("="*60)

    return result