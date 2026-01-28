"""
Dimension tables for reference data.

This module contains dimension tables used for:
- ICD-10 diagnosis code lookup and validation
- CPT/Procedure code lookup and matching
- Service type standardization
- Body region classification
"""

from datetime import datetime
from typing import Optional

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
from referral_crm.models.enums import ServiceModality


class DimICD10(Base):
    """
    ICD-10 diagnosis code dimension table.

    Used for:
    - Validating extracted ICD-10 codes
    - Looking up descriptions for codes
    - Categorizing diagnoses by body region
    - Suggesting related procedure codes
    """

    __tablename__ = "dim_icd10"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # CODE & DESCRIPTION
    # =========================================================================
    code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================
    category: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    # e.g., "Musculoskeletal", "Nervous System", "Injury", "Pain"

    subcategory: Mapped[Optional[str]] = mapped_column(String(100))
    # e.g., "Dorsopathies", "Soft tissue disorders"

    body_region: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    # e.g., "Back", "Shoulder", "Knee", "Neck", "Hip"

    body_side: Mapped[Optional[str]] = mapped_column(String(20))
    # e.g., "left", "right", "bilateral", "unspecified"

    # =========================================================================
    # ASSOCIATIONS
    # =========================================================================
    common_services: Mapped[Optional[list]] = mapped_column(JSON)
    # e.g., ["MRI", "Physical Therapy", "Injection"]

    common_cpt_codes: Mapped[Optional[list]] = mapped_column(JSON)
    # e.g., ["72148", "97110", "20610"]

    # =========================================================================
    # STATUS
    # =========================================================================
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DimICD10(code='{self.code}', desc='{self.description[:50]}...')>"


class DimProcedureCode(Base):
    """
    CPT/Procedure code dimension table.

    Used for:
    - Deriving procedure codes from service descriptions (Step 2 reasoning)
    - Looking up pricing and authorization requirements
    - Categorizing procedures by modality and body region
    """

    __tablename__ = "dim_procedure_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # CODE & DESCRIPTION
    # =========================================================================
    code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================
    service_type: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    # e.g., "PT Evaluation", "MRI", "CT Scan", "X-Ray", "Injection"

    modality: Mapped[Optional[str]] = mapped_column(String(100))
    # e.g., "Physical Therapy", "Imaging", "Diagnostic", "Pain Management"

    body_region: Mapped[Optional[str]] = mapped_column(String(100))
    # e.g., "Spine", "Upper Extremity", "Lower Extremity", "Whole Body"

    # =========================================================================
    # MODIFIERS
    # =========================================================================
    with_contrast: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_auth: Mapped[bool] = mapped_column(Boolean, default=False)

    # =========================================================================
    # PRICING REFERENCE
    # =========================================================================
    rvu: Mapped[Optional[float]] = mapped_column(Float)  # Relative Value Units
    national_rate: Mapped[Optional[float]] = mapped_column(Float)  # Medicare rate

    # =========================================================================
    # STATUS
    # =========================================================================
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DimProcedureCode(code='{self.code}', type='{self.service_type}')>"


class DimServiceType(Base):
    """
    Service type dimension table.

    Standardizes service types for consistent matching and categorization.
    Used by the line item parser to classify extracted services.
    """

    __tablename__ = "dim_service_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # IDENTITY
    # =========================================================================
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================
    modality: Mapped[Optional[ServiceModality]] = mapped_column(Enum(ServiceModality))

    # =========================================================================
    # MATCHING
    # =========================================================================
    keywords: Mapped[Optional[list]] = mapped_column(JSON)
    # e.g., ["mri", "magnetic resonance", "mr imaging"] for fuzzy matching

    # =========================================================================
    # DEFAULTS
    # =========================================================================
    default_cpt_code: Mapped[Optional[str]] = mapped_column(String(20))

    # =========================================================================
    # STATUS & ORDERING
    # =========================================================================
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<DimServiceType(name='{self.name}', modality={self.modality})>"


class DimBodyRegion(Base):
    """
    Body region dimension table.

    Standardizes body regions for consistent categorization.
    Supports a hierarchical structure (e.g., Spine > Lumbar Spine).
    """

    __tablename__ = "dim_body_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # IDENTITY
    # =========================================================================
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # =========================================================================
    # HIERARCHY
    # =========================================================================
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_body_regions.id"))

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================
    anatomical_group: Mapped[Optional[str]] = mapped_column(String(100))
    # e.g., "Spine", "Upper Extremity", "Lower Extremity", "Head/Neck", "Trunk"

    # =========================================================================
    # MATCHING
    # =========================================================================
    keywords: Mapped[Optional[list]] = mapped_column(JSON)
    # e.g., ["lumbar", "lower back", "L-spine", "lumbosacral"] for "Lumbar Spine"

    # =========================================================================
    # STATUS & ORDERING
    # =========================================================================
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    parent: Mapped[Optional["DimBodyRegion"]] = relationship(
        "DimBodyRegion", remote_side=[id], backref="children"
    )

    def __repr__(self) -> str:
        return f"<DimBodyRegion(name='{self.name}', group='{self.anatomical_group}')>"
