"""Job type names. Add new names, never rename existing ones."""

INDEX_DOCUMENT_VERSION = "documents.index_version"
"""Payload: {"document_version_id": "<uuid>"}. Handler: `app.worker.handlers.indexing`."""

DELIVER_INQUIRY = "inquiries.deliver"
"""Payload: {"inquiry_id": "<uuid>"}. Handler: `app.worker.handlers.delivery`."""
