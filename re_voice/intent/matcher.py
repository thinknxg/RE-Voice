"""Tier-1 deterministic intent matcher. Pure — takes command dicts, returns a match.

Scoring is intentionally simple and explainable: keyword hits dominate, phrase
token overlap breaks ties. Anything ambiguous falls through to the LLM tier."""

import re

STOPWORDS = {"the", "a", "an", "for", "to", "of", "and", "please", "can", "you",
             "me", "my", "is", "it", "this", "that", "with", "on", "in", "at"}


def _tokens(text):
    """Lowercase, strip possessives, split on non-alphanumerics, drop stopwords.
    Possessive stripping matters: "today's" must match the keyword "today"."""
    lowered = (text or "").lower().replace("'s", "").replace("'", "")
    return [t for t in re.split(r"[^a-z0-9]+", lowered)
            if t and t not in STOPWORDS]


def _phrase_overlap(transcript_tokens, phrase):
    phrase_tokens = set(_tokens(phrase))
    if not phrase_tokens:
        return 0.0
    hits = len(phrase_tokens & set(transcript_tokens))
    return hits / len(phrase_tokens)


def match(transcript, commands):
    """commands: list of dicts with command_name, keywords (csv), sample_phrases
    (newline-separated). Returns (command_name, confidence) or (None, 0.0)."""
    tokens = _tokens(transcript)
    if not tokens:
        return None, 0.0
    joined = " ".join(tokens)

    scored = []
    for command in commands:
        score = 0.0
        for keyword in [k.strip().lower() for k in
                        (command.get("keywords") or "").split(",") if k.strip()]:
            keyword_tokens = _tokens(keyword)
            if not keyword_tokens:
                continue
            if " ".join(keyword_tokens) in joined:
                # multi-word keywords are stronger evidence than single words
                score += 0.55 + 0.1 * (len(keyword_tokens) - 1)
        best_phrase = max(
            (_phrase_overlap(tokens, phrase) for phrase in
             (command.get("sample_phrases") or "").splitlines() if phrase.strip()),
            default=0.0)
        score += best_phrase * 0.45
        if score > 0:
            scored.append((command["command_name"], round(min(score, 0.99), 3)))

    if not scored:
        return None, 0.0
    scored.sort(key=lambda pair: pair[1], reverse=True)
    best_name, best_score = scored[0]
    # Ambiguity guard: two near-equal candidates should go to the LLM tier instead
    if len(scored) > 1 and scored[1][1] >= best_score - 0.05:
        return None, best_score
    return (best_name, best_score) if best_score >= 0.5 else (None, best_score)
