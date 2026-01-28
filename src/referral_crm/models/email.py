"""
Email and Attachment models.

This module contains models for raw email records and their attachments.
Emails are the source records from which referrals are extracted.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
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
from referral_crm.models.enums import DocumentType, EmailStatus

if TYPE_CHECKING:
    from referral_crm.models.referral import Referral


class Email(Base):
    """
    Raw email records from inbox.

    This is the source record - each email may generate zero or one referral.
    Attachments are linked here, not to referrals.
    """

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # GRAPH API IDENTIFIERS
    # =========================================================================
    graph_id: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False, index=True
    )
    internet_message_id: Mapped[Optional[str]] = mapped_column(String(500))
    conversation_id: Mapped[Optional[str]] = mapped_column(String(500))
    web_link: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # EMAIL METADATA
    # =========================================================================
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    from_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    from_name: Mapped[Optional[str]] = mapped_column(String(255))
    to_emails: Mapped[Optional[dict]] = mapped_column(JSON)  # JSON array
    cc_emails: Mapped[Optional[dict]] = mapped_column(JSON)  # JSON array

    # =========================================================================
    # CONTENT
    # =========================================================================
    body_preview: Mapped[Optional[str]] = mapped_column(Text)
    body_html: Mapped[Optional[str]] = mapped_column(Text)
    body_text: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # FLAGS
    # =========================================================================
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    importance: Mapped[Optional[str]] = mapped_column(String(20))  # normal, high, low

    # =========================================================================
    # PROCESSING STATUS
    # =========================================================================
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus), default=EmailStatus.RECEIVED, index=True
    )
    extraction_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_extraction_error: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # S3 STORAGE
    # =========================================================================
    s3_raw_key: Mapped[Optional[str]] = mapped_column(String(500))  # Original email
    s3_html_key: Mapped[Optional[str]] = mapped_column(String(500))  # HTML content
    s3_extraction_key: Mapped[Optional[str]] = mapped_column(
        String(500)
    )  # Extraction JSON

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="email", cascade="all, delete-orphan"
    )
    referral: Mapped[Optional["Referral"]] = relationship(
        "Referral", back_populates="source_email", uselist=False
    )
    extraction_result: Mapped[Optional["ExtractionResult"]] = relationship(
        "ExtractionResult", back_populates="email", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Email(id={self.id}, subject='{self.subject[:50] if self.subject else ''}...', status={self.status.value})>"


class Attachment(Base):
    """
    Attachments associated with emails or referrals.

    Attachments can come from:
    1. Email ingestion (email_id set)
    2. Direct upload to a referral (referral_id set)
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Source: either email or direct referral upload (one should be set)
    email_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("emails.id"), nullable=True, index=True
    )
    referral_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("referrals.id"), nullable=True, index=True
    )

    # =========================================================================
    # FILE METADATA
    # =========================================================================
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)

    # =========================================================================
    # GRAPH API REFERENCE
    # =========================================================================
    graph_attachment_id: Mapped[Optional[str]] = mapped_column(String(500))

    # =========================================================================
    # STORAGE
    # =========================================================================
    storage_path: Mapped[Optional[str]] = mapped_column(Text)  # Local path (fallback)
    s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    s3_text_key: Mapped[Optional[str]] = mapped_column(String(500))  # Extracted text

    # =========================================================================
    # DOCUMENT CLASSIFICATION
    # =========================================================================
    document_type: Mapped[Optional[DocumentType]] = mapped_column(Enum(DocumentType))

    # =========================================================================
    # OCR/TEXT EXTRACTION
    # =========================================================================
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float)

    # =========================================================================
    # FLAGS
    # =========================================================================
    has_preview: Mapped[bool] = mapped_column(Boolean, default=False)
    is_relevant: Mapped[bool] = mapped_column(
        Boolean, default=True
    )  # False for logos/signatures

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    email: Mapped[Optional["Email"]] = relationship("Email", back_populates="attachments")
    referral: Mapped[Optional["Referral"]] = relationship(
        "Referral",
        foreign_keys=[referral_id],
        back_populates="uploaded_attachments",
    )

    def __repr__(self) -> str:
        return f"<Attachment(id={self.id}, filename='{self.filename}', type={self.document_type})>"


class ExtractionResult(Base):
    """
    Stores LLM extraction results separately from referral data.

    This allows tracking of extraction confidence, raw values vs. validated values,
    and supports re-extraction without losing original data.
    """

    __tablename__ = "extraction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(
        ForeignKey("emails.id"), unique=True, nullable=False
    )

    # =========================================================================
    # RAW EXTRACTION DATA
    # =========================================================================
    raw_extraction: Mapped[dict] = mapped_column(JSON, nullable=False)

    # =========================================================================
    # EXTRACTION STEPS
    # =========================================================================
    extraction_step: Mapped[int] = mapped_column(Integer, default=1)  # 1 or 2
    enrichment_data: Mapped[Optional[dict]] = mapped_column(JSON)  # Step 2 data

    # =========================================================================
    # CONFIDENCE METRICS
    # =========================================================================
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    field_confidences: Mapped[dict] = mapped_column(JSON, default=dict)

    # =========================================================================
    # VALIDATION
    # =========================================================================
    validation_errors: Mapped[Optional[list]] = mapped_column(JSON)
    validation_warnings: Mapped[Optional[list]] = mapped_column(JSON)

    # =========================================================================
    # MODEL INFO
    # =========================================================================
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    extraction_duration_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    email: Mapped["Email"] = relationship("Email", back_populates="extraction_result")

    def __repr__(self) -> str:
        return f"<ExtractionResult(id={self.id}, email_id={self.email_id}, confidence={self.overall_confidence:.1%})>"
