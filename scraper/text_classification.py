from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .database import utc_now
from .text_analysis import TextDocument, load_documents


CLASSIFICATION_VERSION = "pln-aula-8-naive-bayes-v1"
TARGET_COLUMNS = {"difficulty": "difficulty", "cost": "cost_label"}


@dataclass(frozen=True)
class LabeledDocument:
    recipe_id: str
    title: str
    tokens: list[str]
    label: str


@dataclass(frozen=True)
class NaiveBayesModel:
    target_field: str
    vocabulary: list[str]
    classes: list[str]
    log_priors: dict[str, float]
    log_likelihoods: dict[str, dict[str, float]]


def load_labeled_documents(
    connection: sqlite3.Connection,
    *,
    target_field: str = "difficulty",
) -> list[LabeledDocument]:
    if target_field not in TARGET_COLUMNS:
        raise ValueError(f"Alvo inválido: {target_field}. Use difficulty ou cost.")
    labels = {
        row["site_recipe_id"]: str(row["label"]).strip()
        for row in connection.execute(
            f"SELECT site_recipe_id, {TARGET_COLUMNS[target_field]} AS label FROM recipes "
            f"WHERE NULLIF(TRIM({TARGET_COLUMNS[target_field]}), '') IS NOT NULL"
        )
    }
    return [
        LabeledDocument(document.recipe_id, document.title, document.tokens, labels[document.recipe_id])
        for document in load_documents(connection)
        if document.recipe_id in labels
    ]


def _stable_key(document: LabeledDocument) -> str:
    return hashlib.sha256(f"{document.label}:{document.recipe_id}".encode("utf-8")).hexdigest()


def stratified_split(
    documents: list[LabeledDocument],
    *,
    test_ratio: float = 0.25,
) -> tuple[list[LabeledDocument], list[LabeledDocument]]:
    ratio = min(0.9, max(0.0, test_ratio))
    grouped: dict[str, list[LabeledDocument]] = defaultdict(list)
    for document in documents:
        grouped[document.label].append(document)
    train: list[LabeledDocument] = []
    test: list[LabeledDocument] = []
    for label in sorted(grouped):
        items = sorted(grouped[label], key=_stable_key)
        if len(items) < 2 or ratio == 0.0:
            train.extend(items)
            continue
        test_count = min(len(items) - 1, max(1, round(len(items) * ratio)))
        test.extend(items[:test_count])
        train.extend(items[test_count:])
    return sorted(train, key=lambda item: item.recipe_id), sorted(test, key=lambda item: item.recipe_id)


def train_naive_bayes(
    documents: list[LabeledDocument],
    *,
    target_field: str = "difficulty",
    alpha: float = 1.0,
) -> NaiveBayesModel:
    if not documents:
        raise ValueError("É necessário ao menos um documento rotulado para treinar.")
    smoothing = max(alpha, 0.000001)
    classes = sorted({document.label for document in documents})
    vocabulary = sorted({token for document in documents for token in document.tokens})
    class_documents = Counter(document.label for document in documents)
    token_counts: dict[str, Counter[str]] = {label: Counter() for label in classes}
    for document in documents:
        token_counts[document.label].update(document.tokens)

    total_documents = len(documents)
    log_priors = {
        label: math.log((class_documents[label] + smoothing) / (total_documents + smoothing * len(classes)))
        for label in classes
    }
    log_likelihoods: dict[str, dict[str, float]] = {}
    for label in classes:
        denominator = sum(token_counts[label].values()) + smoothing * max(1, len(vocabulary))
        log_likelihoods[label] = {
            token: math.log((token_counts[label][token] + smoothing) / denominator)
            for token in vocabulary
        }
    return NaiveBayesModel(
        target_field=target_field,
        vocabulary=vocabulary,
        classes=classes,
        log_priors=log_priors,
        log_likelihoods=log_likelihoods,
    )


def predict_tokens(model: NaiveBayesModel, tokens: list[str]) -> tuple[str, dict[str, float]]:
    counts = Counter(token for token in tokens if token in model.vocabulary)
    scores = {
        label: model.log_priors[label]
        + sum(count * model.log_likelihoods[label][token] for token, count in counts.items())
        for label in model.classes
    }
    predicted = max(model.classes, key=lambda label: (scores[label], label))
    maximum = max(scores.values())
    exponentials = {label: math.exp(score - maximum) for label, score in scores.items()}
    total = sum(exponentials.values()) or 1.0
    probabilities = {label: exponentials[label] / total for label in model.classes}
    return predicted, probabilities


