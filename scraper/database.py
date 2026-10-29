from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import PARSER_VERSION, USER_AGENT
from .models import RecipeData, RecipeLink, RelatedCategory
from .text_utils import (
    canonical_url,
    clean_text,
    normalize_cost_label,
    normalize_difficulty,
    normalize_text,
    prepare_text,
    search_index_text,
    search_terms,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _apply_schema_migrations(connection)
    connection.commit()


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _apply_schema_migrations(connection: sqlite3.Connection) -> None:
    if "z" not in _column_names(connection, "document_vectors"):
        connection.execute("ALTER TABLE document_vectors ADD COLUMN z REAL NOT NULL DEFAULT 0")
    analysis_columns = _column_names(connection, "text_analysis_runs")
    if "clustering_method" not in analysis_columns:
        connection.execute(
            "ALTER TABLE text_analysis_runs ADD COLUMN clustering_method TEXT NOT NULL DEFAULT 'legacy'"
        )
    if "silhouette_score" not in analysis_columns:
        connection.execute("ALTER TABLE text_analysis_runs ADD COLUMN silhouette_score REAL")
    recipe_columns = _column_names(connection, "recipes")
    if "origin_category" not in recipe_columns:
        connection.execute("ALTER TABLE recipes ADD COLUMN origin_category TEXT")
    if "content_fingerprint" not in recipe_columns:
        connection.execute(
            "ALTER TABLE recipes ADD COLUMN content_fingerprint TEXT NOT NULL DEFAULT ''"
        )
    if "duplicate_of_recipe_id" not in recipe_columns:
        connection.execute(
            "ALTER TABLE recipes ADD COLUMN duplicate_of_recipe_id TEXT "
            "REFERENCES recipes(site_recipe_id) ON DELETE SET NULL"
        )
    if "duplicate_similarity" not in recipe_columns:
        connection.execute("ALTER TABLE recipes ADD COLUMN duplicate_similarity REAL")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_recipes_content_fingerprint "
        "ON recipes(content_fingerprint)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_recipes_duplicate_of ON recipes(duplicate_of_recipe_id)"
    )


