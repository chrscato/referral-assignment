"""
Referral service - Core CRUD operations and business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from referral_crm.models import (
    Attachment,
    AuditLog,
    Carrier,
    Referral,
    ReferralStatus,
    Priority,
)


class ReferralService:
    """Service for managing referrals."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        email_subject: Optional[str] = None,
        adjuster_email: Optional[str] = None,
        **kwargs,
    ) -> Referral:
        """Create a new referral."""
        referral = Referral(
            email_subject=email_subject,
            adjuster_email=adjuster_email,
            status=ReferralStatus.PENDING,
            **kwargs,
        )
        self.session.add(referral)
        self.session.commit()
        self.session.refresh(referral)

        self._log_action(referral.id, "created", notes="Referral created")
        return referral

    def get(self, referral_id: int) -> Optional[Referral]:
        """Get a referral by ID with related data."""
        return (
            self.session.query(Referral)
            .options(
                joinedload(Referral.carrier),
                joinedload(Referral.provider),
                joinedload(Referral.attachments),
            )
            .filter(Referral.id == referral_id)
            .first()
        )

    def get_by_email_id(self, email_id: str) -> Optional[Referral]:
        """Get a referral by its Graph API email ID."""
        return self.session.query(Referral).filter(Referral.email_id == email_id).first()

    def list(
        self,
        status: Optional[ReferralStatus] = None,
        priority: Optional[Priority] = None,
        carrier_id: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "received_at",
        order_desc: bool = True,
    ) -> list[Referral]:
        """List referrals with optional filtering."""
        query = self.session.query(Referral).options(
            joinedload(Referral.carrier),
            joinedload(Referral.provider),
        )

        if status:
            query = query.filter(Referral.status == status)
        if priority:
            query = query.filter(Referral.priority == priority)
        if carrier_id:
            query = query.filter(Referral.carrier_id == carrier_id)
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Referral.claimant_name.ilike(search_term),
                    Referral.claim_number.ilike(search_term),
                    Referral.adjuster_name.ilike(search_term),
                    Referral.email_subject.ilike(search_term),
                )
            )

        order_column = getattr(Referral, order_by, Referral.received_at)
        if order_desc:
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())

        return query.offset(offset).limit(limit).all()

    def count_by_status(self) -> dict[str, int]:
        """Get counts of referrals grouped by status."""
        results = (
            self.session.query(Referral.status, func.count(Referral.id))
            .group_by(Referral.status)
            .all()
        )
        return {status.value: count for status, count in results}

    def update(self, referral_id: int, user: str = "system", **kwargs) -> Optional[Referral]:
        """Update a referral with audit logging."""
        referral = self.get(referral_id)
        if not referral:
            return None

        for field, new_value in kwargs.items():
            if hasattr(referral, field):
                old_value = getattr(referral, field)
                if old_value != new_value:
                    setattr(referral, field, new_value)
                    self._log_action(
                        referral_id,
                        "updated",
                        field_name=field,
                        old_value=str(old_value) if old_value else None,
                        new_value=str(new_value) if new_value else None,
                        user=user,
                    )

        referral.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(referral)
        return referral

    def update_status(
        self,
        referral_id: int,
        new_status: ReferralStatus,
        user: str = "system",
        notes: Optional[str] = None,
    ) -> Optional[Referral]:
        """Update the status of a referral."""
        referral = self.get(referral_id)
        if not referral:
            return None

        old_status = referral.status
        referral.status = new_status
        referral.updated_at = datetime.utcnow()

        if new_status == ReferralStatus.COMPLETED:
            referral.completed_at = datetime.utcnow()

        self._log_action(
            referral_id,
            "status_changed",
            field_name="status",
            old_value=old_status.value,
            new_value=new_status.value,
            user=user,
            notes=notes,
        )

        self.session.commit()
        self.session.refresh(referral)
        return referral

    def approve(self, referral_id: int, user: str = "system") -> Optional[Referral]:
        """Move referral to approved status."""
        return self.update_status(
            referral_id, ReferralStatus.APPROVED, user, notes="Referral approved"
        )

    def reject(
        self, referral_id: int, reason: str, user: str = "system"
    ) -> Optional[Referral]:
        """Reject a referral with a reason."""
        referral = self.get(referral_id)
        if not referral:
            return None

        referral.status = ReferralStatus.REJECTED
        referral.rejection_reason = reason
        referral.updated_at = datetime.utcnow()

        self._log_action(
            referral_id,
            "rejected",
            notes=f"Rejected: {reason}",
            user=user,
        )

        self.session.commit()
        self.session.refresh(referral)
        return referral

    def mark_needs_info(
        self, referral_id: int, info_needed: str, user: str = "system"
    ) -> Optional[Referral]:
        """Mark a referral as needing additional information."""
        referral = self.update(
            referral_id,
            user=user,
            status=ReferralStatus.NEEDS_INFO,
            notes=f"Info needed: {info_needed}",
        )
        return referral

    def mark_submitted_to_filemaker(
        self, referral_id: int, filemaker_record_id: str, user: str = "system"
    ) -> Optional[Referral]:
        """Mark a referral as submitted to FileMaker."""
        return self.update(
            referral_id,
            user=user,
            status=ReferralStatus.SUBMITTED_TO_FILEMAKER,
            filemaker_record_id=filemaker_record_id,
            filemaker_submitted_at=datetime.utcnow(),
        )

    def add_attachment(
        self,
        referral_id: int,
        filename: str,
        content_type: Optional[str] = None,
        size_bytes: Optional[int] = None,
        storage_path: Optional[str] = None,
        graph_attachment_id: Optional[str] = None,
        document_type: Optional[str] = None,
        extracted_text: Optional[str] = None,
        s3_key: Optional[str] = None,
        s3_text_key: Optional[str] = None,
    ) -> Attachment:
        """Add an attachment to a referral."""
        attachment = Attachment(
            referral_id=referral_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            graph_attachment_id=graph_attachment_id,
            document_type=document_type,
            extracted_text=extracted_text,
            s3_key=s3_key,
            s3_text_key=s3_text_key,
        )
        self.session.add(attachment)
        self.session.commit()
        self.session.refresh(attachment)
        return attachment

    def get_audit_log(self, referral_id: int) -> list[AuditLog]:
        """Get the audit history for a referral."""
        return (
            self.session.query(AuditLog)
            .filter(AuditLog.referral_id == referral_id)
            .order_by(AuditLog.timestamp.desc())
            .all()
        )

    def _log_action(
        self,
        referral_id: int,
        action: str,
        field_name: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        user: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Log an action to the audit trail."""
        log = AuditLog(
            referral_id=referral_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            user=user or "system",
            notes=notes,
        )
        self.session.add(log)

    def delete(self, referral_id: int) -> bool:
        """Delete a referral (cascade deletes attachments and audit logs)."""
        referral = self.get(referral_id)
        if not referral:
            return False

        self.session.delete(referral)
        self.session.commit()
        return True


class CarrierService:
    """Service for managing carriers."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, name: str, **kwargs) -> Carrier:
        """Create a new carrier."""
        carrier = Carrier(name=name, **kwargs)
        self.session.add(carrier)
        self.session.commit()
        self.session.refresh(carrier)
        return carrier

    def get(self, carrier_id: int) -> Optional[Carrier]:
        """Get a carrier by ID."""
        return self.session.query(Carrier).filter(Carrier.id == carrier_id).first()

    def get_by_name(self, name: str) -> Optional[Carrier]:
        """Get a carrier by name (case-insensitive)."""
        return (
            self.session.query(Carrier)
            .filter(func.lower(Carrier.name) == func.lower(name))
            .first()
        )

    def find_or_create(self, name: str, **kwargs) -> Carrier:
        """Find an existing carrier or create a new one."""
        carrier = self.get_by_name(name)
        if carrier:
            return carrier
        return self.create(name=name, **kwargs)

    def list(self, active_only: bool = True) -> list[Carrier]:
        """List all carriers."""
        query = self.session.query(Carrier)
        if active_only:
            query = query.filter(Carrier.is_active == True)
        return query.order_by(Carrier.name).all()

    def update(self, carrier_id: int, **kwargs) -> Optional[Carrier]:
        """Update a carrier."""
        carrier = self.get(carrier_id)
        if not carrier:
            return None

        for field, value in kwargs.items():
            if hasattr(carrier, field):
                setattr(carrier, field, value)

        carrier.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(carrier)
        return carrier
