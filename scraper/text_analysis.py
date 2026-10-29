from __future__ import annotations

import json
import math
import random
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .database import utc_now


ANALYSIS_VERSION = "pln-aula-6-v2"


@dataclass(frozen=True)
class TextDocument:
    recipe_id: str
    title: str
    tokens: list[str]


@dataclass(frozen=True)
class TfidfModel:
    documents: list[TextDocument]
    vocabulary: list[str]
    idf: dict[str, float]
    term_frequencies: dict[str, Counter[str]]
    vectors: dict[str, list[float]]


def _load_json_list(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item)]


def load_documents(connection: sqlite3.Connection) -> list[TextDocument]:
    rows = connection.execute(
        """
        SELECT r.site_recipe_id, r.title, tp.lemma_tokens_json
        FROM recipes r
        LEFT JOIN text_preparations tp ON tp.recipe_id = r.site_recipe_id
        WHERE r.duplicate_of_recipe_id IS NULL
        ORDER BY r.site_recipe_id, tp.field_name, tp.position
        """
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        recipe_id = row["site_recipe_id"]
        grouped.setdefault(recipe_id, {"title": row["title"], "tokens": []})
        grouped[recipe_id]["tokens"].extend(_load_json_list(row["lemma_tokens_json"] or "[]"))
    return [
        TextDocument(recipe_id=recipe_id, title=str(data["title"]), tokens=list(data["tokens"]))
        for recipe_id, data in grouped.items()
    ]


def build_tfidf_model(documents: list[TextDocument]) -> TfidfModel:
    term_frequencies = {
        document.recipe_id: Counter(document.tokens)
        for document in documents
    }
    vocabulary = sorted({term for counter in term_frequencies.values() for term in counter})
    document_count = len(documents)
    document_frequencies = {
        term: sum(1 for counter in term_frequencies.values() if term in counter)
        for term in vocabulary
    }
    idf = {
        term: math.log(document_count / document_frequencies[term])
        if document_count and document_frequencies[term]
        else 0.0
        for term in vocabulary
    }
    vectors: dict[str, list[float]] = {}
    for document in documents:
        counter = term_frequencies[document.recipe_id]
        vectors[document.recipe_id] = [
            float(counter[term]) * idf[term]
            for term in vocabulary
        ]
    return TfidfModel(
        documents=documents,
        vocabulary=vocabulary,
        idf=idf,
        term_frequencies=term_frequencies,
        vectors=vectors,
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot / (left_norm * right_norm)


def nearest_neighbors(model: TfidfModel, *, limit: int = 5) -> dict[str, list[tuple[str, float]]]:
    limit = max(0, limit)
    result: dict[str, list[tuple[str, float]]] = {}
    for document in model.documents:
        vector = model.vectors[document.recipe_id]
        similarities = [
            (other.recipe_id, cosine_similarity(vector, model.vectors[other.recipe_id]))
            for other in model.documents
            if other.recipe_id != document.recipe_id
        ]
        result[document.recipe_id] = sorted(
            similarities,
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    return result


def _euclidean_squared(left: list[float], right: list[float]) -> float:
    return sum((left_value - right_value) ** 2 for left_value, right_value in zip(left, right))


def _mean_vector(vectors: list[list[float]], dimension: int) -> list[float]:
    if not vectors:
        return [0.0] * dimension
    return [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimension)
    ]


def _normalized_document_vectors(model: TfidfModel) -> dict[str, list[float]]:
    return {
        document.recipe_id: _normalize(model.vectors[document.recipe_id])
        for document in model.documents
    }


def _kmeans_plus_plus(
    ordered_vectors: list[list[float]],
    cluster_count: int,
    *,
    random_seed: int,
) -> list[list[float]]:
    randomizer = random.Random(random_seed)
    selected = [randomizer.randrange(len(ordered_vectors))]
    while len(selected) < cluster_count:
        weights = [
            0.0
            if index in selected
            else min(
                _euclidean_squared(vector, ordered_vectors[selected_index])
                for selected_index in selected
            )
            for index, vector in enumerate(ordered_vectors)
        ]
        total = sum(weights)
        if total <= 0.0:
            selected.append(next(index for index in range(len(ordered_vectors)) if index not in selected))
            continue
        threshold = randomizer.random() * total
        cumulative = 0.0
        next_index = len(ordered_vectors) - 1
        for index, weight in enumerate(weights):
            cumulative += weight
            if cumulative >= threshold:
                next_index = index
                break
        selected.append(next_index)
    return [list(ordered_vectors[index]) for index in selected]


def _fit_kmeans(
    recipe_ids: list[str],
    vectors: dict[str, list[float]],
    *,
    cluster_count: int,
    max_iterations: int,
    random_seed: int,
) -> tuple[dict[str, int], float]:
    ordered_vectors = [vectors[recipe_id] for recipe_id in recipe_ids]
    dimension = len(ordered_vectors[0]) if ordered_vectors else 0
    centroids = _kmeans_plus_plus(ordered_vectors, cluster_count, random_seed=random_seed)
    previous_labels: list[int] | None = None
    labels: list[int] = []

    for _ in range(max_iterations):
        labels = [
            min(
                range(cluster_count),
                key=lambda label: (_euclidean_squared(vector, centroids[label]), label),
            )
            for vector in ordered_vectors
        ]
        counts = Counter(labels)
        for empty_label in (label for label in range(cluster_count) if counts[label] == 0):
            candidates = [
                index
                for index, label in enumerate(labels)
                if counts[label] > 1
            ]
            if not candidates:
                break
            candidate = max(
                candidates,
                key=lambda index: (
                    _euclidean_squared(ordered_vectors[index], centroids[labels[index]]),
                    recipe_ids[index],
                ),
            )
            counts[labels[candidate]] -= 1
            labels[candidate] = empty_label
            counts[empty_label] += 1

        centroids = [
            _mean_vector(
                [vector for vector, assigned in zip(ordered_vectors, labels) if assigned == label],
                dimension,
            )
            for label in range(cluster_count)
        ]
        if labels == previous_labels:
            break
        previous_labels = list(labels)

    inertia = sum(
        _euclidean_squared(vector, centroids[label])
        for vector, label in zip(ordered_vectors, labels)
    )
    assignments = dict(zip(recipe_ids, labels))
    members = {
        label: sorted(recipe_id for recipe_id, assigned in assignments.items() if assigned == label)
        for label in range(cluster_count)
    }
    label_order = sorted(members, key=lambda label: members[label][0] if members[label] else "")
    label_map = {old_label: new_label for new_label, old_label in enumerate(label_order)}
    return ({recipe_id: label_map[label] for recipe_id, label in assignments.items()}, inertia)


def _cluster_normalized_vectors(
    model: TfidfModel,
    *,
    cluster_count: int,
    max_iterations: int,
    restarts: int,
    random_seed: int,
) -> dict[str, int]:
    recipe_ids = [document.recipe_id for document in model.documents]
    vectors = _normalized_document_vectors(model)
    candidates = [
        _fit_kmeans(
            recipe_ids,
            vectors,
            cluster_count=cluster_count,
            max_iterations=max_iterations,
            random_seed=random_seed + restart,
        )
        for restart in range(max(1, restarts))
    ]
    return min(
        candidates,
        key=lambda item: (
            item[1],
            tuple(item[0][recipe_id] for recipe_id in recipe_ids),
        ),
    )[0]


def _pairwise_distances(
    recipe_ids: list[str],
    vectors: dict[str, list[float]],
) -> dict[tuple[str, str], float]:
    distances: dict[tuple[str, str], float] = {}
    for left_index, left_id in enumerate(recipe_ids):
        distances[(left_id, left_id)] = 0.0
        for right_id in recipe_ids[left_index + 1 :]:
            distance = math.sqrt(_euclidean_squared(vectors[left_id], vectors[right_id]))
            distances[(left_id, right_id)] = distance
            distances[(right_id, left_id)] = distance
    return distances


def _silhouette_from_distances(
    recipe_ids: list[str],
    assignments: dict[str, int],
    distances: dict[tuple[str, str], float],
) -> float:
    groups: dict[int, list[str]] = {}
    for recipe_id in recipe_ids:
        groups.setdefault(assignments[recipe_id], []).append(recipe_id)
    if len(groups) < 2:
        return 0.0

    scores = []
    for recipe_id in recipe_ids:
        own_label = assignments[recipe_id]
        own_group = groups[own_label]
        if len(own_group) == 1:
            scores.append(0.0)
            continue
        intra = sum(distances[(recipe_id, other)] for other in own_group if other != recipe_id) / (
            len(own_group) - 1
        )
        nearest = min(
            sum(distances[(recipe_id, other)] for other in group) / len(group)
            for label, group in groups.items()
            if label != own_label
        )
        denominator = max(intra, nearest)
        scores.append((nearest - intra) / denominator if denominator else 0.0)
    return sum(scores) / len(scores)


def silhouette_score(model: TfidfModel, assignments: dict[str, int]) -> float:
    recipe_ids = [document.recipe_id for document in model.documents]
    vectors = _normalized_document_vectors(model)
    return _silhouette_from_distances(recipe_ids, assignments, _pairwise_distances(recipe_ids, vectors))


def cluster_vectors(
    model: TfidfModel,
    *,
    cluster_count: int = 4,
    max_iterations: int = 50,
    restarts: int = 6,
    random_seed: int = 42,
) -> dict[str, int]:
    if not model.documents:
        return {}
    effective_count = max(1, min(cluster_count, len(model.documents)))
    return _cluster_normalized_vectors(
        model,
        cluster_count=effective_count,
        max_iterations=max_iterations,
        restarts=restarts,
        random_seed=random_seed,
    )


def select_cluster_count(
    model: TfidfModel,
    *,
    max_clusters: int = 8,
    max_iterations: int = 50,
    restarts: int = 4,
    random_seed: int = 42,
) -> tuple[int, dict[str, int], float]:
    document_count = len(model.documents)
    if document_count <= 1:
        assignments = {document.recipe_id: 0 for document in model.documents}
        return document_count, assignments, 0.0

    recipe_ids = [document.recipe_id for document in model.documents]
    vectors = _normalized_document_vectors(model)
    distances = _pairwise_distances(recipe_ids, vectors)
    upper_bound = max(2, min(max_clusters, document_count - 1))
    candidates = []
    for cluster_count in range(2, upper_bound + 1):
        assignments = _cluster_normalized_vectors(
            model,
            cluster_count=cluster_count,
            max_iterations=max_iterations,
            restarts=restarts,
            random_seed=random_seed + cluster_count * 100,
        )
        score = _silhouette_from_distances(recipe_ids, assignments, distances)
        candidates.append((score, cluster_count, assignments))
    score, cluster_count, assignments = max(candidates, key=lambda item: (item[0], -item[1]))
    return cluster_count, assignments, score


def _centered_vectors(vectors: list[list[float]]) -> list[list[float]]:
    if not vectors:
        return []
    dimension = len(vectors[0])
    means = _mean_vector(vectors, dimension)
    return [
        [value - means[index] for index, value in enumerate(vector)]
        for vector in vectors
    ]


def _covariance_multiply(centered: list[list[float]], vector: list[float]) -> list[float]:
    if not centered:
        return [0.0] * len(vector)
    projections = [
        sum(value * vector[index] for index, value in enumerate(row))
        for row in centered
    ]
    scale = max(1, len(centered) - 1)
    return [
        sum(row[index] * projection for row, projection in zip(centered, projections)) / scale
        for index in range(len(vector))
    ]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def _principal_component(centered: list[list[float]], dimension: int) -> list[float]:
    if dimension == 0:
        return []
    vector = _normalize([1.0] * dimension)
    for _ in range(60):
        next_vector = _normalize(_covariance_multiply(centered, vector))
        if next_vector == [0.0] * dimension:
            return next_vector
        vector = next_vector
    return vector


def _project_vectors(model: TfidfModel, *, component_count: int) -> dict[str, tuple[float, ...]]:
    if not model.documents:
        return {}
    dimension = len(model.vocabulary)
    if dimension == 0 or len(model.documents) == 1:
        return {
            document.recipe_id: tuple(0.0 for _ in range(component_count))
            for document in model.documents
        }

    ordered_vectors = [model.vectors[document.recipe_id] for document in model.documents]
    centered = _centered_vectors(ordered_vectors)
    residual = centered
    component_scores: list[list[float]] = []
    for _ in range(component_count):
        component = _principal_component(residual, dimension)
        scores = [
            sum(value * component[index] for index, value in enumerate(row))
            for row in residual
        ]
        component_scores.append(scores)
        residual = [
            [value - scores[row_index] * component[index] for index, value in enumerate(row)]
            for row_index, row in enumerate(residual)
        ]
    return {
        document.recipe_id: tuple(scores[index] for scores in component_scores)
        for index, document in enumerate(model.documents)
    }


def project_vectors_3d(model: TfidfModel) -> dict[str, tuple[float, float, float]]:
    return {
        recipe_id: (values[0], values[1], values[2])
        for recipe_id, values in _project_vectors(model, component_count=3).items()
    }


def top_terms(model: TfidfModel, recipe_id: str, *, limit: int = 8) -> list[dict[str, float]]:
    counter = model.term_frequencies[recipe_id]
    weighted_terms = [
        {
            "term": term,
            "tf": float(counter[term]),
            "idf": model.idf[term],
            "tfidf": float(counter[term]) * model.idf[term],
        }
        for term in model.vocabulary
        if counter[term] > 0
    ]
    return sorted(
        weighted_terms,
        key=lambda item: (-item["tfidf"], -item["tf"], item["term"]),
    )[:limit]


def run_text_analysis(
    connection: sqlite3.Connection,
    *,
    cluster_count: int = 0,
    neighbor_count: int = 5,
) -> int:
    documents = load_documents(connection)
    model = build_tfidf_model(documents)
    if cluster_count <= 0:
        effective_cluster_count, clusters, clustering_score = select_cluster_count(model)
        clustering_method = "tfidf-l2+kmeans++-silhouette-auto"
    else:
        effective_cluster_count = max(1, min(cluster_count, len(model.documents))) if model.documents else 0
        clusters = cluster_vectors(model, cluster_count=effective_cluster_count)
        clustering_score = silhouette_score(model, clusters) if clusters else 0.0
        clustering_method = "tfidf-l2+kmeans++"
    projection = project_vectors_3d(model)
    neighbors = nearest_neighbors(model, limit=neighbor_count)
    created_at = utc_now()

    cursor = connection.execute(
        """
        INSERT INTO text_analysis_runs
            (model_version, document_count, vocabulary_size, cluster_count,
             clustering_method, silhouette_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ANALYSIS_VERSION,
            len(model.documents),
            len(model.vocabulary),
            effective_cluster_count,
            clustering_method,
            clustering_score,
            created_at,
        ),
    )
    run_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO document_vectors
            (run_id, recipe_id, vector_json, norm, cluster_label, x, y, z, top_terms_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                run_id,
                document.recipe_id,
                json.dumps(model.vectors[document.recipe_id], ensure_ascii=False),
                math.sqrt(sum(value * value for value in model.vectors[document.recipe_id])),
                clusters.get(document.recipe_id, 0),
                projection.get(document.recipe_id, (0.0, 0.0, 0.0))[0],
                projection.get(document.recipe_id, (0.0, 0.0, 0.0))[1],
                projection.get(document.recipe_id, (0.0, 0.0, 0.0))[2],
                json.dumps(top_terms(model, document.recipe_id), ensure_ascii=False),
            )
            for document in model.documents
        ),
    )
    term_rows = []
    for document in model.documents:
        counter = model.term_frequencies[document.recipe_id]
        for term_index, term in enumerate(model.vocabulary):
            tf = float(counter[term])
            weight = model.vectors[document.recipe_id][term_index]
            if tf == 0.0 and weight == 0.0:
                continue
            term_rows.append((run_id, document.recipe_id, term, tf, model.idf[term], weight))
    connection.executemany(
        """
        INSERT INTO document_term_weights
            (run_id, recipe_id, term, tf, idf, tfidf)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        term_rows,
    )
    similarity_rows = []
    for recipe_id, items in neighbors.items():
        for rank, (neighbor_id, similarity) in enumerate(items, 1):
            similarity_rows.append((run_id, recipe_id, neighbor_id, rank, similarity))
    connection.executemany(
        """
        INSERT INTO document_similarities
            (run_id, recipe_id, neighbor_recipe_id, rank, cosine_similarity)
        VALUES (?, ?, ?, ?, ?)
        """,
        similarity_rows,
    )
    connection.commit()
    return run_id


def latest_text_analysis(connection: sqlite3.Connection) -> dict[str, Any] | None:
    run = connection.execute(
        """
        SELECT *
        FROM text_analysis_runs
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
            "top_terms_data": json.loads(row["top_terms_json"]),
        }
        for row in connection.execute(
            """
            SELECT dv.*, r.title
            FROM document_vectors dv
            JOIN recipes r ON r.site_recipe_id = dv.recipe_id
            WHERE dv.run_id = ?
            ORDER BY dv.cluster_label, r.title COLLATE NOCASE
            """,
            (run_id,),
        )
    ]
    similarities = [
        dict(row)
        for row in connection.execute(
            """
            SELECT ds.*, source.title AS recipe_title, neighbor.title AS neighbor_title
            FROM document_similarities ds
            JOIN recipes source ON source.site_recipe_id = ds.recipe_id
            JOIN recipes neighbor ON neighbor.site_recipe_id = ds.neighbor_recipe_id
            WHERE ds.run_id = ?
            ORDER BY ds.recipe_id, ds.rank
            """,
            (run_id,),
        )
    ]
    return {"run": dict(run), "documents": documents, "similarities": similarities}
