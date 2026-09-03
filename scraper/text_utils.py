from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_text(value: str | None) -> str:
    value = clean_text(value).casefold()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def parse_localized_number(value: str | None) -> int | None:
    if not value:
        return None
    text = clean_text(value).casefold().replace(" ", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1].replace(",", ".")
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1].replace(",", ".")
    else:
        text = re.sub(r"[^0-9]", "", text)
        return int(text) if text else None
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def parse_rating(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[,.]\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_minutes(value: str | None) -> int | None:
    if not value:
        return None
    text = clean_text(value).casefold()
    hours = re.search(r"(\d+)\s*h", text)
    minutes = re.search(r"(\d+)\s*(?:min|m)\b", text)
    if not hours and not minutes:
        return None
    return (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)


def site_recipe_id_from_url(url: str) -> str | None:
    match = re.search(r"/receita/(\d+)(?:[-/.?]|$)", urlsplit(url).path + ("?" if "?" in url else ""))
    return match.group(1) if match else None


def site_category_id_from_url(url: str) -> str | None:
    match = re.search(r"/categorias/([^/?#]+)", urlsplit(url).path)
    if not match:
        return None
    numeric = re.match(r"\d+", match.group(1))
    return numeric.group(0) if numeric else match.group(1)

