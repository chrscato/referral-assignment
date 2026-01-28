"""
Line item service for parsing and managing referral service line items.

This service handles:
- Parsing service_requested text into structured line items
- Detecting service types, body regions, laterality, and contrast
- Linking to dimension tables for ICD-10 and CPT codes
"""

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from referral_crm.models import (
    DimBodyRegion,
    DimICD10,
    DimProcedureCode,
    DimServiceType,
    ReferralLineItem,
    ServiceModality,
)

logger = logging.getLogger(__name__)


class ServiceLineItemParser:
    """
    Parses service_requested text into individual line items.

    Examples:
    - "MRI lumbar spine w/o contrast, MRI cervical spine w/o contrast"
      -> 2 line items
    - "PT evaluation and treatment x 12 visits"
      -> 1 line item with quantity=12
    - "CT right shoulder with contrast"
      -> 1 line item with with_contrast=True, laterality="right"
    """

    # Service type patterns for matching
    SERVICE_PATTERNS = {
        "MRI": {
            "modality": ServiceModality.IMAGING,
            "keywords": ["mri", "magnetic resonance", "mr imaging", "mr scan"],
        },
        "CT Scan": {
            "modality": ServiceModality.IMAGING,
            "keywords": ["ct", "cat scan", "computed tomography", "ct scan"],
        },
        "X-Ray": {
            "modality": ServiceModality.IMAGING,
            "keywords": ["x-ray", "xray", "x ray", "radiograph", "plain film"],
        },
        "Ultrasound": {
            "modality": ServiceModality.IMAGING,
            "keywords": ["ultrasound", "sonograph", "us ", "sonogram"],
        },
        "PT Evaluation": {
            "modality": ServiceModality.PHYSICAL_THERAPY,
            "keywords": ["pt eval", "physical therapy eval", "pt evaluation"],
        },
        "PT Treatment": {
            "modality": ServiceModality.PHYSICAL_THERAPY,
            "keywords": [
                "pt ",
                "physical therapy",
                "physiotherapy",
                "pt treatment",
                "therapeutic exercise",
            ],
        },
        "OT Evaluation": {
            "modality": ServiceModality.OCCUPATIONAL_THERAPY,
            "keywords": ["ot eval", "occupational therapy eval"],
        },
        "OT Treatment": {
            "modality": ServiceModality.OCCUPATIONAL_THERAPY,
            "keywords": ["ot ", "occupational therapy"],
        },
        "Chiropractic": {
            "modality": ServiceModality.CHIROPRACTIC,
            "keywords": ["chiro", "chiropractic", "spinal manipulation"],
        },
        "IME": {
            "modality": ServiceModality.IME,
            "keywords": ["ime", "independent medical exam", "independent medical evaluation"],
        },
        "FCE": {
            "modality": ServiceModality.FCE,
            "keywords": ["fce", "functional capacity", "functional capacity evaluation"],
        },
        "Injection": {
            "modality": ServiceModality.INJECTION,
            "keywords": [
                "injection",
                "epidural",
                "nerve block",
                "facet",
                "trigger point",
                "cortisone",
            ],
        },
    }

    # Body region patterns
    BODY_REGION_PATTERNS = {
        "lumbar_spine": {
            "name": "Lumbar Spine",
            "group": "Spine",
            "keywords": ["lumbar", "lower back", "l-spine", "lumbosacral", "ls spine"],
        },
        "cervical_spine": {
            "name": "Cervical Spine",
            "group": "Spine",
            "keywords": ["cervical", "c-spine", "neck"],
        },
        "thoracic_spine": {
            "name": "Thoracic Spine",
            "group": "Spine",
            "keywords": ["thoracic", "t-spine", "mid back", "dorsal"],
        },
        "shoulder": {
            "name": "Shoulder",
            "group": "Upper Extremity",
            "keywords": ["shoulder", "rotator cuff", "glenohumeral"],
        },
        "elbow": {
            "name": "Elbow",
            "group": "Upper Extremity",
            "keywords": ["elbow", "cubital"],
        },
        "wrist": {
            "name": "Wrist",
            "group": "Upper Extremity",
            "keywords": ["wrist", "carpal"],
        },
        "hand": {
            "name": "Hand",
            "group": "Upper Extremity",
            "keywords": ["hand", "finger", "thumb"],
        },
        "hip": {
            "name": "Hip",
            "group": "Lower Extremity",
            "keywords": ["hip", "pelvis", "acetabul"],
        },
        "knee": {
            "name": "Knee",
            "group": "Lower Extremity",
            "keywords": ["knee", "patella", "meniscus", "acl", "mcl"],
        },
        "ankle": {
            "name": "Ankle",
            "group": "Lower Extremity",
            "keywords": ["ankle", "achilles"],
        },
        "foot": {
            "name": "Foot",
            "group": "Lower Extremity",
            "keywords": ["foot", "toe", "plantar"],
        },
        "brain": {
            "name": "Brain",
            "group": "Head/Neck",
            "keywords": ["brain", "head", "cranial"],
        },
    }

    # Laterality patterns
    LATERALITY_PATTERNS = {
        "left": ["left", "l ", "lt ", "l.", "lt."],
        "right": ["right", "r ", "rt ", "r.", "rt."],
        "bilateral": ["bilateral", "both", "b/l", "bil"],
    }

    def __init__(self, session: Session):
        self.session = session

    def parse(
        self,
        service_text: str,
        icd10_code: Optional[str] = None,
        icd10_description: Optional[str] = None,
        confidence: float = 0.0,
    ) -> list[ReferralLineItem]:
        """
        Parse service text into structured line items.

        Args:
            service_text: Raw service requested text (may contain multiple services)
            icd10_code: ICD-10 code to apply to all line items
            icd10_description: ICD-10 description
            confidence: Confidence score from extraction

        Returns:
            List of ReferralLineItem objects (not yet committed)
        """
        if not service_text:
            return []

        # Split on common delimiters
        service_parts = self._split_services(service_text)

        line_items = []
        for i, part in enumerate(service_parts, start=1):
            part = part.strip()
            if not part:
                continue

            item = self._parse_single_service(part, i)
            if item:
                # Apply ICD-10 if provided
                if icd10_code:
                    item.icd10_code = icd10_code
                    item.icd10_description = icd10_description
                    # Try to link to dimension table
                    self._link_icd10(item)

                item.confidence = confidence
                item.source = "extraction"
                line_items.append(item)

        return line_items

    def _split_services(self, text: str) -> list[str]:
        """Split service text into individual services."""
        # Split on comma, semicolon, "and", newlines, or numbered lists
        # But be careful not to split "with and without contrast"
        text = re.sub(r"\n+", ", ", text)  # Convert newlines to commas
        text = re.sub(r"\s*;\s*", ", ", text)  # Convert semicolons to commas

        # Split on comma but not within parentheses
        parts = []
        current = ""
        paren_depth = 0

        for char in text:
            if char == "(":
                paren_depth += 1
                current += char
            elif char == ")":
                paren_depth -= 1
                current += char
            elif char == "," and paren_depth == 0:
                if current.strip():
                    parts.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            parts.append(current.strip())

        # Further split on " and " if it's clearly separating services
        # But not if it's "with and without"
        final_parts = []
        for part in parts:
            if " and " in part.lower() and "with and without" not in part.lower():
                # Check if it's truly separate services
                sub_parts = re.split(r"\s+and\s+", part, flags=re.IGNORECASE)
                final_parts.extend(sub_parts)
            else:
                final_parts.append(part)

        return final_parts

    def _parse_single_service(self, text: str, line_number: int) -> Optional[ReferralLineItem]:
        """Parse a single service description into a line item."""
        if not text or len(text) < 3:
            return None

        text_lower = text.lower()

        item = ReferralLineItem(
            line_number=line_number,
            service_description=text,
        )

        # Detect service type
        for service_name, config in self.SERVICE_PATTERNS.items():
            for keyword in config["keywords"]:
                if keyword in text_lower:
                    item.modality = config["modality"]
                    # Try to find in dimension table
                    service_type = (
                        self.session.query(DimServiceType)
                        .filter(DimServiceType.name == service_name)
                        .first()
                    )
                    if service_type:
                        item.service_type_id = service_type.id
                    break
            if item.modality:
                break

        # Detect body region
        for region_key, config in self.BODY_REGION_PATTERNS.items():
            for keyword in config["keywords"]:
                if keyword in text_lower:
                    # Try to find in dimension table
                    body_region = (
                        self.session.query(DimBodyRegion)
                        .filter(DimBodyRegion.name == config["name"])
                        .first()
                    )
                    if body_region:
                        item.body_region_id = body_region.id
                    break
            if item.body_region_id:
                break

        # Detect laterality
        for laterality, keywords in self.LATERALITY_PATTERNS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    item.laterality = laterality
                    break
            if item.laterality:
                break

        # Detect contrast
        if "with contrast" in text_lower or "w/ contrast" in text_lower or "w/contrast" in text_lower:
            item.with_contrast = True
        elif "without contrast" in text_lower or "w/o contrast" in text_lower or "w/o" in text_lower:
            item.with_contrast = False

        # Detect quantity (e.g., "x 12 visits" or "12 sessions")
        quantity_match = re.search(r"x\s*(\d+)|(\d+)\s*(visits?|sessions?|treatments?)", text_lower)
        if quantity_match:
            qty = quantity_match.group(1) or quantity_match.group(2)
            if qty:
                item.quantity = int(qty)

        # Try to derive procedure code
        self._derive_procedure_code(item)

        return item

    def _link_icd10(self, item: ReferralLineItem) -> None:
        """Link line item to ICD-10 dimension table if code exists."""
        if not item.icd10_code:
            return

        icd10 = (
            self.session.query(DimICD10)
            .filter(DimICD10.code == item.icd10_code.upper())
            .first()
        )
        if icd10:
            item.icd10_id = icd10.id
            if not item.icd10_description:
                item.icd10_description = icd10.description

    def _derive_procedure_code(self, item: ReferralLineItem) -> None:
        """Attempt to derive CPT procedure code from service details."""
        if not item.modality:
            return

        # Build query based on what we know
        query = self.session.query(DimProcedureCode).filter(
            DimProcedureCode.is_active == True
        )

        # Filter by modality/service type
        modality_service_map = {
            ServiceModality.IMAGING: ["MRI", "CT Scan", "X-Ray", "Ultrasound"],
            ServiceModality.PHYSICAL_THERAPY: ["PT Evaluation", "PT Treatment"],
            ServiceModality.OCCUPATIONAL_THERAPY: ["OT Evaluation", "OT Treatment"],
        }

        if item.modality in modality_service_map:
            query = query.filter(
                DimProcedureCode.service_type.in_(modality_service_map[item.modality])
            )

        # Try to match on contrast if imaging
        if item.modality == ServiceModality.IMAGING:
            query = query.filter(DimProcedureCode.with_contrast == item.with_contrast)

        # Get first matching code
        procedure = query.first()
        if procedure:
            item.procedure_code = procedure.code
            item.procedure_code_id = procedure.id
            item.procedure_description = procedure.description


