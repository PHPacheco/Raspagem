from pathlib import Path

from scraper.category_parser import page_url, parse_category_page


FIXTURES = Path(__file__).parent / "fixtures"
CATEGORY_URL = "https://www.tudogostoso.com.br/categorias/1004-carnes"


def test_extracts_only_the_recommended_fifteen_recipes() -> None:
    html = (FIXTURES / "category_page_1.html").read_text(encoding="utf-8")

    page = parse_category_page(html, CATEGORY_URL)

    assert len(page.recipe_links) == 15
    assert page.recipe_links[0].site_recipe_id == "1438"
    assert page.recipe_links[0].title == "Carne de panela de pressão"
    assert page.recipe_links[-1].position == 15
    assert all("999-menu" not in link.url for link in page.recipe_links)
    assert page.has_next_page is True


def test_page_url_preserves_the_category_and_sets_page_query() -> None:
    assert page_url(CATEGORY_URL, 1) == CATEGORY_URL
    assert page_url(CATEGORY_URL, 2) == f"{CATEGORY_URL}?page=2"

