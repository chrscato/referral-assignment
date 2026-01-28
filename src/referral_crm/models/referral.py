"""
Core referral and related models.

This module contains:
- Referral: The core referral record
- ReferralLineItem: Individual service line items
- Carrier: Insurance carriers
- Provider: Service providers
- Supporting models (ProviderService, RateSchedule, ReplyTemplate, AuditLog)
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from referral_crm.models.base import Base
from referral_crm.models.enums import (
    LineItemStatus,
    Priority,
    ReferralStatus,
    ServiceModality,
)

if TYPE_CHECKING:
    from referral_crm.models.dimensions import (
        DimBodyRegion,
        DimICD10,
        DimProcedureCode,
        DimServiceType,
    )
    from referral_crm.models.email import Attachment, Email
    from referral_crm.models.queue import QueueItem


# =============================================================================
# CARRIER MODEL
# =============================================================================


class Carrier(Base):
    """Insurance carrier/company."""

    __tablename__ = "carriers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(50))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    referrals: Mapped[list["Referral"]] = relationship(
        "Referral", back_populates="carrier"
    )
    rate_schedules: Mapped[list["RateSchedule"]] = relationship(
        "RateSchedule", back_populates="carrier"
    )


# =============================================================================
# PROVIDER MODEL
# =============================================================================


class Provider(Base):
    """Service provider (PT, imaging center, etc.)."""

    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    npi: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    tax_id: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(2))
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    fax: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_name: Mapped[Optional[str]] = mapped_column(String(255))
    accepting_new: Mapped[bool] = mapped_column(Boolean, default=True)
    avg_wait_days: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    services: Mapped[list["ProviderService"]] = relationship(
        "ProviderService", back_populates="provider"
    )
    line_items: Mapped[list["ReferralLineItem"]] = relationship(
        "ReferralLineItem", back_populates="provider"
    )


class ProviderService(Base):
    """Services offered by a provider."""

    __tablename__ = "provider_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id"), nullable=False
    )
    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    provider: Mapped["Provider"] = relationship("Provider", back_populates="services")


# =============================================================================
# RATE SCHEDULE MODEL
# =============================================================================


class RateSchedule(Base):
    """Rate schedules for carriers/services."""

    __tablename__ = "rate_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    carrier_id: Mapped[int] = mapped_column(ForeignKey("carriers.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    body_region: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(2))
    rate_amount: Mapped[float] = mapped_column(Float, nullable=False)
    rate_unit: Mapped[str] = mapped_column(String(50), default="per_visit")
    effective_date: Mapped[Optional[datetime]] = mapped_column(Date)
    expiration_date: Mapped[Optional[datetime]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    carrier: Mapped["Carrier"] = relationship("Carrier", back_populates="rate_schedules")


# =============================================================================
# REFERRAL MODEL (RESTRUCTURED)
# =============================================================================


class Referral(Base):
    """
    Core referral record - represents a validated work item.

    This table now focuses on the referral itself, not email metadata.
    Email data is accessed via the source_email relationship.
    Line items capture individual services requested.
    """

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # SOURCE EMAIL (one-to-one)
    # =========================================================================
    email_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("emails.id"), unique=True, index=True
    )

    # =========================================================================
    # ADJUSTER / ASSIGNING PARTY
    # =========================================================================
    adjuster_name: Mapped[Optional[str]] = mapped_column(String(255))
    adjuster_email: Mapped[Optional[str]] = mapped_column(String(255))
    adjuster_phone: Mapped[Optional[str]] = mapped_column(String(50))

    # =========================================================================
    # ASSIGNING COMPANY (Insurance Carrier)
    # =========================================================================
    carrier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("carriers.id"))
    carrier_name_raw: Mapped[Optional[str]] = mapped_column(String(255))

    # =========================================================================
    # CLAIM INFORMATION
    # =========================================================================
    claim_number: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    jurisdiction_state: Mapped[Optional[str]] = mapped_column(String(2))
    order_type: Mapped[Optional[str]] = mapped_column(String(100))
    authorization_number: Mapped[Optional[str]] = mapped_column(String(100))

    # =========================================================================
    # PATIENT DEMOGRAPHICS
    # =========================================================================
    patient_first_name: Mapped[Optional[str]] = mapped_column(String(100))
    patient_last_name: Mapped[Optional[str]] = mapped_column(String(100))
    patient_dob: Mapped[Optional[datetime]] = mapped_column(Date)
    patient_doi: Mapped[Optional[datetime]] = mapped_column(Date)  # Date of injury
    patient_gender: Mapped[Optional[str]] = mapped_column(String(20))
    patient_phone: Mapped[Optional[str]] = mapped_column(String(50))
    patient_email: Mapped[Optional[str]] = mapped_column(String(255))
    patient_ssn: Mapped[Optional[str]] = mapped_column(String(20))  # Last 4 or masked

    # =========================================================================
    # PATIENT ADDRESS
    # =========================================================================
    patient_address_1: Mapped[Optional[str]] = mapped_column(String(255))
    patient_address_2: Mapped[Optional[str]] = mapped_column(String(255))
    patient_city: Mapped[Optional[str]] = mapped_column(String(100))
    patient_state: Mapped[Optional[str]] = mapped_column(String(2))
    patient_zip: Mapped[Optional[str]] = mapped_column(String(10))

    # =========================================================================
    # EMPLOYER INFORMATION
    # =========================================================================
    employer_name: Mapped[Optional[str]] = mapped_column(String(255))
    employer_job_title: Mapped[Optional[str]] = mapped_column(String(255))
    employer_address: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # REFERRING PHYSICIAN
    # =========================================================================
    referring_physician_name: Mapped[Optional[str]] = mapped_column(String(255))
    referring_physician_npi: Mapped[Optional[str]] = mapped_column(String(10))

    # =========================================================================
    # SERVICE SUMMARY (derived from line items)
    # =========================================================================
    service_summary: Mapped[Optional[str]] = mapped_column(
        Text
    )  # Aggregated from line items
    body_parts: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # PREFERENCES
    # =========================================================================
    suggested_providers: Mapped[Optional[str]] = mapped_column(Text)
    special_requirements: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # RX (PRESCRIPTION) ATTACHMENT
    # =========================================================================
    rx_attachment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("attachments.id"), nullable=True
    )

    # =========================================================================
    # STATUS & WORKFLOW
    # =========================================================================
    status: Mapped[ReferralStatus] = mapped_column(
        Enum(ReferralStatus), default=ReferralStatus.DRAFT, index=True
    )
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.MEDIUM)

    # =========================================================================
    # EXTRACTION METADATA
    # =========================================================================
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extraction_data: Mapped[Optional[dict]] = mapped_column(JSON)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # FILEMAKER INTEGRATION
    # =========================================================================
    filemaker_record_id: Mapped[Optional[str]] = mapped_column(String(100))
    filemaker_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================================================================
    # NOTES & REJECTION
    # =========================================================================
    notes: Mapped[Optional[str]] = mapped_column(Text)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    source_email: Mapped[Optional["Email"]] = relationship(
        "Email", back_populates="referral"
    )
    carrier: Mapped[Optional["Carrier"]] = relationship(
        "Carrier", back_populates="referrals"
    )
    line_items: Mapped[list["ReferralLineItem"]] = relationship(
        "ReferralLineItem", back_populates="referral", cascade="all, delete-orphan"
    )
    queue_items: Mapped[list["QueueItem"]] = relationship(
        "QueueItem", back_populates="referral", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="referral", cascade="all, delete-orphan"
    )
    # RX attachment relationship
    rx_attachment: Mapped[Optional["Attachment"]] = relationship(
        "Attachment", foreign_keys=[rx_attachment_id]
    )
    # Directly uploaded attachments (not from email)
    uploaded_attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        foreign_keys="Attachment.referral_id",
        back_populates="referral",
        cascade="all, delete-orphan",
    )

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================
    @property
    def attachments(self) -> list["Attachment"]:
        """Get attachments from the source email."""
        return self.source_email.attachments if self.source_email else []

    @property
    def patient_full_name(self) -> str:
        """Get patient's full name."""
        parts = [self.patient_first_name, self.patient_last_name]
        return " ".join(p for p in parts if p)

    def __repr__(self) -> str:
        return f"<Referral(id={self.id}, claim={self.claim_number}, status={self.status.value})>"


