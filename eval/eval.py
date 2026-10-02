import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.agent import run_agent, classify_ticket
from agent.mcp_client import MCPClient
from anthropic import Anthropic
from config import JUDGE_MODEL

client = Anthropic()

# 20 test cases
TEST_CASES = [
    {"id": 1, "ticket": "I was charged twice for my subscription this month.", "customer_id": "CUST0001", "expected_category": "billing", "expected_action": "escalate"},
    {"id": 2, "ticket": "I need a refund for my purchase last week.", "customer_id": "CUST0002", "expected_category": "billing", "expected_action": "resolve"},
    {"id": 3, "ticket": "The app keeps crashing when I open it.", "customer_id": "CUST0003", "expected_category": "technical", "expected_action": "resolve"},
    {"id": 4, "ticket": "I can't log into my account, password reset isn't working.", "customer_id": "CUST0004", "expected_category": "account", "expected_action": "resolve"},
    {"id": 5, "ticket": "My order hasn't arrived after 3 weeks.", "customer_id": "CUST0005", "expected_category": "shipping", "expected_action": "escalate"},
    {"id": 6, "ticket": "I want to cancel my subscription immediately.", "customer_id": "CUST0006", "expected_category": "billing", "expected_action": "resolve"},
    {"id": 7, "ticket": "The API is returning 500 errors on all requests.", "customer_id": "CUST0007", "expected_category": "technical", "expected_action": "escalate"},
    {"id": 8, "ticket": "I was charged for a plan I didn't subscribe to.", "customer_id": "CUST0008", "expected_category": "billing", "expected_action": "escalate"},
    {"id": 9, "ticket": "How do I export my data from your platform?", "customer_id": "CUST0009", "expected_category": "technical", "expected_action": "resolve"},
    {"id": 10, "ticket": "My account was suspended without any warning.", "customer_id": "CUST0010", "expected_category": "account", "expected_action": "escalate"},
    {"id": 11, "ticket": "I received the wrong item in my order.", "customer_id": "CUST0011", "expected_category": "shipping", "expected_action": "resolve"},
    {"id": 12, "ticket": "Can you upgrade my plan to enterprise?", "customer_id": "CUST0012", "expected_category": "billing", "expected_action": "resolve"},
    {"id": 13, "ticket": "Your service has been down for 2 hours.", "customer_id": "CUST0013", "expected_category": "technical", "expected_action": "escalate"},
    {"id": 14, "ticket": "I need to update my billing information.", "customer_id": "CUST0014", "expected_category": "billing", "expected_action": "resolve"},
    {"id": 15, "ticket": "My team members can't access the shared workspace.", "customer_id": "CUST0015", "expected_category": "account", "expected_action": "resolve"},
    {"id": 16, "ticket": "Package was delivered to wrong address.", "customer_id": "CUST0016", "expected_category": "shipping", "expected_action": "escalate"},
    {"id": 17, "ticket": "I'm getting a permission denied error on the dashboard.", "customer_id": "CUST0017", "expected_category": "technical", "expected_action": "resolve"},
    {"id": 18, "ticket": "I want to delete my account and all my data.", "customer_id": "CUST0018", "expected_category": "account", "expected_action": "resolve"},
    {"id": 19, "ticket": "My invoice shows incorrect tax charges.", "customer_id": "CUST0019", "expected_category": "billing", "expected_action": "escalate"},
    {"id": 20, "ticket": "The mobile app is extremely slow on my device.", "customer_id": "CUST0020", "expected_category": "technical", "expected_action": "resolve"},
]