def evaluate_predictions(
    actual: list[str],
    predicted: list[str],
    *,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    ordered_labels = labels or sorted(set(actual) | set(predicted))
    confusion = {
        label: {candidate: 0 for candidate in ordered_labels}
        for label in ordered_labels
    }
    for expected, received in zip(actual, predicted):
        confusion[expected][received] += 1

    metrics = []
    for label in ordered_labels:
        true_positive = confusion[label][label]
        false_positive = sum(confusion[other][label] for other in ordered_labels if other != label)
        false_negative = sum(confusion[label][other] for other in ordered_labels if other != label)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics.append(
            {
                "label": label,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": sum(confusion[label].values()),
            }
        )
    total = len(actual)
    accuracy = sum(1 for expected, received in zip(actual, predicted) if expected == received) / total if total else None
    divisor = len(metrics) or 1
    return {
        "accuracy": accuracy,
        "macro_precision": sum(item["precision"] for item in metrics) / divisor if metrics else None,
        "macro_recall": sum(item["recall"] for item in metrics) / divisor if metrics else None,
        "macro_f1": sum(item["f1"] for item in metrics) / divisor if metrics else None,
        "metrics": metrics,
        "confusion": confusion,
    }


def _model_payload(model: NaiveBayesModel) -> dict[str, Any]:
    return {
        "target_field": model.target_field,
        "vocabulary": model.vocabulary,
        "classes": model.classes,
        "log_priors": model.log_priors,
        "log_likelihoods": model.log_likelihoods,
    }


def run_text_classification(
    connection: sqlite3.Connection,
    *,
    target_field: str = "difficulty",
    test_ratio: float = 0.25,
) -> int:
    documents = load_labeled_documents(connection, target_field=target_field)
    train, test = stratified_split(documents, test_ratio=test_ratio)
    if not train:
        raise ValueError(f"Não há receitas rotuladas para o alvo {target_field}.")
    model = train_naive_bayes(train, target_field=target_field)
    predictions = []
    for split, items in (("train", train), ("test", test)):
        for document in items:
            label, probabilities = predict_tokens(model, document.tokens)
            predictions.append(
                {
                    "recipe_id": document.recipe_id,
                    "split": split,
                    "actual_label": document.label,
                    "predicted_label": label,
                    "probabilities": probabilities,
                }
            )
    test_predictions = [item for item in predictions if item["split"] == "test"]
    evaluation = evaluate_predictions(
        [item["actual_label"] for item in test_predictions],
        [item["predicted_label"] for item in test_predictions],
        labels=model.classes,
    )
    if len(model.classes) < 2:
        status = "insufficient_classes"
    elif not test:
        status = "insufficient_test_data"
    else:
        status = "evaluated"

    cursor = connection.execute(
        """
        INSERT INTO classification_runs
            (model_version, target_field, classification_type, document_count,
             train_count, test_count, class_count, status, accuracy,
             macro_precision, macro_recall, macro_f1, model_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            CLASSIFICATION_VERSION,
            target_field,
            "ordinal",
            len(documents),
            len(train),
            len(test),
            len(model.classes),
            status,
            evaluation["accuracy"] if status == "evaluated" else None,
            evaluation["macro_precision"] if status == "evaluated" else None,
            evaluation["macro_recall"] if status == "evaluated" else None,
            evaluation["macro_f1"] if status == "evaluated" else None,
            json.dumps(_model_payload(model), ensure_ascii=False),
            utc_now(),
        ),
    )
    run_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO classification_predictions
            (run_id, recipe_id, split, actual_label, predicted_label, probabilities_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                run_id,
                item["recipe_id"],
                item["split"],
                item["actual_label"],
                item["predicted_label"],
                json.dumps(item["probabilities"], ensure_ascii=False),
            )
            for item in predictions
        ),
    )
    connection.executemany(
        """
        INSERT INTO classification_metrics
            (run_id, label, precision, recall, f1, support)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                run_id,
                item["label"],
                item["precision"],
                item["recall"],
                item["f1"],
                item["support"],
            )
            for item in evaluation["metrics"]
        ),
    )
    connection.commit()
    return run_id


def latest_text_classification(connection: sqlite3.Connection) -> dict[str, Any] | None:
    run = connection.execute(
        "SELECT * FROM classification_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return None
    run_id = int(run["id"])
    predictions = [
        {
            **dict(row),
            "probabilities": json.loads(row["probabilities_json"]),
        }
        for row in connection.execute(
            """
            SELECT cp.*, r.title
            FROM classification_predictions cp
            JOIN recipes r ON r.site_recipe_id = cp.recipe_id
            WHERE cp.run_id = ?
            ORDER BY cp.split, r.title COLLATE NOCASE
            """,
            (run_id,),
        )
    ]
    metrics = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM classification_metrics WHERE run_id = ? ORDER BY label COLLATE NOCASE",
            (run_id,),
        )
    ]
    labels = sorted({item["actual_label"] for item in predictions} | {item["predicted_label"] for item in predictions})
    test_predictions = [item for item in predictions if item["split"] == "test"]
    confusion = evaluate_predictions(
        [item["actual_label"] for item in test_predictions],
        [item["predicted_label"] for item in test_predictions],
        labels=labels,
    )["confusion"]
    return {"run": dict(run), "predictions": predictions, "metrics": metrics, "confusion": confusion}