# =============================================================================
# REFERRAL LINE ITEM MODEL (NEW)
# =============================================================================


class ReferralLineItem(Base):
    """
    Individual service line items for a referral.

    A single referral can have multiple services requested:
    - MRI lumbar spine without contrast
    - MRI cervical spine without contrast
    - CT scan right shoulder with contrast

    Each line item has its own ICD-10, CPT, status, and scheduling.
    """

    __tablename__ = "referral_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(
        ForeignKey("referrals.id"), nullable=False, index=True
    )

    # Line number for ordering
    line_number: Mapped[int] = mapped_column(Integer, default=1)

    # =========================================================================
    # SERVICE DETAILS
    # =========================================================================
    service_description: Mapped[str] = mapped_column(String(500), nullable=False)
    # e.g., "MRI lumbar spine without contrast"

    # Structured service components
    service_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dim_service_types.id")
    )
    body_region_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dim_body_regions.id")
    )
    modality: Mapped[Optional[ServiceModality]] = mapped_column(Enum(ServiceModality))

    # Service modifiers
    with_contrast: Mapped[bool] = mapped_column(Boolean, default=False)
    laterality: Mapped[Optional[str]] = mapped_column(
        String(20)
    )  # left, right, bilateral
    view_type: Mapped[Optional[str]] = mapped_column(
        String(100)
    )  # AP, lateral, oblique

    # =========================================================================
    # DIAGNOSIS (ICD-10)
    # =========================================================================
    icd10_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    icd10_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_icd10.id"))
    icd10_description: Mapped[Optional[str]] = mapped_column(String(500))

    # =========================================================================
    # PROCEDURE CODE (CPT) - Derived via Step 2 Reasoning
    # =========================================================================
    procedure_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    procedure_code_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dim_procedure_codes.id")
    )
    procedure_description: Mapped[Optional[str]] = mapped_column(String(500))

    # =========================================================================
    # AUTHORIZATION
    # =========================================================================
    authorization_number: Mapped[Optional[str]] = mapped_column(String(100))
    authorized_visits: Mapped[Optional[int]] = mapped_column(Integer)
    authorization_start: Mapped[Optional[datetime]] = mapped_column(Date)
    authorization_end: Mapped[Optional[datetime]] = mapped_column(Date)

    # =========================================================================
    # PROVIDER ASSIGNMENT
    # =========================================================================
    provider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("providers.id"))
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================================================================
    # SCHEDULING
    # =========================================================================
    scheduled_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    scheduled_time: Mapped[Optional[str]] = mapped_column(String(20))
    appointment_confirmation: Mapped[Optional[str]] = mapped_column(String(100))

    # =========================================================================
    # PRICING
    # =========================================================================
    rate_schedule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rate_schedules.id")
    )
    unit_rate: Mapped[Optional[float]] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_amount: Mapped[Optional[float]] = mapped_column(Float)

    # =========================================================================
    # STATUS
    # =========================================================================
    status: Mapped[LineItemStatus] = mapped_column(
        Enum(LineItemStatus), default=LineItemStatus.PENDING
    )

    # =========================================================================
    # NOTES
    # =========================================================================
    special_instructions: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # EXTRACTION METADATA
    # =========================================================================
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[Optional[str]] = mapped_column(String(50))  # "extraction", "manual"

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    referral: Mapped["Referral"] = relationship("Referral", back_populates="line_items")
    provider: Mapped[Optional["Provider"]] = relationship(
        "Provider", back_populates="line_items"
    )
    rate_schedule: Mapped[Optional["RateSchedule"]] = relationship("RateSchedule")
    service_type: Mapped[Optional["DimServiceType"]] = relationship("DimServiceType")
    body_region: Mapped[Optional["DimBodyRegion"]] = relationship("DimBodyRegion")
    icd10: Mapped[Optional["DimICD10"]] = relationship("DimICD10")
    procedure: Mapped[Optional["DimProcedureCode"]] = relationship("DimProcedureCode")

    def __repr__(self) -> str:
        return f"<ReferralLineItem(id={self.id}, desc='{self.service_description[:30]}...', status={self.status.value})>"


# =============================================================================
# REPLY TEMPLATE MODEL
# =============================================================================


class ReplyTemplate(Base):
    """Email reply templates."""

    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_template: Mapped[Optional[str]] = mapped_column(String(500))
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# =============================================================================
# AUDIT LOG MODEL
# =============================================================================


class AuditLog(Base):
    """Audit trail for referral changes."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(
        ForeignKey("referrals.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(100))
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    user: Mapped[Optional[str]] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    referral: Mapped["Referral"] = relationship("Referral", back_populates="audit_logs")
