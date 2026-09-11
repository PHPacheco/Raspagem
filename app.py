from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import streamlit as st

from scraper.database import connect_database, distinct_filter_values, query_recipes, recipe_details


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
