from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from scraper.database import connect_database, distinct_filter_values, initialize_database, query_recipes, recipe_details
from scraper.text_embeddings import latest_embedding_analysis
from scraper.text_analysis import latest_text_analysis


DATABASE_PATH = Path(__file__).resolve().parent / "data" / "recipes.sqlite"
FILTER_STATE_DEFAULTS = {
    "filter_search": "",
    "filter_difficulty": "",
    "filter_cost": "",
    "filter_max_time": 0,
    "filter_min_rating": 0.0,
    "filter_category": "",
}


def _open_database() -> sqlite3.Connection:
    connection = connect_database(DATABASE_PATH)
    initialize_database(connection)
    return connection


def _recipe_label(row: sqlite3.Row) -> str:
    rating = f"{row['rating_value']:.1f}/5" if row["rating_value"] is not None else "sem nota"
    return f"{row['title']} — {rating}"


def _show_details(details: dict[str, object]) -> None:
    st.subheader(str(details["title"]))
    st.caption(str(details.get("description") or ""))
    if details.get("url"):
        st.link_button("Abrir receita original", str(details["url"]))

    metric_columns = st.columns(5)
    metric_columns[0].metric("Avaliação", f"{details['rating_value']}/5" if details["rating_value"] is not None else "—")
    metric_columns[1].metric("Avaliações", details["ratings_count"] or "—")
    metric_columns[2].metric("Tempo", f"{details['prep_time_minutes']} min" if details["prep_time_minutes"] is not None else "—")
    metric_columns[3].metric("Dificuldade", details["difficulty"] or "—")
    metric_columns[4].metric("Custo", details["cost_label"] or "—")

    st.caption(f"Coletada em {details['retrieved_at']} · parser {details['parser_version']}")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Ingredientes")
        for ingredient in details["ingredients"]:
            st.markdown(f"- {ingredient}")
        st.markdown("#### Utensílios")
        for utensil in details["utensils"]:
            st.markdown(f"- {utensil}")
    with right:
        st.markdown("#### Modo de preparo")
        for position, step in enumerate(details["preparation_steps"], 1):
            st.markdown(f"{position}. {step}")
        st.markdown("#### Categorias relacionadas")
        categories = details["related_categories"]
        st.write(", ".join(str(category["name"]) for category in categories) or "Nenhuma informada")

    prepared_texts = details.get("prepared_texts") or []
    if prepared_texts:
        with st.expander("Preparação dos textos"):
            first = prepared_texts[0]
            st.caption(f"Pipeline {first['pipeline_version']} · {len(prepared_texts)} unidade(s) preparada(s)")
            st.dataframe(
                [
                    {
                        "Campo": row["field_name"],
                        "Posição": row["position"],
                        "Bruto": row["raw_text"],
                        "Limpo": row["clean_text"],
                        "Tokens": ", ".join(json.loads(row["content_tokens_json"])),
                    }
                    for row in prepared_texts
                ],
                width="stretch",
                hide_index=True,
            )


