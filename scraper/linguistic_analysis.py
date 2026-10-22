from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from .database import utc_now
from .text_utils import lemmatize_token, normalize_text, tokenize_words


LINGUISTIC_VERSION = "pln-aula-9-domain-rules-v1"
COOKING_VERBS = {
    "adicionar", "assar", "bater", "cobrir", "colocar", "cozinhar", "cortar",
    "deixar", "despejar", "fatiar", "ferver", "fritar", "juntar", "levar",
    "mexer", "misturar", "picar", "refogar", "retirar", "servir", "temperar",
}
VERB_FORMS = {
    "adicione": "adicionar", "asse": "assar", "bata": "bater", "cubra": "cobrir",
    "coloque": "colocar", "cozinhe": "cozinhar", "corte": "cortar", "deixe": "deixar",
    "despeje": "despejar", "fatie": "fatiar", "ferva": "ferver", "frite": "fritar",
    "junte": "juntar", "leve": "levar", "mexa": "mexer", "misture": "misturar",
    "pique": "picar", "refogue": "refogar", "retire": "retirar", "sirva": "servir",
    "tempere": "temperar",
}
DETERMINERS = {"a", "as", "o", "os", "um", "uma", "uns", "umas"}
PREPOSITIONS = {"a", "ate", "com", "da", "das", "de", "do", "dos", "em", "na", "nas", "no", "nos", "para", "por", "sobre"}
NEGATIONS = {"nao", "nunca", "jamais", "sem"}
INTENSIFIERS = {"bem": 1.25, "muito": 1.5, "super": 1.5, "extremamente": 2.0}
POSITIVE_WORDS = {
    "bom": 1.0, "delicioso": 1.5, "excelente": 2.0, "facil": 1.0,
    "macio": 1.0, "otimo": 1.7, "perfeito": 2.0, "rapido": 0.8,
    "saboroso": 1.5, "crocante": 0.8,
}
NEGATIVE_WORDS = {
    "amargo": -1.0, "azedo": -1.0, "caro": -0.8, "demorado": -0.8,
    "dificil": -1.0, "lento": -0.8, "queimado": -1.5, "ruim": -1.5,
    "salgado": -0.8, "seco": -0.8,
}
ASPECT_TERMS = {
    "sabor": {"sabor", "gosto", "delicioso", "saboroso", "amargo", "azedo", "salgado"},
    "textura": {"textura", "macio", "crocante", "seco"},
    "tempo": {"tempo", "rapido", "lento", "demorado", "minuto", "hora"},
    "custo": {"custo", "preco", "barato", "caro"},
    "preparo": {"preparo", "facil", "dificil", "simples", "complexo"},
}
UNIT_PATTERN = r"(?:kg|g|mg|l|ml|x[ií]caras?|colheres?|unidades?|dentes?|pitadas?|latas?|pacotes?)"
NUMBER_PATTERN = r"(?:\d+\s*/\s*\d+|\d+(?:[.,]\d+)?)"
QUANTITY_RE = re.compile(rf"\b{NUMBER_PATTERN}\b", re.IGNORECASE)
UNIT_RE = re.compile(rf"\b{UNIT_PATTERN}\b", re.IGNORECASE)
DURATION_RE = re.compile(rf"\b{NUMBER_PATTERN}\s*(?:minutos?|horas?)\b", re.IGNORECASE)
TEMPERATURE_RE = re.compile(r"\b\d{2,3}\s*°?\s*[cC]\b")


@dataclass(frozen=True)
class Dependency:
    token_index: int
    token: str
    lemma: str
    head_index: int | None
    relation: str


@dataclass(frozen=True)
class Entity:
    start_char: int
    end_char: int
    text: str
    entity_type: str
    normalized_value: str
    bio_tag: str
    extraction_method: str


def _lemma(token: str) -> str:
    normalized = normalize_text(token)
    return VERB_FORMS.get(normalized, lemmatize_token(normalized))


