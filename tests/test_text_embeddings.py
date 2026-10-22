from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.models import RecipeData
from scraper.text_analysis import TextDocument
from scraper.text_embeddings import (
    build_embedding_model,
    contextual_similarity,
    contextualize_tokens,
    embed_text,
    latest_embedding_analysis,
    load_latest_embedding_model,
    run_embedding_analysis,
    semantic_search,
)


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

    restored = load_latest_embedding_model(connection)
    assert restored is not None
    assert restored.dimension == 16
    assert restored.document_vectors.keys() == model_document_ids(connection, run_id)


def model_document_ids(connection, run_id: int) -> set[str]:
    return {
        row["recipe_id"]
        for row in connection.execute(
            "SELECT recipe_id FROM document_embeddings WHERE run_id = ?",
            (run_id,),
        )
    }


def test_semantic_search_embeds_a_query_in_the_learned_space() -> None:
    model = build_embedding_model(
        [
            TextDocument("1", "Bolo", ["bolo", "chocolate", "sobremesa", "cacau"]),
            TextDocument("2", "Frango", ["frango", "alho", "salgado", "cebola"]),
        ],
        dimension=12,
        window_size=2,
    )

    vector, matched = embed_text("sobremesa com chocolate", model)
    results = semantic_search(model, "sobremesa com chocolate", limit=2)

    assert matched == ["sobremesa", "chocolate"]
    assert len(vector) == 12
    assert results[0]["recipe_id"] == "1"
    assert semantic_search(model, "palavra completamente desconhecida") == []


def test_contextual_vectors_change_with_the_local_neighborhood() -> None:
    model = build_embedding_model(
        [
            TextDocument("1", "Cozinha", ["banco", "massa", "madeira", "banco"]),
            TextDocument("2", "Finanças", ["banco", "credito", "juros", "banco"]),
        ],
        dimension=10,
        window_size=1,
    )
    tokens = ["massa", "banco", "madeira", "credito", "banco", "juros"]
    occurrences = contextualize_tokens(tokens, model, window_size=1)
    first_bank = occurrences[1]
    second_bank = occurrences[4]

    assert first_bank.token == second_bank.token == "banco"
    assert first_bank.context != second_bank.context
    assert contextual_similarity(first_bank, second_bank) < 1.0