def _render_3d_recipe_map(documents: list[dict[str, object]]) -> None:
    if not documents:
        return
    points = [
        {
            "title": str(row["title"]),
            "cluster": int(row["cluster_label"]),
            "x": float(row["x"]),
            "y": float(row["y"]),
            "z": float(row["z"]),
            "terms": ", ".join(item["term"] for item in row["top_terms_data"][:6]),
        }
        for row in documents
    ]
    points_json = json.dumps(points, ensure_ascii=False).replace("</", "<\\/")
    components.html(
        f"""
        <div class="map3d-wrap">
          <canvas id="recipe-map-3d" width="920" height="520" aria-label="Mapa 3D das receitas"></canvas>
          <div id="recipe-map-info">
            <strong>Mapa 3D das receitas</strong>
            <span>Arraste para girar. As cores indicam clusters.</span>
          </div>
        </div>
        <style>
          .map3d-wrap {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) 260px;
            gap: 12px;
            align-items: stretch;
            width: 100%;
            min-height: 520px;
          }}
          #recipe-map-3d {{
            width: 100%;
            height: 520px;
            border: 1px solid #d9dbe3;
            border-radius: 8px;
            background: #fbfcff;
          }}
          #recipe-map-info {{
            border: 1px solid #d9dbe3;
            border-radius: 8px;
            padding: 14px;
            color: #252936;
            font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #ffffff;
          }}
          #recipe-map-info strong, #recipe-map-info span {{
            display: block;
          }}
          #recipe-map-info span {{
            margin-top: 8px;
            color: #596174;
          }}
          @media (max-width: 760px) {{
            .map3d-wrap {{ grid-template-columns: 1fr; }}
            #recipe-map-3d {{ height: 420px; }}
          }}
        </style>
        <script>
        (() => {{
          const points = {points_json};
          const canvas = document.getElementById("recipe-map-3d");
          const ctx = canvas.getContext("2d");
          const info = document.getElementById("recipe-map-info");
          const colors = ["#1763dc", "#00856f", "#ab571e", "#8455a1", "#b42318", "#126d89"];
          let angleX = -0.55;
          let angleY = 0.75;
          let dragging = false;
          let lastX = 0;
          let lastY = 0;
          let projected = [];

          function resize() {{
            const ratio = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = Math.max(600, Math.floor(rect.width * ratio));
            canvas.height = Math.max(360, Math.floor(rect.height * ratio));
            draw();
          }}

          function extent(axis) {{
            const values = points.map((point) => point[axis]);
            const min = Math.min(...values);
            const max = Math.max(...values);
            const span = Math.max(max - min, 1e-9);
            return points.map((point) => ((point[axis] - min) / span - 0.5) * 2);
          }}

          const nx = extent("x");
          const ny = extent("y");
          const nz = extent("z");

          function rotate(point) {{
            const cx = Math.cos(angleX);
            const sx = Math.sin(angleX);
            const cy = Math.cos(angleY);
            const sy = Math.sin(angleY);
            const y1 = point.y * cx - point.z * sx;
            const z1 = point.y * sx + point.z * cx;
            const x2 = point.x * cy + z1 * sy;
            const z2 = -point.x * sy + z1 * cy;
            return {{ x: x2, y: y1, z: z2 }};
          }}

          function project(point) {{
            const rotated = rotate(point);
            const scale = 0.84 / (1.8 - rotated.z * 0.38);
            const size = Math.min(canvas.width, canvas.height) * 0.36;
            return {{
              x: canvas.width / 2 + rotated.x * size * scale,
              y: canvas.height / 2 + rotated.y * size * scale,
              z: rotated.z,
              scale
            }};
          }}

          function drawAxis(label, point, color) {{
            const origin = project({{ x: 0, y: 0, z: 0 }});
            const end = project(point);
            ctx.strokeStyle = color;
            ctx.fillStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(origin.x, origin.y);
            ctx.lineTo(end.x, end.y);
            ctx.stroke();
            ctx.fillText(label, end.x + 6, end.y - 6);
          }}

          function draw() {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.font = `${{13 * (window.devicePixelRatio || 1)}}px system-ui, sans-serif`;
            drawAxis("X", {{ x: 1.18, y: 0, z: 0 }}, "#687083");
            drawAxis("Y", {{ x: 0, y: 1.18, z: 0 }}, "#687083");
            drawAxis("Z", {{ x: 0, y: 0, z: 1.18 }}, "#687083");
            projected = points.map((point, index) => {{
              const coords = project({{ x: nx[index], y: ny[index], z: nz[index] }});
              return {{ ...point, ...coords }};
            }}).sort((a, b) => a.z - b.z);
            for (const point of projected) {{
              const radius = Math.max(6, 11 * point.scale) * (window.devicePixelRatio || 1);
              ctx.beginPath();
              ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
              ctx.fillStyle = colors[point.cluster % colors.length];
              ctx.fill();
              ctx.strokeStyle = "#ffffff";
              ctx.lineWidth = 2;
              ctx.stroke();
            }}
          }}

          function nearest(clientX, clientY) {{
            const rect = canvas.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            const x = (clientX - rect.left) * ratio;
            const y = (clientY - rect.top) * ratio;
            let best = null;
            let bestDistance = Infinity;
            for (const point of projected) {{
              const distance = Math.hypot(point.x - x, point.y - y);
              if (distance < bestDistance) {{
                best = point;
                bestDistance = distance;
              }}
            }}
            return bestDistance <= 24 * ratio ? best : null;
          }}

          canvas.addEventListener("pointerdown", (event) => {{
            dragging = true;
            lastX = event.clientX;
            lastY = event.clientY;
            canvas.setPointerCapture(event.pointerId);
          }});
          canvas.addEventListener("pointermove", (event) => {{
            if (dragging) {{
              angleY += (event.clientX - lastX) * 0.01;
              angleX += (event.clientY - lastY) * 0.01;
              lastX = event.clientX;
              lastY = event.clientY;
              draw();
              return;
            }}
            const point = nearest(event.clientX, event.clientY);
            if (point) {{
              const title = document.createElement("strong");
              const cluster = document.createElement("span");
              const terms = document.createElement("span");
              title.textContent = point.title;
              cluster.textContent = `Cluster ${{point.cluster}}`;
              terms.textContent = point.terms || "Sem termos principais";
              info.replaceChildren(title, cluster, terms);
            }}
          }});
          canvas.addEventListener("pointerup", () => {{ dragging = false; }});
          canvas.addEventListener("pointerleave", () => {{ dragging = false; }});
          window.addEventListener("resize", resize);
          resize();
        }})();
        </script>
        """,
        height=560,
    )


