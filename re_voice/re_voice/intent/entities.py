"""Locale-aware entity extraction. Pure functions — no Frappe imports, so this
module is unit-testable outside a site."""

import re
from datetime import datetime, timedelta

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

MULTIPLIERS_INDIAN = {"lakh": 100000, "lakhs": 100000, "lac": 100000,
                      "lacs": 100000, "crore": 10000000, "crores": 10000000,
                      "cr": 10000000}
MULTIPLIERS_COMMON = {"k": 1000, "thousand": 1000, "million": 1000000,
                      "m": 1000000, "mn": 1000000}

UNIT_TYPE_WORDS = {
    "studio": "Studio", "penthouse": "Penthouse", "shop": "Shop",
    "office": "Office", "warehouse": "Warehouse", "villa": "Villa",
}
WORD_DIGIT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]


def normalize(text):
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def words_to_number(phrase):
    """'forty five' -> 45. Returns None when no number words are present."""
    total, current, seen = 0, 0, False
    for token in normalize(phrase).replace("-", " ").split():
        if token in UNITS:
            current += UNITS[token]; seen = True
        elif token in TENS:
            current += TENS[token]; seen = True
        elif token == "hundred" and seen:
            current = (current or 1) * 100
        elif token == "and":
            continue
        else:
            if seen:
                total += current
                current, seen = 0, False
    total += current
    return total if (total or seen) else None


def parse_money(text, number_system="International"):
    """Extract a monetary amount. Handles digits and number words, with
    lakh/crore multipliers when the locale uses the Indian number system."""
    text = normalize(text)
    multipliers = dict(MULTIPLIERS_COMMON)
    if number_system == "Indian":
        multipliers.update(MULTIPLIERS_INDIAN)
    mult_pattern = "|".join(sorted(multipliers, key=len, reverse=True))

    # digit form: "45 lakhs", "1.2 crore", "45k", "950000"
    match = re.search(rf"(\d+(?:[.,]\d+)?)\s*({mult_pattern})?\b", text)
    digit_value = None
    if match:
        raw = float(match.group(1).replace(",", ""))
        digit_value = raw * multipliers.get(match.group(2) or "", 1)

    # word form: "forty five lakhs"
    word_value = None
    wm = re.search(rf"([a-z\s\-]+?)\s*({mult_pattern})\b", text)
    if wm:
        base = words_to_number(wm.group(1))
        if base:
            word_value = base * multipliers[wm.group(2)]

    if digit_value is not None and word_value is not None:
        return float(max(digit_value, word_value))
    value = digit_value if digit_value is not None else word_value
    return float(value) if value is not None else None


def parse_budget_range(text, number_system="International"):
    """'between 40 and 60 lakhs' / '40 to 60 lakhs' -> (4000000.0, 6000000.0)."""
    text = normalize(text)
    match = re.search(r"(.+?)\s*(?:to|-|and|until)\s*(.+)", text)
    if not match:
        value = parse_money(text, number_system)
        return (None, value) if value else (None, None)
    tail = match.group(2)
    high = parse_money(tail, number_system)
    low = parse_money(match.group(1), number_system)
    # "40 to 60 lakhs": the multiplier only appears on the second half
    if low and high and low < high / 1000:
        mult = re.search(r"(lakh|lakhs|crore|crores|thousand|k|million)\b", tail)
        if mult:
            table = dict(MULTIPLIERS_COMMON, **MULTIPLIERS_INDIAN)
            low = low * table[mult.group(1)]
    return (low, high)


def parse_unit_type(text):
    """'2 BHK' / 'two bedroom' / 'studio' -> platform unit type code."""
    text = normalize(text)
    for word, code in UNIT_TYPE_WORDS.items():
        if word in text:
            return code
    match = re.search(r"(\d)\s*(?:bhk|br|bed\s?rooms?|bedrooms?|bed)\b", text)
    if not match:
        wm = re.search(r"\b(one|two|three|four|five|six)\s*(?:bhk|br|bed\s?rooms?|"
                       r"bedrooms?|bed)\b", text)
        if not wm:
            return None
        count = WORD_DIGIT[wm.group(1)]
    else:
        count = int(match.group(1))
    if count >= 4:
        return "4BR+"
    return f"{count}BR"


def parse_bedrooms(text):
    unit_type = parse_unit_type(text)
    if not unit_type:
        return None
    if unit_type == "Studio":
        return 0
    match = re.match(r"(\d)", unit_type)
    return int(match.group(1)) if match else None


def parse_datetime(text, now=None):
    """Resolve common spoken date/time phrases. Returns a datetime or None.
    `now` is injectable so this is deterministic under test."""
    now = now or datetime.now()
    text = normalize(text)

    hour, minute = None, None
    tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if tm:
        hour = int(tm.group(1)) % 12
        minute = int(tm.group(2) or 0)
        if tm.group(3) == "pm":
            hour += 12
    elif "morning" in text:
        hour, minute = 10, 0
    elif "afternoon" in text:
        hour, minute = 15, 0
    elif "evening" in text:
        hour, minute = 18, 0
    elif re.search(r"\b(\d{1,2})\s*o'?clock\b", text):
        hour = int(re.search(r"\b(\d{1,2})\s*o'?clock\b", text).group(1))
        minute = 0

    base = None
    if "day after tomorrow" in text:
        base = now + timedelta(days=2)
    elif "tomorrow" in text:
        base = now + timedelta(days=1)
    elif "today" in text or "this evening" in text or "tonight" in text:
        base = now
    else:
        for index, day in enumerate(WEEKDAYS):
            if day in text:
                ahead = (index - now.weekday()) % 7
                if ahead == 0 or "next" in text:
                    ahead = ahead or 7
                base = now + timedelta(days=ahead)
                break
    if base is None and hour is None:
        return None
    base = base or now
    if hour is None:
        hour, minute = 10, 0
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def parse_phone(text):
    match = re.search(r"(\+?\d[\d\s\-]{6,17}\d)", text or "")
    if not match:
        return None
    cleaned = re.sub(r"[\s\-]", "", match.group(1))
    return cleaned if 7 <= len(cleaned.lstrip("+")) <= 15 else None


# Words that terminate a spoken name — everything after them is another entity.
NAME_STOP = {
    "budget", "phone", "number", "mobile", "contact", "interested", "looking",
    "wants", "want", "needs", "need", "for", "with", "in", "at", "from", "and",
    "bhk", "br", "bedroom", "bedrooms", "lakhs", "lakh", "crore", "thousand",
    "rent", "buy", "sale", "villa", "apartment", "flat", "studio", "office",
    "his", "her", "their", "he", "she", "they", "tomorrow", "today",
}


def parse_name(text, markers=("named", "name is", "called", "for")):
    """Best-effort name capture, stopping at the next entity keyword.
    Always confirmed before use — ASR is weakest on proper nouns."""
    lowered = normalize(text)
    for marker in markers:
        index = lowered.find(marker + " ")
        if index < 0:
            continue
        tail = text[index + len(marker) + 1:].strip()
        words = []
        for word in re.split(r"[,.;]|\s+", tail):
            token = word.strip()
            if not token.isalpha() or token.lower() in NAME_STOP:
                break
            words.append(token)
            if len(words) == 3:
                break
        if words:
            return " ".join(w.capitalize() for w in words)
    return None
