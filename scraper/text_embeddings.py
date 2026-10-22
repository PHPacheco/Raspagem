from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .database import utc_now
from .text_analysis import TextDocument, cosine_similarity, load_documents
from .text_utils import prepare_text


EMBEDDING_VERSION = "pln-aula-7-distributional-v1"


@dataclass(frozen=True)
class EmbeddingModel:
    documents: list[TextDocument]
    vocabulary: list[str]
    dimension: int
    window_size: int
    word_vectors: dict[str, list[float]]
    document_vectors: dict[str, list[float]]
    top_contexts: dict[str, list[dict[str, float]]]


@dataclass(frozen=True)
class ContextualOccurrence:
    token: str
    position: int
    context: list[str]
    vector: list[float]


def _hash_sign(term: str, index: int) -> float:
    digest = hashlib.sha256(f"{term}:{index}".encode("utf-8")).digest()
    return 1.0 if digest[0] % 2 == 0 else -1.0


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def _context_counts(
    documents: list[TextDocument],
    *,
    window_size: int,
) -> tuple[dict[str, Counter[str]], Counter[str], Counter[str], float]:
    cooccurrences: dict[str, Counter[str]] = defaultdict(Counter)
    term_totals: Counter[str] = Counter()
    context_totals: Counter[str] = Counter()
    total_weight = 0.0
    for document in documents:
        tokens = document.tokens
        for index, term in enumerate(tokens):
            for context_index in range(
                max(0, index - window_size),
                min(len(tokens), index + window_size + 1),
            ):
                if context_index == index:
                    continue
                context = tokens[context_index]
                distance = abs(index - context_index)
                weight = 1.0 / max(distance, 1)
                cooccurrences[term][context] += weight
                term_totals[term] += weight
                context_totals[context] += weight
                total_weight += weight
    return cooccurrences, term_totals, context_totals, total_weight


def _ppmi_contexts(
    cooccurrences: dict[str, Counter[str]],
    term_totals: Counter[str],
    context_totals: Counter[str],
    total_weight: float,
) -> dict[str, dict[str, float]]:
    if total_weight == 0.0:
        return {}
    result: dict[str, dict[str, float]] = {}
    for term, contexts in cooccurrences.items():
        result[term] = {}
        for context, count in contexts.items():
            denominator = float(term_totals[term]) * float(context_totals[context])
            if denominator == 0.0:
                continue
            pmi = math.log((float(count) * total_weight) / denominator)
            if pmi > 0:
                result[term][context] = pmi
    return result


def _project_context_vector(context_weights: dict[str, float], dimension: int) -> list[float]:
    if dimension <= 0:
        return []
    scale = 1.0 / math.sqrt(dimension)
    vector = [0.0] * dimension
    for context, weight in context_weights.items():
        for index in range(dimension):
            vector[index] += weight * _hash_sign(context, index) * scale
    return _normalize(vector)


def _mean_embedding(tokens: list[str], word_vectors: dict[str, list[float]], dimension: int) -> list[float]:
    vectors = [word_vectors[token] for token in tokens if token in word_vectors]
    if not vectors:
        return [0.0] * dimension
    return _normalize(
        [
            sum(vector[index] for vector in vectors) / len(vectors)
            for index in range(dimension)
        ]
    )


def embed_text(text: str, model: EmbeddingModel) -> tuple[list[float], list[str]]:
    """Representa uma consulta com o mesmo espaço vetorial aprendido no corpus."""
    prepared = prepare_text(text)
    tokens = [token for token in prepared.lemma_tokens if token in model.word_vectors]
    return _mean_embedding(tokens, model.word_vectors, model.dimension), tokens


