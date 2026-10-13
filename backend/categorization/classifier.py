import csv
import time
from collections.abc import Iterable
from functools import cache
from pathlib import Path

from ..extraction.schema import ExtractedReceipt
from ..logging_config import setup_logging
from .categories import CATEGORIES, Category

logger = setup_logging(__name__)

# Hand-written, synthetic receipts in English: vendor, items separated by ";", category
TRAINING_DATA_PATH = Path(__file__).with_name("training_data.csv")

# Below this probability the category stays unknown (None), the way an unreadable field stays null.
# Chosen by cross-validation; tests/test_categorizer.py checks how many receipts get one and how many are right.
MIN_CONFIDENCE = 0.4


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


def build_model():
    """An untrained scikit-learn pipeline: TF-IDF features, then logistic regression."""
    # Imported here, not at the top: scikit-learn takes about a second to import, and only uploads need it
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


def _math_threads() -> str:
    """The threads each loaded math library uses, e.g. "openblas 1, openmp 1" (OMP_NUM_THREADS and similar set them)."""
    from threadpoolctl import threadpool_info  # installed with scikit-learn

    return ", ".join(sorted({f"{lib['internal_api']} {lib['num_threads']}" for lib in threadpool_info()}))


class ExpenseCategorizer:
    """Predicts a receipt's expense category from its vendor and line items with a classical classifier.

    Trained from the training CSV when it's created; that takes well under a second, so there's no model file.
    """

    def __init__(self):
        started = time.perf_counter()
        texts, categories = load_training_data()
        read = time.perf_counter()
        model = build_model()  # the first call imports scikit-learn
        imported = time.perf_counter()
        self.model = model.fit(texts, categories)
        # Each step's time separately: on a cold Lambda instance the total was 22-28 s, and the parts tell why
        logger.info(f"[Categorizer] Loaded scikit-learn and trained on {len(texts)} receipts "
                    f"in {time.perf_counter() - started:.2f} s (reading {read - started:.2f} s, "
                    f"importing {imported - read:.2f} s, training {time.perf_counter() - imported:.2f} s; "
                    f"{_math_threads()})")

    def predict(self, receipt: ExtractedReceipt) -> Category | None:
        """The most likely category, or None if the receipt has no text or no category is likely enough."""
        text = receipt_text(receipt.vendor, (item.description for item in receipt.line_items))
        if not text:
            return None
        probabilities = self.model.predict_proba([text])[0]
        best = probabilities.argmax()
        return str(self.model.classes_[best]) if probabilities[best] >= MIN_CONFIDENCE else None


@cache
def get_categorizer() -> ExpenseCategorizer:
    """The categorizer, trained on first use and kept for the life of the process."""
    return ExpenseCategorizer()
