# Acceptance checks outside the 40 cases

The plan asks for separate checks of document replacement and deletion, inquiry confirmation, HubSpot failure handling, retries without duplicates and blocked visitor access to administrative actions. The 40 evaluation cases do not cover these. Automated tests do, and this file maps each check to the tests that prove it.

All paths are relative to `backend/tests/`. Run them with `make check`, or with `cd backend && uv run pytest`.

## What these tests prove and what they do not

- Every test runs the real API, worker, queue and handlers on PostgreSQL. Nothing in the tested path is mocked except the outside services.
- **HubSpot was never called.** The HubSpot tests run the real provider against an in-memory fake of the HubSpot API that follows the documented request and response shapes. A live account may behave differently. No HubSpot key was available for this task.
- The chat in these tests runs in the local demo mode (no LLM).
- "Worker dies" means the handler is stopped by an exception that skips all cleanup, and the lease is then expired by hand. No operating system process is killed.

## Document replacement

| Behavior | Tests |
| --- | --- |
| After the new version is indexed, admin search returns only its passages | `test_replacement_and_deletion.py::test_after_a_replacement_answers_rely_only_on_the_new_version`, `test_documents_admin_api.py::test_replacement_becomes_active_only_after_it_is_indexed`, `test_migrations.py::test_vector_search_reads_only_chunks_of_the_active_version` |
| Chat replies quote and cite only the new version | `test_replacement_and_deletion.py::test_after_a_replacement_answers_rely_only_on_the_new_version`, `test_replacement_and_deletion.py::test_a_replaced_shipping_policy_no_longer_gives_the_old_rate` |
| The old version keeps answering until the new one is indexed | `test_replacement_and_deletion.py::test_after_a_replacement_answers_rely_only_on_the_new_version`, `test_documents_admin_api.py::test_replacement_becomes_active_only_after_it_is_indexed` |
| A replacement that fails to index leaves the old version active: unreadable file, retries used up, worker death on the last attempt | `test_documents_admin_api.py::test_a_failed_replacement_leaves_the_old_version_active`, `test_documents_admin_api.py::test_a_replacement_that_runs_out_of_retries_leaves_the_old_version_active`, `test_indexing_recovery.py::test_worker_death_while_replacing_a_document_keeps_the_old_version_answering` |
| An older upload that is indexed late does not replace a newer one | `test_documents_admin_api.py::test_an_older_upload_indexed_late_does_not_replace_a_newer_one` |
| A stored reply keeps the citation of the version it was based on | `test_replacement_and_deletion.py::test_an_earlier_reply_keeps_its_citation_after_the_document_is_replaced` |

## Document deletion

| Behavior | Tests |
| --- | --- |
| A deleted document leaves admin search and the document list | `test_documents_admin_api.py::test_delete_removes_the_document_from_the_api_and_from_retrieval`, `test_replacement_and_deletion.py::test_a_deleted_document_is_not_cited_and_leaves_a_knowledge_gap` |
| Chat replies no longer use it; a question only it could answer becomes a knowledge gap | `test_replacement_and_deletion.py::test_a_deleted_document_is_not_cited_and_leaves_a_knowledge_gap`, `test_replacement_and_deletion.py::test_deleting_one_document_leaves_the_others_searchable` |
| A deleted document cannot be read, deleted again or replaced (404) | `test_documents_admin_api.py::test_delete_removes_the_document_from_the_api_and_from_retrieval` |
| A reply given before the deletion still shows its citation | `test_replacement_and_deletion.py::test_a_deleted_document_is_not_cited_and_leaves_a_knowledge_gap` |
| An indexing job that runs or finishes after the deletion does not bring the document back | `test_documents_admin_api.py::test_a_document_deleted_before_indexing_never_becomes_searchable`, `test_documents_admin_api.py::test_a_document_deleted_while_it_is_indexed_is_not_activated` |

## Inquiry confirmation

| Behavior | Tests |
| --- | --- |
| Nothing reaches the CRM before the visitor confirms, for a draft made through the API and for a draft made in the chat, even after the visitor writes "Yes, that's correct" | `test_inquiry_delivery.py::test_nothing_is_sent_to_the_crm_before_confirmation`, `test_inquiry_delivery.py::test_a_draft_made_in_the_chat_is_not_sent_even_when_the_visitor_agrees` |
| The chat only creates and fills a draft; it never confirms one | `test_inquiry_intent.py::test_follow_up_messages_fill_the_same_draft`, `test_inquiry_intent.py::test_confirmed_inquiry_is_final_and_a_new_request_starts_a_new_draft`, `test_chat_api.py::test_purchase_intent_from_the_inquiry_seam_becomes_an_inquiry_offer` |
| An incomplete draft cannot be confirmed: 422 that names the missing fields, no delivery and no job | `test_inquiries_api.py::test_incomplete_draft_cannot_be_confirmed`, `test_inquiries_api.py::test_empty_purchase_draft_lists_every_required_field`, `test_inquiries_api.py::test_handoff_draft_requires_contact_and_the_question` |
| A confirmed inquiry cannot be changed (409), purchase and handoff | `test_inquiries_api.py::test_confirmed_inquiry_cannot_be_changed` |
| Confirming twice, or five times at once, queues one delivery | `test_inquiries_api.py::test_confirming_twice_queues_one_delivery`, `test_inquiries_api.py::test_concurrent_confirmations_queue_one_delivery` |
| A confirmed inquiry is delivered, purchase and handoff | `test_inquiry_delivery.py::test_confirmed_inquiry_is_delivered` |

