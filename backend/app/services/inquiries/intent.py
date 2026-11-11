"""Builds the detector the chat service uses to ask about purchase intent.

Owner: T4. Return the real detector here; the signature is part of the contract.
"""

from app.core.config import Settings
from app.providers.factory import Providers
from app.services.inquiry_intent import InquiryIntentDetector, NoOpInquiryIntentDetector


def build_inquiry_intent_detector(
    settings: Settings, providers: Providers
) -> InquiryIntentDetector:
    return NoOpInquiryIntentDetector()
