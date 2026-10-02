import os
import re
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from agent.mcp_client import MCPClient
from agent.agent import run_agent
import ssl
import certifi
ssl._create_default_https_context = ssl.create_default_context
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

app = App(token=os.environ["SLACK_BOT_TOKEN"])
mcp = MCPClient()
tools = mcp.get_tools()

# extract customer ID from message if present e.g. "CUST0001"
def extract_customer_id(text: str) -> str:
    match = re.search(r'CUST\d{4}', text)
    return match.group(0) if match else "CUST0001"


@app.event("app_mention")
def handle_mention(event, say):
    text = event.get("text", "")
    user = event.get("user", "unknown")
    channel = event.get("channel")

    # strip the bot mention
    ticket = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
    customer_id = extract_customer_id(ticket)

    say(f"👋 Got it <@{user}>! Processing ticket for `{customer_id}`...")

    try:
        result = run_agent(ticket, customer_id, tools, interactive=False)

        category = result.get("classification", {}).get("category", "unknown")
        confidence = result.get("classification", {}).get("confidence", 0)
        action = result.get("final_action", "unknown")
        draft_body = result.get("draft", {}).get("body", "No draft generated")[:500]

        # build response blocks
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Ticket `{result['ticket_id']}`* processed"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Category:* {category} ({confidence:.0%})"},
                    {"type": "mrkdwn", "text": f"*Action:* {action.upper()}"},
                    {"type": "mrkdwn", "text": f"*Customer:* {result.get('customer_info', {}).get('name', customer_id)}"},
                    {"type": "mrkdwn", "text": f"*Plan:* {result.get('customer_info', {}).get('plan', 'unknown')}"},
                ]
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Draft response:*\n{draft_body}"}
            },
        ]

        if action == "escalate":
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn",
                         "text": f"🔴 *Escalated* — {result.get('draft', {}).get('escalation_reason', 'Low confidence')}"}
            })

        say(blocks=blocks)

    except Exception as e:
        say(f"❌ Error processing ticket: {e}")


if __name__ == "__main__":
    print("Starting Slack bot...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()