def _show_text_analysis(analysis: dict[str, object] | None) -> None:
    if not analysis:
        st.info("Análise textual ainda não gerada. Rode `.\\.venv\\bin\\python.exe -m scraper analyze-texts`.")
        return

    run = analysis["run"]
    documents = analysis["documents"]
    similarities = analysis["similarities"]
    with st.expander("Análise textual: TF-IDF, similaridade, clusters e projeção 3D"):
        st.caption(
            f"Execução {run['id']} · {run['document_count']} documento(s) · "
            f"{run['vocabulary_size']} termo(s) · modelo {run['model_version']}"
        )
        _render_3d_recipe_map(documents)
        st.dataframe(
            [
                {
                    "Receita": row["title"],
                    "Cluster": row["cluster_label"],
                    "X": round(float(row["x"]), 4),
                    "Y": round(float(row["y"]), 4),
                    "Z": round(float(row["z"]), 4),
                    "Termos principais": ", ".join(item["term"] for item in row["top_terms_data"][:6]),
                }
                for row in documents
            ],
            width="stretch",
            hide_index=True,
        )
        if similarities:
            st.markdown("#### Vizinhos por cosseno")
            st.dataframe(
                [
                    {
                        "Receita": row["recipe_title"],
                        "Vizinha": row["neighbor_title"],
                        "Rank": row["rank"],
                        "Cosseno": round(float(row["cosine_similarity"]), 4),
                    }
                    for row in similarities
                ],
                width="stretch",
                hide_index=True,
            )


def _show_embedding_analysis(analysis: dict[str, object] | None) -> None:
    if not analysis:
        st.info("Embeddings ainda não gerados. Rode `.\\.venv\\bin\\python.exe -m scraper build-embeddings`.")
        return

    run = analysis["run"]
    documents = analysis["documents"]
    similarities = analysis["similarities"]
    words = analysis["words"]
    with st.expander("Etapa 7: embeddings densos por contexto"):
        st.caption(
            f"Execução {run['id']} · {run['document_count']} documento(s) · "
            f"{run['vocabulary_size']} termo(s) · dimensão {run['dimension']} · "
            f"janela {run['window_size']} · modelo {run['model_version']}"
        )
        st.dataframe(
            [
                {
                    "Receita": row["title"],
                    "Norma": round(float(row["norm"]), 4),
                    "Tokens principais": ", ".join(item["token"] for item in row["top_tokens"][:8]),
                }
                for row in documents
            ],
            width="stretch",
            hide_index=True,
        )
        if similarities:
            st.markdown("#### Vizinhos por embeddings")
            st.dataframe(
                [
                    {
                        "Receita": row["recipe_title"],
                        "Vizinha": row["neighbor_title"],
                        "Rank": row["rank"],
                        "Cosseno": round(float(row["cosine_similarity"]), 4),
                    }
                    for row in similarities
                ],
                width="stretch",
                hide_index=True,
            )
        if words:
            st.markdown("#### Amostra de contextos aprendidos")
            st.dataframe(
                [
                    {
                        "Termo": row["term"],
                        "Contextos": ", ".join(item["context"] for item in row["top_contexts"][:5]),
                    }
                    for row in words
                ],
                width="stretch",
                hide_index=True,
            )