class LineItemService:
    """Service for managing referral line items."""

    def __init__(self, session: Session):
        self.session = session
        self.parser = ServiceLineItemParser(session)

    def create_line_items_from_extraction(
        self,
        service_requested: str,
        icd10_code: Optional[str] = None,
        icd10_description: Optional[str] = None,
        confidence: float = 0.0,
    ) -> list[ReferralLineItem]:
        """
        Create line items from extracted service_requested text.

        Args:
            service_requested: Raw service text from extraction
            icd10_code: Extracted ICD-10 code
            icd10_description: Extracted ICD-10 description
            confidence: Extraction confidence score

        Returns:
            List of unsaved ReferralLineItem objects
        """
        return self.parser.parse(
            service_requested,
            icd10_code=icd10_code,
            icd10_description=icd10_description,
            confidence=confidence,
        )

    def add_line_item(
        self,
        referral_id: int,
        service_description: str,
        **kwargs,
    ) -> ReferralLineItem:
        """Manually add a line item to a referral."""
        # Get the next line number
        from referral_crm.models import Referral

        referral = self.session.query(Referral).get(referral_id)
        if not referral:
            raise ValueError(f"Referral {referral_id} not found")

        max_line = max([li.line_number for li in referral.line_items], default=0)

        item = ReferralLineItem(
            referral_id=referral_id,
            line_number=max_line + 1,
            service_description=service_description,
            source="manual",
            **kwargs,
        )

        self.session.add(item)
        self.session.commit()
        return item

    def create(
        self,
        referral_id: int,
        service_description: str,
        icd10_code: Optional[str] = None,
        icd10_description: Optional[str] = None,
        procedure_code: Optional[str] = None,
        procedure_description: Optional[str] = None,
        laterality: Optional[str] = None,
        with_contrast: bool = False,
        source: str = "manual",
        user: str = "api",
    ) -> ReferralLineItem:
        """Create a new line item for a referral."""
        from referral_crm.models import Referral

        referral = self.session.query(Referral).get(referral_id)
        if not referral:
            raise ValueError(f"Referral {referral_id} not found")

        max_line = max([li.line_number for li in referral.line_items], default=0)

        item = ReferralLineItem(
            referral_id=referral_id,
            line_number=max_line + 1,
            service_description=service_description,
            icd10_code=icd10_code,
            icd10_description=icd10_description,
            procedure_code=procedure_code,
            procedure_description=procedure_description,
            laterality=laterality,
            with_contrast=with_contrast,
            source=source,
        )

        self.session.add(item)
        self.session.commit()
        logger.info(f"Line item created for referral {referral_id} by {user}")
        return item

    def update(self, line_item_id: int, user: str = "api", **updates) -> Optional[ReferralLineItem]:
        """Update an existing line item."""
        item = self.session.query(ReferralLineItem).get(line_item_id)
        if not item:
            return None

        for key, value in updates.items():
            if hasattr(item, key) and value is not None:
                setattr(item, key, value)

        self.session.commit()
        logger.info(f"Line item {line_item_id} updated by {user}")
        return item

    def delete(self, line_item_id: int, user: str = "api") -> bool:
        """Delete a line item."""
        item = self.session.query(ReferralLineItem).get(line_item_id)
        if not item:
            return False

        referral_id = item.referral_id
        self.session.delete(item)
        self.session.commit()
        logger.info(f"Line item {line_item_id} deleted from referral {referral_id} by {user}")
        return True

    def update_line_item(self, line_item_id: int, **updates) -> Optional[ReferralLineItem]:
        """Update an existing line item (legacy method)."""
        return self.update(line_item_id, **updates)

    def delete_line_item(self, line_item_id: int) -> bool:
        """Delete a line item (legacy method)."""
        return self.delete(line_item_id)