## HubSpot failure handling

| Behavior | Tests |
| --- | --- |
| HTTP statuses are classified: 423, 429, 477 and 5xx are temporary, other 4xx are permanent | `test_crm_hubspot.py::test_http_errors_are_classified` |
| A temporary error (timeout, 429, 502, 503) keeps the delivery pending and is retried after the backoff | `test_crm_hubspot.py::test_temporary_hubspot_errors_are_retried_after_the_backoff`, `test_crm_hubspot.py::test_worker_delivers_to_hubspot_and_retries_without_duplicates`, `test_inquiry_delivery.py::test_temporary_failure_is_retried_without_a_duplicate` |
| The backoff doubles with each attempt up to a maximum | `test_job_queue.py::test_failure_requeues_the_job_with_exponential_backoff` |
| A permanent error (400, 401, 403) fails the delivery at once, with no automatic retry | `test_crm_hubspot.py::test_permanent_hubspot_errors_fail_at_once_and_a_manual_retry_delivers`, `test_crm_hubspot.py::test_rejected_token_fails_the_delivery_at_once`, `test_inquiry_delivery.py::test_permanent_error_fails_at_once` |
| When the automatic attempts run out, the delivery is `failed` with the reason `attempts_exhausted` | `test_inquiry_delivery.py::test_attempts_run_out_and_a_manual_retry_delivers` |
| The stored and displayed error contains no token and no contact details | `test_crm_hubspot.py::test_errors_never_contain_the_token_or_an_email`, `test_crm_hubspot.py::test_errors_never_contain_the_contact_name_company_or_phone`, `test_crm_hubspot.py::test_permanent_hubspot_errors_fail_at_once_and_a_manual_retry_delivers` |
| A manual retry of a failed delivery works; a retry of a draft, a pending or a delivered inquiry is refused (409) | `test_inquiry_delivery.py::test_manual_retry_after_a_permanent_error`, `test_inquiry_delivery.py::test_attempts_run_out_and_a_manual_retry_delivers`, `test_inquiries_api.py::test_delivery_endpoints_reject_a_draft`, `test_inquiries_api.py::test_retry_is_rejected_unless_the_delivery_failed`, `test_inquiry_delivery.py::test_a_delivered_inquiry_cannot_be_retried` |
| A rejected token found by the access check at startup is reported by `/api/health` as `degraded`; the API still starts | `test_crm_hubspot.py::test_the_access_check_at_startup_is_reported_by_health`, `test_crm_access.py::test_health_is_degraded_when_the_crm_access_check_fails`, `test_crm_access.py::test_failed_checks_never_raise` |

## Retries without duplicates

| Behavior | Tests |
| --- | --- |
| One job per inquiry: the same idempotency key returns the existing job, also under concurrent requests | `test_job_queue.py::test_same_idempotency_key_returns_the_existing_job`, `test_job_queue.py::test_concurrent_enqueues_with_one_key_create_one_job`, `test_inquiries_api.py::test_concurrent_confirmations_queue_one_delivery` |
| A job that starts after the inquiry was delivered sends nothing | `test_inquiry_delivery.py::test_second_job_for_a_delivered_inquiry_does_not_call_the_crm` |
| The CRM stored the record but the answer was lost: the retry finds the record and creates nothing (simulated CRM) | `test_inquiry_delivery.py::test_answer_lost_after_the_crm_stored_the_record_does_not_duplicate_it`, `test_crm_simulated.py::test_repeating_a_delivery_returns_the_existing_record` |
| The same for HubSpot: the note is found by its inquiry reference, also among many other notes | `test_crm_hubspot.py::test_note_saved_but_answer_lost_then_retry_reuses_the_note`, `test_crm_hubspot.py::test_note_of_this_inquiry_is_found_among_many_other_notes`, `test_crm_hubspot.py::test_repeated_delivery_finds_the_note_and_creates_nothing` |
| A HubSpot contact is updated by email, not duplicated | `test_crm_hubspot.py::test_existing_contact_is_updated_not_duplicated`, `test_crm_hubspot.py::test_contact_saved_but_answer_lost_then_retry_keeps_one_contact`, `test_inquiry_delivery.py::test_repeat_inquiries_from_one_email_share_a_contact` |
| Two workers on one inquiry create one record; a worker that lost its lease cannot overwrite the result | `test_inquiry_delivery.py::test_two_workers_delivering_the_same_inquiry_create_one_record`, `test_inquiry_delivery.py::test_worker_that_lost_its_lease_cannot_undo_a_delivery`, `test_job_queue.py::test_a_worker_that_lost_its_lease_cannot_finish_or_fail_the_job` |

