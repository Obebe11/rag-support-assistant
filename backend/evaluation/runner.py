"""Run the evaluation cases against the real API on isolated databases.

For every knowledge base the runner creates a fresh database, applies the
migrations, loads the Northline corpus (plus the injection fixtures a case
lists), starts the application in this process and talks to it over its HTTP
API: `POST /api/admin/documents/search` for retrieval on its own and
`POST /api/conversations/{id}/messages` for the reply. A multi-turn case is one
conversation, so every later turn sees the assistant's real earlier replies.

Providers come from the settings, as for the API. The CRM is forced to the
simulated mode with the access check off: the cases confirm no inquiry, so
nothing is ever sent to a CRM.
"""

import asyncio
import json
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import REPO_ROOT, CRMProviderMode, Settings
from app.core.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Chunk, Document, DocumentVersion
from app.providers.factory import build_embedding_provider, build_llm_provider
from app.services.documents.seeding import SeedResult, load_manifest, seed_manifest
from evaluation.cases import CORPUS_MANIFEST, FIXTURES_MANIFEST, Case, Turn, load_cases
from evaluation.judge import ERROR, Judge
from evaluation.scoring import (
    FAIL,
    PASS,
    TOP_K,
    Passage,
    case_status,
    review_items,
    score_turn,
    source_matches,
    summarize_group,
    timing_stats,
    turn_status,
    verdict_digest,
)

SCHEMA_VERSION = 1
BACKEND_DIR = REPO_ROOT / "backend"
PROVIDER_RETRIES = 2
"""Extra attempts for a message the API answered with 503 (a provider failure)."""
PROVIDER_RETRY_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 600.0
"""For one request to the in-process API. A live LLM reply can take a while."""
CATEGORIES = ("answerable", "unanswerable", "multi_turn", "instruction_override")


class EvaluationError(Exception):
    """The run could not be completed."""


@dataclass(frozen=True, slots=True)
class RunOptions:
    settings: Settings
    """Provider modes, models and prices. The database URL in it is not used."""
    server_url: str
    """Any database on the PostgreSQL server where the run may create databases."""
    case_ids: frozenset[str] | None = None
    use_judge: bool = False
    command: str = "make eval"


# --- Databases ----------------------------------------------------------------


async def _admin_statement(server_url: str, statement: str) -> None:
    engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")


@asynccontextmanager
async def isolated_database(server_url: str, name: str) -> AsyncIterator[str]:
    """Create the database `name` with the current schema; drop it afterwards."""
    if not name.isidentifier():
        raise EvaluationError(f"Not a valid database name: {name!r}")
    await _admin_statement(server_url, f'CREATE DATABASE "{name}"')
    try:
        url = make_url(server_url).set(database=name).render_as_string(hide_password=False)
        # Alembic runs its own event loop, so it gets its own thread.
        await asyncio.to_thread(_migrate, url)
        yield url
    finally:
        await _admin_statement(server_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


# --- Knowledge bases ----------------------------------------------------------


def _fixture_manifest(fixtures: Sequence[str], directory: Path) -> Path:
    """A manifest in `directory` that holds only the listed fixture documents."""
    available = {document.doc_id: document for document in load_manifest(FIXTURES_MANIFEST)}
    unknown = sorted(set(fixtures) - set(available))
    if unknown:
        raise EvaluationError(f"Unknown fixture doc_id: {', '.join(unknown)}")
    entries = []
    for doc_id in fixtures:
        document = available[doc_id]
        shutil.copy(document.path, directory / document.path.name)
        entries.append(
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "version": document.version,
                "path": document.path.name,
            }
        )
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps({"documents": entries}), encoding="utf-8")
    return manifest_path