def shallow_dependency_parse(text: str) -> list[Dependency]:
    tokens = tokenize_words(text)
    if not tokens:
        return []
    lemmas = [_lemma(token) for token in tokens]
    root_index = next((index for index, lemma in enumerate(lemmas) if lemma in COOKING_VERBS), 0)
    object_assigned = False
    result: list[Dependency] = []
    for index, (token, lemma) in enumerate(zip(tokens, lemmas)):
        if index == root_index:
            relation, head = "root", None
        elif token in DETERMINERS:
            relation, head = "det", min(index + 1, len(tokens) - 1)
        elif token in PREPOSITIONS:
            relation, head = "case", min(index + 1, len(tokens) - 1)
        elif index < root_index:
            relation, head = "nsubj", root_index
        elif not object_assigned:
            relation, head = "obj", root_index
            object_assigned = True
        else:
            relation, head = "nmod", root_index
        result.append(Dependency(index, token, lemma, head, relation))
    return result


def analyze_sentiment(text: str) -> dict[str, Any]:
    tokens = tokenize_words(text)
    evidence = []
    total = 0.0
    for index, token in enumerate(tokens):
        base = POSITIVE_WORDS.get(token, NEGATIVE_WORDS.get(token))
        if base is None:
            continue
        previous = tokens[max(0, index - 3):index]
        negated = any(item in NEGATIONS for item in previous)
        intensity = max((INTENSIFIERS.get(item, 1.0) for item in previous), default=1.0)
        contribution = base * intensity * (-1.0 if negated else 1.0)
        total += contribution
        evidence.append(
            {
                "token": token,
                "base": base,
                "negated": negated,
                "intensity": intensity,
                "contribution": contribution,
            }
        )
    score = max(-1.0, min(1.0, total / max(1.0, len(evidence) * 1.5)))
    polarity = "positivo" if score > 0.1 else "negativo" if score < -0.1 else "neutro"
    subjectivity = min(1.0, len(evidence) / max(1, len(tokens)) * 4)
    aspects = [
        {"aspect": aspect, "polarity": polarity, "score": score}
        for aspect, terms in ASPECT_TERMS.items()
        if any(token in terms for token in tokens)
    ]
    return {
        "polarity": polarity,
        "score": score,
        "subjectivity": subjectivity,
        "evidence": evidence,
        "aspects": aspects,
    }


def _regex_entities(text: str) -> list[Entity]:
    entities: list[Entity] = []
    specifications = (
        (DURATION_RE, "DURATION"),
        (TEMPERATURE_RE, "TEMPERATURE"),
        (QUANTITY_RE, "QUANTITY"),
        (UNIT_RE, "UNIT"),
    )
    occupied: set[tuple[int, int, str]] = set()
    for pattern, entity_type in specifications:
        for match in pattern.finditer(text):
            key = (match.start(), match.end(), entity_type)
            if key in occupied:
                continue
            occupied.add(key)
            entities.append(
                Entity(
                    match.start(),
                    match.end(),
                    match.group(0),
                    entity_type,
                    normalize_text(match.group(0)),
                    f"B-{entity_type}",
                    "domain_regex",
                )
            )
    return sorted(entities, key=lambda item: (item.start_char, item.end_char, item.entity_type))