def _reset_filters() -> None:
    for key, value in FILTER_STATE_DEFAULTS.items():
        st.session_state[key] = value


def main() -> None:
    st.set_page_config(page_title="Receitas acadêmicas", page_icon="🍲", layout="wide")
    st.title("🍲 Receitas do TudoGostoso")
    st.write("Busca e filtros sobre o banco local da coleta acadêmica.")

    if not DATABASE_PATH.exists():
        st.warning(f"Banco não encontrado em `{DATABASE_PATH}`.")
        st.code(".\\.venv\\bin\\python.exe -m scraper fixture")
        st.info("Carregue a fixture local ou execute uma coleta autorizada antes de abrir a aplicação.")
        return

    connection = _open_database()
    try:
        filters = distinct_filter_values(connection)
        with st.sidebar:
            st.header("Filtros")
            st.button("Limpar filtros", on_click=_reset_filters, use_container_width=True)
            search = st.text_input(
                "Buscar",
                placeholder="carne, panela, cebola...",
                key="filter_search",
            )
            difficulty = st.selectbox(
                "Dificuldade",
                ["", *filters["difficulties"]],
                format_func=lambda value: "Todas" if not value else str(value),
                key="filter_difficulty",
            )
            cost = st.selectbox(
                "Custo",
                ["", *filters["costs"]],
                format_func=lambda value: "Todos" if not value else str(value),
                key="filter_cost",
            )
            max_time_value = st.number_input(
                "Tempo máximo (minutos)",
                min_value=0,
                step=5,
                key="filter_max_time",
                help="Use 0 para não limitar o tempo.",
            )
            min_rating_value = st.slider(
                "Avaliação mínima",
                min_value=0.0,
                max_value=5.0,
                step=0.5,
                key="filter_min_rating",
            )
            category_labels = {"": "Todas"}
            category_ids = [""]
            for item in filters["categories"]:
                category_id = str(item["site_category_id"])
                category_ids.append(category_id)
                category_labels[category_id] = str(item["name"])
            category_id = st.selectbox(
                "Categoria",
                category_ids,
                format_func=lambda value: category_labels.get(str(value), str(value)),
                key="filter_category",
            )

        rows = query_recipes(
            connection,
            search=search,
            difficulty=difficulty,
            cost_label=cost,
            max_time=max_time_value or None,
            min_rating=min_rating_value or None,
            category_id=category_id,
        )
        _show_text_analysis(latest_text_analysis(connection))
        _show_embedding_analysis(latest_embedding_analysis(connection))
        st.subheader(f"{len(rows)} receita(s) encontrada(s)")
        if not rows:
            st.info("Nenhuma receita corresponde aos filtros atuais.")
            return

        st.dataframe(
            [
                {
                    "Receita": row["title"],
                    "Avaliação": row["rating_value"],
                    "Avaliações": row["ratings_count"],
                    "Tempo (min)": row["prep_time_minutes"],
                    "Dificuldade": row["difficulty"],
                    "Custo": row["cost_label"],
                }
                for row in rows
            ],
            width="stretch",
            hide_index=True,
        )

        selected_id = st.selectbox(
            "Ver detalhes",
            options=[""] + [str(row["site_recipe_id"]) for row in rows],
            format_func=lambda value: "Selecione uma receita" if not value else _recipe_label(next(row for row in rows if str(row["site_recipe_id"]) == value)),
        )
        if selected_id:
            details = recipe_details(connection, selected_id)
            if details:
                st.divider()
                _show_details(details)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
