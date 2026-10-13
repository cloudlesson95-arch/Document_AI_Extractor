import json
import random
from collections import Counter

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.categorization.categories import CATEGORIES
from backend.categorization.classifier import (
    MIN_CONFIDENCE,
    build_model,
    load_training_data,
    model_from_pipeline,
    training_data_fingerprint,
)
from backend.categorization.model import MODEL_PATH, CategoryModel, char_terms, word_terms

# Texts that stress the text splitting: case, accents, other scripts, digits, punctuation, odd whitespace, short words
TRICKY_TEXTS = [
    "", " ", "a", "ab", "Café CAFÉ café", "Straße STRASSE", "naïve Ünleaded95", "日本 東京 coffee", "50% OFF!!",
    "co-op @home e-mail", "№7 3.50 12", "tab\tseparated\nnew line", "  many   spaces  ", "x y z",
    "Costa Coffee Flat White Toasted Teacake", "Qwxz Vbnm Zzkq 7", "UNLEADED 87 GAS 11.4 GAL",
]


@pytest.fixture(scope="module")
def trained():
    """A freshly trained pipeline, and a CategoryModel read back from its export through JSON, as the app reads it."""
    texts, categories = load_training_data()
    pipeline = build_model().fit(texts, categories)
    return texts, pipeline, CategoryModel(json.loads(json.dumps(model_from_pipeline(pipeline))))


def random_texts(texts: list[str], count: int) -> list[str]:
    words = sorted({word for text in texts for word in text.split()}) + [text or "Zzz" for text in TRICKY_TEXTS]
    generator = random.Random(0)
    return [" ".join(generator.choice(words) for _ in range(generator.randint(0, 12))) for _ in range(count)]


@pytest.mark.parametrize("text", TRICKY_TEXTS)
def test_word_terms_match_scikit_learn(text):
    assert Counter(word_terms(text, (1, 2))) == Counter(TfidfVectorizer(ngram_range=(1, 2)).build_analyzer()(text))


@pytest.mark.parametrize("text", TRICKY_TEXTS)
def test_char_terms_match_scikit_learn(text):
    analyzer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).build_analyzer()
    assert Counter(char_terms(text, (3, 5))) == Counter(analyzer(text))


def test_probabilities_match_scikit_learn(trained):
    texts, pipeline, model = trained
    batch = texts + TRICKY_TEXTS + random_texts(texts, 2000)

    expected = pipeline.predict_proba(batch)
    actual = np.array([list(model.probabilities(text).values()) for text in batch])

    assert model.classes == list(pipeline.classes_)
    assert np.abs(expected - actual).max() < 1e-9  # 1e-15 when measured: only the order of additions differs
    assert (expected.argmax(axis=1) == actual.argmax(axis=1)).all()
    assert ((expected.max(axis=1) >= MIN_CONFIDENCE) == (actual.max(axis=1) >= MIN_CONFIDENCE)).all()


def test_the_committed_model_is_up_to_date():
    # Fails after training_data.csv or build_model() changes until the model is exported again
    texts, categories = load_training_data()
    committed = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    fresh = model_from_pipeline(build_model().fit(texts, categories))
    hint = "model.json is out of date: run python -m backend.app export-model and commit it"

    assert committed["training_data_sha256"] == training_data_fingerprint(texts, categories), hint
    assert committed["classes"] == sorted(CATEGORIES), hint
    for saved, current in zip(committed["vectorizers"], fresh["vectorizers"], strict=True):
        assert (saved["analyzer"], saved["ngram_range"], saved["vocabulary"]) == \
               (current["analyzer"], current["ngram_range"], current["vocabulary"]), hint
    # Retraining on another machine may round the last digits differently, so the numbers are compared loosely
    assert np.allclose(committed["coef"], fresh["coef"], rtol=0, atol=1e-6), hint
    assert np.allclose(committed["intercept"], fresh["intercept"], rtol=0, atol=1e-6), hint


def test_the_fingerprint_ignores_line_endings(tmp_path):
    rows = ["vendor,items,category", "Staples,Printer Paper;Pens,Office Supplies", "Shell,Unleaded 95,Transport"]
    (tmp_path / "lf.csv").write_bytes("\n".join(rows).encode())
    (tmp_path / "crlf.csv").write_bytes("\r\n".join(rows).encode())

    assert training_data_fingerprint(*load_training_data(tmp_path / "lf.csv")) == \
           training_data_fingerprint(*load_training_data(tmp_path / "crlf.csv"))


@pytest.mark.parametrize("settings", [{"sublinear_tf": False}, {"lowercase": False}, {"analyzer": "char"}],
                         ids=["plain tf", "case-sensitive", "char analyzer"])
def test_export_refuses_settings_the_model_does_not_reproduce(settings):
    pipeline = build_model()
    pipeline.steps[0][1].transformer_list[0][1].set_params(**settings)
    texts, categories = load_training_data()
    pipeline.fit(texts, categories)

    with pytest.raises(ValueError, match="doesn't reproduce"):
        model_from_pipeline(pipeline)


def test_a_missing_model_file_names_the_export_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="export-model"):
        CategoryModel.load(tmp_path / "model.json")