def _ingredient_name(text: str) -> str:
    value = QUANTITY_RE.sub(" ", text)
    value = UNIT_RE.sub(" ", value)
    value = re.sub(r"\b(?:de|da|do|a|gosto|picad[oa]s?|fatiad[oa]s?)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" ,.-")
    return value or text.strip()


def extract_domain_entities(field_name: str, text: str) -> list[Entity]:
    entities = _regex_entities(text)
    entity_type = None
    normalized_value = ""
    if field_name == "ingredient":
        entity_type = "INGREDIENT"
        normalized_value = normalize_text(_ingredient_name(text))
    elif field_name == "utensil":
        entity_type = "UTENSIL"
        normalized_value = normalize_text(text)
    elif field_name == "related_category":
        entity_type = "CATEGORY"
        normalized_value = normalize_text(text)
    if entity_type and text.strip():
        start = text.find(text.strip())
        entities.append(
            Entity(
                start,
                start + len(text.strip()),
                text.strip(),
                entity_type,
                normalized_value,
                f"B-{entity_type}",
                "structured_field",
            )
        )
    return sorted(entities, key=lambda item: (item.start_char, item.end_char, item.entity_type))


def _text_units(connection: sqlite3.Connection, recipe_id: str) -> Iterable[tuple[str, int, str]]:
    recipe = connection.execute(
        "SELECT title, description FROM recipes WHERE site_recipe_id = ?",
        (recipe_id,),
    ).fetchone()
    if recipe is None:
        return
    yield "title", 0, recipe["title"]
    if recipe["description"]:
        yield "description", 0, recipe["description"]
    for row in connection.execute(
        "SELECT position, raw_text FROM ingredients WHERE recipe_id = ? ORDER BY position",
        (recipe_id,),
    ):
        yield "ingredient", int(row["position"]), row["raw_text"]
    for row in connection.execute(
        "SELECT position, name FROM utensils WHERE recipe_id = ? ORDER BY position",
        (recipe_id,),
    ):
        yield "utensil", int(row["position"]), row["name"]
    for row in connection.execute(
        "SELECT position, raw_text FROM preparation_steps WHERE recipe_id = ? ORDER BY position",
        (recipe_id,),
    ):
        yield "preparation_step", int(row["position"]), row["raw_text"]
    for position, row in enumerate(
        connection.execute(
            """
            SELECT c.name FROM recipe_categories rc
            JOIN categories c ON c.site_category_id = rc.category_id
            WHERE rc.recipe_id = ? ORDER BY c.name COLLATE NOCASE
            """,
            (recipe_id,),
        ),
        1,
    ):
        yield "related_category", position, row["name"]


def run_linguistic_analysis(connection: sqlite3.Connection) -> int:
    recipe_rows = connection.execute(
        "SELECT site_recipe_id, title FROM recipes ORDER BY site_recipe_id"
    ).fetchall()
    dependency_rows = []
    sentiment_rows = []
    entity_rows = []
    relation_rows = []
    sentence_count = 0

    cursor = connection.execute(
        """
        INSERT INTO linguistic_analysis_runs
            (model_version, document_count, sentence_count, dependency_count,
             sentiment_count, entity_count, relation_count, created_at)
        VALUES (?, ?, 0, 0, 0, 0, 0, ?)
        """,
        (LINGUISTIC_VERSION, len(recipe_rows), utc_now()),
    )
    run_id = int(cursor.lastrowid)

    for recipe in recipe_rows:
        recipe_id = recipe["site_recipe_id"]
        recipe_title = recipe["title"]
        for field_name, position, text in _text_units(connection, recipe_id):
            sentiment = analyze_sentiment(text)
            sentiment_rows.append(
                (
                    run_id, recipe_id, field_name, position, text,
                    sentiment["polarity"], sentiment["score"], sentiment["subjectivity"],
                    json.dumps(sentiment["evidence"], ensure_ascii=False),
                    json.dumps(sentiment["aspects"], ensure_ascii=False),
                )
            )
            entities = extract_domain_entities(field_name, text)
            for entity in entities:
                entity_rows.append(
                    (
                        run_id, recipe_id, field_name, position, entity.start_char, entity.end_char,
                        entity.text, entity.entity_type, entity.normalized_value,
                        entity.bio_tag, entity.extraction_method,
                    )
                )
                if entity.entity_type == "INGREDIENT":
                    relation_rows.append((run_id, recipe_id, recipe_title, "tem_ingrediente", entity.normalized_value, field_name, position, 1.0, "structured_field"))
                elif entity.entity_type == "UTENSIL":
                    relation_rows.append((run_id, recipe_id, recipe_title, "usa_utensilio", entity.normalized_value, field_name, position, 1.0, "structured_field"))
                elif entity.entity_type == "CATEGORY":
                    relation_rows.append((run_id, recipe_id, recipe_title, "pertence_categoria", entity.normalized_value, field_name, position, 1.0, "structured_field"))

            if field_name == "preparation_step":
                sentence_index = sentence_count
                dependencies = shallow_dependency_parse(text)
                sentence_count += 1
                for dependency in dependencies:
                    dependency_rows.append(
                        (
                            run_id, recipe_id, sentence_index, dependency.token_index,
                            dependency.token, dependency.lemma, dependency.head_index,
                            dependency.relation, text,
                        )
                    )
                root = next((item for item in dependencies if item.relation == "root"), None)
                obj = next((item for item in dependencies if item.relation == "obj"), None)
                if root and obj:
                    relation_rows.append((run_id, recipe_id, recipe_title, root.lemma, obj.lemma, field_name, position, 0.65, "shallow_dependency"))

    connection.executemany(
        """
        INSERT INTO syntactic_dependencies
            (run_id, recipe_id, sentence_index, token_index, token, lemma,
             head_index, relation, source_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        dependency_rows,
    )
    connection.executemany(
        """
        INSERT INTO sentiment_analyses
            (run_id, recipe_id, field_name, position, source_text, polarity,
             score, subjectivity, evidence_json, aspects_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        sentiment_rows,
    )
    connection.executemany(
        """
        INSERT INTO named_entities
            (run_id, recipe_id, field_name, position, start_char, end_char,
             entity_text, entity_type, normalized_value, bio_tag, extraction_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        entity_rows,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO semantic_relations
            (run_id, recipe_id, subject, relation, object, source_field,
             source_position, confidence, extraction_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        relation_rows,
    )
    relation_count = connection.execute(
        "SELECT COUNT(*) AS count FROM semantic_relations WHERE run_id = ?",
        (run_id,),
    ).fetchone()["count"]
    connection.execute(
        """
        UPDATE linguistic_analysis_runs
        SET sentence_count = ?, dependency_count = ?, sentiment_count = ?,
            entity_count = ?, relation_count = ?
        WHERE id = ?
        """,
        (sentence_count, len(dependency_rows), len(sentiment_rows), len(entity_rows), relation_count, run_id),
    )
    connection.commit()
    return run_id


def latest_linguistic_analysis(connection: sqlite3.Connection) -> dict[str, Any] | None:
    run = connection.execute(
        "SELECT * FROM linguistic_analysis_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return None
    run_id = int(run["id"])
    dependencies = [
        dict(row)
        for row in connection.execute(
            """
            SELECT sd.*, r.title FROM syntactic_dependencies sd
            JOIN recipes r ON r.site_recipe_id = sd.recipe_id
            WHERE sd.run_id = ? ORDER BY sd.recipe_id, sd.sentence_index, sd.token_index
            """,
            (run_id,),
        )
    ]
    sentiments = []
    for row in connection.execute(
        """
        SELECT sa.*, r.title FROM sentiment_analyses sa
        JOIN recipes r ON r.site_recipe_id = sa.recipe_id
        WHERE sa.run_id = ? ORDER BY sa.recipe_id, sa.field_name, sa.position
        """,
        (run_id,),
    ):
        sentiments.append({**dict(row), "evidence": json.loads(row["evidence_json"]), "aspects": json.loads(row["aspects_json"])})
    entities = [
        dict(row)
        for row in connection.execute(
            """
            SELECT ne.*, r.title FROM named_entities ne
            JOIN recipes r ON r.site_recipe_id = ne.recipe_id
            WHERE ne.run_id = ? ORDER BY ne.recipe_id, ne.field_name, ne.position, ne.start_char
            """,
            (run_id,),
        )
    ]
    relations = [
        dict(row)
        for row in connection.execute(
            """
            SELECT sr.*, r.title FROM semantic_relations sr
            JOIN recipes r ON r.site_recipe_id = sr.recipe_id
            WHERE sr.run_id = ? ORDER BY sr.recipe_id, sr.source_field, sr.source_position, sr.relation
            """,
            (run_id,),
        )
    ]
    return {
        "run": dict(run),
        "dependencies": dependencies,
        "sentiments": sentiments,
        "entities": entities,
        "relations": relations,
    }
