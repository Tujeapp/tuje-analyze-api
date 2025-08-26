# adjustement_main_router.py
from fastapi import APIRouter
import os

# Import your new components
from adjustement_models import router as api_router

# This will be your main router to replace the old service
router = APIRouter()

# Include your API routes
router.include_router(api_router)

# Add any additional setup needed
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
