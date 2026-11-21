"""End-to-end smoke check over HTTP: `python -m scripts.smoke` (`make smoke`).

The command starts an embedded PostgreSQL in a temporary directory, applies the
migrations, loads the Northline knowledge base, starts the API and the worker
as separate processes and walks the demo scenario through the public HTTP API:

    question -> cited answer -> knowledge gap -> human handoff ->
    purchase request -> confirmation -> delivery -> delivery error and retry

It always runs in the local and simulated modes, whatever `.env` says, so it
needs no API key and writes to no CRM. Any difference from the expected
behavior stops the run with a message and exit code 1. It uses no browser; the
UI is covered by the frontend tests.
"""

import asyncio
import contextlib
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from scripts.dev import BACKEND_DIR, DEMO_MANIFEST, migrate
from scripts.embedded_postgres import embedded_postgres
from scripts.seed_knowledge_base import seed

STARTUP_TIMEOUT_SECONDS = 60.0
DELIVERY_TIMEOUT_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30.0

# Fixed for the run: the check must not depend on the developer's `.env`.
MODES = {
    "APP_ENV": "test",
    "LLM_PROVIDER": "local",
    "EMBEDDING_PROVIDER": "local",
    "CRM_PROVIDER": "simulated",
    # Short waits between delivery attempts, so the retry path takes seconds.
    "WORKER_POLL_INTERVAL_SECONDS": "0.2",
    "JOB_BACKOFF_BASE_SECONDS": "1",
    "JOB_BACKOFF_MAX_SECONDS": "2",
}

Json = dict[str, Any]


class SmokeError(Exception):
    """The system did not behave as the scenario expects."""


def check(condition: object, message: str, got: object = None) -> None:
    if not condition:
        raise SmokeError(message if got is None else f"{message} Got: {got!r}")


def step(title: str) -> None:
    print(f"  ok  {title}", flush=True)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port: int = listener.getsockname()[1]
        return port


@contextmanager
def processes(database_url: str, port: int, admin_token: str) -> Iterator[None]:
    """The API and the worker as their own processes, as `make dev` runs them."""
    env = {**os.environ, **MODES, "DATABASE_URL": database_url, "ADMIN_API_TOKEN": admin_token}
    commands = {
        "api": [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        "worker": [sys.executable, "-m", "app.worker"],
    }
    with tempfile.TemporaryFile() as output:
        started = {
            name: subprocess.Popen(  # noqa: S603 - fixed commands, no shell
                argv, cwd=BACKEND_DIR, env=env, stdout=output, stderr=subprocess.STDOUT
            )
            for name, argv in commands.items()
        }
        try:
            yield
        except BaseException:
            for process in started.values():
                process.terminate()
            for process in started.values():
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=10)
            output.seek(0)
            tail = output.read().decode(errors="replace")[-4000:]
            if tail.strip():
                print("--- last output of the API and the worker ---")
                print(tail)
            raise
        finally:
            for process in started.values():
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
            for process in started.values():
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


def wait_until[T](
    read: Callable[[], T], done: Callable[[T], bool], *, timeout: float, what: str
) -> T:
    deadline = time.monotonic() + timeout
    value = read()
    while not done(value):
        if time.monotonic() > deadline:
            raise SmokeError(f"Timed out waiting for {what}. Last state: {value!r}")
        time.sleep(0.2)
        value = read()
    return value


class Api:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def call(self, method: str, path: str, *, expect: int, **kwargs: Any) -> Json:
        response = self.client.request(method, path, **kwargs)
        check(
            response.status_code == expect,
            f"{method} {path} should answer {expect}.",
            f"{response.status_code} {response.text[:300]}",
        )
        body: Json = response.json() if response.content else {}
        return body

    def ask(self, conversation_id: str, content: str) -> Json:
        exchange = self.call(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            expect=201,
            json={"content": content},
        )
        reply: Json = exchange["assistant_message"]
        return reply

    def delivery(self, inquiry_id: str) -> Json:
        return self.call("GET", f"/api/inquiries/{inquiry_id}/delivery", expect=200)

    def wait_for_delivery(self, inquiry_id: str, status: str) -> Json:
        seen: list[tuple[str, int]] = []

        def read() -> Json:
            delivery = self.delivery(inquiry_id)
            state = (delivery["status"], delivery["attempt_count"])
            if not seen or seen[-1] != state:
                seen.append(state)
            return delivery

        delivery = wait_until(
            read,
            lambda current: current["status"] in ("delivered", "failed"),
            timeout=DELIVERY_TIMEOUT_SECONDS,
            what=f"the delivery of inquiry {inquiry_id}",
        )
        check(delivery["status"] == status, f"The delivery should end as {status}.", delivery)
        delivery["seen"] = seen
        return delivery


def wait_for_api(api: Api) -> None:
    def healthy() -> bool:
        try:
            return api.client.get("/api/health").status_code == 200
        except httpx.TransportError:
            return False

    wait_until(healthy, bool, timeout=STARTUP_TIMEOUT_SECONDS, what="the API to start")


