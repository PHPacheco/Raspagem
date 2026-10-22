from __future__ import annotations

import html
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .database import connect_database, initialize_database
from .text_analysis import latest_text_analysis
from .text_classification import latest_text_classification
from .linguistic_analysis import latest_linguistic_analysis
from .text_embeddings import (
    contextualize_tokens,
    latest_embedding_analysis,
    load_latest_embedding_model,
    semantic_search,
)


DEFAULT_NOTEBOOK = Path("notebooks") / "Trabalho PLN.ipynb"


def _ensure_parent(path: Path) -> None:
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)


def _plain(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _html_table(
    rows: Iterable[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    empty_message: str = "Nenhum registro encontrado.",
) -> str:
    row_list = list(rows)
    style = """
    <style>
      table.raspagem-table {
        border-collapse: collapse;
        width: 100%;
        font: 14px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .raspagem-table th, .raspagem-table td {
        border: 1px solid #d9dbe3;
        padding: 8px 10px;
        vertical-align: top;
      }
      .raspagem-table th {
        background: #f4f6fb;
        text-align: left;
      }
      .raspagem-note {
        border: 1px solid #d9dbe3;
        border-radius: 8px;
        padding: 12px;
        color: #4a5263;
        background: #fbfcff;
      }
    </style>
    """
    if not row_list:
        return f"{style}<div class=\"raspagem-note\">{html.escape(empty_message)}</div>"

    header = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body_rows = []
    for row in row_list:
        cells = "".join(
            f"<td>{html.escape(_plain(row.get(key)))}</td>"
            for key, _ in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return f"{style}<table class=\"raspagem-table\"><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _rows(connection: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, params)]


def _count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"]) if row is not None else 0


def _latest_id(connection: sqlite3.Connection, table: str) -> int | None:
    row = connection.execute(f"SELECT MAX(id) AS id FROM {table}").fetchone()
    return int(row["id"]) if row is not None and row["id"] is not None else None


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _svg_3d(documents: list[dict[str, Any]]) -> str:
    width = 920
    height = 560
    colors = ["#1763dc", "#00856f", "#ab571e", "#8455a1", "#b42318", "#126d89"]

    def normalize(axis: str) -> list[float]:
        values = [float(row.get(axis) or 0.0) for row in documents]
        if not values:
            return []
        low = min(values)
        high = max(values)
        span = high - low
        if span == 0:
            return [0.0 for _ in values]
        return [((value - low) / span - 0.5) * 2 for value in values]

    xs = normalize("x")
    ys = normalize("y")
    zs = normalize("z")

    angle_x = -0.55
    angle_y = 0.75

    def project(x: float, y: float, z: float) -> tuple[float, float, float]:
        cx = math.cos(angle_x)
        sx = math.sin(angle_x)
        cy = math.cos(angle_y)
        sy = math.sin(angle_y)
        y1 = y * cx - z * sx
        z1 = y * sx + z * cx
        x2 = x * cy + z1 * sy
        z2 = -x * sy + z1 * cy
        perspective = 0.84 / (1.8 - z2 * 0.38)
        size = min(width, height) * 0.34
        return (
            width / 2 + x2 * size * perspective,
            height / 2 + y1 * size * perspective,
            z2,
        )

    def line(label: str, end: tuple[float, float, float], color: str) -> str:
        origin = project(0, 0, 0)
        target = project(*end)
        return (
            f'<line x1="{origin[0]:.1f}" y1="{origin[1]:.1f}" x2="{target[0]:.1f}" y2="{target[1]:.1f}" '
            f'stroke="{color}" stroke-width="2" />'
            f'<text x="{target[0] + 8:.1f}" y="{target[1] - 8:.1f}" fill="{color}" '
            f'font-size="14" font-family="system-ui, sans-serif">{label}</text>'
        )

    points = []
    for index, row in enumerate(documents):
        px, py, depth = project(xs[index], ys[index], zs[index])
        points.append((depth, px, py, row))
    points.sort(key=lambda item: item[0])

    point_markup = []
    for _, px, py, row in points:
        cluster = int(row.get("cluster_label") or 0)
        color = colors[cluster % len(colors)]
        title = html.escape(str(row.get("title") or row.get("recipe_id") or "Receita"))
        terms = ", ".join(str(item.get("term")) for item in row.get("top_terms_data", [])[:6])
        tooltip = html.escape(f"{title} | cluster {cluster} | termos: {terms or 'sem termos'}")
        point_markup.append(
            f'<g><title>{tooltip}</title>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="9" fill="{color}" stroke="#fff" stroke-width="2" />'
            f'<text x="{px + 12:.1f}" y="{py - 10:.1f}" fill="#252936" font-size="12" '
            f'font-family="system-ui, sans-serif">{title}</text></g>'
        )

    if not documents:
        point_markup.append(
            '<text x="460" y="280" text-anchor="middle" fill="#596174" font-size="16" '
            'font-family="system-ui, sans-serif">Sem documentos para projetar.</text>'
        )

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
  <rect width="100%" height="100%" rx="10" fill="#fbfcff" stroke="#d9dbe3" />
  <text x="24" y="36" fill="#252936" font-size="20" font-weight="700" font-family="system-ui, sans-serif">
    Mapa 3D das receitas
  </text>
  <text x="24" y="60" fill="#596174" font-size="13" font-family="system-ui, sans-serif">
    Projeção 3D da matriz TF-IDF. Cores indicam clusters.
  </text>
  {line("X", (1.18, 0, 0), "#687083")}
  {line("Y", (0, 1.18, 0), "#687083")}
  {line("Z", (0, 0, 1.18), "#687083")}
  {''.join(point_markup)}
</svg>
""".strip()


def _stream(text: str) -> dict[str, Any]:
    return {"output_type": "stream", "name": "stdout", "text": text}


def _html_output(markup: str) -> dict[str, Any]:
    return {
        "output_type": "display_data",
        "metadata": {},
        "data": {
            "text/html": markup,
            "text/plain": "Tabela HTML pronta no output do notebook.",
        },
    }


def _svg_output(svg: str) -> dict[str, Any]:
    return {
        "output_type": "display_data",
        "metadata": {},
        "data": {
            "image/svg+xml": svg,
            "text/plain": "Mapa 3D em SVG pronto no output do notebook.",
        },
    }


def _markdown_cell(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.strip() + "\n"}


def _code_cell(source: str, outputs: list[dict[str, Any]], execution_count: int) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": execution_count,
        "metadata": {},
        "outputs": outputs,
        "source": source.strip() + "\n",
    }


def _first_recipe_details(connection: sqlite3.Connection) -> dict[str, Any] | None:
    recipe = connection.execute(
        """
        SELECT *
        FROM recipes
        ORDER BY title COLLATE NOCASE
        LIMIT 1
        """
    ).fetchone()
    if recipe is None:
        return None
    recipe_id = recipe["site_recipe_id"]
    return {
        **dict(recipe),
        "ingredients": [
            row["raw_text"]
            for row in connection.execute(
                "SELECT raw_text FROM ingredients WHERE recipe_id = ? ORDER BY position",
                (recipe_id,),
            )
        ],
        "utensils": [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM utensils WHERE recipe_id = ? ORDER BY position",
                (recipe_id,),
            )
        ],
        "preparation_steps": [
            row["raw_text"]
            for row in connection.execute(
                "SELECT raw_text FROM preparation_steps WHERE recipe_id = ? ORDER BY position",
                (recipe_id,),
            )
        ],
        "categories": [
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
        ],
    }


def _details_html(details: dict[str, Any] | None) -> str:
    if details is None:
        return "<div class=\"raspagem-note\">Nenhuma receita disponível.</div>"
    ingredients = "".join(f"<li>{html.escape(item)}</li>" for item in details["ingredients"])
    utensils = "".join(f"<li>{html.escape(item)}</li>" for item in details["utensils"])
    steps = "".join(
        f"<li>{html.escape(item)}</li>"
        for item in details["preparation_steps"]
    )
    categories = ", ".join(html.escape(item) for item in details["categories"]) or "—"
    return f"""
    <style>
      .recipe-card {{
        border: 1px solid #d9dbe3;
        border-radius: 10px;
        padding: 16px;
        font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      .recipe-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
      }}
      .recipe-card h3 {{ margin: 0 0 6px; }}
      .recipe-card h4 {{ margin-bottom: 6px; }}
      .metric-list {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }}
      .metric-list span {{ background: #f4f6fb; border-radius: 999px; padding: 5px 9px; }}
    </style>
    <div class="recipe-card">
      <h3>{html.escape(str(details["title"]))}</h3>
      <p>{html.escape(_plain(details.get("description")))}</p>
      <div class="metric-list">
        <span>Nota: {html.escape(_plain(details.get("rating_value")))}</span>
        <span>Avaliações: {html.escape(_plain(details.get("ratings_count")))}</span>
        <span>Tempo: {html.escape(_plain(details.get("prep_time_minutes")))} min</span>
        <span>Dificuldade: {html.escape(_plain(details.get("difficulty")))}</span>
        <span>Custo: {html.escape(_plain(details.get("cost_label")))}</span>
      </div>
      <div class="recipe-grid">
        <div><h4>Ingredientes</h4><ul>{ingredients or "<li>—</li>"}</ul></div>
        <div><h4>Utensílios</h4><ul>{utensils or "<li>—</li>"}</ul></div>
        <div><h4>Modo de preparo</h4><ol>{steps or "<li>—</li>"}</ol></div>
        <div><h4>Categorias</h4><p>{categories}</p></div>
      </div>
    </div>
    """.strip()


def _top_terms_rows(text_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not text_analysis:
        return []
    rows: list[dict[str, Any]] = []
    for document in text_analysis["documents"]:
        for term in document["top_terms_data"]:
            rows.append(
                {
                    "recipe": document["title"],
                    "cluster": document["cluster_label"],
                    "term": term["term"],
                    "tf": term["tf"],
                    "idf": term["idf"],
                    "tfidf": term["tfidf"],
                }
            )
    return rows


def _embedding_token_rows(embedding_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not embedding_analysis:
        return []
    rows: list[dict[str, Any]] = []
    for document in embedding_analysis["documents"]:
        for token in document["top_tokens"]:
            rows.append(
                {
                    "recipe": document["title"],
                    "token": token["token"],
                    "count": token["count"],
                    "norm": document["norm"],
                }
            )
    return rows


def _context_rows(embedding_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not embedding_analysis:
        return []
    rows: list[dict[str, Any]] = []
    for word in embedding_analysis["words"]:
        for context in word["top_contexts"]:
            rows.append(
                {
                    "term": word["term"],
                    "context": context["context"],
                    "weight": context["weight"],
                }
            )
    return rows


def export_analysis_notebook(database_path: str | Path, output_path: str | Path = DEFAULT_NOTEBOOK) -> Path:
    database = Path(database_path)
    output = Path(output_path)
    _ensure_parent(output)

    connection = connect_database(database)
    initialize_database(connection)

    text_analysis = latest_text_analysis(connection)
    embedding_analysis = latest_embedding_analysis(connection)
    embedding_model = load_latest_embedding_model(connection)
    classification_analysis = latest_text_classification(connection)
    linguistic_analysis = latest_linguistic_analysis(connection)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    summary_rows = [
        {"metric": "Receitas", "value": _count(connection, "recipes")},
        {"metric": "Ingredientes", "value": _count(connection, "ingredients")},
        {"metric": "Passos de preparo", "value": _count(connection, "preparation_steps")},
        {"metric": "Categorias", "value": _count(connection, "categories")},
        {"metric": "Textos preparados", "value": _count(connection, "text_preparations")},
        {"metric": "Última análise TF-IDF", "value": _latest_id(connection, "text_analysis_runs")},
        {"metric": "Última análise de embeddings", "value": _latest_id(connection, "embedding_runs")},
        {"metric": "Última classificação", "value": _latest_id(connection, "classification_runs")},
        {"metric": "Última análise linguística", "value": _latest_id(connection, "linguistic_analysis_runs")},
    ]
    prepared_text_count = int(summary_rows[4]["value"])
    recipe_rows = _rows(
        connection,
        """
        SELECT
            site_recipe_id AS id,
            title,
            rating_value,
            ratings_count,
            prep_time_minutes,
            difficulty,
            cost_label,
            servings,
            url
        FROM recipes
        ORDER BY title COLLATE NOCASE
        """,
    )
    prepared_rows = _rows(
        connection,
        """
        SELECT
            r.title AS recipe,
            tp.field_name,
            tp.position,
            tp.raw_text,
            tp.clean_text,
            tp.content_tokens_json
        FROM text_preparations tp
        JOIN recipes r ON r.site_recipe_id = tp.recipe_id
        ORDER BY r.title COLLATE NOCASE, tp.field_name, tp.position
        LIMIT 40
        """,
    )
    for row in prepared_rows:
        row["tokens"] = ", ".join(str(item) for item in _json_list(row.pop("content_tokens_json")))

    details = _first_recipe_details(connection)
    text_run = text_analysis["run"] if text_analysis else {}
    embedding_run = embedding_analysis["run"] if embedding_analysis else {}
    tfidf_rows = _top_terms_rows(text_analysis)
    tfidf_similarity_rows = (text_analysis or {}).get("similarities", [])
    embedding_token_rows = _embedding_token_rows(embedding_analysis)
    context_rows = _context_rows(embedding_analysis)
    embedding_similarity_rows = (embedding_analysis or {}).get("similarities", [])
    classification_run = (classification_analysis or {}).get("run", {})
    classification_prediction_rows = []
    for prediction in (classification_analysis or {}).get("predictions", []):
        probabilities = prediction.get("probabilities", {})
        classification_prediction_rows.append(
            {
                "title": prediction.get("title"),
                "split": prediction.get("split"),
                "actual_label": prediction.get("actual_label"),
                "predicted_label": prediction.get("predicted_label"),
                "confidence": max(probabilities.values()) if probabilities else None,
            }
        )
    classification_metric_rows = (classification_analysis or {}).get("metrics", [])
    confusion_rows = [
        {"actual": actual, "predicted": predicted, "count": count}
        for actual, candidates in (classification_analysis or {}).get("confusion", {}).items()
        for predicted, count in candidates.items()
    ]
    linguistic_run = (linguistic_analysis or {}).get("run", {})
    dependency_rows = (linguistic_analysis or {}).get("dependencies", [])[:80]
    sentiment_rows = []
    for item in (linguistic_analysis or {}).get("sentiments", [])[:40]:
        sentiment_rows.append(
            {
                "title": item.get("title"),
                "field_name": item.get("field_name"),
                "position": item.get("position"),
                "polarity": item.get("polarity"),
                "score": item.get("score"),
                "subjectivity": item.get("subjectivity"),
                "evidence": ", ".join(evidence.get("token", "") for evidence in item.get("evidence", [])) or "—",
                "aspects": ", ".join(aspect.get("aspect", "") for aspect in item.get("aspects", [])) or "—",
            }
        )
    entity_rows = (linguistic_analysis or {}).get("entities", [])[:80]
    relation_rows = (linguistic_analysis or {}).get("relations", [])[:80]
    semantic_query = "carne com cebola"
    semantic_rows = semantic_search(embedding_model, semantic_query, limit=5) if embedding_model else []
    contextual_rows: list[dict[str, Any]] = []
    if embedding_model and embedding_model.documents:
        contextual_document = embedding_model.documents[0]
        occurrences = contextualize_tokens(contextual_document.tokens, embedding_model)
        counts: dict[str, int] = {}
        for token in contextual_document.tokens:
            counts[token] = counts.get(token, 0) + 1
        repeated = next((token for token in contextual_document.tokens if counts[token] > 1), None)
        selected = repeated or (contextual_document.tokens[0] if contextual_document.tokens else None)
        for occurrence in occurrences:
            if occurrence.token == selected:
                contextual_rows.append(
                    {
                        "recipe": contextual_document.title,
                        "token": occurrence.token,
                        "position": occurrence.position,
                        "context": ", ".join(occurrence.context) or "—",
                        "dimensions": len(occurrence.vector),
                    }
                )
            if len(contextual_rows) >= 4:
                break
    svg = _svg_3d((text_analysis or {}).get("documents", []))

    connection.close()

    cells: list[dict[str, Any]] = [
        _markdown_cell(
            f"""
            # Trabalho PLN

            Este notebook substitui a antiga visualização em página web. Ele já foi gerado com output pronto em `{generated_at}`.

            A ideia é ler o projeto em blocos: dados coletados, filtros, detalhes das receitas, limpeza/preparação, TF-IDF, gráfico 3D e embeddings da etapa 7.
            """
        ),
        _code_cell(
            """
            from pathlib import Path
            import json
            import sqlite3
            from html import escape
            from IPython.display import HTML, SVG, display

            from scraper.database import connect_database, initialize_database, rebuild_text_preparations
            from scraper.text_analysis import run_text_analysis, latest_text_analysis
            from scraper.text_classification import run_text_classification, latest_text_classification
            from scraper.linguistic_analysis import run_linguistic_analysis, latest_linguistic_analysis
            from scraper.text_embeddings import (
                contextualize_tokens,
                load_latest_embedding_model,
                run_embedding_analysis,
                latest_embedding_analysis,
                semantic_search,
            )

            DATABASE_PATH = Path("data/recipes.sqlite")
            print(f"Banco configurado: {DATABASE_PATH.resolve()}")
            print("Se quiser atualizar os resultados, execute as células na ordem.")
            """,
            [
                _stream(
                    f"Banco configurado: {database.resolve()}\n"
                    "Se quiser atualizar os resultados, execute as células na ordem.\n"
                )
            ],
            1,
        ),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            initialize_database(connection)
            prepared_count = rebuild_text_preparations(connection)
            analysis_run_id = run_text_analysis(connection, cluster_count=4, neighbor_count=5)
            embedding_run_id = run_embedding_analysis(connection, dimension=32, window_size=2, neighbor_count=5)
            classification_run_id = run_text_classification(connection, target_field="difficulty", test_ratio=0.25)
            linguistic_run_id = run_linguistic_analysis(connection)
            connection.close()

            print(f"Preparação atualizada: {prepared_count} unidade(s)")
            print(f"Análise TF-IDF gerada: execução {analysis_run_id}")
            print(f"Embeddings gerados: execução {embedding_run_id}")
            print(f"Classificação gerada: execução {classification_run_id}")
            print(f"Análise linguística gerada: execução {linguistic_run_id}")
            """,
            [
                _stream(
                    f"Preparação atualizada: {prepared_text_count} unidade(s)\n"
                    f"Análise TF-IDF disponível: execução {text_run.get('id', '—')}\n"
                    f"Embeddings disponíveis: execução {embedding_run.get('id', '—')}\n"
                    f"Classificação disponível: execução {classification_run.get('id', '—')}\n"
                    f"Análise linguística disponível: execução {linguistic_run.get('id', '—')}\n"
                )
            ],
            2,
        ),
        _markdown_cell("## 1. Resumo do banco"),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            initialize_database(connection)
            resumo = [
                {"metric": "Receitas", "value": connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]},
                {"metric": "Ingredientes", "value": connection.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]},
                {"metric": "Passos de preparo", "value": connection.execute("SELECT COUNT(*) FROM preparation_steps").fetchone()[0]},
                {"metric": "Categorias", "value": connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]},
                {"metric": "Textos preparados", "value": connection.execute("SELECT COUNT(*) FROM text_preparations").fetchone()[0]},
            ]
            connection.close()
            display(HTML("Resumo já exibido no output desta célula."))
            """,
            [
                _html_output(
                    _html_table(
                        summary_rows,
                        [("metric", "Métrica"), ("value", "Valor")],
                    )
                )
            ],
            3,
        ),
        _markdown_cell("## 2. Dados coletados"),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            receitas = [dict(row) for row in connection.execute(\"\"\"
                SELECT site_recipe_id AS id, title, rating_value, ratings_count, prep_time_minutes,
                       difficulty, cost_label, servings, url
                FROM recipes
                ORDER BY title COLLATE NOCASE
            \"\"\")]
            connection.close()
            display(HTML("Tabela de receitas coletadas já exibida no output."))
            """,
            [
                _html_output(
                    _html_table(
                        recipe_rows,
                        [
                            ("id", "ID"),
                            ("title", "Receita"),
                            ("rating_value", "Nota"),
                            ("ratings_count", "Avaliações"),
                            ("prep_time_minutes", "Tempo min"),
                            ("difficulty", "Dificuldade"),
                            ("cost_label", "Custo"),
                            ("servings", "Porções"),
                            ("url", "URL"),
                        ],
                    )
                )
            ],
            4,
        ),
        _markdown_cell(
            """
            ## 3. Filtros em notebook

            A página web tinha campos de filtro. No notebook, a mesma ideia fica em variáveis: altere `busca`, `dificuldade`, `custo`, `tempo_maximo` e `nota_minima`, depois execute a célula.
            """
        ),
        _code_cell(
            """
            busca = ""
            dificuldade = ""
            custo = ""
            tempo_maximo = None
            nota_minima = None

            connection = connect_database(DATABASE_PATH)
            sql = [
                "SELECT site_recipe_id AS id, title, rating_value, prep_time_minutes, difficulty, cost_label",
                "FROM recipes WHERE 1 = 1",
            ]
            params = []
            if busca:
                sql.append("AND search_text LIKE ?")
                params.append(f"%{busca.lower()}%")
            if dificuldade:
                sql.append("AND difficulty = ?")
                params.append(dificuldade)
            if custo:
                sql.append("AND cost_label = ?")
                params.append(custo)
            if tempo_maximo is not None:
                sql.append("AND prep_time_minutes <= ?")
                params.append(tempo_maximo)
            if nota_minima is not None:
                sql.append("AND rating_value >= ?")
                params.append(nota_minima)
            sql.append("ORDER BY title COLLATE NOCASE")
            receitas_filtradas = [dict(row) for row in connection.execute(" ".join(sql), params)]
            connection.close()
            display(HTML("Resultado dos filtros já exibido no output."))
            """,
            [
                _html_output(
                    _html_table(
                        [
                            {
                                "id": row["id"],
                                "title": row["title"],
                                "rating_value": row["rating_value"],
                                "prep_time_minutes": row["prep_time_minutes"],
                                "difficulty": row["difficulty"],
                                "cost_label": row["cost_label"],
                            }
                            for row in recipe_rows
                        ],
                        [
                            ("id", "ID"),
                            ("title", "Receita"),
                            ("rating_value", "Nota"),
                            ("prep_time_minutes", "Tempo min"),
                            ("difficulty", "Dificuldade"),
                            ("cost_label", "Custo"),
                        ],
                    )
                )
            ],
            5,
        ),
        _markdown_cell("## 4. Detalhe da receita"),
        _code_cell(
            """
            # Por padrão, o notebook mostra a primeira receita em ordem alfabética.
            # Troque o ID se quiser inspecionar outra:
            receita_id = None
            display(HTML("Detalhe da receita já exibido no output."))
            """,
            [_html_output(_details_html(details))],
            6,
        ),
        _markdown_cell("## 5. Limpeza e preparação dos textos"),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            preparacao = [dict(row) for row in connection.execute(\"\"\"
                SELECT r.title AS recipe, tp.field_name, tp.position, tp.raw_text,
                       tp.clean_text, tp.content_tokens_json
                FROM text_preparations tp
                JOIN recipes r ON r.site_recipe_id = tp.recipe_id
                ORDER BY r.title COLLATE NOCASE, tp.field_name, tp.position
                LIMIT 40
            \"\"\")]
            connection.close()
            display(HTML("Amostra da preparação textual já exibida no output."))
            """,
            [
                _html_output(
                    _html_table(
                        prepared_rows,
                        [
                            ("recipe", "Receita"),
                            ("field_name", "Campo"),
                            ("position", "Posição"),
                            ("raw_text", "Texto bruto"),
                            ("clean_text", "Texto limpo"),
                            ("tokens", "Tokens úteis"),
                        ],
                    )
                )
            ],
            7,
        ),
        _markdown_cell("## 6. TF-IDF, clusters e termos principais"),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            analise = latest_text_analysis(connection)
            connection.close()
            display(HTML("Termos principais por TF-IDF já exibidos no output."))
            """,
            [
                _html_output(
                    _html_table(
                        tfidf_rows,
                        [
                            ("recipe", "Receita"),
                            ("cluster", "Cluster"),
                            ("term", "Termo"),
                            ("tf", "TF"),
                            ("idf", "IDF"),
                            ("tfidf", "TF-IDF"),
                        ],
                    )
                )
            ],
            8,
        ),
        _markdown_cell("## 7. Mapa 3D das receitas"),
        _code_cell(
            """
            # O gráfico abaixo usa a projeção 3D salva na tabela document_vectors.
            # A variável `analise` foi carregada na célula anterior.
            import math

            def renderizar_mapa_3d(analise):
                docs = (analise or {}).get("documents", [])
                width, height = 920, 560
                colors = ["#1763dc", "#00856f", "#ab571e", "#8455a1", "#b42318", "#126d89"]

                def normalizar(axis):
                    values = [float(row.get(axis) or 0.0) for row in docs]
                    if not values:
                        return []
                    low, high = min(values), max(values)
                    if high == low:
                        return [0.0 for _ in values]
                    return [((value - low) / (high - low) - 0.5) * 2 for value in values]

                xs, ys, zs = normalizar("x"), normalizar("y"), normalizar("z")
                angle_x, angle_y = -0.55, 0.75

                def projetar(x, y, z):
                    cx, sx = math.cos(angle_x), math.sin(angle_x)
                    cy, sy = math.cos(angle_y), math.sin(angle_y)
                    y1 = y * cx - z * sx
                    z1 = y * sx + z * cx
                    x2 = x * cy + z1 * sy
                    z2 = -x * sy + z1 * cy
                    perspective = 0.84 / (1.8 - z2 * 0.38)
                    size = min(width, height) * 0.34
                    return width / 2 + x2 * size * perspective, height / 2 + y1 * size * perspective, z2

                def eixo(label, end, color):
                    origin = projetar(0, 0, 0)
                    target = projetar(*end)
                    return (
                        f'<line x1="{origin[0]:.1f}" y1="{origin[1]:.1f}" x2="{target[0]:.1f}" y2="{target[1]:.1f}" '
                        f'stroke="{color}" stroke-width="2" />'
                        f'<text x="{target[0] + 8:.1f}" y="{target[1] - 8:.1f}" fill="{color}" '
                        f'font-size="14" font-family="system-ui, sans-serif">{label}</text>'
                    )

                pontos = []
                for index, row in enumerate(docs):
                    px, py, depth = projetar(xs[index], ys[index], zs[index])
                    cluster = int(row.get("cluster_label") or 0)
                    title = escape(str(row.get("title") or row.get("recipe_id") or "Receita"))
                    color = colors[cluster % len(colors)]
                    pontos.append(
                        f'<g><circle cx="{px:.1f}" cy="{py:.1f}" r="9" fill="{color}" stroke="#fff" stroke-width="2" />'
                        f'<text x="{px + 12:.1f}" y="{py - 10:.1f}" fill="#252936" font-size="12" '
                        f'font-family="system-ui, sans-serif">{title}</text></g>'
                    )

                if not pontos:
                    pontos.append('<text x="460" y="280" text-anchor="middle">Sem documentos para projetar.</text>')

                return f'''
                <svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
                  <rect width="100%" height="100%" rx="10" fill="#fbfcff" stroke="#d9dbe3" />
                  <text x="24" y="36" fill="#252936" font-size="20" font-weight="700" font-family="system-ui, sans-serif">
                    Mapa 3D das receitas
                  </text>
                  <text x="24" y="60" fill="#596174" font-size="13" font-family="system-ui, sans-serif">
                    Projeção 3D da matriz TF-IDF. Cores indicam clusters.
                  </text>
                  {eixo("X", (1.18, 0, 0), "#687083")}
                  {eixo("Y", (0, 1.18, 0), "#687083")}
                  {eixo("Z", (0, 0, 1.18), "#687083")}
                  {''.join(pontos)}
                </svg>
                '''

            display(SVG(renderizar_mapa_3d(analise)))
            """,
            [_svg_output(svg)],
            9,
        ),
        _markdown_cell("## 8. Similaridade por TF-IDF"),
        _code_cell(
            """
            # Similaridade por cosseno entre vetores TF-IDF.
            display(HTML("Tabela de similaridades TF-IDF já exibida no output."))
            """,
            [
                _html_output(
                    _html_table(
                        tfidf_similarity_rows,
                        [
                            ("recipe_title", "Receita"),
                            ("neighbor_title", "Vizinha"),
                            ("rank", "Rank"),
                            ("cosine_similarity", "Similaridade"),
                        ],
                        empty_message="Com apenas uma receita, não há vizinhos para comparar.",
                    )
                )
            ],
            10,
        ),
        _markdown_cell("## 9. Etapa 7 — embeddings densos por contexto"),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            embeddings = latest_embedding_analysis(connection)
            connection.close()
            display(HTML("Tokens mais representativos dos embeddings já exibidos no output."))
            """,
            [
                _html_output(
                    _html_table(
                        [
                            {"metric": "Execução", "value": embedding_run.get("id")},
                            {"metric": "Versão", "value": embedding_run.get("model_version")},
                            {"metric": "Documentos", "value": embedding_run.get("document_count")},
                            {"metric": "Vocabulário", "value": embedding_run.get("vocabulary_size")},
                            {"metric": "Dimensão", "value": embedding_run.get("dimension")},
                            {"metric": "Janela de contexto", "value": embedding_run.get("window_size")},
                        ],
                        [("metric", "Métrica"), ("value", "Valor")],
                    )
                    + _html_table(
                        embedding_token_rows,
                        [
                            ("recipe", "Receita"),
                            ("token", "Token"),
                            ("count", "Contagem"),
                            ("norm", "Norma do vetor"),
                        ],
                    )
                )
            ],
            11,
        ),
        _markdown_cell("## 10. Contextos aprendidos pelas palavras"),
        _code_cell(
            """
            # Mostra quais palavras apareceram como contexto de outras palavras.
            display(HTML("Contextos aprendidos já exibidos no output."))
            """,
            [
                _html_output(
                    _html_table(
                        context_rows,
                        [
                            ("term", "Termo"),
                            ("context", "Contexto"),
                            ("weight", "Peso PPMI"),
                        ],
                    )
                )
            ],
            12,
        ),
        _markdown_cell("## 11. Similaridade por embeddings"),
        _code_cell(
            """
            # Similaridade por cosseno entre embeddings densos das receitas.
            display(HTML("Tabela de similaridades por embeddings já exibida no output."))
            """,
            [
                _html_output(
                    _html_table(
                        embedding_similarity_rows,
                        [
                            ("recipe_title", "Receita"),
                            ("neighbor_title", "Vizinha"),
                            ("rank", "Rank"),
                            ("cosine_similarity", "Similaridade"),
                        ],
                        empty_message="Com apenas uma receita, não há vizinhos por embeddings para comparar.",
                    )
                )
            ],
            13,
        ),
        _markdown_cell(
            """
            ## 12. Aula 7 — busca semântica

            A consulta é preparada e projetada no mesmo espaço denso das receitas. Diferentemente da busca literal, ela compara a direção dos vetores. Com o banco atual de uma receita, o mecanismo pode ser executado, mas ainda não há diversidade suficiente para avaliar o ranking.
            """
        ),
        _code_cell(
            f"""
            consulta_semantica = {semantic_query!r}
            connection = connect_database(DATABASE_PATH)
            modelo_embeddings = load_latest_embedding_model(connection)
            resultados_semanticos = semantic_search(modelo_embeddings, consulta_semantica, limit=5) if modelo_embeddings else []
            connection.close()
            display(HTML("Resultado da busca semântica já exibido no output."))
            """,
            [
                _html_output(
                    _html_table(
                        semantic_rows,
                        [
                            ("title", "Receita"),
                            ("cosine_similarity", "Similaridade"),
                            ("matched_tokens", "Termos reconhecidos"),
                        ],
                        empty_message="A consulta não encontrou termos presentes no vocabulário.",
                    )
                )
            ],
            14,
        ),
        _markdown_cell(
            """
            ## 13. Aula 7 — embedding estático e representação contextual

            O vetor estático associa uma palavra a um único vetor. A composição contextual abaixo combina esse vetor com as palavras da janela local, produzindo um vetor por ocorrência. É uma demonstração didática da ideia `palavra + contexto → vetor`, não uma implementação de BERT ou de atenção Transformer.
            """
        ),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            modelo_embeddings = load_latest_embedding_model(connection)
            exemplos_contextuais = []
            if modelo_embeddings and modelo_embeddings.documents:
                documento = modelo_embeddings.documents[0]
                ocorrencias = contextualize_tokens(documento.tokens, modelo_embeddings)
                exemplos_contextuais = [
                    {
                        "token": item.token,
                        "posição": item.position,
                        "contexto": item.context,
                        "dimensões": len(item.vector),
                    }
                    for item in ocorrencias[:8]
                ]
            connection.close()
            display(HTML("Ocorrências contextualizadas já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        contextual_rows,
                        [
                            ("recipe", "Receita"),
                            ("token", "Token"),
                            ("position", "Posição"),
                            ("context", "Janela local"),
                            ("dimensions", "Dimensões"),
                        ],
                        empty_message="Não há tokens suficientes para a demonstração contextual.",
                    )
                )
            ],
            15,
        ),
        _markdown_cell(
            """
            ## 14. Aula 8 — classificação supervisionada

            Classificar significa aprender, a partir de receitas já rotuladas, uma função que associa texto a uma classe. O baseline implementado usa os tokens preparados e Naive Bayes multinomial. O alvo padrão é `difficulty`, uma classificação ordinal porque as categorias possuem uma ordem conceitual.

            O campo `status` evita interpretações incorretas: `evaluated` indica que existiam ao menos duas classes e exemplos de teste; `insufficient_classes` ou `insufficient_test_data` indicam que as métricas não devem ser calculadas.
            """
        ),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            classificacao = latest_text_classification(connection)
            connection.close()
            display(HTML("Resumo da classificação já exibido no output."))
            """,
            [
                _html_output(
                    _html_table(
                        [
                            {"metric": "Execução", "value": classification_run.get("id")},
                            {"metric": "Modelo", "value": classification_run.get("model_version")},
                            {"metric": "Alvo", "value": classification_run.get("target_field")},
                            {"metric": "Tipo", "value": classification_run.get("classification_type")},
                            {"metric": "Documentos", "value": classification_run.get("document_count")},
                            {"metric": "Treino", "value": classification_run.get("train_count")},
                            {"metric": "Teste", "value": classification_run.get("test_count")},
                            {"metric": "Classes", "value": classification_run.get("class_count")},
                            {"metric": "Status", "value": classification_run.get("status")},
                        ],
                        [("metric", "Métrica"), ("value", "Valor")],
                    )
                )
            ],
            16,
        ),
        _markdown_cell(
            """
            ## 15. Aula 8 — previsões, probabilidades e divisão treino/teste

            A divisão é estratificada e determinística. Cada classe com pelo menos dois exemplos mantém dados no treino e separa uma parte para teste. A probabilidade abaixo é a distribuição normalizada dos escores do classificador, não uma garantia de acerto.
            """
        ),
        _code_cell(
            """
            previsoes = (classificacao or {}).get("predictions", [])
            display(HTML("Previsões já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        classification_prediction_rows,
                        [
                            ("title", "Receita"),
                            ("split", "Conjunto"),
                            ("actual_label", "Classe real"),
                            ("predicted_label", "Classe prevista"),
                            ("confidence", "Maior probabilidade"),
                        ],
                        empty_message="Nenhuma previsão foi gerada.",
                    )
                )
            ],
            17,
        ),
        _markdown_cell(
            """
            ## 16. Aula 8 — matriz de confusão e métricas

            Acurácia mede o total de acertos. Precisão pergunta quantas previsões de uma classe estavam corretas; revocação mede quantos exemplos reais daquela classe foram encontrados; F1 combina as duas. O projeto calcula esses valores somente no conjunto de teste. Com o banco demonstrativo atual, eles permanecem indisponíveis porque existe apenas uma receita e uma classe.
            """
        ),
        _code_cell(
            """
            metricas = (classificacao or {}).get("metrics", [])
            matriz_confusao = (classificacao or {}).get("confusion", {})
            display(HTML("Métricas e matriz de confusão já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        [
                            {"metric": "Acurácia", "value": classification_run.get("accuracy")},
                            {"metric": "Precisão macro", "value": classification_run.get("macro_precision")},
                            {"metric": "Revocação macro", "value": classification_run.get("macro_recall")},
                            {"metric": "F1 macro", "value": classification_run.get("macro_f1")},
                        ],
                        [("metric", "Métrica global"), ("value", "Valor")],
                    )
                    + _html_table(
                        classification_metric_rows,
                        [
                            ("label", "Classe"),
                            ("precision", "Precisão"),
                            ("recall", "Revocação"),
                            ("f1", "F1"),
                            ("support", "Suporte"),
                        ],
                        empty_message="Sem métricas válidas: são necessárias classes e amostras de teste suficientes.",
                    )
                    + _html_table(
                        confusion_rows,
                        [
                            ("actual", "Classe real"),
                            ("predicted", "Classe prevista"),
                            ("count", "Quantidade"),
                        ],
                        empty_message="A matriz de confusão exige exemplos no conjunto de teste.",
                    )
                )
            ],
            18,
        ),
        _markdown_cell(
            """
            ## 17. Aula 9 — análise linguística e extração de informação

            Esta etapa vai além dos vetores e produz informação explícita. O pipeline local reúne quatro tarefas: dependências sintáticas rasas, sentimento baseado em léxico e regras, entidades do domínio culinário e relações em forma de triplas.

            Os métodos são determinísticos e interpretáveis. Eles não substituem spaCy, Stanza, BERT ou um modelo de NER treinado; servem como baseline de domínio e deixam cada decisão auditável.
            """
        ),
        _code_cell(
            """
            connection = connect_database(DATABASE_PATH)
            linguistica = latest_linguistic_analysis(connection)
            connection.close()
            display(HTML("Resumo da aula 9 já exibido no output."))
            """,
            [
                _html_output(
                    _html_table(
                        [
                            {"metric": "Execução", "value": linguistic_run.get("id")},
                            {"metric": "Versão", "value": linguistic_run.get("model_version")},
                            {"metric": "Documentos", "value": linguistic_run.get("document_count")},
                            {"metric": "Sentenças", "value": linguistic_run.get("sentence_count")},
                            {"metric": "Dependências", "value": linguistic_run.get("dependency_count")},
                            {"metric": "Sentimentos", "value": linguistic_run.get("sentiment_count")},
                            {"metric": "Entidades", "value": linguistic_run.get("entity_count")},
                            {"metric": "Relações", "value": linguistic_run.get("relation_count")},
                        ],
                        [("metric", "Métrica"), ("value", "Valor")],
                    )
                )
            ],
            19,
        ),
        _markdown_cell(
            """
            ## 18. Aula 9 — parsing e dependências

            O parser raso procura a ação culinária central e liga os demais tokens com relações inspiradas em Universal Dependencies: `root`, `obj`, `nsubj`, `det`, `case` e `nmod`. O resultado ajuda a formar pares ação–objeto, mas não representa uma árvore sintática neural completa.
            """
        ),
        _code_cell(
            """
            dependencias = (linguistica or {}).get("dependencies", [])
            display(HTML("Dependências sintáticas rasas já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        dependency_rows,
                        [
                            ("title", "Receita"),
                            ("sentence_index", "Sentença"),
                            ("token_index", "Índice"),
                            ("token", "Token"),
                            ("lemma", "Lema"),
                            ("head_index", "Núcleo"),
                            ("relation", "Relação"),
                        ],
                    )
                )
            ],
            20,
        ),
        _markdown_cell(
            """
            ## 19. Aula 9 — análise de sentimentos e aspectos

            A polaridade usa um léxico pequeno, inversão por negação e pesos de intensidade. Também marca aspectos culinários como sabor, textura, tempo, custo e preparo. Textos descritivos tendem a ser neutros; a técnica é mais útil quando o corpus contém avaliações ou comentários.
            """
        ),
        _code_cell(
            """
            sentimentos = (linguistica or {}).get("sentiments", [])
            display(HTML("Análises de sentimento já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        sentiment_rows,
                        [
                            ("title", "Receita"),
                            ("field_name", "Campo"),
                            ("position", "Posição"),
                            ("polarity", "Polaridade"),
                            ("score", "Escore"),
                            ("subjectivity", "Subjetividade"),
                            ("evidence", "Evidências"),
                            ("aspects", "Aspectos"),
                        ],
                    )
                )
            ],
            21,
        ),
        _markdown_cell(
            """
            ## 20. Aula 9 — entidades nomeadas de domínio

            O esquema de entidades foi adaptado ao domínio de receitas: `INGREDIENT`, `UTENSIL`, `CATEGORY`, `QUANTITY`, `UNIT`, `DURATION` e `TEMPERATURE`. Campos estruturados funcionam como gazetteers confiáveis; expressões regulares reconhecem medidas, tempos e temperaturas. A coluna BIO mostra o início da entidade.
            """
        ),
        _code_cell(
            """
            entidades = (linguistica or {}).get("entities", [])
            display(HTML("Entidades de domínio já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        entity_rows,
                        [
                            ("title", "Receita"),
                            ("field_name", "Campo"),
                            ("position", "Posição"),
                            ("entity_text", "Entidade"),
                            ("entity_type", "Tipo"),
                            ("normalized_value", "Valor normalizado"),
                            ("bio_tag", "BIO"),
                            ("extraction_method", "Método"),
                        ],
                    )
                )
            ],
            22,
        ),
        _markdown_cell(
            """
            ## 21. Aula 9 — extração de relações

            As relações são armazenadas como `(sujeito, relação, objeto)`. As triplas estruturais têm confiança 1, pois vêm de ingredientes, utensílios e categorias já extraídos. As triplas ação–objeto recebem confiança menor porque resultam do parser raso.
            """
        ),
        _code_cell(
            """
            relacoes = (linguistica or {}).get("relations", [])
            display(HTML("Relações semânticas já exibidas no output."))
            """,
            [
                _html_output(
                    _html_table(
                        relation_rows,
                        [
                            ("title", "Receita"),
                            ("subject", "Sujeito"),
                            ("relation", "Relação"),
                            ("object", "Objeto"),
                            ("confidence", "Confiança"),
                            ("extraction_method", "Método"),
                        ],
                    )
                )
            ],
            23,
        ),
        _markdown_cell(
            """
            ## Como estudar este notebook

            - Primeiro veja os dados coletados e os filtros.
            - Depois compare texto bruto, texto limpo e tokens.
            - Em seguida veja os termos com maior TF-IDF e o mapa 3D.
            - Por fim, leia a etapa de embeddings, a busca semântica e a comparação entre vetores estáticos e contextuais.
            - Na aula 8, observe como rótulos transformam representação em decisão e por que métricas exigem dados de teste.
            - Na aula 9, acompanhe a passagem de texto livre para dependências, sentimentos, entidades e triplas estruturadas.
            """
        ),
    ]

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
                "version": sys.version.split()[0],
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    output.write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
