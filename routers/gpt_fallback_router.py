@router.post("/gpt-interpret")
async def gpt_interpret_transcript(
    interaction_id: str,
    transcript: str,
    interaction_context: str = ""
):
    """
    Always calls GPT to interpret what the user said.
    No intent matching — just free interpretation.
    Used when no intents are configured or match fails.
    """
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        prompt = f"""A user is learning French. They were asked: "{interaction_context}"
They responded: "{transcript}"

In one short sentence, describe what the user said and whether it makes sense as a French response to the question. Be encouraging."""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        
        interpretation = response.choices[0].message.content
        cost = response.usage.total_tokens * 0.00000015
        
        return {
            "success": True,
            "transcript": transcript,
            "interpretation": interpretation,
            "cost_usd": round(cost, 6)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
