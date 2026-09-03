from pathlib import Path

from scraper.category_parser import parse_category_page
from scraper.database import (
    connect_database,
    create_scrape_run,
    distinct_filter_values,
    initialize_database,
    query_recipes,
    recipe_details,
    save_listing,
    save_recipe,
)
from scraper.recipe_parser import parse_recipe


FIXTURES = Path(__file__).parent / "fixtures"
CATEGORY_URL = "https://www.tudogostoso.com.br/categorias/1004-carnes"
RECIPE_URL = "https://www.tudogostoso.com.br/receita/1438-carne-de-panela-de-pressao.html"


def _database_with_sample(tmp_path: Path):
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    run_id = create_scrape_run(connection, category_url=CATEGORY_URL, max_pages=1)
    category = parse_category_page(
        (FIXTURES / "category_page_1.html").read_text(encoding="utf-8"), CATEGORY_URL
    )
    save_listing(
        connection,
        run_id=run_id,
        category_id="1004",
        category_name="Carnes",
        category_url=CATEGORY_URL,
        recipe_link=category.recipe_links[0],
    )
    recipe = parse_recipe(
        (FIXTURES / "recipe_1438.html").read_text(encoding="utf-8"), RECIPE_URL
    )
    save_recipe(connection, recipe)
    return connection, recipe


def test_upsert_keeps_one_recipe_and_related_lists(tmp_path: Path) -> None:
    connection, recipe = _database_with_sample(tmp_path)
    save_recipe(connection, recipe)

    count = connection.execute("SELECT COUNT(*) AS count FROM recipes").fetchone()["count"]
    ingredient_count = connection.execute("SELECT COUNT(*) AS count FROM ingredients").fetchone()["count"]
    details = recipe_details(connection, "1438")

    assert count == 1
    assert ingredient_count == 3
    assert details is not None
    assert len(details["preparation_steps"]) == 4


def test_search_is_accent_insensitive_and_category_filter_works(tmp_path: Path) -> None:
    connection, _ = _database_with_sample(tmp_path)

    by_text = query_recipes(connection, search="pressao")
    by_category = query_recipes(connection, category_id="101")
    by_collected_category = query_recipes(connection, category_id="1004")

    assert len(by_text) == 1
    assert len(by_category) == 1
    assert len(by_collected_category) == 1

    filters = distinct_filter_values(connection)
    assert {item["site_category_id"] for item in filters["categories"]} >= {"1004", "101"}


def test_filters_are_combined_without_dropping_collected_category(tmp_path: Path) -> None:
    connection, _ = _database_with_sample(tmp_path)

    matching = query_recipes(
        connection,
        search="cebola",
        difficulty="Fácil",
        cost_label="Custo médio",
        max_time=25,
        min_rating=4.5,
        category_id="1004",
    )
    too_fast = query_recipes(connection, max_time=24, category_id="1004")

    assert len(matching) == 1
    assert too_fast == []

