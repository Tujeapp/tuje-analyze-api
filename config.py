import os
from dotenv import load_dotenv

load_dotenv()  # Optional: loads variables from a .env file if present

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")

# Safety checks
if not DATABASE_URL:
    raise RuntimeError("Missing environment variable: DATABASE_URL")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing environment variable: OPENAI_API_KEY")

# Optional: set default fallback values or raise for critical ones
# Example:
# DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
