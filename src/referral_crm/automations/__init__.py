"""
Automation scripts for Referral CRM.
"""

from referral_crm.automations.email_ingestion import EmailIngestionPipeline
from referral_crm.automations.batch_processor import BatchProcessor

__all__ = [
    "EmailIngestionPipeline",
    "BatchProcessor",
]