async def _seed(
    settings: Settings, fixtures: Sequence[str]
) -> tuple[list[SeedResult], list[Passage]]:
    """Load the corpus and the listed fixtures. Returns the seed results and every
    searchable passage, reduced to document, section and page."""
    engine = create_engine(settings.database_url)
    embeddings = build_embedding_provider(settings)
    try:
        session_factory = create_session_factory(engine)
        results = await seed_manifest(
            session_factory,
            embeddings,
            CORPUS_MANIFEST,
            max_upload_bytes=settings.max_upload_bytes,
        )
        if fixtures:
            with tempfile.TemporaryDirectory(prefix="handoff-eval-fixtures-") as directory:
                results += await seed_manifest(
                    session_factory,
                    embeddings,
                    _fixture_manifest(fixtures, Path(directory)),
                    max_upload_bytes=settings.max_upload_bytes,
                )
        doc_ids = {result.document_id: result.doc_id for result in results}
        async with session_factory() as session:
            rows = await session.execute(
                select(Document.id, Chunk.heading, Chunk.page_number)
                .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
                .join(Document, DocumentVersion.document_id == Document.id)
                .where(DocumentVersion.is_active.is_(True), Document.deleted_at.is_(None))
            )
            indexed = [
                Passage(doc_id=doc_ids.get(row[0]), section=row[1], page_number=row[2])
                for row in rows.all()
            ]
        return results, indexed
    finally:
        await embeddings.aclose()
        await engine.dispose()


def unresolved_sources(cases: Sequence[Case], indexed: Sequence[Passage]) -> list[dict[str, Any]]:
    """Expected sources that match no indexed passage at all.

    Such a source can never be retrieved or cited, whatever the search does: the
    case names a section or a page that the indexed document does not have. That
    is an error in the case or in the chunking, not a retrieval result.
    """
    return [
        {
            "case_id": case.id,
            "turn": index,
            "doc_id": source.doc_id,
            "section": source.section,
            "page": source.page,
        }
        for case in cases
        for index, turn in enumerate(case.turns, start=1)
        for source in turn.expect.sources
        if not any(source_matches(source, passage) for passage in indexed)
    ]


# --- One conversation ---------------------------------------------------------


def _passage(item: dict[str, Any], doc_ids: dict[str, str]) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "score": item.get("score"),
        "doc_id": doc_ids.get(str(item["document_id"])),
        "document_title": item["document_title"],
        "version_label": item.get("version_label"),
        "section": item.get("section"),
        "page_number": item.get("page_number"),
    }


def _as_passage(item: dict[str, Any]) -> Passage:
    return Passage(doc_id=item["doc_id"], section=item["section"], page_number=item["page_number"])


def _expected(turn: Turn) -> dict[str, Any]:
    expect = turn.expect
    return {
        "response_type": expect.response_type,
        "offer_handoff": expect.offer_handoff,
        "require_all_sources": expect.require_all_sources,
        "reference_answer": expect.reference_answer,
        "sources": [
            {"doc_id": source.doc_id, "section": source.section, "page": source.page}
            for source in expect.sources
        ],
    }


