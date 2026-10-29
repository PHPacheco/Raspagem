from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.models import RecipeData
from scraper.text_classification import (
    LabeledDocument,
    evaluate_predictions,
    latest_text_classification,
    predict_tokens,
    run_text_classification,
    stratified_split,
    train_naive_bayes,
)


def _labeled(recipe_id: str, label: str, tokens: list[str]) -> LabeledDocument:
    return LabeledDocument(recipe_id, f"Receita {recipe_id}", tokens, label)


def _recipe(recipe_id: str, difficulty: str, description: str) -> RecipeData:
    return RecipeData(
        site_recipe_id=recipe_id,
        title=f"Receita {recipe_id}",
        url=f"https://example.test/receita/{recipe_id}.html",
        difficulty=difficulty,
        description=description,
        retrieved_at="2026-10-22T12:00:00+00:00",
        parser_version="test",
    )


def test_naive_bayes_learns_classes_and_probabilities() -> None:
    documents = [
        _labeled("1", "Fácil", ["rapido", "simples", "misturar"]),
        _labeled("2", "Fácil", ["facil", "rapido", "assar"]),
        _labeled("3", "Difícil", ["complexo", "demorado", "tecnica"]),
        _labeled("4", "Difícil", ["tecnica", "avancado", "demorado"]),
    ]
    model = train_naive_bayes(documents)
    label, probabilities = predict_tokens(model, ["rapido", "simples"])

    assert label == "Fácil"
    assert set(probabilities) == {"Difícil", "Fácil"}
    assert abs(sum(probabilities.values()) - 1.0) < 0.000001


def test_stratified_split_keeps_each_class_in_training() -> None:
    documents = [
        _labeled(str(index), label, [label.lower()])
        for label in ("Fácil", "Difícil")
        for index in range(1 if label == "Fácil" else 10, 5 if label == "Fácil" else 14)
    ]
    train, test = stratified_split(documents, test_ratio=0.25)

    assert {document.label for document in train} == {"Fácil", "Difícil"}
    assert {document.label for document in test} == {"Fácil", "Difícil"}
    assert len(train) + len(test) == len(documents)


def test_metrics_include_confusion_precision_recall_and_f1() -> None:
    result = evaluate_predictions(
        ["positivo", "positivo", "negativo", "negativo"],
        ["positivo", "negativo", "negativo", "negativo"],
    )

    assert result["accuracy"] == 0.75
    assert result["confusion"]["positivo"]["negativo"] == 1
    assert all({"precision", "recall", "f1", "support"} <= item.keys() for item in result["metrics"])


def test_classification_run_persists_predictions_and_warns_about_small_data(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Fácil", "receita simples rápida misturar"))
    save_recipe(connection, _recipe("2", "Fácil", "preparo fácil rápido assar"))
    save_recipe(connection, _recipe("3", "Difícil", "técnica complexa e demorada"))
    save_recipe(connection, _recipe("4", "Difícil", "preparo avançado com técnica"))

    run_id = run_text_classification(connection, target_field="difficulty", test_ratio=0.5)
    latest = latest_text_classification(connection)

    assert latest is not None
    assert latest["run"]["id"] == run_id
    assert latest["run"]["status"] == "evaluated"
    assert latest["run"]["class_count"] == 2
    assert len(latest["predictions"]) == 4
    assert len(latest["metrics"]) == 2


def test_single_class_is_recorded_without_fake_evaluation(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Fácil", "receita simples"))

    run_id = run_text_classification(connection, target_field="difficulty")
    run = connection.execute("SELECT * FROM classification_runs WHERE id = ?", (run_id,)).fetchone()

    assert run["status"] == "insufficient_classes"
    assert run["accuracy"] is None
    assert run["test_count"] == 0


def test_difficulty_labels_differing_only_by_case_are_one_class(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Fácil", "receita simples"))
    save_recipe(connection, _recipe("2", "fácil", "receita rápida"))

    run_id = run_text_classification(connection, target_field="difficulty", test_ratio=0.5)
    run = connection.execute("SELECT * FROM classification_runs WHERE id = ?", (run_id,)).fetchone()
    labels = {
        row["actual_label"]
        for row in connection.execute(
            "SELECT actual_label FROM classification_predictions WHERE run_id = ?", (run_id,)
        )
    }

    assert run["class_count"] == 1
    assert run["status"] == "insufficient_classes"
    assert labels == {"fácil"}
