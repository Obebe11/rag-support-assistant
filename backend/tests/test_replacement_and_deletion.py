"""Replacing and deleting a document, seen from the chat.

Uses the superseded documents in `knowledge-base/northline-replacement-test/`
and follows the test steps of its README: each knowledge base holds only the
document under test.
"""

from typing import Any

import httpx
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionFactory
from app.models import Chunk
from tests.kb import NORTHLINE_DOCUMENTS, REPLACEMENT_TEST, ask, ingest, run_jobs, upload

RESTOCKING_FEE = "What is the restocking fee for an opened item?"
RMA_VALIDITY = "For how many days is an RMA number valid?"
GROUND_RATE = "What does Standard Ground shipping cost per order?"


async def _search(
    client: httpx.AsyncClient, headers: dict[str, str], query: str
) -> list[dict[str, Any]]:
    response = await client.post(
        "/api/admin/documents/search", headers=headers, json={"query": query, "top_k": 50}
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _quoted(reply: dict[str, Any]) -> str:
    excerpts = " ".join(citation["excerpt"] for citation in reply["citations"])
    return f"{reply['content']} {excerpts}"


async def test_after_a_replacement_answers_rely_only_on_the_new_version(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(
        client,
        admin_headers,
        session_factory,
        settings,
        REPLACEMENT_TEST / "returns-policy-v1.3.md",
        title="Returns Policy",
        version_label="1.3",
    )
    old_fee = await ask(client, RESTOCKING_FEE)
    old_rma = await ask(client, RMA_VALIDITY)

    # The superseded version answers while it is the active one.
    assert old_fee["answer_type"] == "grounded"
    assert "20% restocking fee" in old_fee["content"]
    assert [(c["version_number"], c["version_label"]) for c in old_fee["citations"]] == [(1, "1.3")]
    assert old_rma["answer_type"] == "grounded"
    assert "valid for 10 days" in old_rma["content"]

    replaced = await upload(
        client,
        admin_headers,
        NORTHLINE_DOCUMENTS / "returns-policy.md",
        document_id=document["id"],
        version_label="2.0",
    )
    assert replaced.status_code == 202
    # Not indexed yet: the old version keeps answering, there is no gap in between.
    waiting = await ask(client, RESTOCKING_FEE)
    assert "20% restocking fee" in waiting["content"]

    assert await run_jobs(session_factory, settings) == 1
    new_fee = await ask(client, RESTOCKING_FEE)
    new_rma = await ask(client, RMA_VALIDITY)

    assert new_fee["answer_type"] == "grounded"
    assert "15% restocking fee" in new_fee["content"]
    assert new_rma["answer_type"] == "grounded"
    assert "valid for 14 days" in new_rma["content"]
    for reply in (new_fee, new_rma):
        assert "20%" not in _quoted(reply)
        assert "10 days" not in _quoted(reply)
        assert {(c["version_number"], c["version_label"]) for c in reply["citations"]} == {
            (2, "2.0")
        }
        assert {source["version_number"] for source in reply["usage"]["retrieved"]} == {2}

    # Retrieval on its own returns no chunk of the superseded version either.
    passages = await _search(client, admin_headers, RESTOCKING_FEE)
    assert passages
    assert {(p["version_number"], p["version_label"]) for p in passages} == {(2, "2.0")}
    assert all("20% restocking fee" not in passage["content"] for passage in passages)

    detail = (
        await client.get(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    ).json()
    assert [(v["version_number"], v["is_active"]) for v in detail["versions"]] == [
        (1, False),
        (2, True),
    ]
    # The earlier reply keeps the citation it was given.
    assert old_fee["citations"][0]["document_version_id"] == detail["versions"][0]["id"]


async def test_a_replaced_shipping_policy_no_longer_gives_the_old_rate(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(
        client,
        admin_headers,
        session_factory,
        settings,
        REPLACEMENT_TEST / "shipping-policy-v2.2.md",
        title="Shipping Policy",
        version_label="2.2",
    )
    before = await ask(client, GROUND_RATE)

    await ingest(
        client,
        admin_headers,
        session_factory,
        settings,
        NORTHLINE_DOCUMENTS / "shipping-policy.md",
        document_id=document["id"],
        version_label="3.0",
    )
    after = await ask(client, GROUND_RATE)

    assert before["answer_type"] == "grounded"
    assert "$12.95 per order; free on orders of $750 or more" in before["content"]
    assert before["citations"][0]["version_label"] == "2.2"
    assert after["answer_type"] == "grounded"
    assert "$14.95 per order; free on orders of $500 or more" in after["content"]
    assert "$12.95" not in _quoted(after)
    assert "$750" not in _quoted(after)
    assert {citation["version_label"] for citation in after["citations"]} == {"3.0"}


async def test_a_deleted_document_is_not_cited_and_leaves_a_knowledge_gap(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(
        client,
        admin_headers,
        session_factory,
        settings,
        NORTHLINE_DOCUMENTS / "returns-policy.md",
        version_label="2.0",
    )
    conversation = (await client.post("/api/conversations")).json()
    before = await ask(client, RESTOCKING_FEE, conversation["id"])
    assert before["answer_type"] == "grounded"
    assert before["citations"][0]["document_id"] == document["id"]

    deleted = await client.delete(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    after = await ask(client, RESTOCKING_FEE, conversation["id"])

    assert deleted.status_code == 204
    assert after["answer_type"] == "knowledge_gap"
    assert after["citations"] == []
    assert "15%" not in after["content"]
    assert "Would you like a person to follow up" in after["content"]
    assert after["usage"]["retrieved"] == []
    assert await _search(client, admin_headers, RESTOCKING_FEE) == []

    # The reply given before the deletion still shows what it was based on.
    history = (await client.get(f"/api/conversations/{conversation['id']}")).json()["messages"]
    assert history[1]["citations"] == before["citations"]
    assert history[1]["citations"][0]["document_title"] == "Returns Policy"


async def test_deleting_one_document_leaves_the_others_searchable(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    returns = await ingest(
        client, admin_headers, session_factory, settings, NORTHLINE_DOCUMENTS / "returns-policy.md"
    )
    shipping = await ingest(
        client, admin_headers, session_factory, settings, NORTHLINE_DOCUMENTS / "shipping-policy.md"
    )

    await client.delete(f"/api/admin/documents/{returns['id']}", headers=admin_headers)
    reply = await ask(client, GROUND_RATE)
    passages = await _search(client, admin_headers, "return an opened item restocking fee")

    assert reply["answer_type"] == "grounded"
    assert reply["citations"][0]["document_id"] == shipping["id"]
    assert passages
    assert {passage["document_id"] for passage in passages} == {shipping["id"]}
    # Deletion is soft: the rows stay for old citations, only retrieval skips them.
    async with session_factory() as session:
        stored = (await session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    assert stored > len(passages)
