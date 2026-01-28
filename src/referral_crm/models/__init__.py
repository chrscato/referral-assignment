"""
Database models for Referral CRM.

This module exports all models, enums, and database utilities.
"""

from referral_crm.models.base import Base, engine, get_session, init_db, reset_db, session_scope

# Enums
from referral_crm.models.enums import (
    DocumentType,
    EmailStatus,
    LineItemStatus,
    Priority,
    QueueItemStatus,
    QueueType,
    ReferralStatus,
    ServiceModality,
)

# Email models
from referral_crm.models.email import (
    Attachment,
    Email,
    ExtractionResult,
)

# Queue models
from referral_crm.models.queue import (
    Queue,
    QueueItem,
)

# Dimension models
from referral_crm.models.dimensions import (
    DimBodyRegion,
    DimICD10,
    DimProcedureCode,
    DimServiceType,
)

# Referral models
from referral_crm.models.referral import (
    AuditLog,
    Carrier,
    Provider,
    ProviderService,
    RateSchedule,
    Referral,
    ReferralLineItem,
    ReplyTemplate,
)

__all__ = [
    # Base and utilities
    "Base",
    "engine",
    "get_session",
    "init_db",
    "reset_db",
    "session_scope",
    # Enums
    "DocumentType",
    "EmailStatus",
    "LineItemStatus",
    "Priority",
    "QueueItemStatus",
    "QueueType",
    "ReferralStatus",
    "ServiceModality",
    # Email models
    "Email",
    "Attachment",
    "ExtractionResult",
    # Queue models
    "Queue",
    "QueueItem",
    # Dimension models
    "DimBodyRegion",
    "DimICD10",
    "DimProcedureCode",
    "DimServiceType",
    # Referral models
    "Referral",
    "ReferralLineItem",
    "Carrier",
    "Provider",
    "ProviderService",
    "RateSchedule",
    "ReplyTemplate",
    "AuditLog",
]
