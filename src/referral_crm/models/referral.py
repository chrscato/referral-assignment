"""
Core referral and related models.
"""

import enum
from datetime import datetime
from typing import Optional

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


class ReferralStatus(enum.Enum):
    """Workflow status for referrals."""

    PENDING = "pending"
    IN_REVIEW = "in_review"
    NEEDS_INFO = "needs_info"
    APPROVED = "approved"
    SUBMITTED_TO_FILEMAKER = "submitted_to_filemaker"
    COMPLETED = "completed"
    REJECTED = "rejected"


class Priority(enum.Enum):
    """Priority levels for referrals."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


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
    referrals: Mapped[list["Referral"]] = relationship("Referral", back_populates="carrier")
    rate_schedules: Mapped[list["RateSchedule"]] = relationship(
        "RateSchedule", back_populates="carrier"
    )


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
    referrals: Mapped[list["Referral"]] = relationship("Referral", back_populates="provider")


class ProviderService(Base):
    """Services offered by a provider."""

    __tablename__ = "provider_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    provider: Mapped["Provider"] = relationship("Provider", back_populates="services")


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


class Referral(Base):
    """Main referral record - the core entity."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Email metadata
    email_id: Mapped[Optional[str]] = mapped_column(String(500))
    email_internet_message_id: Mapped[Optional[str]] = mapped_column(String(500))
    email_web_link: Mapped[Optional[str]] = mapped_column(Text)
    email_conversation_id: Mapped[Optional[str]] = mapped_column(String(500))
    email_subject: Mapped[Optional[str]] = mapped_column(String(500))
    email_body_preview: Mapped[Optional[str]] = mapped_column(Text)
    email_body_html: Mapped[Optional[str]] = mapped_column(Text)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Adjuster information
    adjuster_name: Mapped[Optional[str]] = mapped_column(String(255))
    adjuster_email: Mapped[Optional[str]] = mapped_column(String(255))
    adjuster_phone: Mapped[Optional[str]] = mapped_column(String(50))

    # Insurance/Claim information
    carrier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("carriers.id"))
    carrier_name_raw: Mapped[Optional[str]] = mapped_column(String(255))
    claim_number: Mapped[Optional[str]] = mapped_column(String(100))

    # Claimant information
    claimant_name: Mapped[Optional[str]] = mapped_column(String(255))
    claimant_dob: Mapped[Optional[datetime]] = mapped_column(Date)
    claimant_phone: Mapped[Optional[str]] = mapped_column(String(50))
    claimant_address: Mapped[Optional[str]] = mapped_column(Text)
    claimant_city: Mapped[Optional[str]] = mapped_column(String(100))
    claimant_state: Mapped[Optional[str]] = mapped_column(String(2))
    claimant_zip: Mapped[Optional[str]] = mapped_column(String(10))

    # Employer information
    employer_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Injury/Service information
    date_of_injury: Mapped[Optional[datetime]] = mapped_column(Date)
    body_parts: Mapped[Optional[str]] = mapped_column(Text)
    service_requested: Mapped[Optional[str]] = mapped_column(String(255))
    authorization_number: Mapped[Optional[str]] = mapped_column(String(100))

    # Provider assignment
    provider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("providers.id"))
    rate_schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rate_schedules.id"))
    rate_amount: Mapped[Optional[float]] = mapped_column(Float)

    # Status and workflow
    status: Mapped[ReferralStatus] = mapped_column(
        Enum(ReferralStatus), default=ReferralStatus.PENDING
    )
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.MEDIUM)

    # LLM extraction metadata (confidence scores as JSON)
    extraction_data: Mapped[Optional[dict]] = mapped_column(JSON)
    extraction_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Notes and additional info
    notes: Mapped[Optional[str]] = mapped_column(Text)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    # FileMaker integration
    filemaker_record_id: Mapped[Optional[str]] = mapped_column(String(100))
    filemaker_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # S3 Storage keys
    s3_email_key: Mapped[Optional[str]] = mapped_column(String(500))
    s3_extraction_key: Mapped[Optional[str]] = mapped_column(String(500))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    carrier: Mapped[Optional["Carrier"]] = relationship("Carrier", back_populates="referrals")
    provider: Mapped[Optional["Provider"]] = relationship("Provider", back_populates="referrals")
    rate_schedule: Mapped[Optional["RateSchedule"]] = relationship("RateSchedule")
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="referral", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="referral", cascade="all, delete-orphan"
    )


class Attachment(Base):
    """Attachments associated with referrals."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    storage_path: Mapped[Optional[str]] = mapped_column(Text)  # Local path (fallback)
    graph_attachment_id: Mapped[Optional[str]] = mapped_column(String(500))

    # S3 Storage
    s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    s3_text_key: Mapped[Optional[str]] = mapped_column(String(500))  # Extracted text location

    # Document classification
    document_type: Mapped[Optional[str]] = mapped_column(String(100))
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)

    # Preview/thumbnail (for images)
    has_preview: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    referral: Mapped["Referral"] = relationship("Referral", back_populates="attachments")


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


class AuditLog(Base):
    """Audit trail for referral changes."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(100))
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    user: Mapped[Optional[str]] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    referral: Mapped["Referral"] = relationship("Referral", back_populates="audit_logs")
