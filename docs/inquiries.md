# Inquiries and CRM delivery

An inquiry is what the visitor asks the company to act on. The visitor reviews it, confirms it, and the worker delivers it to the CRM. This document covers the inquiry lifecycle, delivery and retries, the simulated CRM, and the HubSpot integration with its limits.

## Kinds

| `kind` | Meaning | Required fields |
| --- | --- | --- |
| `purchase` (default) | The visitor wants to buy. | product, quantity, timeline, contact name, contact email |
| `handoff` | The documents did not answer the question and the visitor asks for a person. | contact name, contact email, notes (the question) |

`kind` is set when the draft is created and never changes. `missing_fields` in every inquiry response lists the required fields that are still empty, in the order the UI should ask for them.

## Lifecycle

1. `POST /api/inquiries` creates a draft. Any subset of fields is accepted.
2. `PATCH /api/inquiries/{id}` updates the draft. A field that is absent stays as it is; `null` clears it.
3. `POST /api/inquiries/{id}/confirm` confirms the draft when `missing_fields` is empty. Otherwise it answers `422` and names the missing fields.
4. A confirmed inquiry cannot be changed: `PATCH` answers `409`. Confirming it again returns the same inquiry and queues nothing.

Confirmation writes the inquiry status, the delivery row and the delivery job in one transaction, so an inquiry is never confirmed without a queued delivery.

In the chat, the intent detector (`app/services/inquiries/intent.py`) creates and updates the purchase draft of a conversation from the visitor's messages. It never confirms a draft and never sends anything to the CRM. With a live LLM provider the reading comes from the LLM, and from rules when the LLM call fails or returns something unusable; without a live LLM it comes from rules only. The rules prefer missing a purchase request over opening a draft for a policy question: "What is your return policy for printers?" opens no draft.

## Delivery

`GET /api/inquiries/{id}/delivery` and the admin list report the delivery state.

| What the response shows | Meaning |
| --- | --- |
| `pending`, `attempt_count` 0 | Queued; no attempt yet. |
| `in_progress` | An attempt is running. |
| `pending`, `attempt_count` above 0 | The last attempt hit a temporary error. The next automatic attempt starts at `next_attempt_at`. |
| `delivered` | The CRM confirmed the record. `crm_contact_id` and `crm_record_id` are set. |
| `failed`, `failure_reason: permanent_error` | The CRM rejected the request. A retry fails the same way until the cause is fixed. |
| `failed`, `failure_reason: attempts_exhausted` | Every automatic attempt hit a temporary error. |

`attempts` lists every attempt with its outcome, error and time. `crm_mode` and `live` say where the delivery went: `live: false` means the simulated CRM, and no real CRM record exists.

**Retries.** Temporary errors (timeout, connection problem, rate limit, CRM unavailable) are retried after a backoff of `JOB_BACKOFF_BASE_SECONDS`, doubled each time up to `JOB_BACKOFF_MAX_SECONDS`, until `DELIVERY_MAX_ATTEMPTS` attempts are used. A permanent error (rejected token, missing scope, invalid data) fails the delivery at once. `POST /api/inquiries/{id}/delivery/retry` gives a failed delivery a new set of attempts; it answers `409` for a delivery that is not failed.

**Restarts.** The queue is a PostgreSQL table, so undelivered inquiries survive a restart of the API and the worker. If a worker dies during an attempt, another worker takes the job over when its lease (`JOB_LEASE_SECONDS`) ends. The delivery status is corrected from the job's state whenever it is read, so a dead worker does not leave a delivery `in_progress` forever. A worker that lost its lease cannot overwrite a result recorded by the worker that took over.

**No duplicates.** Three layers keep one inquiry from becoming two CRM records:

- The delivery job has the idempotency key `inquiries.deliver:{inquiry_id}`: a second confirmation or enqueue returns the existing job.
- A delivery that is already `delivered` is never sent again, whatever job asks for it.
- Each delivery carries the CRM idempotency key `inquiry:{inquiry_id}`. The CRM provider uses it to find a record that an earlier attempt created before it failed.

**Privacy.** The access token is read from the environment only and is never logged or returned by the API. Delivery errors are stored without the token and without email addresses. The worker logs inquiry and job IDs, not contact details.

