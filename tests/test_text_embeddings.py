from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.models import RecipeData
from scraper.text_analysis import TextDocument
from scraper.text_embeddings import build_embedding_model, latest_embedding_analysis, run_embedding_analysis


def _recipe(recipe_id: str, title: str, description: str) -> RecipeData:
    return RecipeData(
        site_recipe_id=recipe_id,
        title=title,
        url=f"https://example.test/receita/{recipe_id}.html",
        description=description,
        retrieved_at="2026-10-08T12:00:00+00:00",
        parser_version="test",
    )


def test_embedding_model_creates_dense_word_and_document_vectors() -> None:
    model = build_embedding_model(
        [
            TextDocument("1", "Bolo", ["bolo", "chocolate", "sobremesa", "bolo"]),
            TextDocument("2", "Frango", ["frango", "alho", "salgado", "frango"]),
        ],
        dimension=12,
        window_size=2,
    )

    assert model.dimension == 12
    assert len(model.word_vectors["bolo"]) == 12
    assert len(model.document_vectors["1"]) == 12
    assert model.top_contexts["bolo"]


def test_embedding_analysis_persists_stage_7_outputs(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Bolo de chocolate", "Receita de bolo com chocolate e sobremesa"))
    save_recipe(connection, _recipe("2", "Bolo de cacau", "Receita de bolo com cacau e sobremesa"))
    save_recipe(connection, _recipe("3", "Frango com alho", "Receita salgada de frango com alho"))

    run_id = run_embedding_analysis(connection, dimension=16, window_size=2, neighbor_count=2)

    run = connection.execute("SELECT * FROM embedding_runs WHERE id = ?", (run_id,)).fetchone()
    word_count = connection.execute("SELECT COUNT(*) AS count FROM word_embeddings WHERE run_id = ?", (run_id,)).fetchone()
    document_count = connection.execute("SELECT COUNT(*) AS count FROM document_embeddings WHERE run_id = ?", (run_id,)).fetchone()
    similarities = connection.execute(
        "SELECT * FROM embedding_similarities WHERE run_id = ? ORDER BY recipe_id, rank", (run_id,)
    ).fetchall()
    latest = latest_embedding_analysis(connection)

    assert run["model_version"] == "pln-aula-7-distributional-v1"
    assert run["dimension"] == 16
    assert word_count["count"] > 0
    assert document_count["count"] == 3
    assert len(similarities) == 6
    assert latest is not None
    assert latest["run"]["id"] == run_id
    assert len(latest["documents"]) == 3
