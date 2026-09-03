from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .models import RecipeLink
from .text_utils import canonical_url, clean_text, site_recipe_id_from_url


RECOMMENDED_HEADING = "receitas recomendadas"
RECIPE_HOST_SUFFIX = "tudogostoso.com.br"


@dataclass(frozen=True)
class CategoryPage:
    url: str
    page_number: int
    recipe_links: list[RecipeLink]
    has_next_page: bool


def _is_allowed_recipe_url(url: str, category_url: str) -> bool:
    recipe_parts = urlsplit(url)
    category_parts = urlsplit(category_url)
    host = (recipe_parts.hostname or "").lower()
    category_host = (category_parts.hostname or "").lower()
    return (
        recipe_parts.scheme in {"http", "https"}
        and host == category_host
        and host.endswith(RECIPE_HOST_SUFFIX)
        and recipe_parts.path.startswith("/receita/")
        and site_recipe_id_from_url(url) is not None
    )


def _heading_is_recommended(tag: Tag) -> bool:
    return tag.name in {"h1", "h2", "h3", "h4", "h5", "h6"} and clean_text(
        tag.get_text(" ", strip=True)
    ).casefold() == RECOMMENDED_HEADING


def _recipe_anchors(node: Tag, category_url: str) -> list[Tag]:
    anchors: list[Tag] = []
    seen: set[str] = set()
    for anchor in node.find_all("a", href=True):
        url = canonical_url(urljoin(category_url, str(anchor["href"])))
        if not _is_allowed_recipe_url(url, category_url) or url in seen:
            continue
        seen.add(url)
        anchors.append(anchor)
    return anchors


def _recommended_container(heading: Tag, category_url: str) -> Tag:
    # Prefer semantic containers. The fallback to a parent is useful for older
    # versions of the site that used div-only layouts.
    for ancestor in heading.parents:
        if not isinstance(ancestor, Tag):
            continue
        if ancestor.name in {"section", "article"}:
            if _recipe_anchors(ancestor, category_url):
                return ancestor
    # Some layouts use divs for sections. Choose the nearest ancestor with
    # recipe links instead of assuming a fixed CSS class.
    for ancestor in heading.parents:
        if isinstance(ancestor, Tag) and _recipe_anchors(ancestor, category_url):
            return ancestor
    parent = heading.parent
    if isinstance(parent, Tag) and _recipe_anchors(parent, category_url):
        return parent
    return heading


def _title_from_anchor(anchor: Tag, url: str) -> str:
    title = clean_text(anchor.get_text(" ", strip=True))
    if title:
        return title
    title = clean_text(anchor.get("aria-label") or anchor.get("title"))
    if title:
        return title
    image = anchor.find("img", alt=True)
    if image:
        return clean_text(image.get("alt"))
    return urlsplit(url).path.rsplit("/", 1)[-1].replace("-", " ").removesuffix(".html")


def parse_category_page(
    html: str,
    category_url: str,
    *,
    page_number: int = 1,
    max_recommendations: int = 15,
) -> CategoryPage:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(_heading_is_recommended)
    if not isinstance(heading, Tag):
        raise ValueError("Seção 'Receitas recomendadas' não encontrada.")

    container = _recommended_container(heading, category_url)
    anchors = _recipe_anchors(container, category_url)

    # If the layout uses a broad parent, stop at the expected recommendation
    # count. The page currently renders 15 cards in this section.
    links: list[RecipeLink] = []
    for position, anchor in enumerate(anchors[:max_recommendations], start=1):
        url = canonical_url(urljoin(category_url, str(anchor["href"])))
        links.append(
            RecipeLink(
                url=url,
                title=_title_from_anchor(anchor, url),
                category_url=canonical_url(category_url),
                page_number=page_number,
                position=position,
                site_recipe_id=site_recipe_id_from_url(url),
            )
        )

    if not links:
        raise ValueError("A seção 'Receitas recomendadas' não contém receitas.")

    return CategoryPage(
        url=canonical_url(category_url),
        page_number=page_number,
        recipe_links=links,
        has_next_page=has_next_page(soup, page_number),
    )


def has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    target_page = current_page + 1
    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get_text(" ", strip=True)).casefold()
        if anchor.get("aria-disabled") == "true" or "disabled" in (anchor.get("class") or []):
            continue
        href = str(anchor["href"])
        query = parse_qs(urlsplit(href).query)
        page_values = query.get("page", [])
        if any(value == str(target_page) for value in page_values):
            return True
        if text in {"próximo", "proximo", ">", ">>"}:
            return True
    return False


def page_url(category_url: str, page_number: int) -> str:
    if page_number <= 1:
        return canonical_url(category_url)
    parts = urlsplit(category_url)
    query = parse_qs(parts.query)
    query["page"] = [str(page_number)]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), "")
    )
