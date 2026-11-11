"""Text helpers and the offline embedding provider."""

import math

import pytest

from app.core.text import content_terms, question_terms, split_sentences, stem, tokenize
from app.providers.embeddings.local import DIMENSIONS, LocalEmbeddingProvider, embed_text


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_tokenize_keeps_product_codes_together_and_splits_other_hyphens() -> None:
    assert tokenize("The LP-420 and the lp420 use third-party labels.") == [
        "the",
        "lp420",
        "and",
        "the",
        "lp420",
        "use",
        "third",
        "party",
        "labels",
    ]
    assert tokenize("Northline's 30-day window") == ["northline", "30", "day", "window"]


@pytest.mark.parametrize(
    ("forms", "expected"),
    [
        (["ship", "ships", "shipping", "shipped"], "ship"),
        (["return", "returns", "returned", "returning"], "return"),
        (["warranty", "warranties"], "warranty"),
        (["box", "boxes"], "box"),
        (["damage", "damaged", "damages"], "damag"),
    ],
)
def test_stem_maps_the_forms_of_a_word_to_one_string(forms: list[str], expected: str) -> None:
    assert {stem(form) for form in forms} == {expected}


def test_stem_leaves_codes_and_short_words_alone() -> None:
    assert [stem(token) for token in ("lp420", "fee", "this", "business")] == [
        "lp420",
        "fee",
        "this",
        "business",
    ]


def test_question_terms_drop_words_that_only_shape_the_question() -> None:
    assert question_terms("How long is the warranty on the L-125?") == ["warranty", "l125"]
    assert question_terms("How much does shipping cost?") == ["ship", "cost"]
    # Embedding keeps them: a FAQ heading repeats the visitor's wording.
    assert content_terms("How long is the warranty?") == ["long", "warranty"]
    assert question_terms("A long cable") == ["long", "cabl"]


def test_split_sentences_does_not_break_after_abbreviations() -> None:
    text = "Orders placed by 2:00 p.m. Pacific Time ship the same day. Later orders ship next day."
    assert split_sentences(text) == [
        "Orders placed by 2:00 p.m. Pacific Time ship the same day.",
        "Later orders ship next day.",
    ]


def test_split_sentences_keeps_closing_quotes_and_brackets() -> None:
    text = 'She said "send it back." Then we refunded it (see note 1.) Next case.'

    assert split_sentences(text) == [
        'She said "send it back."',
        "Then we refunded it (see note 1.)",
        "Next case.",
    ]
    assert " ".join(split_sentences(text)) == text


def test_local_embedding_is_deterministic_and_normalized() -> None:
    first = embed_text("You can return most items within 30 days of the delivery date.")
    second = embed_text("You can return most items within 30 days of the delivery date.")

    assert first == second
    assert len(first) == DIMENSIONS
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0, rel_tol=1e-9)


def test_local_embedding_ranks_a_passage_with_shared_words_first() -> None:
    query = embed_text("How long do I have to return an item?")
    returns = embed_text("Return window. You can return most items within 30 days.")
    shipping = embed_text("Standard Ground shipping costs $14.95 per order.")

    assert _cosine(query, returns) > _cosine(query, shipping)


def test_local_embedding_of_text_without_content_is_still_a_unit_vector() -> None:
    vector = embed_text("the of and")

    assert math.isclose(sum(value * value for value in vector), 1.0)


async def test_local_provider_embeds_documents_in_order_without_any_network() -> None:
    provider = LocalEmbeddingProvider()
    texts = ["Shipping policy", "Returns policy", "Warranty policy"]

    vectors = await provider.embed_documents(texts)

    assert vectors == [embed_text(text) for text in texts]
    assert await provider.embed_query("Returns policy") == vectors[1]
    assert provider.model_name.startswith("local-hashing")
    assert provider.live is False