## Undelivered inquiries are kept

| Behavior | Tests |
| --- | --- |
| A delivery queued while no worker was running is sent after the API and the worker restart | `test_inquiry_delivery.py::test_a_delivery_queued_while_nothing_was_running_is_sent_after_a_restart`, `test_inquiry_delivery.py::test_undelivered_inquiry_survives_a_restart` |
| A worker dies in the middle of an attempt: another worker takes the delivery over | `test_inquiry_delivery.py::test_delivery_recovers_after_the_worker_dies_mid_attempt`, `test_job_queue.py::test_a_job_with_an_expired_lease_is_reclaimed` |
| A worker dies on the last attempt: the delivery is reported as failed and can be retried by hand | `test_inquiry_delivery.py::test_worker_death_on_the_last_attempt_is_reported_and_can_be_retried`, `test_job_queue.py::test_an_expired_lease_on_the_final_attempt_fails_the_job` |
| The same for indexing: the document version becomes `failed` instead of staying in `indexing` | `test_indexing_recovery.py::test_worker_death_on_the_final_attempt_fails_the_version_instead_of_leaving_it_indexing`, `test_worker.py::test_a_job_abandoned_on_its_final_attempt_fails_together_with_its_hook` |

## Blocked visitor access to administrative actions

| Behavior | Tests |
| --- | --- |
| Every admin operation in the API contract answers 401 without a token and 403 with a wrong one. The list of operations is read from the contract, so a new admin route is covered without a new test | `test_admin_auth.py::test_every_admin_endpoint_without_a_token_returns_401`, `test_admin_auth.py::test_every_admin_endpoint_with_a_wrong_token_returns_403`, `test_admin_auth.py::test_the_access_tests_cover_every_admin_operation` |
| With no admin token configured on the server, every admin operation is closed | `test_admin_auth.py::test_every_admin_endpoint_is_closed_when_no_token_is_configured`, `test_documents_admin_api.py::test_uploads_are_closed_when_no_admin_token_is_configured`, `test_admin_inquiries.py::test_list_is_closed_when_no_admin_token_is_configured` |
| A refused request changes nothing: documents stay as they were, no inquiry data is returned | `test_documents_admin_api.py::test_a_visitor_cannot_read_upload_replace_delete_or_search_documents`, `test_admin_inquiries.py::test_visitor_without_a_token_cannot_list_inquiries`, `test_admin_inquiries.py::test_wrong_token_cannot_list_inquiries` |
| The token is checked before the request is validated, so a visitor learns no validation rules | `test_admin_auth.py::test_authorization_is_checked_before_the_request_is_validated` |
| An upload is refused before its body is read, without a token and with a wrong one | `test_documents_admin_api.py::test_a_visitor_upload_is_refused_before_its_body_is_read` |
| Visitor endpoints do not ask for a token | `test_admin_auth.py::test_no_visitor_endpoint_asks_for_a_token` |

## Tests added while this table was written

The table was first built from the existing tests. Behaviors that no test asserted got a test; none of them exposed a defect.

| Added test | Gap it closes |
| --- | --- |
| `test_replacement_and_deletion.py::test_an_earlier_reply_keeps_its_citation_after_the_document_is_replaced` | The stored conversation was read again only after a deletion, not after a replacement |
| `test_documents_admin_api.py::test_a_replacement_that_runs_out_of_retries_leaves_the_old_version_active` | Used-up retries were tested for a first upload only |
| `test_inquiry_delivery.py::test_a_draft_made_in_the_chat_is_not_sent_even_when_the_visitor_agrees` | No chat-made draft was run through the delivery worker |
| `test_inquiries_api.py::test_confirmed_inquiry_cannot_be_changed` (handoff case) | The 409 was tested for a purchase only |
| `test_inquiry_delivery.py::test_a_delivered_inquiry_cannot_be_retried` | The 409 was tested for a draft and a pending delivery only |
| `test_inquiry_delivery.py::test_a_delivery_queued_while_nothing_was_running_is_sent_after_a_restart` | Every restart test ran one attempt before the restart |
| `test_crm_hubspot.py::test_temporary_hubspot_errors_are_retried_after_the_backoff` | 429 and 5xx were classified but never run through the worker; no delivery test checked the delay |
| `test_crm_hubspot.py::test_permanent_hubspot_errors_fail_at_once_and_a_manual_retry_delivers` | 400 and 403 never reached the worker; the stored error was checked for contact details only at the provider level |
| `test_crm_hubspot.py::test_the_access_check_at_startup_is_reported_by_health` | The failing check was injected after startup; the startup path was tested for the simulated CRM only |
| `test_admin_auth.py::test_authorization_is_checked_before_the_request_is_validated` (wrong-token case) | Only the request without a token was tested |
| `test_documents_admin_api.py::test_a_visitor_upload_is_refused_before_its_body_is_read` (wrong token, new version) | Only an anonymous upload of a new document was tested |