def semantic_search(
    model: EmbeddingModel,
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Ordena documentos pela similaridade entre a consulta e seus embeddings."""
    query_vector, matched_tokens = embed_text(query, model)
    if not matched_tokens or not any(query_vector):
        return []
    ranked = [
        {
            "recipe_id": document.recipe_id,
            "title": document.title,
            "cosine_similarity": cosine_similarity(query_vector, model.document_vectors[document.recipe_id]),
            "matched_tokens": matched_tokens,
        }
        for document in model.documents
    ]
    return sorted(
        ranked,
        key=lambda item: (-float(item["cosine_similarity"]), str(item["recipe_id"])),
    )[: max(0, limit)]


def contextualize_tokens(
    tokens: list[str],
    model: EmbeddingModel,
    *,
    window_size: int | None = None,
    context_weight: float = 0.5,
) -> list[ContextualOccurrence]:
    """Cria vetores por ocorrência combinando o vetor estático ao contexto local.

    É uma composição didática, não um Transformer: a mesma palavra parte do
    embedding estático, mas recebe uma contribuição diferente de suas vizinhas.
    """
    window = max(1, window_size or model.window_size)
    weight = min(1.0, max(0.0, context_weight))
    occurrences: list[ContextualOccurrence] = []
    for position, token in enumerate(tokens):
        static_vector = model.word_vectors.get(token, [0.0] * model.dimension)
        context = [
            tokens[index]
            for index in range(max(0, position - window), min(len(tokens), position + window + 1))
            if index != position and tokens[index] in model.word_vectors
        ]
        context_vector = _mean_embedding(context, model.word_vectors, model.dimension)
        combined = _normalize(
            [
                (1.0 - weight) * static_vector[index] + weight * context_vector[index]
                for index in range(model.dimension)
            ]
        )
        occurrences.append(
            ContextualOccurrence(
                token=token,
                position=position,
                context=context,
                vector=combined,
            )
        )
    return occurrences


def contextual_similarity(left: ContextualOccurrence, right: ContextualOccurrence) -> float:
    return cosine_similarity(left.vector, right.vector)


def load_latest_embedding_model(connection: sqlite3.Connection) -> EmbeddingModel | None:
    run = connection.execute(
        "SELECT * FROM embedding_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return None
    run_id = int(run["id"])
    documents = load_documents(connection)
    word_rows = connection.execute(
        "SELECT term, vector_json, top_contexts_json FROM word_embeddings WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    word_vectors = {row["term"]: list(json.loads(row["vector_json"])) for row in word_rows}
    top_contexts = {row["term"]: list(json.loads(row["top_contexts_json"])) for row in word_rows}
    document_rows = connection.execute(
        "SELECT recipe_id, vector_json FROM document_embeddings WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    document_vectors = {
        row["recipe_id"]: list(json.loads(row["vector_json"]))
        for row in document_rows
    }
    return EmbeddingModel(
        documents=documents,
        vocabulary=sorted(word_vectors),
        dimension=int(run["dimension"]),
        window_size=int(run["window_size"]),
        word_vectors=word_vectors,
        document_vectors=document_vectors,
        top_contexts=top_contexts,
    )


def build_embedding_model(
    documents: list[TextDocument],
    *,
    dimension: int = 32,
    window_size: int = 2,
) -> EmbeddingModel:
    dimension = max(1, dimension)
    window_size = max(1, window_size)
    vocabulary = sorted({token for document in documents for token in document.tokens})
    cooccurrences, term_totals, context_totals, total_weight = _context_counts(
        documents,
        window_size=window_size,
    )
    contexts = _ppmi_contexts(cooccurrences, term_totals, context_totals, total_weight)
    word_vectors = {
        term: _project_context_vector(contexts.get(term, {}), dimension)
        for term in vocabulary
    }
    top_contexts = {
        term: [
            {"context": context, "weight": weight}
            for context, weight in sorted(
                contexts.get(term, {}).items(),
                key=lambda item: (-item[1], item[0]),
            )[:8]
        ]
        for term in vocabulary
    }
    document_vectors = {
        document.recipe_id: _mean_embedding(document.tokens, word_vectors, dimension)
        for document in documents
    }
    return EmbeddingModel(
        documents=documents,
        vocabulary=vocabulary,
        dimension=dimension,
        window_size=window_size,
        word_vectors=word_vectors,
        document_vectors=document_vectors,
        top_contexts=top_contexts,
    )


def nearest_embedding_neighbors(model: EmbeddingModel, *, limit: int = 5) -> dict[str, list[tuple[str, float]]]:
    limit = max(0, limit)
    result: dict[str, list[tuple[str, float]]] = {}
    for document in model.documents:
        vector = model.document_vectors[document.recipe_id]
        similarities = [
            (other.recipe_id, cosine_similarity(vector, model.document_vectors[other.recipe_id]))
            for other in model.documents
            if other.recipe_id != document.recipe_id
        ]
        result[document.recipe_id] = sorted(similarities, key=lambda item: (-item[1], item[0]))[:limit]
    return result


def _top_document_tokens(document: TextDocument, *, limit: int = 8) -> list[dict[str, Any]]:
    counts = Counter(document.tokens)
    return [
        {"token": token, "count": count}
        for token, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def run_embedding_analysis(
    connection: sqlite3.Connection,
    *,
    dimension: int = 32,
    window_size: int = 2,
    neighbor_count: int = 5,
) -> int:
    documents = load_documents(connection)
    model = build_embedding_model(documents, dimension=dimension, window_size=window_size)
    neighbors = nearest_embedding_neighbors(model, limit=neighbor_count)
    cursor = connection.execute(
        """
        INSERT INTO embedding_runs
            (model_version, document_count, vocabulary_size, dimension, window_size, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            EMBEDDING_VERSION,
            len(model.documents),
            len(model.vocabulary),
            model.dimension,
            model.window_size,
            utc_now(),
        ),
    )
    run_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO word_embeddings
            (run_id, term, vector_json, top_contexts_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            (
                run_id,
                term,
                json.dumps(model.word_vectors[term], ensure_ascii=False),
                json.dumps(model.top_contexts[term], ensure_ascii=False),
            )
            for term in model.vocabulary
        ),
    )
    connection.executemany(
        """
        INSERT INTO document_embeddings
            (run_id, recipe_id, vector_json, norm, top_tokens_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            (
                run_id,
                document.recipe_id,
                json.dumps(model.document_vectors[document.recipe_id], ensure_ascii=False),
                math.sqrt(sum(value * value for value in model.document_vectors[document.recipe_id])),
                json.dumps(_top_document_tokens(document), ensure_ascii=False),
            )
            for document in model.documents
        ),
    )
    similarity_rows = []
    for recipe_id, items in neighbors.items():
        for rank, (neighbor_id, similarity) in enumerate(items, 1):
            similarity_rows.append((run_id, recipe_id, neighbor_id, rank, similarity))
    connection.executemany(
        """
        INSERT INTO embedding_similarities
            (run_id, recipe_id, neighbor_recipe_id, rank, cosine_similarity)
        VALUES (?, ?, ?, ?, ?)
        """,
        similarity_rows,
    )
    connection.commit()
    return run_id


def latest_embedding_analysis(connection: sqlite3.Connection) -> dict[str, Any] | None:
    run = connection.execute(
        """
        SELECT *
        FROM embedding_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if run is None:
        return None
    run_id = int(run["id"])
    documents = [
        {
            **dict(row),
            "top_tokens": json.loads(row["top_tokens_json"]),
        }
        for row in connection.execute(
            """
            SELECT de.*, r.title
            FROM document_embeddings de
            JOIN recipes r ON r.site_recipe_id = de.recipe_id
            WHERE de.run_id = ?
            ORDER BY r.title COLLATE NOCASE
            """,
            (run_id,),
        )
    ]
    similarities = [
        dict(row)
        for row in connection.execute(
            """
            SELECT es.*, source.title AS recipe_title, neighbor.title AS neighbor_title
            FROM embedding_similarities es
            JOIN recipes source ON source.site_recipe_id = es.recipe_id
            JOIN recipes neighbor ON neighbor.site_recipe_id = es.neighbor_recipe_id
            WHERE es.run_id = ?
            ORDER BY es.recipe_id, es.rank
            """,
            (run_id,),
        )
    ]
    words = [
        {
            **dict(row),
            "top_contexts": json.loads(row["top_contexts_json"]),
        }
        for row in connection.execute(
            """
            SELECT term, top_contexts_json
            FROM word_embeddings
            WHERE run_id = ?
            ORDER BY term COLLATE NOCASE
            LIMIT 20
            """,
            (run_id,),
        )
    ]
    return {"run": dict(run), "documents": documents, "similarities": similarities, "words": words}
