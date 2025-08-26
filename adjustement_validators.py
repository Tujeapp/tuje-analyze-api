# adjustement_validators.py
from fastapi import HTTPException

def validate_input(transcript: str):
    """Validate input transcript"""
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")
    
    if len(transcript) > 1000:
        raise HTTPException(status_code=400, detail="Transcript too long (max 1000 characters)")
