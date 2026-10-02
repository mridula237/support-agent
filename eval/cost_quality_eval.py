import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.mcp_client import MCPClient
from agent.agent import run_agent
from anthropic import Anthropic
from config import MODEL_TIERS, TIER_COSTS, JUDGE_MODEL
import config

client = Anthropic()

# use first 10 cases for speed
TEST_CASES = [
    {"id": 1, "ticket": "I was charged twice for my subscription this month.", "customer_id": "CUST0001", "expected_category": "billing", "expected_action": "escalate"},
    {"id": 2, "ticket": "I need a refund for my purchase last week.", "customer_id": "CUST0002", "expected_category": "billing", "expected_action": "resolve"},
    {"id": 3, "ticket": "The app keeps crashing when I open it.", "customer_id": "CUST0003", "expected_category": "technical", "expected_action": "resolve"},
    {"id": 4, "ticket": "I can't log into my account, password reset not working.", "customer_id": "CUST0004", "expected_category": "account", "expected_action": "resolve"},
    {"id": 5, "ticket": "My order hasn't arrived after 3 weeks.", "customer_id": "CUST0005", "expected_category": "shipping", "expected_action": "escalate"},
    {"id": 6, "ticket": "I want to cancel my subscription immediately.", "customer_id": "CUST0006", "expected_category": "billing", "expected_action": "resolve"},
    {"id": 7, "ticket": "The API is returning 500 errors on all requests.", "customer_id": "CUST0007", "expected_category": "technical", "expected_action": "escalate"},
    {"id": 8, "ticket": "I was charged for a plan I didn't subscribe to.", "customer_id": "CUST0008", "expected_category": "billing", "expected_action": "escalate"},
    {"id": 9, "ticket": "How do I export my data from your platform?", "customer_id": "CUST0009", "expected_category": "technical", "expected_action": "resolve"},
    {"id": 10, "ticket": "My account was suspended without any warning.", "customer_id": "CUST0010", "expected_category": "account", "expected_action": "escalate"},
]


def llm_judge(ticket: str, draft: dict, category: str) -> float:
    prompt = f"""Rate this support response 1-5 overall.
Ticket: {ticket}
Category: {category}
Response body: {draft.get('body', '')[:300]}
Reply with JSON only: {{"score": 1-5}}"""

    r = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=50,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw).get("score", 3)
    except Exception:
        return 3.0


def run_tier(tier_name: str, model: str) -> dict:
    print(f"\n{'='*60}")
    print(f"Testing tier: {tier_name} ({model})")
    print("="*60)

    # override agent model
    config.AGENT_MODEL = model

    mcp = MCPClient()
    tools = mcp.get_tools()

    results = []
    total_cost = 0.0

    for case in TEST_CASES:
        print(f"  [{case['id']}/10] {case['ticket'][:50]}...")
        start = time.perf_counter()

        try:
            result = run_agent(case["ticket"], case["customer_id"],
                               tools, interactive=False)
            latency = time.perf_counter() - start

            # estimate cost from tool logs
            in_tokens = sum(
                log.get("input_tokens", 0)
                for log in result.get("tool_logs", [])
            )
            # rough estimate: classify (~500 in, ~50 out) + draft (~1000 in, ~300 out)
            p_in, p_out = TIER_COSTS.get(model, (0, 0))
            est_cost = (1500 / 1e6 * p_in) + (350 / 1e6 * p_out)
            total_cost += est_cost

            correct_cat = (
                result.get("classification", {}).get("category")
                == case["expected_category"]
            )
            correct_act = result.get("final_action") == case["expected_action"]
            judge_score = llm_judge(
                case["ticket"],
                result.get("draft", {}),
                case["expected_category"]
            )

            results.append({
                "id": case["id"],
                "correct_category": correct_cat,
                "correct_action": correct_act,
                "judge_score": judge_score,
                "latency_s": round(latency, 2),
                "est_cost": round(est_cost, 6),
                "success": result.get("success", False),
            })

            status = "✅" if correct_cat else "⚠️"
            print(f"    {status} cat={result.get('classification', {}).get('category')} "
                  f"judge={judge_score}/5 cost=${est_cost:.4f}")

        except Exception as e:
            print(f"    ❌ {e}")
            results.append({"id": case["id"], "success": False, "error": str(e)})

    mcp.close()

    ok = [r for r in results if r.get("success")]
    return {
        "tier": tier_name,
        "model": model,
        "category_accuracy": round(sum(1 for r in ok if r.get("correct_category")) / max(len(ok), 1), 2),
        "action_accuracy": round(sum(1 for r in ok if r.get("correct_action")) / max(len(ok), 1), 2),
        "avg_judge_score": round(sum(r.get("judge_score", 0) for r in ok) / max(len(ok), 1), 2),
        "avg_latency_s": round(sum(r.get("latency_s", 0) for r in ok) / max(len(ok), 1), 2),
        "total_cost_10_tickets": round(total_cost, 4),
        "cost_per_ticket": round(total_cost / max(len(ok), 1), 4),
        "successful": len(ok),
        "results": results,
    }


def main():
    tier_results = []

    for tier_name, model in MODEL_TIERS.items():
        try:
            result = run_tier(tier_name, model)
            tier_results.append(result)
        except Exception as e:
            print(f"Tier {tier_name} failed: {e}")

    print(f"\n{'='*60}")
    print("COST vs QUALITY COMPARISON")
    print("="*60)
    print(f"{'Tier':<10}{'Model':<30}{'CatAcc':>8}{'ActAcc':>8}{'Judge':>8}{'Latency':>10}{'Cost/ticket':>14}")
    print("-"*88)
    for r in tier_results:
        print(f"{r['tier']:<10}{r['model']:<30}{r['category_accuracy']:>8.0%}"
              f"{r['action_accuracy']:>8.0%}{r['avg_judge_score']:>8.1f}"
              f"{r['avg_latency_s']:>9.1f}s{r['cost_per_ticket']:>13.4f}$")

    with open("eval/cost_quality_results.json", "w") as f:
        json.dump(tier_results, f, indent=2)
    print("\nSaved to eval/cost_quality_results.json")


if __name__ == "__main__":
    main()