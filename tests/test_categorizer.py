import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from backend.categorization.categories import CATEGORIES
from backend.categorization.classifier import (
    MIN_CONFIDENCE,
    ExpenseCategorizer,
    build_model,
    get_categorizer,
    load_training_data,
    receipt_text,
)
from backend.extraction.schema import ExtractedReceipt

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def categorizer() -> ExpenseCategorizer:
    return ExpenseCategorizer()


def receipt(vendor: str | None, *items: str) -> ExtractedReceipt:
    return ExtractedReceipt(
        vendor=vendor, date=None, total_amount=None, currency=None,
        line_items=[{"description": item, "quantity": 1, "unit_price": None} for item in items],
    )


def test_training_data_has_at_least_30_receipts_per_category():
    _, categories = load_training_data()

    counts = Counter(categories)

    assert set(counts) == set(CATEGORIES)
    assert min(counts.values()) >= 30


def test_training_data_with_an_unknown_category_is_refused(tmp_path):
    path = tmp_path / "training_data.csv"
    path.write_text("vendor,items,category\nStaples,Printer Paper,Office Supplies\nAcme,Widget,Widgets\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Widgets"):
        load_training_data(path)


def test_cross_validation_keeps_accuracy_and_confident_precision_up():
    # Guards edits to the training data or the model. The receipts are synthetic, so real ones will score lower.
    texts, categories = load_training_data()
    categories = np.array(categories)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)

    probabilities = cross_val_predict(build_model(), texts, categories, cv=folds, method="predict_proba")
    predicted = np.array(sorted(CATEGORIES))[probabilities.argmax(axis=1)]
    confident = probabilities.max(axis=1) >= MIN_CONFIDENCE

    assert (predicted == categories).mean() >= 0.85  # every receipt, 0.90 when written
    assert confident.mean() >= 0.80  # share of receipts that get a category, 0.88 when written
    assert (predicted[confident] == categories[confident]).mean() >= 0.90  # of those, the share that's right: 0.93


@pytest.mark.parametrize("vendor, items, expected", [
    ("Costa Coffee", ["Flat White", "Toasted Teacake"], "Meals"),
    ("Stop & Shop", ["Whole Milk", "Eggs Dozen", "Bananas"], "Groceries"),
    ("Virgin Atlantic", ["Flight LHR to JFK", "Seat Upgrade"], "Travel"),
    ("Sunoco", ["Unleaded 87 Gas 11.4 gal"], "Transport"),
    ("Quill", ["Copy Paper Case", "Black Pens"], "Office Supplies"),
    ("Asana", ["Premium Plan Annual Subscription"], "Software & Subscriptions"),
    ("Sprint", ["Monthly Wireless Bill"], "Utilities & Phone"),
    (None, ["Cappuccino", "Croissant"], "Meals"),
])
def test_categorizes_receipts_it_was_not_trained_on(categorizer, vendor, items, expected):
    assert categorizer.predict(receipt(vendor, *items)) == expected


@pytest.mark.parametrize("vendor, items", [(None, []), ("  ", [" "])], ids=["nothing", "blank"])
def test_a_receipt_without_text_gets_no_category(categorizer, vendor, items):
    assert categorizer.predict(receipt(vendor, *items)) is None


@pytest.mark.parametrize("vendor, items", [("Qwxz Vbnm", ["Zzkq 7"]), ("CVS Pharmacy", ["Ibuprofen", "Toothpaste"])])
def test_an_unfamiliar_receipt_gets_no_category_rather_than_a_guess(categorizer, vendor, items):
    assert categorizer.predict(receipt(vendor, *items)) is None


def test_receipt_text_joins_the_vendor_and_items_and_skips_blanks():
    assert receipt_text(" Starbucks ", ["Caffe Latte", " ", " Muffin"]) == "Starbucks Caffe Latte Muffin"
    assert receipt_text(None, []) == ""


def test_get_categorizer_loads_once():
    assert get_categorizer() is get_categorizer()


def test_categorizing_loads_neither_scikit_learn_nor_numpy():
    # Fresh interpreter: this test module imports both itself. The deployed image doesn't have them, and on a cold
    # Lambda instance loading them took 26 s, so predicting must work from model.json alone.
    code = (
        "import sys\nfrom backend.categorization.classifier import ExpenseCategorizer\n"
        "from backend.extraction.schema import ExtractedReceipt\n"
        "receipt = ExtractedReceipt(vendor='Costa Coffee', date=None, total_amount=None, currency=None, line_items=[])\n"
        "print(ExpenseCategorizer().predict(receipt), sorted({'sklearn', 'numpy', 'scipy'} & set(sys.modules)))"
    )
    env = {**os.environ, "LOG_TO_FILE": "false", "LOG_TO_CONSOLE": "false"}

    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "Meals []"
