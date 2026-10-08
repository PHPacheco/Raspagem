import json
from pathlib import Path

from scraper.database import connect_database, initialize_database, save_recipe
from scraper.models import RecipeData
from scraper.notebook_export import export_analysis_notebook
from scraper.text_analysis import run_text_analysis
from scraper.text_embeddings import run_embedding_analysis


def _recipe(recipe_id: str, title: str, description: str) -> RecipeData:
    return RecipeData(
        site_recipe_id=recipe_id,
        title=title,
        url=f"https://example.test/receita/{recipe_id}.html",
        description=description,
        retrieved_at="2026-10-08T12:00:00+00:00",
        parser_version="test",
    )


def test_export_analysis_notebook_writes_ipynb_with_ready_outputs(tmp_path: Path) -> None:
    database_path = tmp_path / "recipes.sqlite"
    notebook_path = tmp_path / "Trabalho PLN.ipynb"
    connection = connect_database(database_path)
    initialize_database(connection)
    save_recipe(connection, _recipe("1", "Bolo de chocolate", "Receita de bolo com chocolate"))
    save_recipe(connection, _recipe("2", "Frango com alho", "Receita salgada de frango com alho"))
    run_text_analysis(connection, cluster_count=2, neighbor_count=1)
    run_embedding_analysis(connection, dimension=8, window_size=2, neighbor_count=1)
    connection.close()

    export_analysis_notebook(database_path, notebook_path)

    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    ready_cells = [cell for cell in code_cells if cell.get("outputs")]

    assert notebook["nbformat"] == 4
    assert len(code_cells) >= 8
    assert len(ready_cells) == len(code_cells)
    assert "Trabalho PLN" in notebook["cells"][0]["source"]
    assert any(
        output.get("data", {}).get("image/svg+xml")
        for cell in code_cells
        for output in cell["outputs"]
    )
