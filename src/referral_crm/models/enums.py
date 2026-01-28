"""
Enum definitions for the Referral CRM system.

This module centralizes all enum types used across the application
to ensure consistency in status values, priorities, and categorizations.
"""

import enum


class EmailStatus(enum.Enum):
    """Status of an email record in the processing pipeline."""

    RECEIVED = "received"  # Just ingested from inbox
    PENDING_EXTRACTION = "pending_extraction"  # Queued for LLM extraction
    EXTRACTION_IN_PROGRESS = "extraction_in_progress"  # Currently being processed
    EXTRACTION_COMPLETE = "extraction_complete"  # Extraction successful
    EXTRACTION_FAILED = "extraction_failed"  # Extraction failed after retries
    PROCESSED = "processed"  # Referral created successfully


class ReferralStatus(enum.Enum):
    """Workflow status for referrals through the intake and care coordination process."""

    DRAFT = "draft"  # Created but incomplete
    PENDING_VALIDATION = "pending_validation"  # In Intake Queue awaiting human review
    VALIDATED = "validated"  # Passed intake validation
    PENDING_SCHEDULING = "pending_scheduling"  # In Care Coordination Queue
    SCHEDULED = "scheduled"  # Appointment scheduled with provider
    IN_PROGRESS = "in_progress"  # Service being delivered
    COMPLETED = "completed"  # Service completed
    SUBMITTED_TO_FILEMAKER = "submitted_to_filemaker"  # Synced to FileMaker
    REJECTED = "rejected"  # Rejected with reason
    ON_HOLD = "on_hold"  # Temporarily paused


class QueueType(enum.Enum):
    """Types of work queues in the system."""

    EXTRACTION = "extraction"  # Emails awaiting LLM extraction
    INTAKE = "intake"  # Referrals needing data validation
    CARE_COORDINATION = "care_coordination"  # Validated referrals ready for scheduling


class QueueItemStatus(enum.Enum):
    """Status of an item within a work queue."""

    PENDING = "pending"  # Waiting to be processed
    IN_PROGRESS = "in_progress"  # Currently being worked on
    COMPLETED = "completed"  # Successfully processed
    SKIPPED = "skipped"  # Intentionally skipped
    FAILED = "failed"  # Processing failed


class LineItemStatus(enum.Enum):
    """Status of a referral line item (individual service)."""

    PENDING = "pending"  # Awaiting authorization/scheduling
    AUTHORIZED = "authorized"  # Authorization received
    SCHEDULED = "scheduled"  # Appointment scheduled
    COMPLETED = "completed"  # Service delivered
    CANCELLED = "cancelled"  # Cancelled


class Priority(enum.Enum):
    """Priority levels for referrals and queue items."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ServiceModality(enum.Enum):
    """Service modality types for categorizing medical services."""

    IMAGING = "imaging"  # MRI, CT, X-Ray, Ultrasound
    PHYSICAL_THERAPY = "physical_therapy"
    OCCUPATIONAL_THERAPY = "occupational_therapy"
    CHIROPRACTIC = "chiropractic"
    IME = "ime"  # Independent Medical Evaluation
    FCE = "fce"  # Functional Capacity Evaluation
    SURGERY = "surgery"
    DIAGNOSTIC = "diagnostic"
    DME = "dme"  # Durable Medical Equipment
    INJECTION = "injection"  # Pain management injections
    OTHER = "other"


class DocumentType(enum.Enum):
    """Types of documents attached to emails."""

    REFERRAL_FORM = "referral_form"
    MEDICAL_RECORD = "medical_record"
    AUTHORIZATION = "authorization"
    PRESCRIPTION = "prescription"
    IMAGING_REPORT = "imaging_report"
    LAB_RESULT = "lab_result"
    LOGO = "logo"  # Email signature images
    OTHER = "other"