## Simulated CRM

`CRM_PROVIDER=simulated` is the default. It makes no network calls, keeps contacts and records in the worker's memory, and labels every delivery with `live: false`. IDs are derived from the contact email and the idempotency key, so the same inquiry always gets the same IDs.

A tag in the contact email makes deliveries fail on purpose, to show error statuses and retries:

| Contact email | Behavior |
| --- | --- |
| `name+fail2@example.com` | The first 2 attempts fail with a temporary error; the third succeeds. |
| `name+fail@example.com` | Every attempt fails with a temporary error, until the attempts are exhausted. |
| `name+reject1@example.com` | The first attempt fails with a permanent error; a manual retry succeeds. |
| `name+reject@example.com` | Every attempt fails with a permanent error. |

The tags work in simulated mode only. HubSpot mode treats them as ordinary plus-addressing.

## HubSpot

**Status: not verified on a live HubSpot account.** The integration follows the official HubSpot documentation as read on November 11, 2026, and is tested against an in-memory fake of the API (`backend/tests/test_crm_hubspot.py`). The only request sent to the real HubSpot API was the startup check with an invalid token; HubSpot answered `401` in the documented error format, and the check reported it as failed. No contact or note has been written to a HubSpot account. Run the live check below before relying on the integration.

### What is written

Both kinds are saved the same way:

1. **Contact**, created or updated by email in one call: `POST /crm/objects/2026-09/contacts/batch/upsert` with `idProperty: "email"`. Properties written: `email`, `firstname`, `lastname`, `company`, `phone`. Empty values are left out, so an update never blanks what HubSpot already has.
2. **Note** associated with the contact: `POST /crm/objects/2026-09/notes` with `hs_timestamp` (the confirmation time), `hs_note_body` (the inquiry details as HTML, visitor input escaped) and the HubSpot-defined association type 202 (note to contact). The note is titled "Purchase inquiry" or "Human handoff request" and ends with `Reference: inquiry:{inquiry_id}`.

Why a note: it needs no pipeline or stage IDs, no custom properties and no paid subscription, and it shows on the contact's timeline. A deal needs a pipeline and a stage from the account, a ticket needs a pipeline stage, and the lead object needs Sales Hub Professional or Enterprise. Mapping inquiries to deals or tickets is a per-account decision and is not built.

Only HubSpot default properties are used. Nothing has to be created in the account besides the access token.

### Authentication and scopes

HubSpot no longer allows creating legacy private apps (new accounts since September 28, 2026; existing accounts since October 26, 2026) and recommends service keys for integrations like this one. The provider sends the key as `Authorization: Bearer <token>`; a token of an existing legacy private app is sent the same way.

Scopes for the service key:

| Scope | Used for |
| --- | --- |
| `crm.objects.contacts.read` | Access check; listing a contact's notes. |
| `crm.objects.contacts.write` | Creating and updating the contact. |
| Notes access | Creating and reading notes. **The exact scope name is not verified**: the documentation page for the notes endpoints did not show a single required scope. Select the scope for notes that the key's scope picker offers; if the picker has none, the contact scopes may be enough. The startup check reports a `403` on notes if access is missing. |
| `crm.schemas.contacts.read` (optional) | Lets the startup check confirm that the properties exist. Without it the check still passes and says that property definitions were not checked. |

### Startup check

At startup the API and the worker call HubSpot with read-only requests: account details, one contact, one note, and the definitions of the properties the integration writes. `GET /api/health` reports the result in `providers.crm.access` (`state`: `ok`, `failed` or `unchecked`, plus a message), and the overall status is `degraded` when the check failed. When health is read and the last result is older than `CRM_ACCESS_CHECK_INTERVAL_SECONDS`, the API repeats the check in the background. A failed check does not stop the application: inquiries stay queued and retryable.

Write permission cannot be checked without writing. A missing write scope shows up as a permanent error of the first delivery.

### Errors and limits

| HubSpot answer | Treated as |
| --- | --- |
| Timeout, connection error | Temporary |
| `429` (rate limit), `423` (locked), `477` (migration in progress), `408`, any `5xx` | Temporary |
| `401` (invalid token), `403` (missing scope), `400`, `404`, `409` and other `4xx` | Permanent |
| `207` from the contact upsert without a result | Permanent |

