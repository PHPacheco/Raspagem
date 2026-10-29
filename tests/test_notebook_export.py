import json
from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.models import RecipeData
from scraper.notebook_export import _details_html, export_analysis_notebook
from scraper.linguistic_analysis import run_linguistic_analysis
from scraper.text_analysis import run_text_analysis
from scraper.text_classification import run_text_classification
from scraper.text_embeddings import run_embedding_analysis


def _recipe(recipe_id: str, title: str, description: str, difficulty: str) -> RecipeData:
    return RecipeData(
        site_recipe_id=recipe_id,
        title=title,
        url=f"https://example.test/receita/{recipe_id}.html",
        description=description,
        difficulty=difficulty,
        ingredients=["200 g de ingrediente"],
        utensils=["panela"],
        preparation_steps=["Adicione o ingrediente na panela por 10 minutos"],
        retrieved_at="2026-10-08T12:00:00+00:00",
        parser_version="test",
    )


def test_details_uses_origin_category_and_omits_empty_placeholder() -> None:
    details = {
        "title": "Almoço rápido",
        "description": "Receita de peixe",
        "rating_value": 4.5,
        "ratings_count": 690,
        "prep_time_minutes": 30,
        "difficulty": "fácil",
        "cost_label": None,
        "ingredients": [],
        "utensils": [],
        "preparation_steps": [],
        "categories": [],
        "origin_category": "Peixes e frutos do mar",
    }

    markup = _details_html(details)
    assert "<h4>Categorias</h4><p>Peixes e frutos do mar</p>" in markup

    details["origin_category"] = None
    markup = _details_html(details)
    assert "<h4>Categorias</h4>" not in markup


def test_export_analysis_notebook_writes_ipynb_with_ready_outputs(tmp_path: Path) -> None:
    database_path = tmp_path / "recipes.sqlite"
    notebook_path = tmp_path / "Trabalho PLN.ipynb"
    connection = connect_database(database_path)
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Bolo de chocolate", "Receita de bolo com chocolate", "Fácil"))
    save_recipe(connection, _recipe("2", "Frango com alho", "Receita salgada de frango com alho", "Difícil"))
    run_text_analysis(connection, cluster_count=2, neighbor_count=1)
    run_embedding_analysis(connection, dimension=8, window_size=2, neighbor_count=1)
    run_text_classification(connection, target_field="difficulty", test_ratio=0.25)
    run_linguistic_analysis(connection)
    connection.close()

    export_analysis_notebook(database_path, notebook_path)

    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    ready_cells = [cell for cell in code_cells if cell.get("outputs")]

    assert notebook["nbformat"] == 4
    assert len(code_cells) >= 8
    assert len(ready_cells) == len(code_cells)
    assert notebook["cells"][0]["cell_type"] == "code"
    assert "# Trabalho PLN" not in "\n".join(cell["source"] for cell in notebook["cells"])
    all_source = "\n".join(cell["source"] for cell in notebook["cells"])
    assert "Classificar significa" not in all_source
    for index, cell in enumerate(code_cells, start=1):
        compile(cell["source"], f"<notebook cell {index}>", "exec")
    assert "Aula 7" in all_source
    assert "Aula 8" in all_source
    assert "Aula 9" in all_source
    assert "Custos informados" in all_source
    assert "Receitas com categoria" in all_source
    assert "Não informado" in notebook_path.read_text(encoding="utf-8")
    svg_outputs = [
        output.get("data", {}).get("image/svg+xml")
        for cell in code_cells
        for output in cell["outputs"]
        if output.get("data", {}).get("image/svg+xml")
    ]
    assert svg_outputs
    map_svg = svg_outputs[0]
    assert 'class="recipe-point"' in map_svg
    assert "Passe o mouse sobre um ponto" in map_svg
    assert "Cluster 0" in map_svg
    assert "<title>" in map_svg


def test_notebook_requirements_define_jupyter_kernel() -> None:
    requirements = (Path(__file__).parents[1] / "requirements-notebook.txt").read_text(encoding="utf-8")

    assert "-r requirements.txt" in requirements
    assert "ipykernel" in requirements
    assert "jupyterlab" in requirements
