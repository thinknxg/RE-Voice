"""Property matching: deterministic filter first, optional LLM re-rank.
Every recommendation carries its match reason — unexplained suggestions don't get sent."""

import frappe
from frappe.utils import flt

from re_voice.ai.client import llm_complete, parse_json_response


def match_properties(requirement, unit_type=None, bedrooms=None, budget=None,
                     locality=None, limit=3):
    filters = {"is_published": 1}
    if unit_type:
        filters["unit_type"] = unit_type
    if bedrooms:
        filters["bedrooms"] = [">=", bedrooms]
    if locality:
        filters["locality"] = ["like", f"%{locality}%"]
    if budget:
        filters["headline_price"] = ["<=", flt(budget) * 1.1]

    candidates = frappe.get_all(
        "Listing", filters=filters,
        fields=["name", "title", "unit", "unit_type", "bedrooms", "headline_price",
                "locality", "furnishing", "area_sqm"],
        order_by="featured desc, headline_price asc", page_length=10)
    if not candidates:
        return []

    for row in candidates:
        row["reason"] = _deterministic_reason(row, bedrooms, budget, locality)

    if len(candidates) <= limit or not requirement:
        return candidates[:limit]
    return _rerank(requirement, candidates, limit)


def _deterministic_reason(row, bedrooms, budget, locality):
    bits = []
    if bedrooms and row.get("bedrooms"):
        bits.append(f"{row['bedrooms']} bed")
    if budget and row.get("headline_price") and flt(row["headline_price"]) <= flt(budget):
        bits.append("within budget")
    if locality and row.get("locality"):
        bits.append(f"in {row['locality']}")
    if row.get("furnishing") and row["furnishing"] != "Unfurnished":
        bits.append(row["furnishing"].lower())
    return ", ".join(bits) or "available now"


def _rerank(requirement, candidates, limit):
    listing_text = "\n".join(
        f"{c['name']}: {c['title']} | {c['unit_type']} | {c['bedrooms']}BR | "
        f"{c['headline_price']} | {c.get('locality') or ''}" for c in candidates)
    prompt = (f"Buyer requirement: \"{requirement}\"\n\nListings:\n{listing_text}\n\n"
              f"Pick the {limit} best matches. JSON only: "
              '{"picks": [{"name": "<listing name>", "reason": "<short reason>"}]}')
    parsed = parse_json_response(
        llm_complete(prompt, task="Matching", json_mode=True))
    if not parsed or not parsed.get("picks"):
        return candidates[:limit]

    by_name = {c["name"]: c for c in candidates}
    ranked = []
    for pick in parsed["picks"][:limit]:
        row = by_name.get(pick.get("name"))
        if row:
            row["reason"] = pick.get("reason") or row["reason"]
            ranked.append(row)
    return ranked or candidates[:limit]
