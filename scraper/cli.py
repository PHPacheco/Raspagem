from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import PARSER_VERSION, USER_AGENT
from .category_parser import parse_category_page, page_url
from .database import (
    connect_database,
    create_scrape_run,
    finish_scrape_run,
    initialize_database,
    listing_count,
    recipe_count,
    rebuild_text_preparations,
    save_listing,
    save_recipe,
)
from .http_client import AcademicHttpClient, RecipeAuthorizationRequired, RobotsBlocked
from .recipe_parser import parse_recipe
from .text_utils import canonical_url, site_category_id_from_url


DEFAULT_CATEGORY_URL = "https://www.tudogostoso.com.br/categorias/1004-carnes"
DEFAULT_RECIPE_URL = "https://www.tudogostoso.com.br/receita/1438-carne-de-panela-de-pressao.html"
DEFAULT_DATABASE = "data/recipes.sqlite"


def _category_id(url: str) -> str:
    return site_category_id_from_url(url) or f"url:{canonical_url(url)}"


def _category_name(url: str) -> str:
    path_part = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = path_part.split("-", 1)[-1] if "-" in path_part else path_part
    return slug.replace("-", " ").strip().title() or "Categoria"


def _ensure_parent(path: Path) -> None:
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)


def _log_path(value: str | None, run_id: int) -> Path:
    path = Path(value) if value else Path("logs") / f"run-{run_id}.jsonl"
    _ensure_parent(path)
    return path


def _write_log(path: Path, event: str, **details: object) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _open_database(path_value: str):
    path = Path(path_value)
    _ensure_parent(path)
    connection = connect_database(path)
    initialize_database(connection)
    return connection


def collect(args: argparse.Namespace) -> int:
    if args.max_pages <= 0:
        raise ValueError("--max-pages deve ser maior que zero.")
    connection = _open_database(args.database)
    run_id = create_scrape_run(
        connection,
        category_url=canonical_url(args.category_url),
        max_pages=args.max_pages,
        user_agent=USER_AGENT,
        parser_version=PARSER_VERSION,
    )
    log_path = _log_path(args.log_file, run_id)
    client = AcademicHttpClient(
        delay_seconds=args.delay,
        allow_authorized_recipe_pages=args.allow_authorized_recipe_pages,
        override_robots_with_permission=args.override_robots_with_permission,
    )
    category_id = _category_id(args.category_url)
    category_name = _category_name(args.category_url)
    links_by_key = {}
    errors = 0
    saved_recipes = 0
    try:
        for page_number in range(1, args.max_pages + 1):
            current_url = page_url(args.category_url, page_number)
            try:
                response = client.fetch(current_url, resource_kind="category")
                category_page = parse_category_page(
                    response.text,
                    response.url,
                    page_number=page_number,
                )
            except Exception as exc:  # page failures are recorded and end discovery
                errors += 1
                _write_log(log_path, "category_error", page=page_number, url=current_url, error=str(exc))
                break

            for link in category_page.recipe_links:
                save_listing(
                    connection,
                    run_id=run_id,
                    category_id=category_id,
                    category_name=category_name,
                    category_url=canonical_url(args.category_url),
                    recipe_link=link,
                )
                key = link.site_recipe_id or link.url
                links_by_key.setdefault(key, link)
            connection.commit()
            _write_log(
                log_path,
                "category_page_ok",
                page=page_number,
                url=current_url,
                recipe_count=len(category_page.recipe_links),
            )
            if not category_page.has_next_page:
                break

        if not args.discover_only:
            for link in links_by_key.values():
                try:
                    response = client.fetch(link.url, resource_kind="recipe")
                    recipe = parse_recipe(response.text, response.url)
                    save_recipe(connection, recipe)
                    saved_recipes += 1
                    _write_log(
                        log_path,
                        "recipe_ok",
                        recipe_id=recipe.site_recipe_id,
                        url=recipe.url,
                        issues=recipe.issues,
                    )
                    if recipe.issues:
                        errors += 1
                except (RecipeAuthorizationRequired, RobotsBlocked) as exc:
                    errors += 1
                    _write_log(log_path, "recipe_blocked", url=link.url, error=str(exc))
                except Exception as exc:
                    errors += 1
                    _write_log(log_path, "recipe_error", url=link.url, error=str(exc))

        total_listings = listing_count(connection, run_id)
        status = "completed" if errors == 0 else ("blocked" if saved_recipes == 0 and not args.discover_only else "partial")
        finish_scrape_run(
            connection,
            run_id,
            status=status,
            listing_count=total_listings,
            recipe_count=saved_recipes,
            error_count=errors,
        )
        print(
            f"Execução {run_id}: {status}; {total_listings} listagens; "
            f"{saved_recipes} receitas detalhadas; {errors} ocorrências. Log: {log_path}"
        )
        return 2 if status == "blocked" else 0
    finally:
        client.close()
        connection.close()


