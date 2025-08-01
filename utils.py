import re
from typing import List
from rapidfuzz import fuzz

def extract_vocab_sequence(transcription: str, vocab_phrases: List[str]) -> List[str]:
    transcription = transcription.lower()
    vocab_phrases = sorted(vocab_phrases, key=lambda p: -len(p))  # Match longest phrases first

    matches = []
    used_spans = []

    for phrase in vocab_phrases:
        pattern = r'\b' + re.escape(phrase) + r'\b'
        for match in re.finditer(pattern, transcription):
            start, end = match.span()
            if all(end <= s or start >= e for s, e in used_spans):
                matches.append((start, end, phrase))
                used_spans.append((start, end))
                break

    matches.sort(key=lambda m: m[0])  # Sort by order of appearance
    result = []
    last_end = 0

    for start, end, phrase in matches:
        gap_text = transcription[last_end:start]
        if gap_text.strip():  # If there's a non-space gap
            result.append("vocabnotfound")
        result.append(phrase)
        last_end = end

    trailing_text = transcription[last_end:]
    if trailing_text.strip():
        result.append("vocabnotfound")

    return result


def find_vocabulary(transcription, vocab_list):
    transcription_lower = transcription.lower()
    phrases = [(v.phrase.lower(), v.phrase) for v in vocab_list]
    phrases.sort(key=lambda x: -len(x[0]))

    matches = []
    matched_spans = []
    entities = {}

    for lowered, original in phrases:
        for match in re.finditer(r'\b' + re.escape(lowered) + r'\b', transcription_lower):
            start, end = match.start(), match.end()
            if all(end <= s or start >= e for s, e in matched_spans):
                matches.append((start, original))
                matched_spans.append((start, end))
                if original.startswith("entity"):
                    entities[original] = match.group()
                break

    matches.sort(key=lambda x: x[0])
    found = [phrase for _, phrase in matches]
    return found, entities


def match_saved_answers(transcription, saved_answers, threshold):
    results = []
    for answer in saved_answers:
        score = fuzz.ratio(transcription.lower(), answer.text.lower())
        if score >= threshold:
            results.append({
                "matched_text": answer.text,
                "is_correct": answer.is_correct,
                "score": score
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
  
