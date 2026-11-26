"""Refresh the food reference data used to estimate recipe nutrition."""

import argparse
import csv
from datetime import datetime, timezone
from io import TextIOWrapper
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zipfile import ZipFile

DATA = Path(__file__).resolve().parent / "data"
MAPPING = DATA / "nutrition-mapping.json"
SNAPSHOT = DATA / "usda-foods.json"
API = "https://api.nal.usda.gov/fdc/v1/foods"
NUTRIENTS = {
    1008: ("caloriesKcal", "KCAL"),
    1003: ("proteinG", "G"),
    1005: ("carbohydratesG", "G"),
    1004: ("fatG", "G"),
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        temporary.write_bytes(text.encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def food_snapshot(food):
    # The full SR Legacy response gives nutrient amounts per 100 g.
    amounts = {}
    for entry in food["foodNutrients"]:
        nutrient = entry["nutrient"]
        name, unit = NUTRIENTS.get(nutrient["id"], (None, None))
        if name and nutrient.get("unitName", "").upper() == unit and number(entry.get("amount")):
            amounts[name] = entry["amount"]
    return {"description": food["description"], "per100g": amounts}


def mapped_ids(mapping):
    return sorted({item["fdcId"] for items in mapping.values() for item in items if not item.get("omitted")})


def dated_snapshot(ids, foods, source):
    missing = set(map(str, ids)) - foods.keys()
    if missing:
        raise ValueError("Registros USDA ausentes: " + ", ".join(sorted(missing)))
    return {
        "retrievedAt": datetime.now(timezone.utc).date().isoformat(),
        "source": source,
        "foods": {str(key): foods[str(key)] for key in ids},
    }


def refresh_foods(mapping, api_key):
    ids = mapped_ids(mapping)
    foods = {}
    for start in range(0, len(ids), 20):
        batch = ids[start:start + 20]
        query = urlencode({"fdcIds": ",".join(map(str, batch)), "api_key": api_key})
        with urlopen(f"{API}?{query}", timeout=30) as response:
            data = json.load(response)
        for food in data:
            food_id = food["fdcId"]
            if food_id not in batch or food.get("dataType") != "SR Legacy":
                raise ValueError(f"Registro inesperado ou tipo sem base de 100 g verificada: {food_id}")
            foods[str(food_id)] = food_snapshot(food)
    return dated_snapshot(ids, foods, API)


def csv_rows(archive, name):
    path, = [entry for entry in archive.namelist() if Path(entry).name == name]
    with TextIOWrapper(archive.open(path), encoding="utf-8-sig", newline="") as table:
        yield from csv.DictReader(table)


def load_sr_legacy(mapping, archive_path):
    ids = mapped_ids(mapping)
    requested = set(map(str, ids))
    with ZipFile(archive_path) as archive:
        foods = {
            row["fdc_id"]: {"description": row["description"], "per100g": {}}
            for row in csv_rows(archive, "food.csv")
            if row["fdc_id"] in requested and row["data_type"] == "sr_legacy_food"
        }
        valid_units = {row["id"]: row["unit_name"].upper() for row in csv_rows(archive, "nutrient.csv")}
        for row in csv_rows(archive, "food_nutrient.csv"):
            key = row["fdc_id"]
            if key not in foods:
                continue
            name, unit = NUTRIENTS.get(int(row["nutrient_id"]), (None, None))
            if name and row["amount"] and valid_units.get(row["nutrient_id"]) == unit:
                amount = float(row["amount"])
                if number(amount):
                    foods[key]["per100g"][name] = amount
    return dated_snapshot(ids, foods, "USDA FoodData Central SR Legacy (arquivo CSV oficial)")


def estimate(recipe, mapping, snapshot):
    components = mapping.get(recipe["id"], [])
    servings = recipe["servings"]
    if not components or not servings or servings < 1:
        return None
    ingredients = [item["original"] for item in recipe["ingredients"]]
    if ingredients != [item["original"] for item in components]:
        return None

    totals = {name: 0.0 for name, _ in NUTRIENTS.values()}
    food_ids = set()
    omissions = []
    choices = []
    for item in components:
        if item.get("omitted"):
            omissions.append(item["omitted"])
            continue
        if item.get("choice"):
            choices.append(item["choice"])
        grams = item["grams"]
        if not number(grams) or grams <= 0:
            raise ValueError(f"Gramagem inválida para a receita {recipe['id']}")
        food = snapshot["foods"].get(str(item["fdcId"]), {})
        food_ids.add(item["fdcId"])
        for nutrient, running_total in totals.items():
            amount = food.get("per100g", {}).get(nutrient)
            totals[nutrient] = running_total + amount * grams / 100 if running_total is not None and number(amount) else None

    if not food_ids or all(value is None for value in totals.values()):
        return None
    return {
        "perServing": {name: round(value / servings, 1) if value is not None else None for name, value in totals.items()},
        "estimated": True,
        "source": "USDA FoodData Central",
        "sourceUrl": "https://fdc.nal.usda.gov/",
        "retrievedAt": snapshot["retrievedAt"],
        "foodIds": sorted(food_ids),
        "omissions": omissions,
        "choices": choices,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--output", type=Path, default=SNAPSHOT)
    parser.add_argument("--sr-legacy-zip", type=Path, help="Arquivo CSV oficial da USDA para importar localmente")
    args = parser.parse_args()
    api_key = os.environ.get("USDA_API_KEY", "").strip()
    if not api_key and args.sr_legacy_zip is None:
        parser.exit(2, "Defina USDA_API_KEY no ambiente para atualizar os dados.\n")
    try:
        mapping = read_json(args.mapping)
        snapshot = load_sr_legacy(mapping, args.sr_legacy_zip) if args.sr_legacy_zip else refresh_foods(mapping, api_key)
        write_json(args.output, snapshot)
    except HTTPError as error:
        parser.exit(1, f"A USDA retornou HTTP {error.code}. O arquivo anterior foi mantido.\n")
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"Falha ao atualizar dados USDA ({type(error).__name__}). O arquivo anterior foi mantido.\n")
    print(f"{len(snapshot['foods'])} alimentos da USDA atualizados")


if __name__ == "__main__":
    main()