def create_scrape_run(
    connection: sqlite3.Connection,
    *,
    category_url: str,
    max_pages: int,
    user_agent: str = USER_AGENT,
    parser_version: str = PARSER_VERSION,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO scrape_runs
            (category_url, max_pages, user_agent, parser_version, started_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (category_url, max_pages, user_agent, parser_version, utc_now()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_scrape_run(
    connection: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    listing_count: int,
    recipe_count: int,
    error_count: int,
) -> None:
    connection.execute(
        """
        UPDATE scrape_runs
        SET finished_at = ?, status = ?, listing_count = ?,
            recipe_count = ?, error_count = ?
        WHERE id = ?
        """,
        (utc_now(), status, listing_count, recipe_count, error_count, run_id),
    )
    connection.commit()


def _upsert_category(
    connection: sqlite3.Connection,
    *,
    site_category_id: str,
    name: str,
    url: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO categories(site_category_id, name, url)
        VALUES (?, ?, ?)
        ON CONFLICT(site_category_id) DO UPDATE SET
            name = excluded.name,
            url = COALESCE(excluded.url, categories.url)
        """,
        (site_category_id, clean_text(name), canonical_url(url) if url else None),
    )


def save_listing(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    category_id: str,
    category_name: str,
    category_url: str,
    recipe_link: RecipeLink,
) -> None:
    _upsert_category(
        connection,
        site_category_id=category_id,
        name=category_name,
        url=category_url,
    )
    recipe_id = recipe_link.site_recipe_id or recipe_link.url
    connection.execute(
        """
        INSERT INTO category_listings
            (run_id, category_id, recipe_id, recipe_url, listed_title, page_number, position)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, category_id, page_number, recipe_id) DO UPDATE SET
            recipe_url = excluded.recipe_url,
            listed_title = excluded.listed_title,
            position = excluded.position
        """,
        (
            run_id,
            category_id,
            recipe_id,
            canonical_url(recipe_link.url),
            clean_text(recipe_link.title),
            recipe_link.page_number,
            recipe_link.position,
        ),
    )


def _category_key(category: RelatedCategory) -> str:
    return category.site_category_id or f"name:{normalize_text(category.name)}"


def _search_text(recipe: RecipeData) -> str:
    values: list[str] = [recipe.title, recipe.description or "", recipe.origin_category or ""]
    values.extend(recipe.ingredients)
    values.extend(recipe.utensils)
    values.extend(recipe.preparation_steps)
    values.extend(category.name for category in recipe.related_categories)
    return search_index_text(values)


def _normalized_recipe(recipe: RecipeData) -> RecipeData:
    return replace(
        recipe,
        title=clean_text(recipe.title),
        url=canonical_url(recipe.url),
        prep_time_raw=clean_text(recipe.prep_time_raw) or None,
        difficulty=normalize_difficulty(recipe.difficulty) or None,
        cost_label=normalize_cost_label(recipe.cost_label) or None,
        description=clean_text(recipe.description) or None,
        origin_category=clean_text(recipe.origin_category) or None,
        ingredients=[value for item in recipe.ingredients if (value := clean_text(item))],
        utensils=[value for item in recipe.utensils if (value := clean_text(item))],
        preparation_steps=[
            value for item in recipe.preparation_steps if (value := clean_text(item))
        ],
        related_categories=[
            RelatedCategory(
                site_category_id=category.site_category_id,
                name=clean_text(category.name),
                url=canonical_url(category.url) if category.url else None,
            )
            for category in recipe.related_categories
            if clean_text(category.name)
        ],
    )


def _database_text_units(connection: sqlite3.Connection, recipe_id: str) -> Iterable[tuple[str, int, str]]:
    recipe = connection.execute(
        "SELECT title, description FROM recipes WHERE site_recipe_id = ?", (recipe_id,)
    ).fetchone()
    if recipe is None:
        return
    yield "title", 0, recipe["title"]
    if recipe["description"]:
        yield "description", 0, recipe["description"]
    for row in connection.execute(
        "SELECT position, raw_text FROM ingredients WHERE recipe_id = ? ORDER BY position", (recipe_id,)
    ):
        yield "ingredient", int(row["position"]), row["raw_text"]
    for row in connection.execute(
        "SELECT position, name FROM utensils WHERE recipe_id = ? ORDER BY position", (recipe_id,)
    ):
        yield "utensil", int(row["position"]), row["name"]
    for row in connection.execute(
        "SELECT position, raw_text FROM preparation_steps WHERE recipe_id = ? ORDER BY position", (recipe_id,)
    ):
        yield "preparation_step", int(row["position"]), row["raw_text"]
    for position, row in enumerate(
        connection.execute(
            """
            SELECT c.name, rc.relation_type
            FROM recipe_categories rc
            JOIN categories c ON c.site_category_id = rc.category_id
            WHERE rc.recipe_id = ?
            ORDER BY c.name COLLATE NOCASE
            """,
            (recipe_id,),
        ),
        1,
    ):
        field_name = "origin_category" if row["relation_type"] == "origin" else "related_category"
        yield field_name, position, row["name"]


def _database_search_values(connection: sqlite3.Connection, recipe_id: str) -> list[str]:
    recipe = connection.execute(
        "SELECT title, description, origin_category FROM recipes WHERE site_recipe_id = ?", (recipe_id,)
    ).fetchone()
    if recipe is None:
        return []
    values = [recipe["title"], recipe["description"] or "", recipe["origin_category"] or ""]
    for table, column in (
        ("ingredients", "raw_text"),
        ("utensils", "name"),
        ("preparation_steps", "raw_text"),
    ):
        values.extend(
            row[column]
            for row in connection.execute(
                f"SELECT {column} FROM {table} WHERE recipe_id = ? ORDER BY position",
                (recipe_id,),
            )
        )
    values.extend(
        row["name"]
        for row in connection.execute(
            """
            SELECT c.name
            FROM recipe_categories rc
            JOIN categories c ON c.site_category_id = rc.category_id
            WHERE rc.recipe_id = ?
            ORDER BY c.name COLLATE NOCASE
            """,
            (recipe_id,),
        )
    )
    return values


def backfill_origin_categories(connection: sqlite3.Connection) -> int:
    """Turn each collected origin label into a queryable category relationship."""
    category_ids = {
        normalize_text(row["name"]): row["site_category_id"]
        for row in connection.execute("SELECT site_category_id, name FROM categories")
    }
    inserted = 0
    for row in connection.execute(
        """
        SELECT site_recipe_id, origin_category
        FROM recipes
        WHERE NULLIF(TRIM(origin_category), '') IS NOT NULL
        ORDER BY site_recipe_id
        """
    ).fetchall():
        category_name = clean_text(row["origin_category"])
        normalized_name = normalize_text(category_name)
        category_id = category_ids.get(normalized_name)
        if category_id is None:
            slug = normalized_name.replace(" ", "-") or "sem-nome"
            category_id = f"origin:{slug}"
            _upsert_category(
                connection,
                site_category_id=category_id,
                name=category_name,
                url=None,
            )
            category_ids[normalized_name] = category_id
        cursor = connection.execute(
            """
            INSERT INTO recipe_categories(recipe_id, category_id, relation_type)
            SELECT ?, ?, 'origin'
            WHERE NOT EXISTS (
                SELECT 1 FROM recipe_categories
                WHERE recipe_id = ? AND category_id = ?
            )
            """,
            (row["site_recipe_id"], category_id, row["site_recipe_id"], category_id),
        )
        inserted += max(0, cursor.rowcount)
    return inserted


def normalize_stored_data(connection: sqlite3.Connection) -> int:
    """Apply the current cleanup rules to data collected by older pipeline versions."""
    changes = 0
    specifications = (
        ("recipes", "site_recipe_id", "title", clean_text, False),
        ("recipes", "site_recipe_id", "prep_time_raw", clean_text, True),
        ("recipes", "site_recipe_id", "difficulty", normalize_difficulty, True),
        ("recipes", "site_recipe_id", "cost_label", normalize_cost_label, True),
        ("recipes", "site_recipe_id", "description", clean_text, True),
        ("recipes", "site_recipe_id", "origin_category", clean_text, True),
        ("ingredients", "id", "raw_text", clean_text, False),
        ("utensils", "id", "name", clean_text, False),
        ("preparation_steps", "id", "raw_text", clean_text, False),
        ("categories", "site_category_id", "name", clean_text, False),
        ("category_listings", "id", "listed_title", clean_text, False),
    )
    for table, key_column, value_column, normalizer, nullable in specifications:
        rows = connection.execute(
            f"SELECT {key_column} AS row_key, {value_column} AS value FROM {table}"
        ).fetchall()
        updates = []
        for row in rows:
            normalized = normalizer(row["value"])
            if nullable and not normalized:
                normalized = None
            if normalized != row["value"]:
                updates.append((normalized, row["row_key"]))
        connection.executemany(
            f"UPDATE {table} SET {value_column} = ? WHERE {key_column} = ?",
            updates,
        )
        changes += len(updates)

    backfill_origin_categories(connection)
    recipe_ids = [
        row["site_recipe_id"]
        for row in connection.execute("SELECT site_recipe_id FROM recipes ORDER BY site_recipe_id")
    ]
    connection.executemany(
        "UPDATE recipes SET search_text = ? WHERE site_recipe_id = ?",
        (
            (search_index_text(_database_search_values(connection, recipe_id)), recipe_id)
            for recipe_id in recipe_ids
        ),
    )
    rebuild_recipe_deduplication(connection)
    return changes


def _deduplication_sort_key(recipe_id: str) -> tuple[int, int | str]:
    return (0, int(recipe_id)) if recipe_id.isdigit() else (1, recipe_id)


def _recipe_content_fingerprint(connection: sqlite3.Connection, recipe_id: str) -> str:
    recipe = connection.execute(
        "SELECT title, description FROM recipes WHERE site_recipe_id = ?", (recipe_id,)
    ).fetchone()
    if recipe is None:
        return ""
    ingredients = [
        row["raw_text"]
        for row in connection.execute(
            "SELECT raw_text FROM ingredients WHERE recipe_id = ? ORDER BY position", (recipe_id,)
        )
    ]
    steps = [
        row["raw_text"]
        for row in connection.execute(
            "SELECT raw_text FROM preparation_steps WHERE recipe_id = ? ORDER BY position", (recipe_id,)
        )
    ]
    content = [recipe["title"], *ingredients, *steps]
    if not ingredients and not steps and recipe["description"]:
        content.append(recipe["description"])
    if len(content) == 1:
        return ""
    return prepare_text("\n".join(content)).duplicate_key


def rebuild_recipe_deduplication(connection: sqlite3.Connection) -> dict[str, int]:
    """Mark only exact content copies; equal titles alone remain independent recipes."""
    recipe_ids = [
        row["site_recipe_id"]
        for row in connection.execute("SELECT site_recipe_id FROM recipes ORDER BY site_recipe_id")
    ]
    fingerprints = {
        recipe_id: _recipe_content_fingerprint(connection, recipe_id)
        for recipe_id in recipe_ids
    }
    connection.execute(
        "UPDATE recipes SET content_fingerprint = '', duplicate_of_recipe_id = NULL, "
        "duplicate_similarity = NULL"
    )
    connection.executemany(
        "UPDATE recipes SET content_fingerprint = ? WHERE site_recipe_id = ?",
        ((fingerprint, recipe_id) for recipe_id, fingerprint in fingerprints.items()),
    )
    groups: dict[str, list[str]] = {}
    for recipe_id, fingerprint in fingerprints.items():
        if fingerprint:
            groups.setdefault(fingerprint, []).append(recipe_id)
    duplicate_count = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=_deduplication_sort_key)
        canonical = ordered[0]
        connection.executemany(
            "UPDATE recipes SET duplicate_of_recipe_id = ?, duplicate_similarity = 1.0 "
            "WHERE site_recipe_id = ?",
            ((canonical, duplicate) for duplicate in ordered[1:]),
        )
        duplicate_count += len(ordered) - 1
    title_collision_count = int(
        connection.execute(
            """
            SELECT COUNT(*) AS count FROM (
                SELECT title
                FROM recipes
                GROUP BY title COLLATE NOCASE
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()["count"]
    )
    return {
        "recipes": len(recipe_ids),
        "exact_duplicates": duplicate_count,
        "distinct_same_title_groups": title_collision_count,
    }


def _save_prepared_texts(
    connection: sqlite3.Connection,
    recipe_id: str,
    units: Iterable[tuple[str, int, str]],
    *,
    prepared_at: str | None = None,
) -> int:
    timestamp = prepared_at or utc_now()
    rows = []
    for field_name, position, raw_text in units:
        prepared = prepare_text(raw_text)
        rows.append(
            (
                recipe_id,
                field_name,
                position,
                prepared.raw_text,
                prepared.clean_text,
                prepared.normalized_text,
                json.dumps(prepared.tokens, ensure_ascii=False),
                json.dumps(prepared.content_tokens, ensure_ascii=False),
                json.dumps(prepared.stemmed_tokens, ensure_ascii=False),
                json.dumps(prepared.lemma_tokens, ensure_ascii=False),
                prepared.duplicate_key,
                prepared.near_duplicate_key,
                prepared.pipeline_version,
                json.dumps(prepared.transformations, ensure_ascii=False),
                timestamp,
            )
        )
    connection.execute("DELETE FROM text_preparations WHERE recipe_id = ?", (recipe_id,))
    connection.executemany(
        """
        INSERT INTO text_preparations
            (recipe_id, field_name, position, raw_text, clean_text, normalized_text,
             tokens_json, content_tokens_json, stemmed_tokens_json, lemma_tokens_json,
             duplicate_key, near_duplicate_key, pipeline_version, transformations_json,
             prepared_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def save_recipe(connection: sqlite3.Connection, recipe: RecipeData) -> None:
    recipe = _normalized_recipe(recipe)
    connection.execute(
        """
        INSERT INTO recipes
            (site_recipe_id, title, url, rating_value, ratings_count,
             prep_time_minutes, prep_time_raw, difficulty, cost_label,
             servings, description, origin_category, search_text, retrieved_at, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site_recipe_id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            rating_value = excluded.rating_value,
            ratings_count = excluded.ratings_count,
            prep_time_minutes = excluded.prep_time_minutes,
            prep_time_raw = excluded.prep_time_raw,
            difficulty = excluded.difficulty,
            cost_label = excluded.cost_label,
            servings = excluded.servings,
            description = excluded.description,
            origin_category = COALESCE(excluded.origin_category, recipes.origin_category),
            search_text = excluded.search_text,
            retrieved_at = excluded.retrieved_at,
            parser_version = excluded.parser_version
        """,
        (
            recipe.site_recipe_id,
            recipe.title,
            recipe.url,
            recipe.rating_value,
            recipe.ratings_count,
            recipe.prep_time_minutes,
            recipe.prep_time_raw,
            recipe.difficulty,
            recipe.cost_label,
            recipe.servings,
            recipe.description,
            recipe.origin_category,
            _search_text(recipe),
            recipe.retrieved_at,
            recipe.parser_version,
        ),
    )

    for table in ("ingredients", "utensils", "preparation_steps", "recipe_categories"):
        connection.execute(f"DELETE FROM {table} WHERE recipe_id = ?", (recipe.site_recipe_id,))

    connection.executemany(
        "INSERT INTO ingredients(recipe_id, position, raw_text) VALUES (?, ?, ?)",
        ((recipe.site_recipe_id, position, value) for position, value in enumerate(recipe.ingredients, 1)),
    )
    connection.executemany(
        "INSERT INTO utensils(recipe_id, position, name) VALUES (?, ?, ?)",
        ((recipe.site_recipe_id, position, value) for position, value in enumerate(recipe.utensils, 1)),
    )
    connection.executemany(
        "INSERT INTO preparation_steps(recipe_id, position, raw_text) VALUES (?, ?, ?)",
        ((recipe.site_recipe_id, position, value) for position, value in enumerate(recipe.preparation_steps, 1)),
    )
    for category in recipe.related_categories:
        category_id = _category_key(category)
        _upsert_category(
            connection,
            site_category_id=category_id,
            name=category.name,
            url=category.url,
        )
        connection.execute(
            """
            INSERT INTO recipe_categories(recipe_id, category_id, relation_type)
            VALUES (?, ?, 'related')
            """,
            (recipe.site_recipe_id, category_id),
        )
    backfill_origin_categories(connection)
    connection.execute(
        "UPDATE recipes SET search_text = ? WHERE site_recipe_id = ?",
        (
            search_index_text(_database_search_values(connection, recipe.site_recipe_id)),
            recipe.site_recipe_id,
        ),
    )
    _save_prepared_texts(
        connection,
        recipe.site_recipe_id,
        _database_text_units(connection, recipe.site_recipe_id),
        prepared_at=recipe.retrieved_at,
    )
    rebuild_recipe_deduplication(connection)
    connection.commit()


def rebuild_text_preparations(connection: sqlite3.Connection) -> int:
    normalize_stored_data(connection)
    total = 0
    recipe_ids = [
        row["site_recipe_id"]
        for row in connection.execute("SELECT site_recipe_id FROM recipes ORDER BY site_recipe_id")
    ]
    for recipe_id in recipe_ids:
        total += _save_prepared_texts(connection, recipe_id, _database_text_units(connection, recipe_id))
    connection.commit()
    return total


def recipe_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM recipes").fetchone()
    return int(row["count"])


def listing_count(connection: sqlite3.Connection, run_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM category_listings WHERE run_id = ?", (run_id,)
    ).fetchone()
    return int(row["count"])


def query_recipes(
    connection: sqlite3.Connection,
    *,
    search: str = "",
    difficulty: str = "",
    cost_label: str = "",
    max_time: int | None = None,
    min_rating: float | None = None,
    category_id: str = "",
) -> list[sqlite3.Row]:
    clauses = ["1 = 1"]
    parameters: list[Any] = []
    if search.strip():
        terms = search_terms(search)
        for term in terms:
            clauses.append("r.search_text LIKE ? ESCAPE '\\'")
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.append(f"%{escaped}%")
    difficulty_value = difficulty.strip()
    if difficulty_value:
        clauses.append("TRIM(r.difficulty) = TRIM(?) COLLATE NOCASE")
        parameters.append(difficulty_value)
    cost_value = cost_label.strip()
    if cost_value:
        clauses.append("TRIM(r.cost_label) = TRIM(?) COLLATE NOCASE")
        parameters.append(cost_value)
    if max_time is not None:
        clauses.append("r.prep_time_minutes <= ?")
        parameters.append(max_time)
    if min_rating is not None:
        clauses.append("r.rating_value >= ?")
        parameters.append(min_rating)
    category_value = category_id.strip()
    if category_value:
        clauses.append(
            "(EXISTS (SELECT 1 FROM recipe_categories rc_filter "
            "WHERE rc_filter.recipe_id = r.site_recipe_id AND rc_filter.category_id = ?) "
            "OR EXISTS (SELECT 1 FROM category_listings cl_filter "
            "WHERE (cl_filter.recipe_id = r.site_recipe_id OR cl_filter.recipe_id = r.url) "
            "AND cl_filter.category_id = ?))"
        )
        parameters.extend((category_value, category_value))
    query = f"""
        SELECT r.*
        FROM recipes r
        WHERE {' AND '.join(clauses)}
        ORDER BY r.rating_value IS NULL, r.rating_value DESC,
                 r.ratings_count IS NULL, r.ratings_count DESC, r.title COLLATE NOCASE
    """
    return list(connection.execute(query, parameters).fetchall())


def recipe_details(connection: sqlite3.Connection, recipe_id: str) -> dict[str, Any] | None:
    recipe = connection.execute(
        "SELECT * FROM recipes WHERE site_recipe_id = ?", (recipe_id,)
    ).fetchone()
    if recipe is None:
        return None
    details: dict[str, Any] = dict(recipe)
    details["ingredients"] = [
        row["raw_text"]
        for row in connection.execute(
            "SELECT raw_text FROM ingredients WHERE recipe_id = ? ORDER BY position", (recipe_id,)
        )
    ]
    details["utensils"] = [
        row["name"]
        for row in connection.execute(
            "SELECT name FROM utensils WHERE recipe_id = ? ORDER BY position", (recipe_id,)
        )
    ]
    details["preparation_steps"] = [
        row["raw_text"]
        for row in connection.execute(
            "SELECT raw_text FROM preparation_steps WHERE recipe_id = ? ORDER BY position", (recipe_id,)
        )
    ]
    details["related_categories"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT c.site_category_id, c.name, c.url
            FROM recipe_categories rc
            JOIN categories c ON c.site_category_id = rc.category_id
            WHERE rc.recipe_id = ?
            ORDER BY c.name COLLATE NOCASE
            """,
            (recipe_id,),
        )
    ]
    details["prepared_texts"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT field_name, position, raw_text, clean_text, normalized_text,
                   tokens_json, content_tokens_json, stemmed_tokens_json,
                   lemma_tokens_json, duplicate_key, near_duplicate_key,
                   pipeline_version, transformations_json, prepared_at
            FROM text_preparations
            WHERE recipe_id = ?
            ORDER BY field_name, position
            """,
            (recipe_id,),
        )
    ]
    return details


def distinct_filter_values(connection: sqlite3.Connection) -> dict[str, Any]:
    difficulties = [
        row["value"]
        for row in connection.execute(
            "SELECT DISTINCT TRIM(difficulty) AS value "
            "FROM recipes WHERE NULLIF(TRIM(difficulty), '') IS NOT NULL ORDER BY value COLLATE NOCASE"
        )
    ]
    costs = [
        row["value"]
        for row in connection.execute(
            "SELECT DISTINCT TRIM(cost_label) AS value "
            "FROM recipes WHERE NULLIF(TRIM(cost_label), '') IS NOT NULL ORDER BY value COLLATE NOCASE"
        )
    ]
    categories = [
        dict(row)
        for row in connection.execute(
            """
            SELECT c.site_category_id, c.name
            FROM categories c
            WHERE NULLIF(TRIM(c.name), '') IS NOT NULL
            AND (EXISTS (
                SELECT 1
                FROM recipe_categories rc
                JOIN recipes r_related ON r_related.site_recipe_id = rc.recipe_id
                WHERE rc.category_id = c.site_category_id
            )
            OR EXISTS (
                SELECT 1
                FROM category_listings cl
                JOIN recipes r_listed
                  ON cl.recipe_id = r_listed.site_recipe_id
                  OR cl.recipe_id = r_listed.url
                WHERE cl.category_id = c.site_category_id
            ))
            ORDER BY c.name COLLATE NOCASE, c.site_category_id
            """
        )
    ]
    return {"difficulties": difficulties, "costs": costs, "categories": categories}

