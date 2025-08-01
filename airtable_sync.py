import os
import httpx
from fastapi import APIRouter, HTTPException
from config import AIRTABLE_BASE_ID, AIRTABLE_API_KEY

router = APIRouter()

# Airtable config
AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}
