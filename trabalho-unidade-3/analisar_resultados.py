from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.text_analysis import (
    TfidfModel,
    build_tfidf_model,
    cosine_similarity,
    load_documents,
    select_cluster_count,
)
from scraper.text_classification import (
    evaluate_predictions,
    load_labeled_documents,
    stratified_split,
)
from scraper.text_embeddings import load_latest_embedding_model, semantic_search
from scraper.text_utils import prepare_text


DATABASE = ROOT / "data" / "recipes.sqlite"
OUTPUT = Path(__file__).resolve().parent / "output" / "results" / "resumo.json"


def rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def query_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(query, parameters)]


def build_bow_model(tfidf: TfidfModel) -> TfidfModel:
    vectors = {
        document.recipe_id: [
            float(tfidf.term_frequencies[document.recipe_id][term])
            for term in tfidf.vocabulary
        ]
        for document in tfidf.documents
    }
    return TfidfModel(
        documents=tfidf.documents,
        vocabulary=tfidf.vocabulary,
        idf={term: 1.0 for term in tfidf.vocabulary},
        term_frequencies=tfidf.term_frequencies,
        vectors=vectors,
    )


def build_dense_model(tfidf: TfidfModel, embedding_model) -> TfidfModel:
    return TfidfModel(
        documents=tfidf.documents,
        vocabulary=[f"d{index}" for index in range(embedding_model.dimension)],
        idf={},
        term_frequencies={document.recipe_id: Counter() for document in tfidf.documents},
        vectors={
            document.recipe_id: embedding_model.document_vectors[document.recipe_id]
            for document in tfidf.documents
        },
    )


def cluster_summary(model: TfidfModel) -> dict[str, object]:
    cluster_count, assignments, score = select_cluster_count(
        model,
        max_clusters=8,
        restarts=4,
        random_seed=42,
    )
    sizes = Counter(assignments.values())
    cluster_terms: dict[str, list[str]] = {}
    for label in sorted(sizes):
        recipe_ids = {recipe_id for recipe_id, value in assignments.items() if value == label}
        terms: Counter[str] = Counter()
        for document in model.documents:
            if document.recipe_id in recipe_ids:
                terms.update(document.tokens)
        cluster_terms[str(label)] = [term for term, _ in terms.most_common(8)]
    return {
        "cluster_count": cluster_count,
        "silhouette": rounded(score, 6),
        "sizes": {str(label): sizes[label] for label in sorted(sizes)},
        "terms": cluster_terms,
    }


def latest_tfidf_summary(connection: sqlite3.Connection) -> dict[str, object]:
    run = dict(connection.execute(
        "SELECT * FROM text_analysis_runs ORDER BY id DESC LIMIT 1"
    ).fetchone())
    sizes = query_rows(
        connection,
        """
        SELECT cluster_label, COUNT(*) AS count
        FROM document_vectors
        WHERE run_id = ?
        GROUP BY cluster_label
        ORDER BY cluster_label
        """,
        (run["id"],),
    )
    terms: dict[str, list[str]] = {}
    for item in sizes:
        rows = query_rows(
            connection,
            """
            SELECT dt.term, SUM(dt.tfidf) AS weight
            FROM document_term_weights dt
            JOIN document_vectors dv
              ON dv.run_id = dt.run_id AND dv.recipe_id = dt.recipe_id
            WHERE dt.run_id = ? AND dv.cluster_label = ?
            GROUP BY dt.term
            ORDER BY weight DESC, dt.term
            LIMIT 8
            """,
            (run["id"], item["cluster_label"]),
        )
        terms[str(item["cluster_label"])] = [str(row["term"]) for row in rows]
    return {
        "run_id": run["id"],
        "cluster_count": run["cluster_count"],
        "silhouette": rounded(run["silhouette_score"], 6),
        "sizes": {str(item["cluster_label"]): item["count"] for item in sizes},
        "terms": terms,
        "method": run["clustering_method"],
    }


