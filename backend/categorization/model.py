import json
import math
import re
from collections import Counter
from pathlib import Path

# The trained categorizer, exported from scikit-learn by classifier.export_model() (python -m backend.app export-model).
# Predicting needs only these numbers and the standard library, so the app never loads scikit-learn or NumPy: on a
# cold Lambda instance that would mean reading about 170 MB of files, which took 26 s.
MODEL_PATH = Path(__file__).with_name("model.json")

# Text splitting and weighting the way scikit-learn's TfidfVectorizer does it for build_model()'s settings;
# tests/test_category_model.py checks the results against scikit-learn itself
_TOKEN = re.compile(r"(?u)\b\w\w+\b")  # TfidfVectorizer's default token_pattern: words of two or more characters
_WHITESPACE_RUNS = re.compile(r"\s\s+")


def word_terms(text: str, ngram_range: tuple[int, int]) -> list[str]:
    """The lowercased words and runs of neighbouring words, e.g. "milk" and "whole milk" for ngram_range (1, 2)."""
    tokens = _TOKEN.findall(text.lower())
    low, high = ngram_range
    return [" ".join(tokens[i:i + n]) for n in range(low, high + 1) for i in range(len(tokens) - n + 1)]


def char_terms(text: str, ngram_range: tuple[int, int]) -> list[str]:
    """Character n-grams inside each lowercased word padded with spaces, e.g. " mi", "mil", "ilk", "lk " (char_wb)."""
    low, high = ngram_range
    terms = []
    for word in _WHITESPACE_RUNS.sub(" ", text.lower()).split():
        word = f" {word} "
        for n in range(low, high + 1):
            offset = 0
            terms.append(word[offset:offset + n])
            while offset + n < len(word):
                offset += 1
                terms.append(word[offset:offset + n])
            if offset == 0:  # a word shorter than n is counted once, whole
                break
    return terms


_ANALYZERS = {"word": word_terms, "char_wb": char_terms}


class _Vectorizer:
    """One TfidfVectorizer's vocabulary and weights; its features start at `offset` in the combined feature list."""

    def __init__(self, exported: dict, offset: int):
        self.terms = _ANALYZERS[exported["analyzer"]]
        self.ngram_range = tuple(exported["ngram_range"])
        self.vocabulary: dict[str, int] = exported["vocabulary"]
        self.idf: list[float] = exported["idf"]
        self.offset = offset

    def features(self, text: str) -> dict[int, float]:
        """The text's non-zero features: (1 + ln count) x idf for each known term, scaled to length 1."""
        counts = Counter(term for term in self.terms(text, self.ngram_range) if term in self.vocabulary)
        weights = {self.vocabulary[term]: (math.log(count) + 1.0) * self.idf[self.vocabulary[term]]
                   for term, count in counts.items()}
        length = math.sqrt(sum(weight * weight for weight in weights.values()))
        return {self.offset + index: weight / length for index, weight in weights.items()} if length else {}


class CategoryModel:
    """TF-IDF features scored by logistic regression, with the numbers scikit-learn learned. Pure Python."""

    def __init__(self, exported: dict):
        self.classes: list[str] = exported["classes"]
        self.coef: list[list[float]] = exported["coef"]
        self.intercept: list[float] = exported["intercept"]
        self.vectorizers = []
        offset = 0
        for vectorizer in exported["vectorizers"]:
            self.vectorizers.append(_Vectorizer(vectorizer, offset))
            offset += len(vectorizer["idf"])
        self.feature_count = offset

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "CategoryModel":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise FileNotFoundError(f"No categorizer model at {path}: run python -m backend.app export-model") from e
        return cls(json.loads(text))

    def probabilities(self, text: str) -> dict[str, float]:
        """Each category's probability for the text; they add up to 1."""
        features = {}
        for vectorizer in self.vectorizers:
            features |= vectorizer.features(text)
        scores = [bias + sum(value * weights[index] for index, value in features.items())
                  for weights, bias in zip(self.coef, self.intercept)]
        top = max(scores)  # softmax, shifted so exp() can't overflow
        exps = [math.exp(score - top) for score in scores]
        total = sum(exps)
        return {category: exp / total for category, exp in zip(self.classes, exps)}
