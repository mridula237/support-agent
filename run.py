from agent.mcp_client import MCPClient
from agent.agent import run_agent

def main():
    print("Starting CRM MCP server...")
    mcp = MCPClient()
    tools = mcp.get_tools()

    # test cases
    tickets = [
        ("I was charged twice for my subscription this month, please help.", "CUST0001"),
        ("The app keeps crashing whenever I try to export my data.", "CUST0002"),
        ("My order hasn't arrived after 2 weeks.", "CUST0003"),
    ]

    for ticket, customer_id in tickets:
        result = run_agent(ticket, customer_id, tools, interactive=True)
        print(f"\nResult: {result['final_action']} | Success: {result['success']}")
        print("-" * 60)

    mcp.close()


if __name__ == "__main__":
    main()