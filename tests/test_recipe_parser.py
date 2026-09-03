from pathlib import Path

from scraper.recipe_parser import parse_recipe


FIXTURES = Path(__file__).parent / "fixtures"
RECIPE_URL = "https://www.tudogostoso.com.br/receita/1438-carne-de-panela-de-pressao.html"


def test_extracts_recipe_metadata_and_ordered_sections() -> None:
    html = (FIXTURES / "recipe_1438.html").read_text(encoding="utf-8")

    recipe = parse_recipe(html, RECIPE_URL, retrieved_at="2026-08-28T12:00:00+00:00")

    assert recipe.site_recipe_id == "1438"
    assert recipe.title == "Carne de panela de pressão"
    assert recipe.rating_value == 4.5
    assert recipe.ratings_count == 1548
    assert recipe.prep_time_minutes == 25
    assert recipe.prep_time_raw == "25min"
    assert recipe.difficulty == "Fácil"
    assert recipe.cost_label == "Custo médio"
    assert recipe.servings == 5
    assert len(recipe.ingredients) == 3
    assert len(recipe.utensils) == 4
    assert len(recipe.preparation_steps) == 4
    assert len(recipe.related_categories) == 8
    assert recipe.issues == []


def test_missing_fields_are_reported_instead_of_invented() -> None:
    recipe = parse_recipe(
        "<html><body><h1>Receita parcial</h1></body></html>",
        RECIPE_URL,
    )

    assert recipe.rating_value is None
    assert recipe.prep_time_minutes is None
    assert "rating_value ausente" in recipe.issues
    assert "ingredients ausentes" in recipe.issues


def test_prefers_recipe_json_ld_when_it_is_available() -> None:
    html = """
    <html><body>
      <h1>Título visual diferente</h1>
      <span>Fácil</span><span>Custo baixo</span>
      <script type="application/ld+json">
      {
        "@type": "Recipe",
        "name": "Receita estruturada",
        "aggregateRating": {"ratingValue": "4.8", "ratingCount": "250"},
        "totalTime": "PT1H5M",
        "recipeYield": "4 porções",
        "recipeIngredient": ["1 xícara de arroz"],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Cozinhe o arroz."}]
      }
      </script>
    </body></html>
    """

    recipe = parse_recipe(html, RECIPE_URL)

    assert recipe.title == "Receita estruturada"
    assert recipe.rating_value == 4.8
    assert recipe.ratings_count == 250
    assert recipe.prep_time_minutes == 65
    assert recipe.servings == 4
    assert recipe.ingredients == ["1 xícara de arroz"]
    assert recipe.preparation_steps == ["Cozinhe o arroz."]
