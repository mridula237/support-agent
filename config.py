import os

# models
AGENT_MODEL = "claude-sonnet-4-6"
JUDGE_MODEL = "claude-haiku-4-5-20251001"

# agent loop
MAX_STEPS = 10
CONFIDENCE_THRESHOLD = 0.7  # below this → escalate

# CRM server
CRM_SERVER_URL = "http://localhost:8001"
CRM_DB_PATH = "crm_server/crm.db"

# costs per 1M tokens
COSTS = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}

# model tiers for comparison
MODEL_TIERS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

TIER_COSTS = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (15.0, 75.0),
}