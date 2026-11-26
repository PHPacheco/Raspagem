"""Generate the read-only recipe catalog from the project's local SQLite source."""

import argparse
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

from usda_nutrition import DATA, MAPPING, SNAPSHOT, estimate, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT.parent / "data" / "recipes.sqlite"
DEFAULT_CATALOG = PROJECT / "functions" / "data" / "recipes.json"
DEFAULT_SOURCES = DATA / "recipe-sources.json"

QUANTITY = r"(?:\d+(?:[,.]\d+)?(?:\s*/\s*\d+)?(?:\s*[¼½¾⅓⅔⅛])?|[¼½¾⅓⅔⅛])"
MEASURE = re.compile(
    rf"^{QUANTITY}(?:\s*(?:e|a|ou)\s*{QUANTITY})?\s*"
    r"(?:(?:kg|g|gr|mg|ml|l|quilos?|gramas?|litros?|"
    r"x[ií]caras?|colheres?|colher|copos?|canecas?|dentes?|cabe[cç]as?|"
    r"latas?|vidros?|caixinhas?|caixas?|pacotes?|pacotinhos?|tabletes?|"
    r"cubos?|potes?|sach[eê]s?|fatias?|pitadas?|ramos?|ma[cç]os?|unidades?)\b"
    r"(?:\s+(?:rasas?|cheias?|pequenas?|grandes?|m[eé]dias?|de ch[aá]|de sopa|de caf[eé])\b)?"
    r"(?:\s*\([^)]*\))?)?"
    r"(?:\s+(?:de|do|da)\b)?\s*",
    re.IGNORECASE,
)
PREPARATION = re.compile(
    r"\s+(?:a gosto\b|ao seu gosto\b|para (?:untar|polvilhar|decorar|empanar|crepioca)\b|"
    r"cortad[oa]s?\b|ralad[oa]s?\b|picad[oa]s?\b|fatiad[oa]s?\b|"
    r"amassad[oa]s?\b|bem madur[oa]s?\b|sem pele\b|sem sementes\b|"
    r"grandes?\b|pequen[oa]s?\b|m[eé]di[oa]s?\b).*$",
    re.IGNORECASE,
)


def normalize(value):
    plain = unicodedata.normalize("NFD", value.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in plain if not unicodedata.combining(c))))


def ingredient(raw):
    name = MEASURE.sub("", raw.strip(), count=1)
    name = re.sub(r"\s+\([^)]*\).*$", "", name)
    name = PREPARATION.sub("", name).strip(" ,;:-") or raw
    return {"name": normalize(name), "label": name, "original": raw}


def build_catalog(database, sources, selected_ids=()):
    uri = database.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT site_recipe_id, title, url, prep_time_minutes, servings, cost_label, origin_category
               FROM recipes WHERE duplicate_of_recipe_id IS NULL ORDER BY site_recipe_id"""
        ).fetchall()
        catalog = []
        for row in rows:
            recipe_id = row["site_recipe_id"]
            if selected_ids and recipe_id not in selected_ids:
                continue
            source_url = sources.get(recipe_id, row["url"])
            source = urlsplit(source_url)
            if source.scheme != "https" or not source.hostname or source.path.endswith("-html-salvo.html"):
                continue
            ingredients = [
                ingredient(item["raw_text"])
                for item in connection.execute(
                    "SELECT raw_text FROM ingredients WHERE recipe_id = ? ORDER BY position",
                    (recipe_id,),
                )
                if item["raw_text"].strip()
            ]
            if not ingredients:
                continue
            catalog.append({
                "id": recipe_id,
                "title": row["title"],
                "sourceUrl": source_url,
                "prepTimeMinutes": row["prep_time_minutes"],
                "servings": row["servings"],
                "cost": row["cost_label"],
                "category": row["origin_category"],
                "ingredients": ingredients,
            })
    missing = set(selected_ids) - {recipe["id"] for recipe in catalog}
    if missing or not catalog:
        raise ValueError(f"Catálogo vazio ou receitas não elegíveis: {', '.join(sorted(missing))}")
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--recipe-id", action="append", default=[])
    args = parser.parse_args()
    catalog = build_catalog(args.database, read_json(args.sources), args.recipe_id)
    mapping, snapshot = read_json(MAPPING), read_json(SNAPSHOT)
    for recipe in catalog:
        recipe["nutrition"] = estimate(recipe, mapping, snapshot)
    write_json(args.output, catalog)
    print(f"{len(catalog)} receitas exportadas para {args.output}")


if __name__ == "__main__":
    main()