async def _post_message(
    client: httpx.AsyncClient, conversation_id: str, content: str
) -> tuple[httpx.Response, int]:
    """Send a visitor message. A 503 (provider failure) is tried again a few times."""
    for attempt in range(PROVIDER_RETRIES + 1):
        started = time.perf_counter()
        response = await client.post(
            f"/api/conversations/{conversation_id}/messages", json={"content": content}
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        if response.status_code != 503 or attempt == PROVIDER_RETRIES:
            break
        await asyncio.sleep(PROVIDER_RETRY_SECONDS)
    return response, elapsed_ms


async def _judge_turn(judge: Judge, turn: Turn, result: dict[str, Any]) -> None:
    """Ask the judge about every review item and about source support of the reply."""
    reply, checks = result["reply"], result["checks"]
    verdicts: dict[str, str] = {}
    for item in result["review"]:
        if item["kind"] == "must_include_miss":
            verdict = await judge.states_fact(
                user=turn.user, reply=reply["text"], fact=item["statement"]
            )
        else:
            verdict = await judge.makes_claim(
                user=turn.user, reply=reply["text"], claim=item["statement"]
            )
        item["judge"] = verdict
        if verdict["verdict"] != ERROR:
            verdicts[item["check"]] = verdict["verdict"]
    if reply["answer_type"] == "grounded" and reply["citations"]:
        checks["judge_support"] = await judge.is_supported(
            user=turn.user,
            reply=reply["text"],
            excerpts=[citation["excerpt"] for citation in reply["citations"]],
        )
    result["judged_status"] = turn_status(checks, verdicts)


async def _run_turn(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    conversation_id: str,
    index: int,
    turn: Turn,
    doc_ids: dict[str, str],
    judge: Judge | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "index": index,
        "user": turn.user,
        "expected": _expected(turn),
        "reply": None,
        "retrieval": {"search_top": [], "reply_top": None},
        "checks": None,
        "review": [],
        "status": FAIL,
        "error": None,
    }

    search = await client.post(
        "/api/admin/documents/search",
        headers=admin_headers,
        json={"query": turn.user, "top_k": TOP_K},
    )
    if search.status_code != 200:
        result["error"] = f"Search failed with status {search.status_code}: {search.text[:300]}"
        return result
    search_top = [_passage(item, doc_ids) for item in search.json()["items"]]
    result["retrieval"]["search_top"] = search_top

    response, wall_time_ms = await _post_message(client, conversation_id, turn.user)
    if response.status_code != 201:
        result["error"] = (
            f"The message failed with status {response.status_code}: {response.text[:300]}"
        )
        return result
    message = response.json()["assistant_message"]
    usage = message["usage"]
    searched = usage["embedding_mode"] is not None
    reply_top = [_passage(item, doc_ids) for item in usage["retrieved"]][:TOP_K]
    citations = [
        {**_passage(citation, doc_ids), "excerpt": citation["excerpt"]}
        for citation in message["citations"]
    ]
    for citation in citations:
        del citation["rank"]
    result["reply"] = {
        "answer_type": message["answer_type"],
        "text": message["content"],
        "citations": citations,
        "inquiry_offered": message["inquiry"] is not None,
        "usage": {key: value for key, value in usage.items() if key != "retrieved"},
        "wall_time_ms": wall_time_ms,
    }
    result["retrieval"]["reply_top"] = reply_top if searched else None

    checks = score_turn(
        turn.expect,
        answer_type=message["answer_type"],
        text=message["content"],
        citations=[(_as_passage(citation), citation["excerpt"]) for citation in citations],
        search_top=[_as_passage(item) for item in search_top],
        reply_top=[_as_passage(item) for item in reply_top] if searched else None,
    )
    result["checks"] = checks
    result["review"] = review_items(checks)
    result["status"] = turn_status(checks)
    if judge is not None:
        await _judge_turn(judge, turn, result)
    return result


async def _run_case(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    case: Case,
    knowledge_base: str,
    doc_ids: dict[str, str],
    judge: Judge | None,
) -> dict[str, Any]:
    created = await client.post("/api/conversations")
    if created.status_code != 201:
        raise EvaluationError(f"Cannot start a conversation: {created.status_code} {created.text}")
    conversation_id = created.json()["id"]
    turns = [
        await _run_turn(client, admin_headers, conversation_id, index, turn, doc_ids, judge)
        for index, turn in enumerate(case.turns, start=1)
    ]
    result: dict[str, Any] = {
        "id": case.id,
        "category": case.category,
        "title": case.title,
        "topics": list(case.topics),
        "attack_vector": case.attack_vector,
        "fixtures": list(case.fixtures),
        "knowledge_base": knowledge_base,
        "status": case_status([turn["status"] for turn in turns]),
        "turns": turns,
    }
    if judge is not None:
        result["judged_status"] = case_status(
            [turn.get("judged_status", turn["status"]) for turn in turns]
        )
    return result


# --- One knowledge base -------------------------------------------------------


async def _run_knowledge_base(
    options: RunOptions,
    name: str,
    fixtures: Sequence[str],
    cases: Sequence[Case],
    judge: Judge | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    database = f"handoff_eval_{uuid.uuid4().hex[:12]}"
    async with isolated_database(options.server_url, database) as database_url:
        token = secrets.token_urlsafe(24)
        settings = options.settings.model_copy(
            update={
                "database_url": database_url,
                "admin_api_token": SecretStr(token),
                "crm_provider": CRMProviderMode.SIMULATED,
                "crm_access_check_enabled": False,
                "cors_allowed_origins": [],
            }
        )
        seeded, indexed = await _seed(settings, fixtures)
        doc_ids = {str(result.document_id): result.doc_id for result in seeded}
        description = {
            "name": name,
            "fixtures": list(fixtures),
            "unresolved_sources": unresolved_sources(cases, indexed),
            "documents": [
                {
                    "doc_id": result.doc_id,
                    "title": result.title,
                    "version": result.version_label,
                    "chunks": result.chunk_count,
                }
                for result in seeded
            ],
        }
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://evaluation", timeout=REQUEST_TIMEOUT_SECONDS
            ) as client:
                admin_headers = {"Authorization": f"Bearer {token}"}
                results = [
                    await _run_case(client, admin_headers, case, name, doc_ids, judge)
                    for case in cases
                ]
    return description, results


# --- The run ------------------------------------------------------------------


def _git(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            ["git", *arguments],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _llm_cost(settings: Settings, live: bool, tokens: dict[str, Any]) -> dict[str, Any]:
    """API cost from token counts and configured prices. Never a made-up zero."""
    if not live:
        return {
            "status": "not_applicable",
            "usd": None,
            "note": "No LLM API was called: the LLM provider ran in local mode.",
        }
    input_price = settings.llm_input_price_per_million_tokens
    output_price = settings.llm_output_price_per_million_tokens
    if input_price is None or output_price is None:
        return {
            "status": "not_configured",
            "usd": None,
            "note": "Set LLM_INPUT_PRICE_PER_MILLION_TOKENS and "
            "LLM_OUTPUT_PRICE_PER_MILLION_TOKENS to compute the cost.",
        }
    if tokens["calls_without_token_data"]:
        return {
            "status": "incomplete",
            "usd": None,
            "note": f"{tokens['calls_without_token_data']} LLM call(s) reported no token "
            "counts, so the cost cannot be computed.",
        }
    usd = (tokens["input_tokens"] * input_price + tokens["output_tokens"] * output_price) / 1e6
    return {"status": "computed", "usd": round(usd, 6), "note": None}


def _reply_tokens(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Tokens of the replies an LLM wrote. Replies without an LLM call are left out."""
    usages = [
        turn["reply"]["usage"]
        for case in cases
        for turn in case["turns"]
        if turn["reply"] is not None and turn["reply"]["usage"]["llm_time_ms"] is not None
    ]
    reported = [usage for usage in usages if usage["input_tokens"] is not None]
    return {
        "llm_calls": len(usages),
        "calls_without_token_data": len(usages) - len(reported),
        "input_tokens": sum(usage["input_tokens"] for usage in reported),
        "output_tokens": sum(usage["output_tokens"] or 0 for usage in reported),
    }


def _timing(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    usages = [
        turn["reply"]["usage"]
        for case in cases
        for turn in case["turns"]
        if turn["reply"] is not None
    ]
    return {
        "response": timing_stats([usage["response_time_ms"] for usage in usages]),
        "retrieval": timing_stats([usage["retrieval_time_ms"] for usage in usages]),
        "llm": timing_stats([usage["llm_time_ms"] for usage in usages]),
    }


def collect_failures(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every turn the automated first pass failed, with the reasons."""
    failures: list[dict[str, Any]] = []
    for case in cases:
        for turn in case["turns"]:
            if turn["status"] != FAIL:
                continue
            reasons: list[str] = []
            checks = turn["checks"]
            if turn["error"]:
                reasons.append(f"error: {turn['error']}")
            if checks:
                response_type = checks["response_type"]
                if response_type["status"] == FAIL:
                    reasons.append(
                        f"response type: expected {response_type['expected']}, "
                        f"got {response_type['actual']}"
                    )
                if checks["offer_handoff"]["status"] == FAIL:
                    reasons.append("no human handoff offered")
                reasons += [
                    f"{item['id']} not found: {item['fact']}"
                    for item in checks["must_include"]
                    if item["status"] == FAIL
                ]
            failures.append({"case_id": case["id"], "turn": turn["index"], "reasons": reasons})
    return failures


def collect_review(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every check that needs a reviewer or a judge, across the run."""
    return [
        {"case_id": case["id"], "turn": turn["index"], **item}
        for case in cases
        for turn in case["turns"]
        for item in turn["review"]
    ]


async def run(options: RunOptions) -> dict[str, Any]:
    """Run the selected cases and return the results document."""
    started_at = datetime.now(UTC)
    cases = load_cases()
    if options.case_ids is not None:
        unknown = sorted(options.case_ids - {case.id for case in cases})
        if unknown:
            raise EvaluationError(f"Unknown case id: {', '.join(unknown)}")
        cases = [case for case in cases if case.id in options.case_ids]

    llm = build_llm_provider(options.settings)
    embeddings = build_embedding_provider(options.settings)
    providers = {
        "llm": {"mode": llm.mode.value, "live": llm.live, "model": llm.model_name},
        "embeddings": {
            "mode": embeddings.mode.value,
            "live": embeddings.live,
            "model": embeddings.model_name,
        },
        "crm": {
            "mode": CRMProviderMode.SIMULATED.value,
            "live": False,
            "note": "Not exercised: the cases confirm no inquiry.",
        },
    }
    await embeddings.aclose()

    judge: Judge | None = None
    if options.use_judge and llm.live:
        judge = Judge(llm)
        judge_info: dict[str, Any] = {"enabled": True, "model": judge.model}
    elif options.use_judge:
        judge_info = {
            "enabled": False,
            "reason": "The judge was requested, but the LLM provider is not live.",
        }
    else:
        judge_info = {"enabled": False, "reason": "Not requested."}

    # One knowledge base per distinct set of fixtures, in order of first use.
    groups: dict[tuple[str, ...], list[Case]] = {}
    for case in cases:
        groups.setdefault(case.fixtures, []).append(case)

    knowledge_bases: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    try:
        for fixtures, group in groups.items():
            name = "corpus" if not fixtures else "corpus+" + "+".join(fixtures)
            description, results = await _run_knowledge_base(options, name, fixtures, group, judge)
            knowledge_bases.append(description)
            by_id.update({result["id"]: result for result in results})
    finally:
        await llm.aclose()
    results = [by_id[case.id] for case in cases]

    tokens = _reply_tokens(results)
    summary: dict[str, Any] = {
        "overall": summarize_group(results),
        "by_category": {
            category: summarize_group([case for case in results if case["category"] == category])
            for category in CATEGORIES
            if any(case["category"] == category for case in results)
        },
        "timing": _timing(results),
        "tokens": tokens,
        "cost": {
            "currency": "USD",
            "llm": _llm_cost(options.settings, llm.live, tokens),
            "embeddings": (
                {
                    "status": "not_measured",
                    "usd": None,
                    "note": "The application does not record embedding token usage.",
                }
                if embeddings.live
                else {
                    "status": "not_applicable",
                    "usd": None,
                    "note": "No embedding API was called: embeddings ran in local mode.",
                }
            ),
        },
    }
    if judge is not None:
        judge_tokens = {
            "llm_calls": judge.usage.calls,
            "calls_without_token_data": judge.usage.calls_without_token_data,
            "input_tokens": judge.usage.input_tokens,
            "output_tokens": judge.usage.output_tokens,
        }
        judge_info.update(
            {
                "calls": judge.usage.calls,
                "errors": judge.usage.errors,
                "tokens": judge_tokens,
                "cost": _llm_cost(options.settings, True, judge_tokens),
            }
        )
        summary["judged_case_status"] = {
            "overall": summarize_group(results, "judged_status")["case_status"],
            "by_category": {
                category: summarize_group(
                    [case for case in results if case["category"] == category], "judged_status"
                )["case_status"]
                for category in summary["by_category"]
            },
        }
        supported = [
            turn["checks"]["judge_support"]["verdict"]
            for case in results
            for turn in case["turns"]
            if turn["checks"] and "judge_support" in turn["checks"]
        ]
        summary["judge_support"] = {
            "passed": supported.count(PASS),
            "failed": supported.count(FAIL),
            "errors": supported.count(ERROR),
            "total": len(supported),
        }

    status = _git("status", "--porcelain")
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "command": options.command,
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(status) if status is not None else None,
            "providers": providers,
            "judge": judge_info,
            "pricing": {
                "currency": "USD",
                "llm_input_per_million_tokens": (
                    options.settings.llm_input_price_per_million_tokens
                ),
                "llm_output_per_million_tokens": (
                    options.settings.llm_output_price_per_million_tokens
                ),
            },
            "top_k": TOP_K,
            "case_filter": sorted(options.case_ids) if options.case_ids is not None else None,
            "verdict_digest": verdict_digest(results),
        },
        "knowledge_bases": knowledge_bases,
        "unresolved_sources": [
            source for base in knowledge_bases for source in base.pop("unresolved_sources")
        ],
        "summary": summary,
        "failures": collect_failures(results),
        "review": collect_review(results),
        "cases": results,
    }
