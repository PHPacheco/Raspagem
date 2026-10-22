from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.linguistic_analysis import (
    analyze_sentiment,
    extract_domain_entities,
    latest_linguistic_analysis,
    run_linguistic_analysis,
    shallow_dependency_parse,
)
from scraper.models import RecipeData


def test_shallow_parser_identifies_action_and_object() -> None:
    dependencies = shallow_dependency_parse("Adicione a cebola na panela")
    root = next(item for item in dependencies if item.relation == "root")
    obj = next(item for item in dependencies if item.relation == "obj")

    assert root.lemma == "adicionar"
    assert obj.lemma == "cebola"
    assert obj.head_index == root.token_index


def test_sentiment_handles_negation_intensity_and_aspects() -> None:
    positive = analyze_sentiment("O preparo foi muito fácil e delicioso")
    negated = analyze_sentiment("O resultado não ficou ruim")

    assert positive["polarity"] == "positivo"
    assert positive["score"] > 0
    assert {item["aspect"] for item in positive["aspects"]} >= {"preparo", "sabor"}
    assert negated["polarity"] == "positivo"
    assert negated["evidence"][0]["negated"] is True


def test_domain_ner_extracts_ingredient_quantity_unit_duration_and_temperature() -> None:
    ingredient = extract_domain_entities("ingredient", "200 g de cebola picada")
    step = extract_domain_entities("preparation_step", "Asse por 30 minutos a 180 °C")

    assert {item.entity_type for item in ingredient} >= {"INGREDIENT", "QUANTITY", "UNIT"}
    assert next(item for item in ingredient if item.entity_type == "INGREDIENT").normalized_value == "cebola"
    assert {item.entity_type for item in step} >= {"DURATION", "TEMPERATURE"}


def test_linguistic_pipeline_persists_dependencies_sentiments_entities_and_relations(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "recipes.sqlite")
    initialize_database(connection)
    save_recipe(
        connection,
        RecipeData(
            site_recipe_id="1",
            title="Cebola assada",
            url="https://example.test/receita/1.html",
            description="Receita fácil e deliciosa",
            ingredients=["200 g de cebola"],
            utensils=["assadeira"],
            preparation_steps=["Adicione a cebola na assadeira", "Asse por 30 minutos a 180 °C"],
            retrieved_at="2026-10-22T12:00:00+00:00",
            parser_version="test",
        ),
    )

    run_id = run_linguistic_analysis(connection)
    latest = latest_linguistic_analysis(connection)

    assert latest is not None
    assert latest["run"]["id"] == run_id
    assert latest["run"]["dependency_count"] > 0
    assert latest["run"]["sentiment_count"] > 0
    assert latest["run"]["entity_count"] > 0
    assert latest["run"]["relation_count"] > 0
    assert any(item["entity_type"] == "INGREDIENT" for item in latest["entities"])
    assert any(item["relation"] == "tem_ingrediente" for item in latest["relations"])
