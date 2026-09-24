from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.models import RecipeData
from scraper.text_analysis import (
    build_tfidf_model,
    cosine_similarity,
    latest_text_analysis,
    run_text_analysis,
    TextDocument,
)


def _recipe(recipe_id: str, title: str, description: str) -> RecipeData:
    return RecipeData(
        site_recipe_id=recipe_id,
        title=title,
        url=f"https://example.test/receita/{recipe_id}.html",
        description=description,
        retrieved_at="2026-09-24T12:00:00+00:00",
        parser_version="test",
    )


def test_cosine_similarity_uses_vector_direction() -> None:
    assert abs(cosine_similarity([1.0, 1.0], [2.0, 2.0]) - 1.0) < 0.000001
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_text_analysis_pipeline_persists_vectors_similarity_clusters_and_projection(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Bolo de chocolate", "Receita de bolo com chocolate e sobremesa"))
    save_recipe(connection, _recipe("2", "Bolo de cacau", "Receita de bolo com cacau e sobremesa"))
    save_recipe(connection, _recipe("3", "Frango com alho", "Receita salgada de frango com alho"))

    run_id = run_text_analysis(connection, cluster_count=2, neighbor_count=2)

    run = connection.execute("SELECT * FROM text_analysis_runs WHERE id = ?", (run_id,)).fetchone()
    vectors = connection.execute("SELECT * FROM document_vectors WHERE run_id = ?", (run_id,)).fetchall()
    weights = connection.execute("SELECT * FROM document_term_weights WHERE run_id = ?", (run_id,)).fetchall()
    similarities = connection.execute(
        "SELECT * FROM document_similarities WHERE run_id = ? ORDER BY recipe_id, rank", (run_id,)
    ).fetchall()
    nearest_to_first = [row for row in similarities if row["recipe_id"] == "1"][0]
    latest = latest_text_analysis(connection)

    assert run["document_count"] == 3
    assert run["vocabulary_size"] >= 6
    assert len(vectors) == 3
    assert len(weights) > 0
    assert len(similarities) == 6
    assert nearest_to_first["neighbor_recipe_id"] == "2"
    assert nearest_to_first["cosine_similarity"] > 0
    assert latest is not None
    assert latest["run"]["id"] == run_id
    assert len(latest["documents"]) == 3


def test_tfidf_model_gives_weight_to_terms_that_do_not_appear_in_every_document() -> None:
    model = build_tfidf_model(
        [
            TextDocument("1", "Doc 1", ["bolo", "chocolate"]),
            TextDocument("2", "Doc 2", ["bolo", "cacau"]),
            TextDocument("3", "Doc 3", ["frango", "alho"]),
        ]
    )

    chocolate_index = model.vocabulary.index("chocolate")
    assert model.vectors["1"][chocolate_index] > 0
