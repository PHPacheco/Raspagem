from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from . import PARSER_VERSION
from .models import RecipeData, RelatedCategory
from .text_utils import (
    canonical_url,
    clean_text,
    normalize_text,
    parse_localized_number,
    parse_minutes,
    parse_rating,
    site_category_id_from_url,
    site_recipe_id_from_url,
)


def _json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                graph = item.get("@graph")
                if isinstance(graph, list):
                    objects.extend(x for x in graph if isinstance(x, dict))
                objects.append(item)
    return objects


def _recipe_json_ld(objects: list[dict[str, Any]]) -> dict[str, Any]:
    for item in objects:
        recipe_type = item.get("@type")
        types = recipe_type if isinstance(recipe_type, list) else [recipe_type]
        if any(str(value).casefold() == "recipe" for value in types):
            return item
    return {}


def _first_heading(soup: BeautifulSoup, prefix: str) -> Tag | None:
    target = normalize_text(prefix)
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if normalize_text(heading.get_text(" ", strip=True)).startswith(target):
            return heading
    return None


def _section_for_heading(heading: Tag | None) -> Tag | None:
    if heading is None:
        return None
    for ancestor in heading.parents:
        if isinstance(ancestor, Tag) and ancestor.name in {"section", "article"}:
            return ancestor
    for ancestor in heading.parents:
        if isinstance(ancestor, Tag) and ancestor.find("li"):
            return ancestor
    return heading.parent if isinstance(heading.parent, Tag) else None


def _list_items(section: Tag | None) -> list[str]:
    if section is None:
        return []
    result: list[str] = []
    for item in section.find_all("li"):
        text = clean_text(item.get_text(" ", strip=True))
        if text and text not in result and text.casefold() not in {"comprar", "imprimir"}:
            result.append(text)
    return result


def _flatten_instructions(value: Any) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_instructions(item))
        return result
    if isinstance(value, dict):
        if "itemListElement" in value:
            return _flatten_instructions(value["itemListElement"])
        text = value.get("text") or value.get("name")
        return _flatten_instructions(text)
    return []


def _extract_visible_rating(soup: BeautifulSoup) -> tuple[float | None, int | None]:
    text = clean_text(soup.get_text(" ", strip=True))
    rating_match = re.search(
        r"(\d+(?:[,.]\d+)?)\s*/\s*5\s*\(([^)]*?)\s+avaliaç(?:ões|oes)\)",
        text,
        flags=re.IGNORECASE,
    )
    if not rating_match:
        return None, None
    return parse_rating(rating_match.group(1)), parse_localized_number(rating_match.group(2))


def _extract_time(soup: BeautifulSoup, recipe_json: dict[str, Any]) -> tuple[int | None, str | None]:
    raw = recipe_json.get("totalTime")
    if isinstance(raw, str) and raw:
        iso_match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", raw.upper())
        if iso_match:
            hours = int(iso_match.group(1) or 0)
            minutes = int(iso_match.group(2) or 0)
            return hours * 60 + minutes, raw
        return parse_minutes(raw), raw
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"\b\d+\s*h(?:oras?)?(?:\s*\d+\s*(?:min|m)\b)?|\b\d+\s*min\b", text, re.IGNORECASE)
    if not match:
        return None, None
    raw = clean_text(match.group(0))
    return parse_minutes(raw), raw


def _extract_difficulty(soup: BeautifulSoup) -> str | None:
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"\b(Fácil|Médio|Média|Difícil)\b", text, re.IGNORECASE)
    return clean_text(match.group(1)) if match else None


def _extract_cost(soup: BeautifulSoup) -> str | None:
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"\b(Custo\s+(?:baixo|médio|medio|alto))\b", text, re.IGNORECASE)
    return clean_text(match.group(1)) if match else None