def vector_for_query(query: str, model: TfidfModel, use_idf: bool) -> list[float]:
    counts = Counter(prepare_text(query).lemma_tokens)
    return [
        float(counts[term]) * (model.idf.get(term, 1.0) if use_idf else 1.0)
        for term in model.vocabulary
    ]


def lexical_search(query: str, model: TfidfModel, use_idf: bool) -> list[dict[str, object]]:
    query_vector = vector_for_query(query, model, use_idf)
    ranked = sorted(
        (
            {
                "title": document.title,
                "score": rounded(cosine_similarity(query_vector, model.vectors[document.recipe_id])),
            }
            for document in model.documents
        ),
        key=lambda item: (-float(item["score"] or 0), str(item["title"])),
    )
    return ranked[:5]


def nearest_centroid_classification(
    model: TfidfModel,
    train,
    test,
) -> dict[str, object]:
    labels = sorted({document.label for document in train})
    centroids: dict[str, list[float]] = {}
    for label in labels:
        vectors = [model.vectors[document.recipe_id] for document in train if document.label == label]
        centroids[label] = [
            sum(vector[index] for vector in vectors) / len(vectors)
            for index in range(len(vectors[0]))
        ]
    actual: list[str] = []
    predicted: list[str] = []
    for document in test:
        scores = {
            label: cosine_similarity(model.vectors[document.recipe_id], centroid)
            for label, centroid in centroids.items()
        }
        actual.append(document.label)
        predicted.append(max(scores, key=lambda label: (scores[label], label)))
    evaluation = evaluate_predictions(actual, predicted, labels=labels)
    return {
        "accuracy": rounded(evaluation["accuracy"]),
        "macro_precision": rounded(evaluation["macro_precision"]),
        "macro_recall": rounded(evaluation["macro_recall"]),
        "macro_f1": rounded(evaluation["macro_f1"]),
        "confusion": evaluation["confusion"],
        "metrics": [
            {
                **metric,
                "precision": rounded(metric["precision"]),
                "recall": rounded(metric["recall"]),
                "f1": rounded(metric["f1"]),
            }
            for metric in evaluation["metrics"]
        ],
    }


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    documents = load_documents(connection)
    tfidf = build_tfidf_model(documents)
    bow = build_bow_model(tfidf)
    embedding_model = load_latest_embedding_model(connection)
    if embedding_model is None:
        raise RuntimeError("A execução de embeddings não foi encontrada no banco.")
    dense = build_dense_model(tfidf, embedding_model)

    labeled = load_labeled_documents(connection, target_field="cost")
    train, test = stratified_split(labeled, test_ratio=0.25)
    classification = {
        "target": "cost_label",
        "classifier": "centroide mais próximo por similaridade de cosseno",
        "documents": len(labeled),
        "train": len(train),
        "test": len(test),
        "class_distribution": dict(Counter(document.label for document in labeled)),
        "representations": {
            "BoW": nearest_centroid_classification(bow, train, test),
            "TF-IDF": nearest_centroid_classification(tfidf, train, test),
            "PPMI-32D": nearest_centroid_classification(dense, train, test),
        },
        "difficulty_limitation": dict(Counter(
            row[0] for row in connection.execute(
                "SELECT difficulty FROM recipes WHERE difficulty IS NOT NULL"
            )
        )),
    }

    searches: dict[str, object] = {}
    for query in ("carne com cebola", "sobremesa de banana"):
        searches[query] = {
            "BoW": lexical_search(query, bow, use_idf=False),
            "TF-IDF": lexical_search(query, tfidf, use_idf=True),
            "PPMI-32D": [
                {
                    "title": result["title"],
                    "score": rounded(result["cosine_similarity"]),
                }
                for result in semantic_search(embedding_model, query, limit=5)
            ],
        }

    corpus = dict(connection.execute(
        """
        SELECT COUNT(*) AS recipes,
               SUM(difficulty IS NOT NULL) AS difficulty_labels,
               SUM(cost_label IS NOT NULL) AS cost_labels,
               SUM(rating_value IS NOT NULL) AS ratings,
               SUM(prep_time_minutes IS NOT NULL) AS preparation_times
        FROM recipes
        """
    ).fetchone())
    corpus["vocabulary"] = len(tfidf.vocabulary)
    corpus["text_units"] = connection.execute(
        "SELECT COUNT(*) FROM text_preparations"
    ).fetchone()[0]

    linguistic_run = dict(connection.execute(
        "SELECT * FROM linguistic_analysis_runs ORDER BY id DESC LIMIT 1"
    ).fetchone())
    sentiments = query_rows(
        connection,
        """
        SELECT polarity, COUNT(*) AS count, AVG(score) AS average_score,
               AVG(subjectivity) AS average_subjectivity
        FROM sentiment_analyses
        WHERE run_id = ?
        GROUP BY polarity
        ORDER BY count DESC
        """,
        (linguistic_run["id"],),
    )
    entities = query_rows(
        connection,
        """
        SELECT entity_type, COUNT(*) AS count
        FROM named_entities
        WHERE run_id = ?
        GROUP BY entity_type
        ORDER BY count DESC
        """,
        (linguistic_run["id"],),
    )
    relations = query_rows(
        connection,
        """
        SELECT relation, COUNT(*) AS count, AVG(confidence) AS average_confidence
        FROM semantic_relations
        WHERE run_id = ?
        GROUP BY relation
        ORDER BY count DESC
        LIMIT 12
        """,
        (linguistic_run["id"],),
    )
    relation_examples = query_rows(
        connection,
        """
        SELECT r.title, sr.subject, sr.relation, sr.object, sr.confidence
        FROM semantic_relations sr
        JOIN recipes r ON r.site_recipe_id = sr.recipe_id
        WHERE sr.run_id = ? AND sr.relation NOT IN
              ('tem_ingrediente', 'usa_utensilio', 'pertence_categoria')
        ORDER BY sr.id
        LIMIT 8
        """,
        (linguistic_run["id"],),
    )

    result = {
        "generated_on": "2026-10-29",
        "corpus": corpus,
        "clustering": {
            "BoW": cluster_summary(bow),
            "TF-IDF": latest_tfidf_summary(connection),
            "PPMI-32D": cluster_summary(dense),
        },
        "searches": searches,
        "classification": classification,
        "linguistic": {
            "run": linguistic_run,
            "sentiments": sentiments,
            "entities": entities,
            "relations": relations,
            "relation_examples": relation_examples,
        },
        "matrix": {
            "clustering": {
                "BoW": "realizado",
                "TF-IDF": "realizado",
                "Word2Vec": "não realizado; foi usado PPMI 32D como substituto denso local",
                "BERT": "não realizado; modelo Transformer não faz parte do ambiente reproduzível",
            },
            "search": {
                "BoW": "realizado",
                "TF-IDF": "realizado",
                "Word2Vec": "não realizado; foi usado PPMI 32D como substituto denso local",
                "BERT": "não realizado; modelo Transformer não faz parte do ambiente reproduzível",
            },
            "classification": {
                "BoW": "realizado",
                "TF-IDF": "realizado",
                "Word2Vec": "não realizado; foi usado PPMI 32D como substituto denso local",
                "BERT": "não realizado; modelo Transformer não faz parte do ambiente reproduzível",
            },
        },
        "ai_disclosure": {
            "provider": "OpenAI",
            "model": "Codex (GPT-5)",
            "prompt": "Analise esse documento preencha ele e coloque na pasta do projeto em uma nova pasta, faça commit.",
            "use": "Leitura do enunciado, estruturação do relatório, redação inicial, geração dos scripts e validação do PDF. As métricas foram calculadas localmente sobre o banco SQLite do projeto.",
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultados gravados em {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
