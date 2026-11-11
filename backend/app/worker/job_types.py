"""Job type names. Shared file: add new names, never rename existing ones."""

INDEX_DOCUMENT_VERSION = "documents.index_version"
"""Payload: {"document_version_id": "<uuid>"}. Handler owner: T3."""

DELIVER_INQUIRY = "inquiries.deliver"
"""Payload: {"inquiry_id": "<uuid>"}. Handler owner: T4."""