def get_line_item_service(session: Session) -> LineItemService:
    """Factory function to create a LineItemService."""
    return LineItemService(session)


def seed_service_types(session: Session) -> None:
    """Seed the dimension tables with common service types and body regions."""
    service_types = [
        ("MRI", "MRI", ServiceModality.IMAGING),
        ("CT Scan", "CT Scan", ServiceModality.IMAGING),
        ("X-Ray", "X-Ray", ServiceModality.IMAGING),
        ("Ultrasound", "Ultrasound", ServiceModality.IMAGING),
        ("PT Evaluation", "Physical Therapy Evaluation", ServiceModality.PHYSICAL_THERAPY),
        ("PT Treatment", "Physical Therapy Treatment", ServiceModality.PHYSICAL_THERAPY),
        ("OT Evaluation", "Occupational Therapy Evaluation", ServiceModality.OCCUPATIONAL_THERAPY),
        ("OT Treatment", "Occupational Therapy Treatment", ServiceModality.OCCUPATIONAL_THERAPY),
        ("Chiropractic", "Chiropractic", ServiceModality.CHIROPRACTIC),
        ("IME", "Independent Medical Evaluation", ServiceModality.IME),
        ("FCE", "Functional Capacity Evaluation", ServiceModality.FCE),
        ("Injection", "Injection/Pain Management", ServiceModality.INJECTION),
    ]

    for name, display_name, modality in service_types:
        existing = session.query(DimServiceType).filter(DimServiceType.name == name).first()
        if not existing:
            session.add(DimServiceType(name=name, display_name=display_name, modality=modality))

    body_regions = [
        ("Lumbar Spine", "Lumbar Spine", "Spine"),
        ("Cervical Spine", "Cervical Spine", "Spine"),
        ("Thoracic Spine", "Thoracic Spine", "Spine"),
        ("Shoulder", "Shoulder", "Upper Extremity"),
        ("Elbow", "Elbow", "Upper Extremity"),
        ("Wrist", "Wrist", "Upper Extremity"),
        ("Hand", "Hand", "Upper Extremity"),
        ("Hip", "Hip", "Lower Extremity"),
        ("Knee", "Knee", "Lower Extremity"),
        ("Ankle", "Ankle", "Lower Extremity"),
        ("Foot", "Foot", "Lower Extremity"),
        ("Brain", "Brain", "Head/Neck"),
    ]

    for name, display_name, group in body_regions:
        existing = session.query(DimBodyRegion).filter(DimBodyRegion.name == name).first()
        if not existing:
            session.add(DimBodyRegion(name=name, display_name=display_name, anatomical_group=group))

    session.commit()
    logger.info("Service types and body regions seeded")