def llm_judge(ticket: str, draft: dict, customer_info: dict, category: str) -> dict:
    """LLM-as-judge: score the draft response."""
    prompt = f"""You are evaluating a customer support response. Score it on these criteria:

Ticket: {ticket}
Category: {category}
Customer Plan: {customer_info.get('plan', 'unknown')}

Draft Response:
Subject: {draft.get('subject', '')}
Body: {draft.get('body', '')}

Score each criterion 0-5:
1. relevance: Does the response address the actual issue?
2. empathy: Is the tone empathetic and professional?
3. accuracy: Is the response factually consistent with the category?
4. completeness: Does it provide a clear next step?
5. appropriate_escalation: Is the escalation decision (escalate={draft.get('escalate')}) correct for this ticket?

Reply with JSON only:
{{"relevance": 0-5, "empathy": 0-5, "accuracy": 0-5, "completeness": 0-5, "appropriate_escalation": 0-5, "overall": 0-5, "feedback": "one sentence"}}"""

    r = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"relevance": 3, "empathy": 3, "accuracy": 3,
                "completeness": 3, "appropriate_escalation": 3,
                "overall": 3, "feedback": "parse error"}


def run_eval():
    print("Running evaluation on 20 test cases...\n")
    mcp = MCPClient()
    tools = mcp.get_tools()
    results = []

    for case in TEST_CASES:
        print(f"[{case['id']}/20] {case['ticket'][:60]}...")
        start = time.perf_counter()

        try:
            result = run_agent(
                case["ticket"],
                case["customer_id"],
                tools,
                interactive=False
            )
            latency = time.perf_counter() - start

            # score classification
            correct_category = (
                result.get("classification", {}).get("category") == case["expected_category"]
            )
            correct_action = (result.get("final_action") == case["expected_action"])

            # LLM judge
            scores = llm_judge(
                case["ticket"],
                result.get("draft", {}),
                result.get("customer_info", {}),
                case["expected_category"]
            )

            results.append({
                "id": case["id"],
                "ticket": case["ticket"],
                "customer_id": case["customer_id"],
                "expected_category": case["expected_category"],
                "predicted_category": result.get("classification", {}).get("category"),
                "correct_category": correct_category,
                "expected_action": case["expected_action"],
                "predicted_action": result.get("final_action"),
                "correct_action": correct_action,
                "llm_scores": scores,
                "latency_s": round(latency, 2),
                "steps": result.get("steps", 0),
                "success": result.get("success", False),
                "error": result.get("error"),
            })

            status = "✅" if correct_category and correct_action else "⚠️"
            print(f"  {status} category={result.get('classification', {}).get('category')} "
                  f"action={result.get('final_action')} "
                  f"judge={scores.get('overall', 0)}/5")

        except Exception as e:
            print(f"  ❌ Error: {e}")
            results.append({
                "id": case["id"],
                "ticket": case["ticket"],
                "success": False,
                "error": str(e)
            })

    mcp.close()

    # summary
    ok = [r for r in results if r.get("success")]
    cat_acc = sum(1 for r in ok if r.get("correct_category")) / max(len(ok), 1)
    act_acc = sum(1 for r in ok if r.get("correct_action")) / max(len(ok), 1)
    avg_judge = sum(r.get("llm_scores", {}).get("overall", 0) for r in ok) / max(len(ok), 1)
    avg_latency = sum(r.get("latency_s", 0) for r in ok) / max(len(ok), 1)

    print(f"\n{'='*60}")
    print(f"EVAL RESULTS ({len(ok)}/20 successful)")
    print(f"Category accuracy: {cat_acc:.1%}")
    print(f"Action accuracy:   {act_acc:.1%}")
    print(f"LLM judge score:   {avg_judge:.1f}/5")
    print(f"Avg latency:       {avg_latency:.1f}s")

    with open("eval/eval_results.json", "w") as f:
        json.dump({
            "summary": {
                "total": len(results),
                "successful": len(ok),
                "category_accuracy": round(cat_acc, 3),
                "action_accuracy": round(act_acc, 3),
                "avg_judge_score": round(avg_judge, 2),
                "avg_latency_s": round(avg_latency, 2),
            },
            "results": results
        }, f, indent=2)
    print("\nSaved to eval/eval_results.json")


if __name__ == "__main__":
    run_eval()