Documented limits that matter here: 100 requests per 10 seconds per app on Free and Starter accounts (more on higher tiers), 250,000 requests per day on Free and Starter, and 100 inputs per batch call. A delivery makes two requests for a new contact and three or more for an existing one, so one worker stays far below these limits. The provider does not wait inside a request on `429`; the job backoff spaces the retries.

### Duplicates: what is and is not guaranteed

- **Contacts.** The upsert is keyed by email on HubSpot's side, so a repeated delivery updates the same contact.
- **Notes.** HubSpot offers no idempotency key for creating a record. Before creating a note for an existing contact, the provider lists the notes associated with that contact and looks for the delivery's reference in their text. This finds a note that an earlier attempt created even when its response was lost.

Limits of that check:

- It is a read followed by a create, not one atomic operation. The job queue runs one delivery of an inquiry at a time, so two creates can overlap only if a worker loses its lease while its request to HubSpot is still in flight. The request timeout (`HUBSPOT_TIMEOUT_SECONDS`) and the cap on one CRM call (half of `JOB_TIMEOUT_SECONDS`) are far below the lease time to make that unlikely, not impossible.
- Up to 2,000 note associations of the contact are listed, and the 300 newest of those notes are read. If the contact has more notes than that, or gets more than 300 new notes between two attempts of one delivery, the earlier note may not be found and a second note is created.
- If someone in HubSpot edits the note and removes the reference line, or removes the note's association with the contact, a later retry of the same delivery does not find it. After a delivery is recorded as delivered, nothing is sent again, so this matters only between a lost response and its retry.
- If HubSpot merges or deletes the contact between attempts, the earlier note is not found.

A stronger guarantee needs a change in the HubSpot account: a custom property with unique values that holds the reference, and a key that can manage properties. That is not built, because the task was to work without mandatory custom properties.

### API version

Request paths use HubSpot's date-based API version from `HUBSPOT_API_VERSION` (default `2026-09`). The paging of the association list in that version is assumed to work as in the earlier versions (`limit` up to 500, `paging.next.after`); this is one of the points the live check should confirm.

### Live check

What the account owner needs:

1. A HubSpot account for testing. A developer test account is free. Whether service keys can be created inside a developer test account is not stated in the documentation; if they cannot, use a free standard account.
2. A service key with the scopes above (in HubSpot: Development > Keys > Service keys, or Settings > Integrations > Service Keys; this needs super admin or developer tools access).
3. In `.env`: `CRM_PROVIDER=hubspot` and `HUBSPOT_ACCESS_TOKEN=<the key>`.

Then:

1. Start the application and open `/api/health`: `providers.crm.access.state` should be `ok`.
2. Confirm a purchase inquiry and a handoff. Each delivery should become `delivered` with `live: true`, and the contact in HubSpot should show one note per inquiry.
3. Confirm another inquiry with the same email: the contact is updated, not duplicated.
4. Stop the worker's network access during a delivery, restore it, and check that the retry leaves one note.

### Sources

Official HubSpot documentation, read on November 11, 2026:

- Service keys: https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/account-service-keys
- End of legacy private app creation: https://developers.hubspot.com/changelog/legacy-private-app-creation-sunset
- API versioning: https://developers.hubspot.com/docs/developer-tooling/platform/versioning
- Contacts: https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/guide
- Contact batch upsert: https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/batch/upsert-contacts
- Notes: https://developers.hubspot.com/docs/api-reference/latest/crm/activities/notes/guide
- Create a note: https://developers.hubspot.com/docs/api-reference/latest/crm/activities/notes/create-note
- Read notes in a batch: https://developers.hubspot.com/docs/api-reference/latest/crm/activities/notes/batch/get-notes
- Associations: https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide
- Properties: https://developers.hubspot.com/docs/api-reference/latest/crm/properties/guide
- Account details: https://developers.hubspot.com/docs/api-reference/latest/account/account-information/get-account-details
- Error handling: https://developers.hubspot.com/docs/api-reference/error-handling
- Usage guidelines and rate limits: https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines
- Scopes: https://developers.hubspot.com/docs/apps/legacy-apps/authentication/scopes
- Account types: https://developers.hubspot.com/docs/getting-started/account-types