def load_fixture(args: argparse.Namespace) -> int:
    connection = _open_database(args.database)
    run_id = create_scrape_run(
        connection,
        category_url=canonical_url(args.category_url),
        max_pages=1,
        user_agent=USER_AGENT,
        parser_version=PARSER_VERSION,
    )
    log_path = _log_path(args.log_file, run_id)
    category_html = Path(args.category_fixture).read_text(encoding="utf-8")
    category_page = parse_category_page(
        category_html,
        args.category_url,
        page_number=1,
    )
    category_id = _category_id(args.category_url)
    category_name = _category_name(args.category_url)
    for link in category_page.recipe_links:
        save_listing(
            connection,
            run_id=run_id,
            category_id=category_id,
            category_name=category_name,
            category_url=canonical_url(args.category_url),
            recipe_link=link,
        )

    recipe_html = Path(args.recipe_fixture).read_text(encoding="utf-8")
    recipe = parse_recipe(recipe_html, args.recipe_url)
    save_recipe(connection, recipe)
    _write_log(log_path, "fixture_recipe_ok", recipe_id=recipe.site_recipe_id, issues=recipe.issues)
    finish_scrape_run(
        connection,
        run_id,
        status="completed" if not recipe.issues else "partial",
        listing_count=listing_count(connection, run_id),
        recipe_count=recipe_count(connection),
        error_count=len(recipe.issues),
    )
    connection.close()
    print(f"Fixture carregada na execução {run_id}: {args.database}")
    return 0


def init_database(args: argparse.Namespace) -> int:
    connection = _open_database(args.database)
    connection.close()
    print(f"Banco inicializado: {args.database}")
    return 0


def prepare_database(args: argparse.Namespace) -> int:
    connection = _open_database(args.database)
    prepared_count = rebuild_text_preparations(connection)
    connection.close()
    print(f"Preparação de textos atualizada: {prepared_count} unidade(s) em {args.database}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coletor acadêmico de receitas")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="inicializa o schema SQLite")
    init_parser.add_argument("--database", default=DEFAULT_DATABASE)
    init_parser.set_defaults(handler=init_database)

    prepare_parser = subparsers.add_parser("prepare-db", help="reconstrói textos limpos, tokens e metadados de preparação")
    prepare_parser.add_argument("--database", default=DEFAULT_DATABASE)
    prepare_parser.set_defaults(handler=prepare_database)

    collect_parser = subparsers.add_parser("collect", help="descobre e coleta receitas")
    collect_parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    collect_parser.add_argument("--max-pages", type=int, default=1)
    collect_parser.add_argument("--database", default=DEFAULT_DATABASE)
    collect_parser.add_argument("--delay", type=float, default=2.0)
    collect_parser.add_argument("--log-file")
    collect_parser.add_argument("--discover-only", action="store_true", help="não acessa páginas de receita")
    collect_parser.add_argument(
        "--allow-authorized-recipe-pages",
        action="store_true",
        help="habilita receitas somente quando houver autorização específica",
    )
    collect_parser.add_argument(
        "--override-robots-with-permission",
        action="store_true",
        help="permite robots.txt desautorizado apenas com autorização escrita",
    )
    collect_parser.set_defaults(handler=collect)

    fixture_parser = subparsers.add_parser("fixture", help="carrega HTML local de teste")
    fixture_parser.add_argument("--category-fixture", default="tests/fixtures/category_page_1.html")
    fixture_parser.add_argument("--recipe-fixture", default="tests/fixtures/recipe_1438.html")
    fixture_parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    fixture_parser.add_argument("--recipe-url", default=DEFAULT_RECIPE_URL)
    fixture_parser.add_argument("--database", default=DEFAULT_DATABASE)
    fixture_parser.add_argument("--log-file")
    fixture_parser.set_defaults(handler=load_fixture)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
        return 2

