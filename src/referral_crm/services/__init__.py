"""
Service layer for Referral CRM.
"""

from referral_crm.services.referral_service import ReferralService
from referral_crm.services.extraction_service import ExtractionService
from referral_crm.services.email_service import EmailService
from referral_crm.services.provider_service import ProviderService
from referral_crm.services.storage_service import StorageService, get_storage_service

__all__ = [
    "ReferralService",
    "ExtractionService",
    "EmailService",
    "ProviderService",
    "StorageService",
    "get_storage_service",
]