def scenario(api: Api, admin_token: str) -> None:
    health = api.call("GET", "/api/health", expect=200)
    providers = health["providers"]
    check(health["status"] == "ok", "Health should be ok.", health)
    check(
        [providers[name]["mode"] for name in ("llm", "embeddings", "crm")]
        == ["local", "local", "simulated"],
        "The run should use the local and simulated modes.",
        providers,
    )
    check(
        not any(providers[name]["live"] for name in ("llm", "embeddings", "crm")),
        "No provider should be reported as live.",
        providers,
    )
    step("health: database ok, modes local / local / simulated, none reported as live")

    conversation = api.call("POST", "/api/conversations", expect=201)
    conversation_id = conversation["id"]

    # 1-2. A question the documents answer: a grounded reply with its source.
    answer = api.ask(conversation_id, "How much does shipping cost?")
    check(answer["answer_type"] == "grounded", "A shipping question should be grounded.", answer)
    check(answer["citations"], "A grounded reply should cite a source.", answer)
    cited = " ".join(citation["excerpt"] for citation in answer["citations"])
    check("$14.95" in cited and "$14.95" in answer["content"], "The cited rate should be $14.95.")
    check(
        all(
            citation["document_title"] and citation["version_number"]
            for citation in answer["citations"]
        ),
        "Every citation should name its document and version.",
        answer["citations"],
    )
    check(not answer["usage"]["llm_live"], "The reply should be labeled as local mode.")
    step("question: grounded answer with a citation (document, version, excerpt)")

    # 3. A question the documents do not answer: offer a simulated handoff.
    question = "Do you offer on-site installation in Brazil?"
    gap = api.ask(conversation_id, question)
    check(gap["answer_type"] == "knowledge_gap", "The question should be a knowledge gap.", gap)
    check(gap["citations"] == [] and gap["inquiry"] is None, "A gap has no source and no inquiry.")
    check(
        "Delivery is simulated" in gap["content"] and "no person will receive" in gap["content"],
        "The gap reply should disclose simulated delivery and offer a handoff.",
        gap["content"],
    )
    step("unanswerable question: knowledge gap without citations, simulated handoff offered")

    handoff = api.call(
        "POST",
        "/api/inquiries",
        expect=201,
        json={
            "kind": "handoff",
            "conversation_id": conversation_id,
            "contact": {"name": "Marcus Oyelaran", "email": "marcus.oyelaran@example.org"},
            "notes": question,
        },
    )
    check(
        (handoff["status"], handoff["missing_fields"]) == ("draft", []),
        "The handoff request should be a complete draft.",
        handoff,
    )
    check(handoff["delivery"] is None, "Nothing is delivered before confirmation.", handoff)
    confirmed = api.call("POST", f"/api/inquiries/{handoff['id']}/confirm", expect=200)
    check(confirmed["status"] == "confirmed", "The handoff should be confirmed.", confirmed)
    delivered = api.wait_for_delivery(handoff["id"], "delivered")
    check(
        (delivered["live"], delivered["crm_mode"], delivered["attempt_count"])
        == (False, "simulated", 1),
        "The handoff should be delivered to the simulated CRM in one attempt.",
        delivered,
    )
    check(delivered["crm_record_id"], "A delivered inquiry should have a CRM record ID.")
    step("human handoff: draft, confirmation, delivered (simulated, not a live CRM)")

    # 4-5. A purchase request that also asks a question: the answer, then the draft.
    offer = api.ask(conversation_id, "I want 12 LP-420 printers, what is the warranty?")
    check(offer["answer_type"] == "inquiry_offer", "The request should get an offer.", offer)
    check(
        offer["usage"]["question_answer_type"] == "grounded" and offer["citations"],
        "The question in the request should be answered with a citation first.",
        offer,
    )
    check("2-year warranty" in offer["content"], "The reply should state the warranty.")
    draft = offer["inquiry"]
    check(
        draft is not None
        and (draft["status"], draft["product"], draft["quantity"])
        == ("draft", "LP-420 printers", 12),
        "The reply should carry a draft with the product and the quantity.",
        draft,
    )
    check(
        draft["missing_fields"] == ["timeline", "contact_name", "contact_email"],
        "The draft should list what is still missing.",
        draft,
    )
    step("purchase request with a question: cited answer first, then the inquiry draft")

    rejected = api.call("POST", f"/api/inquiries/{draft['id']}/confirm", expect=422)
    check(rejected["error"]["code"] == "validation_error", "An incomplete draft is not sent.")
    preview = api.call(
        "PATCH",
        f"/api/inquiries/{draft['id']}",
        expect=200,
        json={
            "timeline": "Within 4 weeks",
            "contact": {"name": "Dana Whitfield", "email": "dana.whitfield+fail2@example.com"},
        },
    )
    check(
        (preview["status"], preview["missing_fields"], preview["delivery"]) == ("draft", [], None),
        "The completed draft should wait for confirmation.",
        preview,
    )
    step("confirmation is required: an incomplete draft is refused, a complete one waits")

    # 6. Delivery with temporary errors: two failed attempts, then delivered.
    api.call("POST", f"/api/inquiries/{draft['id']}/confirm", expect=200)
    again = api.call("POST", f"/api/inquiries/{draft['id']}/confirm", expect=200)
    check(again["status"] == "confirmed", "Confirming twice returns the same inquiry.", again)
    api.call("PATCH", f"/api/inquiries/{draft['id']}", expect=409, json={"quantity": 99})
    retried = api.wait_for_delivery(draft["id"], "delivered")
    outcomes = [attempt["outcome"] for attempt in retried["attempts"]]
    check(
        retried["attempt_count"] == 3 and outcomes == ["failed", "failed", "succeeded"],
        "The delivery should succeed on the third attempt.",
        retried,
    )
    check(
        any(status == "pending" and attempts > 0 for status, attempts in retried["seen"]),
        "The status should show the wait for an automatic retry.",
        retried["seen"],
    )
    step("delivery: two temporary errors, automatic retries, delivered on attempt 3")

    # Delivery with a permanent error: failed at once, a manual retry delivers it.
    failing = api.call(
        "POST",
        "/api/inquiries",
        expect=201,
        json={
            "conversation_id": conversation_id,
            "product": "P-240 laser printer",
            "quantity": 5,
            "timeline": "By the end of March",
            "contact": {"name": "Priya Raman", "email": "priya.raman+reject1@example.com"},
        },
    )
    api.call("POST", f"/api/inquiries/{failing['id']}/confirm", expect=200)
    failed = api.wait_for_delivery(failing["id"], "failed")
    check(
        (failed["failure_reason"], failed["attempt_count"]) == ("permanent_error", 1),
        "A rejected delivery should fail at once with its reason.",
        failed,
    )
    check(failed["last_error"], "A failed delivery should keep its error.", failed)
    api.call("POST", f"/api/inquiries/{draft['id']}/delivery/retry", expect=409)
    api.call("POST", f"/api/inquiries/{failing['id']}/delivery/retry", expect=202)
    recovered = api.wait_for_delivery(failing["id"], "delivered")
    check(recovered["attempt_count"] == 2, "The manual retry should be attempt 2.", recovered)
    step("delivery error: failed with a reason, manual retry delivers; no retry of a delivered one")

    # The conversation lists its inquiries, so a client can restore them after a reload.
    restored = api.call("GET", f"/api/conversations/{conversation_id}", expect=200)
    check(
        [(inquiry["kind"], inquiry["status"]) for inquiry in restored["inquiries"]]
        == [("handoff", "confirmed"), ("purchase", "confirmed"), ("purchase", "confirmed")],
        "The conversation should list its three inquiries, oldest first.",
        restored["inquiries"],
    )
    check(
        all(inquiry["delivery"]["status"] == "delivered" for inquiry in restored["inquiries"]),
        "Every inquiry of the conversation should read as delivered.",
        restored["inquiries"],
    )
    check(len(restored["messages"]) == 6, "The conversation should keep its six messages.")
    step("conversation: messages and inquiries are restored with their delivery status")

    # Admin: closed to visitors, and one record per inquiry.
    api.call("GET", "/api/admin/inquiries", expect=401)
    api.call(
        "GET", "/api/admin/inquiries", expect=403, headers={"Authorization": "Bearer wrong-token"}
    )
    listed = api.call(
        "GET",
        "/api/admin/inquiries",
        expect=200,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    check(listed["total"] == 3, "The admin list should hold exactly three inquiries.", listed)
    records = [item["delivery"]["crm_record_id"] for item in listed["items"]]
    check(len(set(records)) == 3, "Each inquiry should have its own CRM record.", records)
    step("admin: no token 401, wrong token 403, three inquiries, one CRM record each")


def main() -> int:
    admin_token = secrets.token_urlsafe(24)
    port = free_port()
    print("Smoke check in the local and simulated modes (no API key, no CRM account).")
    try:
        with (
            tempfile.TemporaryDirectory(prefix="handoff-smoke-pg-") as directory,
            embedded_postgres(Path(directory), database="handoff_smoke") as database_url,
        ):
            migrate(database_url)
            seeded = asyncio.run(
                seed(Settings(database_url=database_url, **_mode_settings()), DEMO_MANIFEST)
            )
            step(f"isolated database: migrations applied, {len(seeded)} documents indexed")
            with (
                processes(database_url, port, admin_token),
                httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", timeout=REQUEST_TIMEOUT_SECONDS
                ) as client,
            ):
                api = Api(client)
                wait_for_api(api)
                scenario(api, admin_token)
    except SmokeError as failure:
        print(f"FAILED: {failure}")
        return 1
    print("Smoke check passed.")
    return 0


def _mode_settings() -> dict[str, Any]:
    """The provider modes of the run as `Settings` fields, for seeding in this process."""
    return {
        "llm_provider": MODES["LLM_PROVIDER"],
        "embedding_provider": MODES["EMBEDDING_PROVIDER"],
        "crm_provider": MODES["CRM_PROVIDER"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
