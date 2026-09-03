from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecipeLink:
    url: str
    title: str
    category_url: str
    page_number: int
    position: int
    site_recipe_id: str | None = None


@dataclass(frozen=True)
class RelatedCategory:
    site_category_id: str
    name: str
    url: str | None = None


@dataclass
class RecipeData:
    site_recipe_id: str
    title: str
    url: str
    rating_value: float | None = None
    ratings_count: int | None = None
    prep_time_minutes: int | None = None
    prep_time_raw: str | None = None
    difficulty: str | None = None
    cost_label: str | None = None
    servings: int | None = None
    description: str | None = None
    ingredients: list[str] = field(default_factory=list)
    utensils: list[str] = field(default_factory=list)
    preparation_steps: list[str] = field(default_factory=list)
    related_categories: list[RelatedCategory] = field(default_factory=list)
    retrieved_at: str = ""
    parser_version: str = ""
    issues: list[str] = field(default_factory=list)

