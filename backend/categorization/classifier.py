import csv
import hashlib
import json
import time
from collections.abc import Iterable
from functools import cache
from pathlib import Path

from ..extraction.schema import ExtractedReceipt
from ..logging_config import setup_logging
from .categories import CATEGORIES, Category
from .model import MODEL_PATH, CategoryModel

logger = setup_logging(__name__)

# Hand-written, synthetic receipts in English: vendor, items separated by ";", category
TRAINING_DATA_PATH = Path(__file__).with_name("training_data.csv")

# Below this probability the category stays unknown (None), the way an unreadable field stays null.
# Chosen by cross-validation; tests/test_categorizer.py checks how many receipts get one and how many are right.
MIN_CONFIDENCE = 0.4

# TfidfVectorizer settings that change its features, with the values CategoryModel reproduces; export_model() refuses
# a pipeline that uses others, rather than writing a model the app would score differently
_REPRODUCED_SETTINGS = {
    "lowercase": True, "token_pattern": r"(?u)\b\w\w+\b", "strip_accents": None, "stop_words": None,
    "preprocessor": None, "tokenizer": None, "binary": False, "use_idf": True, "sublinear_tf": True, "norm": "l2",
}


def receipt_text(vendor: str | None, item_descriptions: Iterable[str]) -> str:
    """The text the classifier reads: the vendor, then the line-item descriptions."""
    return " ".join(part.strip() for part in [vendor or "", *item_descriptions] if part.strip())


def load_training_data(path: Path = TRAINING_DATA_PATH) -> tuple[list[str], list[str]]:
    """Return the texts and categories of the training receipts.

    Raises:
        ValueError: If a row names a category outside CATEGORIES (a typo would otherwise become a new class).
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    unknown = {row["category"] for row in rows} - set(CATEGORIES)
    if unknown:
        raise ValueError(f"{path.name} has unknown categories: {sorted(unknown)}")
    return [receipt_text(row["vendor"], row["items"].split(";")) for row in rows], [row["category"] for row in rows]


def training_data_fingerprint(texts: list[str], categories: list[str]) -> str:
    """SHA-256 of the training data as read, so the file's line endings or quoting don't count as a change."""
    return hashlib.sha256(json.dumps([texts, categories]).encode("utf-8")).hexdigest()


def build_model():
    """An untrained scikit-learn pipeline: TF-IDF features, then logistic regression.

    Only training uses it (export_model and the tests); scikit-learn comes with requirements-dev.txt.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline, make_union

    return make_pipeline(
        make_union(
            TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),  # words and word pairs
            # Character n-grams within words: they match variants such as "Unleaded95" or "Groceries"/"Grocery"
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True),
        ),
        LogisticRegression(C=10, max_iter=1000),
    )


def model_from_pipeline(pipeline) -> dict:
    """What a trained build_model() pipeline predicts with, in the form CategoryModel reads.

    Raises:
        ValueError: If the pipeline uses settings CategoryModel doesn't reproduce.
    """
    union, regression = (step for _, step in pipeline.steps)
    vectorizers = []
    for _, vectorizer in union.transformer_list:
        settings = vectorizer.get_params()
        different = {name: settings[name] for name, value in _REPRODUCED_SETTINGS.items() if settings[name] != value}
        if different or settings["analyzer"] not in ("word", "char_wb"):
            raise ValueError(f"CategoryModel doesn't reproduce these TfidfVectorizer settings: "
                             f"{different or {'analyzer': settings['analyzer']}}")
        vectorizers.append({
            "analyzer": settings["analyzer"],
            "ngram_range": list(settings["ngram_range"]),
            # In feature order, so a re-export of the same data writes the same file
            "vocabulary": dict(sorted(((term, int(index)) for term, index in vectorizer.vocabulary_.items()),
                                      key=lambda item: item[1])),
            "idf": vectorizer.idf_.tolist(),
        })
    if len(regression.classes_) < 3:  # with two classes scikit-learn scores one class with a sigmoid, not a softmax
        raise ValueError("CategoryModel needs at least three categories")
    return {
        "classes": regression.classes_.tolist(),
        "intercept": regression.intercept_.tolist(),
        "coef": regression.coef_.tolist(),
        "vectorizers": vectorizers,
    }


def export_model(path: Path = MODEL_PATH) -> dict:
    """Train on the training data and write model.json, the categorizer's model; return what was written.

    Run python -m backend.app export-model after changing training_data.csv or build_model(), and commit the file:
    tests/test_category_model.py fails while it's out of date.
    """
    texts, categories = load_training_data()
    model = model_from_pipeline(build_model().fit(texts, categories))
    model["training_data_sha256"] = training_data_fingerprint(texts, categories)
    Path(path).write_text(json.dumps(model), encoding="utf-8")
    return model


class ExpenseCategorizer:
    """Predicts a receipt's expense category from its vendor and line items with a classical classifier.

    The model is trained with scikit-learn ahead of time (export_model) and read from model.json, so predicting
    loads neither scikit-learn nor NumPy.
    """

    def __init__(self, path: Path = MODEL_PATH):
        started = time.perf_counter()
        self.model = CategoryModel.load(path)
        logger.info(f"[Categorizer] Loaded the model ({self.model.feature_count:,} features, "
                    f"{len(self.model.classes)} categories) in {(time.perf_counter() - started) * 1000:.0f} ms")

    def predict(self, receipt: ExtractedReceipt) -> Category | None:
        """The most likely category, or None if the receipt has no text or no category is likely enough."""
        text = receipt_text(receipt.vendor, (item.description for item in receipt.line_items))
        if not text:
            return None
        probabilities = self.model.probabilities(text)
        best = max(probabilities, key=probabilities.get)
        return best if probabilities[best] >= MIN_CONFIDENCE else None


@cache
def get_categorizer() -> ExpenseCategorizer:
    """The categorizer, loaded on first use and kept for the life of the process."""
    return ExpenseCategorizer()
