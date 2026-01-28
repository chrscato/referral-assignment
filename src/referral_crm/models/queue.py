"""
Queue system models for workflow management.

This module contains models for the work queue system that manages
the flow of items through extraction, intake validation, and care coordination.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from referral_crm.models.base import Base
from referral_crm.models.enums import Priority, QueueItemStatus, QueueType

if TYPE_CHECKING:
    from referral_crm.models.email import Email
    from referral_crm.models.referral import Referral


class Queue(Base):
    """
    Queue configuration table.

    Defines the available queues in the system:
    - Extraction Queue: Emails awaiting LLM data extraction
    - Intake Queue: Referrals needing data validation and review
    - Care Coordination Queue: Validated referrals ready for scheduling
    """

    __tablename__ = "queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # QUEUE IDENTITY
    # =========================================================================
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    queue_type: Mapped[QueueType] = mapped_column(Enum(QueueType), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # QUEUE BEHAVIOR
    # =========================================================================
    auto_assign: Mapped[bool] = mapped_column(Boolean, default=False)
    max_concurrent: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Max items per user
    sla_minutes: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Target processing time

    # =========================================================================
    # ORDERING & STATUS
    # =========================================================================
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    items: Mapped[list["QueueItem"]] = relationship("QueueItem", back_populates="queue")

    def __repr__(self) -> str:
        return f"<Queue(id={self.id}, name='{self.name}', type={self.queue_type.value})>"


class QueueItem(Base):
    """
    Items in work queues.

    Tracks the progression of items through queues:
    1. Extraction Queue - emails awaiting LLM extraction
    2. Intake Queue - referrals needing data validation
    3. Care Coordination Queue - validated referrals for scheduling

    Each queue item tracks:
    - What is being processed (email or referral)
    - Current status in the queue
    - Assignment to workers
    - SLA tracking (entered, due, started, completed times)
    - Retry attempts and errors
    """

    __tablename__ = "queue_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # QUEUE REFERENCE
    # =========================================================================
    queue_id: Mapped[int] = mapped_column(
        ForeignKey("queues.id"), nullable=False, index=True
    )

    # =========================================================================
    # ITEM BEING QUEUED (one of these should be set)
    # =========================================================================
    email_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("emails.id"), index=True
    )
    referral_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("referrals.id"), index=True
    )

    # =========================================================================
    # STATUS & PRIORITY
    # =========================================================================
    status: Mapped[QueueItemStatus] = mapped_column(
        Enum(QueueItemStatus), default=QueueItemStatus.PENDING, index=True
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority), default=Priority.MEDIUM, index=True
    )

    # =========================================================================
    # ASSIGNMENT
    # =========================================================================
    assigned_to: Mapped[Optional[str]] = mapped_column(
        String(255), index=True
    )  # User/agent ID
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================================================================
    # SLA TRACKING
    # =========================================================================
    entered_queue_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================================================================
    # PROCESSING METADATA
    # =========================================================================
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # NOTES
    # =========================================================================
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    queue: Mapped["Queue"] = relationship("Queue", back_populates="items")
    email: Mapped[Optional["Email"]] = relationship("Email")
    referral: Mapped[Optional["Referral"]] = relationship(
        "Referral", back_populates="queue_items"
    )

    def __repr__(self) -> str:
        item_type = "email" if self.email_id else "referral"
        item_id = self.email_id or self.referral_id
        return f"<QueueItem(id={self.id}, {item_type}={item_id}, status={self.status.value})>"

    @property
    def is_overdue(self) -> bool:
        """Check if this queue item is past its due date."""
        if self.due_at is None:
            return False
        return datetime.utcnow() > self.due_at

    @property
    def wait_time_minutes(self) -> float:
        """Calculate how long this item has been waiting in the queue."""
        end_time = self.started_at or datetime.utcnow()
        delta = end_time - self.entered_queue_at
        return delta.total_seconds() / 60

    @property
    def processing_time_minutes(self) -> Optional[float]:
        """Calculate how long this item took to process (if completed)."""
        if not self.started_at or not self.completed_at:
            return None
        delta = self.completed_at - self.started_at
        return delta.total_seconds() / 60