def _extract_servings(soup: BeautifulSoup, recipe_json: dict[str, Any]) -> int | None:
    recipe_yield = recipe_json.get("recipeYield")
    if isinstance(recipe_yield, list):
        recipe_yield = " ".join(str(item) for item in recipe_yield)
    if recipe_yield:
        match = re.search(r"\d+", str(recipe_yield))
        if match:
            return int(match.group(0))
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"Ingredientes\s*\((\d+)\s*porções?\)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_related_categories(soup: BeautifulSoup, recipe_url: str) -> list[RelatedCategory]:
    heading = _first_heading(soup, "Categorias relacionadas")
    section = _section_for_heading(heading)
    if section is None:
        return []
    result: list[RelatedCategory] = []
    seen: set[str] = set()
    for anchor in section.find_all("a", href=True):
        url = canonical_url(urljoin(recipe_url, str(anchor["href"])))
        name = clean_text(anchor.get_text(" ", strip=True))
        if not name:
            continue
        category_id = site_category_id_from_url(url) or f"name:{normalize_text(name)}"
        if category_id in seen:
            continue
        seen.add(category_id)
        result.append(RelatedCategory(category_id, name, url))
    return result


def parse_recipe(
    html: str,
    recipe_url: str,
    *,
    retrieved_at: str | None = None,
    parser_version: str = PARSER_VERSION,
) -> RecipeData:
    canonical = canonical_url(recipe_url)
    recipe_id = site_recipe_id_from_url(canonical)
    if recipe_id is None:
        raise ValueError(f"Não foi possível extrair o ID da receita: {recipe_url}")

    soup = BeautifulSoup(html, "html.parser")
    objects = _json_ld_objects(soup)
    recipe_json = _recipe_json_ld(objects)
    h1 = soup.find("h1")
    title = clean_text(recipe_json.get("name")) or (clean_text(h1.get_text(" ", strip=True)) if h1 else "")
    description = clean_text(recipe_json.get("description"))
    if not description:
        meta = soup.select_one('meta[name="description"]')
        description = clean_text(meta.get("content")) if meta else None

    aggregate = recipe_json.get("aggregateRating")
    rating_value = None
    ratings_count = None
    if isinstance(aggregate, dict):
        rating_value = parse_rating(aggregate.get("ratingValue"))
        ratings_count = parse_localized_number(str(aggregate.get("ratingCount") or aggregate.get("reviewCount") or ""))
    if rating_value is None or ratings_count is None:
        visible_rating, visible_count = _extract_visible_rating(soup)
        rating_value = rating_value if rating_value is not None else visible_rating
        ratings_count = ratings_count if ratings_count is not None else visible_count

    ingredients = recipe_json.get("recipeIngredient")
    if isinstance(ingredients, str):
        ingredients = [ingredients]
    if not isinstance(ingredients, list):
        ingredients = _list_items(_section_for_heading(_first_heading(soup, "Ingredientes")))
    ingredients = [clean_text(str(item)) for item in ingredients if clean_text(str(item))]

    instructions = _flatten_instructions(recipe_json.get("recipeInstructions"))
    if not instructions:
        instructions = _list_items(_section_for_heading(_first_heading(soup, "Modo de preparo")))

    utensils = _list_items(_section_for_heading(_first_heading(soup, "Utensílios")))
    prep_minutes, prep_raw = _extract_time(soup, recipe_json)

    data = RecipeData(
        site_recipe_id=recipe_id,
        title=title,
        url=canonical,
        rating_value=rating_value,
        ratings_count=ratings_count,
        prep_time_minutes=prep_minutes,
        prep_time_raw=prep_raw,
        difficulty=_extract_difficulty(soup),
        cost_label=_extract_cost(soup),
        servings=_extract_servings(soup, recipe_json),
        description=description or None,
        ingredients=ingredients,
        utensils=utensils,
        preparation_steps=instructions,
        related_categories=_extract_related_categories(soup, canonical),
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
        parser_version=parser_version,
    )
    if not data.title:
        data.issues.append("title ausente")
    if data.rating_value is None:
        data.issues.append("rating_value ausente")
    if data.ratings_count is None:
        data.issues.append("ratings_count ausente")
    if data.prep_time_minutes is None:
        data.issues.append("prep_time_minutes ausente")
    if not data.difficulty:
        data.issues.append("difficulty ausente")
    if not data.cost_label:
        data.issues.append("cost_label ausente")
    if not data.ingredients:
        data.issues.append("ingredients ausentes")
    if not data.utensils:
        data.issues.append("utensils ausentes")
    if not data.preparation_steps:
        data.issues.append("preparation_steps ausentes")
    if not data.related_categories:
        data.issues.append("related_categories ausentes")
    return data
