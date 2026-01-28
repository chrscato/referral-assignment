"""
Workflow service for queue management and status transitions.

This service manages the flow of items through the processing pipeline:
1. Extraction Queue - Emails awaiting LLM extraction
2. Intake Queue - Referrals needing data validation
3. Care Coordination Queue - Validated referrals for scheduling
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from referral_crm.models import (
    Email,
    EmailStatus,
    Priority,
    Queue,
    QueueItem,
    QueueItemStatus,
    QueueType,
    Referral,
    ReferralLineItem,
    ReferralStatus,
)

logger = logging.getLogger(__name__)


class WorkflowService:
    """
    Manages referral lifecycle through queues.

    Handles:
    - Adding items to queues
    - Status transitions
    - SLA tracking
    - Assignment management
    """

    def __init__(self, session: Session):
        self.session = session

    # =========================================================================
    # QUEUE RETRIEVAL
    # =========================================================================

    def get_queue(self, queue_type: QueueType) -> Optional[Queue]:
        """Get a queue by type."""
        return (
            self.session.query(Queue)
            .filter(Queue.queue_type == queue_type, Queue.is_active == True)
            .first()
        )

    def get_queue_by_name(self, name: str) -> Optional[Queue]:
        """Get a queue by name."""
        return (
            self.session.query(Queue)
            .filter(Queue.name == name, Queue.is_active == True)
            .first()
        )

    def get_current_queue_item(
        self, referral_id: int, queue_type: QueueType
    ) -> Optional[QueueItem]:
        """Get the current queue item for a referral in a specific queue."""
        queue = self.get_queue(queue_type)
        if not queue:
            return None
        return (
            self.session.query(QueueItem)
            .filter(
                QueueItem.queue_id == queue.id,
                QueueItem.referral_id == referral_id,
                QueueItem.status.in_(
                    [QueueItemStatus.PENDING, QueueItemStatus.IN_PROGRESS]
                ),
            )
            .first()
        )

    # =========================================================================
    # EMAIL -> EXTRACTION QUEUE
    # =========================================================================

    def queue_email_for_extraction(self, email: Email) -> QueueItem:
        """
        Add a new email to the extraction queue.

        Called when an email is first ingested from the inbox.
        """
        extraction_queue = self.get_queue(QueueType.EXTRACTION)
        if not extraction_queue:
            raise ValueError("Extraction queue not found. Run seed_queues() first.")

        # Calculate due date based on SLA
        due_at = None
        if extraction_queue.sla_minutes:
            due_at = datetime.utcnow() + timedelta(minutes=extraction_queue.sla_minutes)

        queue_item = QueueItem(
            queue_id=extraction_queue.id,
            email_id=email.id,
            status=QueueItemStatus.PENDING,
            priority=self._determine_email_priority(email),
            entered_queue_at=datetime.utcnow(),
            due_at=due_at,
        )

        email.status = EmailStatus.PENDING_EXTRACTION

        self.session.add(queue_item)
        self.session.commit()

        logger.info(f"Email {email.id} queued for extraction")
        return queue_item

    def start_extraction(self, email: Email) -> QueueItem:
        """Mark an email as being extracted."""
        queue_item = (
            self.session.query(QueueItem)
            .filter(
                QueueItem.email_id == email.id,
                QueueItem.status == QueueItemStatus.PENDING,
            )
            .first()
        )

        if queue_item:
            queue_item.status = QueueItemStatus.IN_PROGRESS
            queue_item.started_at = datetime.utcnow()
            queue_item.attempt_count += 1

        email.status = EmailStatus.EXTRACTION_IN_PROGRESS
        email.extraction_attempts += 1

        self.session.commit()
        return queue_item

    def fail_extraction(self, email: Email, error: str) -> None:
        """Mark an extraction as failed."""
        queue_item = (
            self.session.query(QueueItem)
            .filter(
                QueueItem.email_id == email.id,
                QueueItem.status == QueueItemStatus.IN_PROGRESS,
            )
            .first()
        )

        if queue_item:
            queue_item.status = QueueItemStatus.FAILED
            queue_item.last_error = error
            queue_item.completed_at = datetime.utcnow()

        email.status = EmailStatus.EXTRACTION_FAILED
        email.last_extraction_error = error

        self.session.commit()
        logger.error(f"Extraction failed for email {email.id}: {error}")

    # =========================================================================
    # EXTRACTION COMPLETE -> INTAKE QUEUE
    # =========================================================================

    def complete_extraction_and_queue_for_intake(
        self,
        email: Email,
        referral: Referral,
        line_items: list[ReferralLineItem],
    ) -> QueueItem:
        """
        After successful extraction:
        1. Mark email as processed
        2. Save referral with line items
        3. Add referral to intake queue
        """
        # Complete extraction queue item
        extraction_item = (
            self.session.query(QueueItem)
            .filter(
                QueueItem.email_id == email.id,
                QueueItem.status == QueueItemStatus.IN_PROGRESS,
            )
            .first()
        )

        if extraction_item:
            extraction_item.status = QueueItemStatus.COMPLETED
            extraction_item.completed_at = datetime.utcnow()

        # Update email status
        email.status = EmailStatus.PROCESSED
        email.processed_at = datetime.utcnow()

        # Link referral to email
        referral.email_id = email.id
        referral.status = ReferralStatus.PENDING_VALIDATION
        referral.received_at = email.received_at
        self.session.add(referral)
        self.session.flush()  # Get referral ID

        # Add line items
        for i, item in enumerate(line_items, start=1):
            item.referral_id = referral.id
            item.line_number = i
            self.session.add(item)

        # Add to intake queue
        intake_queue = self.get_queue(QueueType.INTAKE)
        if not intake_queue:
            raise ValueError("Intake queue not found. Run seed_queues() first.")

        due_at = None
        if intake_queue.sla_minutes:
            due_at = datetime.utcnow() + timedelta(minutes=intake_queue.sla_minutes)

        queue_item = QueueItem(
            queue_id=intake_queue.id,
            referral_id=referral.id,
            status=QueueItemStatus.PENDING,
            priority=referral.priority,
            entered_queue_at=datetime.utcnow(),
            due_at=due_at,
        )

        self.session.add(queue_item)
        self.session.commit()

        logger.info(
            f"Extraction complete for email {email.id}, "
            f"referral {referral.id} queued for intake"
        )
        return queue_item

    # =========================================================================
    # INTAKE QUEUE OPERATIONS
    # =========================================================================

    def claim_intake_item(self, referral_id: int, user: str) -> Optional[QueueItem]:
        """Claim a referral from the intake queue for validation."""
        queue_item = self.get_current_queue_item(referral_id, QueueType.INTAKE)

        if not queue_item:
            return None

        if queue_item.status != QueueItemStatus.PENDING:
            return None

        queue_item.status = QueueItemStatus.IN_PROGRESS
        queue_item.assigned_to = user
        queue_item.assigned_at = datetime.utcnow()
        queue_item.started_at = datetime.utcnow()

        self.session.commit()
        logger.info(f"Referral {referral_id} claimed by {user} for intake validation")
        return queue_item

    def release_queue_item(self, queue_item_id: int, user: str) -> bool:
        """Release a claimed queue item back to pending."""
        item = (
            self.session.query(QueueItem)
            .filter(
                QueueItem.id == queue_item_id,
                QueueItem.assigned_to == user,
                QueueItem.status == QueueItemStatus.IN_PROGRESS,
            )
            .first()
        )
        if not item:
            return False

        item.status = QueueItemStatus.PENDING
        item.assigned_to = None
        item.assigned_at = None
        item.started_at = None

        self.session.commit()
        logger.info(f"Queue item {queue_item_id} released by {user}")
        return True

    def validate_and_queue_for_scheduling(
        self,
        referral: Referral,
        validated_by: str,
    ) -> QueueItem:
        """
        After intake validation:
        1. Mark referral as validated
        2. Complete intake queue item
        3. Add to care coordination queue
        """
        referral.status = ReferralStatus.VALIDATED
        referral.validated_at = datetime.utcnow()
        referral.needs_human_review = False

        # Complete intake queue item
        intake_item = self.get_current_queue_item(referral.id, QueueType.INTAKE)
        if intake_item:
            intake_item.status = QueueItemStatus.COMPLETED
            intake_item.completed_at = datetime.utcnow()

        # Add to care coordination queue
        cc_queue = self.get_queue(QueueType.CARE_COORDINATION)
        if not cc_queue:
            raise ValueError(
                "Care coordination queue not found. Run seed_queues() first."
            )

        due_at = None
        if cc_queue.sla_minutes:
            due_at = datetime.utcnow() + timedelta(minutes=cc_queue.sla_minutes)

        queue_item = QueueItem(
            queue_id=cc_queue.id,
            referral_id=referral.id,
            status=QueueItemStatus.PENDING,
            priority=referral.priority,
            entered_queue_at=datetime.utcnow(),
            due_at=due_at,
        )

        self.session.add(queue_item)
        self.session.commit()

        logger.info(
            f"Referral {referral.id} validated by {validated_by}, "
            f"queued for care coordination"
        )
        return queue_item

    def reject_referral(
        self, referral: Referral, rejected_by: str, reason: str
    ) -> None:
        """Reject a referral during intake validation."""
        referral.status = ReferralStatus.REJECTED
        referral.rejection_reason = reason

        # Complete intake queue item
        intake_item = self.get_current_queue_item(referral.id, QueueType.INTAKE)
        if intake_item:
            intake_item.status = QueueItemStatus.COMPLETED
            intake_item.completed_at = datetime.utcnow()
            intake_item.notes = f"Rejected by {rejected_by}: {reason}"

        self.session.commit()
        logger.info(f"Referral {referral.id} rejected by {rejected_by}: {reason}")

    # =========================================================================
    # CARE COORDINATION QUEUE OPERATIONS
    # =========================================================================

    def claim_care_coordination_item(
        self, referral_id: int, user: str
    ) -> Optional[QueueItem]:
        """Claim a referral from the care coordination queue."""
        queue_item = self.get_current_queue_item(referral_id, QueueType.CARE_COORDINATION)

        if not queue_item:
            return None

        if queue_item.status != QueueItemStatus.PENDING:
            return None

        queue_item.status = QueueItemStatus.IN_PROGRESS
        queue_item.assigned_to = user
        queue_item.assigned_at = datetime.utcnow()
        queue_item.started_at = datetime.utcnow()

        referral = self.session.query(Referral).get(referral_id)
        if referral:
            referral.status = ReferralStatus.PENDING_SCHEDULING

        self.session.commit()
        logger.info(f"Referral {referral_id} claimed by {user} for scheduling")
        return queue_item

    def complete_scheduling(self, referral: Referral, scheduled_by: str) -> None:
        """
        After care coordinator schedules services:
        1. Update referral status
        2. Complete queue item
        """
        referral.status = ReferralStatus.SCHEDULED
        referral.scheduled_at = datetime.utcnow()

        # Complete queue item
        cc_item = self.get_current_queue_item(
            referral.id, QueueType.CARE_COORDINATION
        )
        if cc_item:
            cc_item.status = QueueItemStatus.COMPLETED
            cc_item.completed_at = datetime.utcnow()

        self.session.commit()
        logger.info(f"Referral {referral.id} scheduled by {scheduled_by}")

    def complete_referral(self, referral: Referral) -> None:
        """Mark a referral as completed after all services are delivered."""
        referral.status = ReferralStatus.COMPLETED
        referral.completed_at = datetime.utcnow()
        self.session.commit()
        logger.info(f"Referral {referral.id} completed")

    # =========================================================================
    # QUEUE QUERIES
    # =========================================================================

    def get_pending_items(
        self, queue_type: QueueType, limit: int = 50
    ) -> list[QueueItem]:
        """Get pending items from a queue, ordered by priority and entered time."""
        queue = self.get_queue(queue_type)
        if not queue:
            return []

        # Order by priority (urgent first) then by entered time
        priority_order = [Priority.URGENT, Priority.HIGH, Priority.MEDIUM, Priority.LOW]

        return (
            self.session.query(QueueItem)
            .filter(
                QueueItem.queue_id == queue.id,
                QueueItem.status == QueueItemStatus.PENDING,
            )
            .order_by(
                # SQLite doesn't support CASE well, so just order by entered_at
                QueueItem.entered_queue_at.asc()
            )
            .limit(limit)
            .all()
        )

    def get_overdue_items(self, queue_type: QueueType) -> list[QueueItem]:
        """Get items that are past their SLA due date."""
        queue = self.get_queue(queue_type)
        if not queue:
            return []

        return (
            self.session.query(QueueItem)
            .filter(
                QueueItem.queue_id == queue.id,
                QueueItem.status.in_(
                    [QueueItemStatus.PENDING, QueueItemStatus.IN_PROGRESS]
                ),
                QueueItem.due_at < datetime.utcnow(),
            )
            .all()
        )

    def get_queue_stats(self, queue_type: QueueType) -> dict:
        """Get statistics for a queue."""
        queue = self.get_queue(queue_type)
        if not queue:
            return {}

        pending = (
            self.session.query(QueueItem)
            .filter(
                QueueItem.queue_id == queue.id,
                QueueItem.status == QueueItemStatus.PENDING,
            )
            .count()
        )

        in_progress = (
            self.session.query(QueueItem)
            .filter(
                QueueItem.queue_id == queue.id,
                QueueItem.status == QueueItemStatus.IN_PROGRESS,
            )
            .count()
        )

        overdue = len(self.get_overdue_items(queue_type))

        return {
            "queue_name": queue.name,
            "queue_type": queue.queue_type.value,
            "pending": pending,
            "in_progress": in_progress,
            "overdue": overdue,
            "sla_minutes": queue.sla_minutes,
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _determine_email_priority(self, email: Email) -> Priority:
        """Determine priority based on email content."""
        if not email.subject:
            return Priority.MEDIUM

        subject_lower = email.subject.lower()
        if any(kw in subject_lower for kw in ["urgent", "asap", "rush", "emergency"]):
            return Priority.URGENT
        if any(kw in subject_lower for kw in ["high priority", "important"]):
            return Priority.HIGH
        return Priority.MEDIUM


def seed_queues(session: Session) -> None:
    """Create initial queue configurations."""
    queues = [
        Queue(
            name="extraction",
            queue_type=QueueType.EXTRACTION,
            description="Emails awaiting LLM data extraction",
            auto_assign=True,
            sla_minutes=15,
            sort_order=1,
        ),
        Queue(
            name="intake",
            queue_type=QueueType.INTAKE,
            description="Referrals requiring data validation and review",
            auto_assign=False,
            sla_minutes=60,
            sort_order=2,
        ),
        Queue(
            name="care_coordination",
            queue_type=QueueType.CARE_COORDINATION,
            description="Validated referrals ready for provider scheduling",
            auto_assign=False,
            sla_minutes=240,
            sort_order=3,
        ),
    ]

    for queue in queues:
        existing = session.query(Queue).filter(Queue.name == queue.name).first()
        if not existing:
            session.add(queue)
            logger.info(f"Created queue: {queue.name}")

    session.commit()
    logger.info("Queue seeding complete")


def get_workflow_service(session: Session) -> WorkflowService:
    """Factory function to create a WorkflowService."""
    return WorkflowService(session)
