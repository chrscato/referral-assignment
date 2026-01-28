"""
Reference data service for ICD-10 and procedure code lookups.

This service provides:
- ICD-10 code validation and lookup
- Procedure code lookup by service type
- Search functionality for codes by description
- Bulk loading from CSV files
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from referral_crm.models import DimICD10 as ICD10Code, DimProcedureCode as ProcedureCode


@dataclass
class ValidationResult:
    """Result of validating a code against reference data."""
    is_valid: bool
    code: str
    normalized_code: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    body_region: Optional[str] = None
    message: Optional[str] = None


@dataclass
class ProcedureLookupResult:
    """Result of looking up procedure codes for a service."""
    found: bool
    codes: List[ProcedureCode]
    service_type: str
    message: Optional[str] = None


class ReferenceDataService:
    """
    Service for looking up and validating reference data.

    Uses the SQLite database for ICD-10 and procedure code lookups.
    """

    def __init__(self, session: Session):
        self.session = session

    # =========================================================================
    # ICD-10 LOOKUPS
    # =========================================================================

    def lookup_icd10(self, code: str) -> Optional[ICD10Code]:
        """
        Look up an ICD-10 code by exact match.

        Args:
            code: The ICD-10 code (e.g., "M54.5")

        Returns:
            ICD10Code if found, None otherwise
        """
        if not code:
            return None

        normalized = self._normalize_icd10_code(code)
        return self.session.query(ICD10Code).filter(
            func.upper(ICD10Code.code) == normalized.upper(),
            ICD10Code.is_active == True
        ).first()

    def validate_icd10(self, code: str) -> ValidationResult:
        """
        Validate an ICD-10 code against the reference table.

        Args:
            code: The ICD-10 code to validate

        Returns:
            ValidationResult with validation status and details
        """
        if not code:
            return ValidationResult(
                is_valid=False,
                code=code or "",
                message="No code provided"
            )

        # Check format first
        normalized = self._normalize_icd10_code(code)
        if not self._is_valid_icd10_format(normalized):
            return ValidationResult(
                is_valid=False,
                code=code,
                normalized_code=normalized,
                message=f"Invalid ICD-10 format: {code}"
            )

        # Look up in database
        icd10 = self.lookup_icd10(normalized)
        if icd10:
            return ValidationResult(
                is_valid=True,
                code=code,
                normalized_code=icd10.code,
                description=icd10.description,
                category=icd10.category,
                body_region=icd10.body_region,
                message="Valid ICD-10 code"
            )
        else:
            return ValidationResult(
                is_valid=False,
                code=code,
                normalized_code=normalized,
                message=f"ICD-10 code not found in reference table: {normalized}"
            )

    def search_icd10_by_description(
        self,
        keywords: str,
        limit: int = 10
    ) -> List[ICD10Code]:
        """
        Search for ICD-10 codes by description keywords.

        Args:
            keywords: Search terms (space-separated)
            limit: Maximum number of results

        Returns:
            List of matching ICD10Code records
        """
        if not keywords:
            return []

        # Split keywords and search for any match
        terms = keywords.lower().split()
        query = self.session.query(ICD10Code).filter(ICD10Code.is_active == True)

        for term in terms:
            query = query.filter(
                func.lower(ICD10Code.description).contains(term)
            )

        return query.limit(limit).all()

    def get_icd10_by_category(self, category: str) -> List[ICD10Code]:
        """Get all ICD-10 codes in a category."""
        return self.session.query(ICD10Code).filter(
            func.lower(ICD10Code.category) == category.lower(),
            ICD10Code.is_active == True
        ).all()

    def get_icd10_by_body_region(self, body_region: str) -> List[ICD10Code]:
        """Get all ICD-10 codes for a body region."""
        return self.session.query(ICD10Code).filter(
            func.lower(ICD10Code.body_region) == body_region.lower(),
            ICD10Code.is_active == True
        ).all()

    # =========================================================================
    # PROCEDURE CODE LOOKUPS
    # =========================================================================

    def lookup_procedure(self, code: str) -> Optional[ProcedureCode]:
        """
        Look up a procedure code by exact match.

        Args:
            code: The procedure/CPT code (e.g., "97110")

        Returns:
            ProcedureCode if found, None otherwise
        """
        if not code:
            return None

        normalized = code.strip().upper()
        return self.session.query(ProcedureCode).filter(
            func.upper(ProcedureCode.code) == normalized,
            ProcedureCode.is_active == True
        ).first()

    def lookup_procedures_for_service(
        self,
        service_requested: str
    ) -> ProcedureLookupResult:
        """
        Find procedure codes that match a service request.

        This does intelligent matching based on service type keywords.

        Args:
            service_requested: The service description (e.g., "PT Evaluation", "MRI lumbar spine")

        Returns:
            ProcedureLookupResult with matching codes
        """
        if not service_requested:
            return ProcedureLookupResult(
                found=False,
                codes=[],
                service_type="",
                message="No service provided"
            )

        service_lower = service_requested.lower()

        # Determine service type from keywords
        service_type = self._categorize_service(service_lower)

        if not service_type:
            return ProcedureLookupResult(
                found=False,
                codes=[],
                service_type="unknown",
                message=f"Could not categorize service: {service_requested}"
            )

        # Look up codes by service type
        codes = self.session.query(ProcedureCode).filter(
            func.lower(ProcedureCode.service_type) == service_type.lower(),
            ProcedureCode.is_active == True
        ).all()

        if codes:
            return ProcedureLookupResult(
                found=True,
                codes=codes,
                service_type=service_type,
                message=f"Found {len(codes)} procedure code(s) for {service_type}"
            )
        else:
            return ProcedureLookupResult(
                found=False,
                codes=[],
                service_type=service_type,
                message=f"No procedure codes found for service type: {service_type}"
            )

    def get_procedures_by_modality(self, modality: str) -> List[ProcedureCode]:
        """Get all procedure codes for a modality (e.g., 'Physical Therapy', 'Imaging')."""
        return self.session.query(ProcedureCode).filter(
            func.lower(ProcedureCode.modality) == modality.lower(),
            ProcedureCode.is_active == True
        ).all()

    def search_procedures_by_description(
        self,
        keywords: str,
        limit: int = 10
    ) -> List[ProcedureCode]:
        """Search for procedure codes by description keywords."""
        if not keywords:
            return []

        terms = keywords.lower().split()
        query = self.session.query(ProcedureCode).filter(ProcedureCode.is_active == True)

        for term in terms:
            query = query.filter(
                func.lower(ProcedureCode.description).contains(term)
            )

        return query.limit(limit).all()

    # =========================================================================
    # BULK LOADING
    # =========================================================================

    def load_icd10_from_csv(self, csv_path: Path) -> int:
        """
        Bulk load ICD-10 codes from a CSV file.

        CSV format: code,description,category,body_region

        Args:
            csv_path: Path to the CSV file

        Returns:
            Number of codes loaded
        """
        count = 0
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('code', '').strip()
                if not code:
                    continue

                # Check if already exists
                existing = self.session.query(ICD10Code).filter(
                    func.upper(ICD10Code.code) == code.upper()
                ).first()

                if existing:
                    # Update existing
                    existing.description = row.get('description', '').strip()
                    existing.category = row.get('category', '').strip() or None
                    existing.body_region = row.get('body_region', '').strip() or None
                    existing.is_active = True
                else:
                    # Create new
                    icd10 = ICD10Code(
                        code=code,
                        description=row.get('description', '').strip(),
                        category=row.get('category', '').strip() or None,
                        body_region=row.get('body_region', '').strip() or None,
                    )
                    self.session.add(icd10)
                count += 1

        self.session.commit()
        return count

    def load_procedures_from_csv(self, csv_path: Path) -> int:
        """
        Bulk load procedure codes from a CSV file.

        CSV format: code,description,service_type,modality,body_region

        Args:
            csv_path: Path to the CSV file

        Returns:
            Number of codes loaded
        """
        count = 0
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('code', '').strip()
                if not code:
                    continue

                # Check if already exists
                existing = self.session.query(ProcedureCode).filter(
                    func.upper(ProcedureCode.code) == code.upper()
                ).first()

                if existing:
                    # Update existing
                    existing.description = row.get('description', '').strip()
                    existing.service_type = row.get('service_type', '').strip() or None
                    existing.modality = row.get('modality', '').strip() or None
                    existing.body_region = row.get('body_region', '').strip() or None
                    existing.is_active = True
                else:
                    # Create new
                    proc = ProcedureCode(
                        code=code,
                        description=row.get('description', '').strip(),
                        service_type=row.get('service_type', '').strip() or None,
                        modality=row.get('modality', '').strip() or None,
                        body_region=row.get('body_region', '').strip() or None,
                    )
                    self.session.add(proc)
                count += 1

        self.session.commit()
        return count

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _normalize_icd10_code(self, code: str) -> str:
        """Normalize an ICD-10 code (remove spaces, ensure proper format)."""
        if not code:
            return ""
        # Remove spaces, make uppercase
        normalized = code.strip().upper().replace(" ", "")
        return normalized

    def _is_valid_icd10_format(self, code: str) -> bool:
        """Check if code matches ICD-10 format (e.g., M54.5, S43.001A)."""
        if not code:
            return False
        # ICD-10 format: letter + 2 digits + optional decimal + more digits/letters
        pattern = r'^[A-Z]\d{2}(\.\d{1,4}[A-Z]?)?$'
        return bool(re.match(pattern, code, re.IGNORECASE))

    def _categorize_service(self, service_text: str) -> Optional[str]:
        """
        Categorize a service request into a standard service type.

        Returns the service_type that matches the procedure_codes table.
        """
        service_lower = service_text.lower()

        # Physical Therapy keywords
        pt_keywords = ['pt ', 'physical therapy', 'pt evaluation', 'pt eval', 'therapeutic exercise']
        for kw in pt_keywords:
            if kw in service_lower:
                if 'eval' in service_lower:
                    return 'PT Evaluation'
                return 'PT Treatment'

        # MRI keywords
        if 'mri' in service_lower:
            return 'MRI'

        # CT keywords
        if 'ct ' in service_lower or 'ct scan' in service_lower or 'computed tomography' in service_lower:
            return 'CT Scan'

        # X-Ray keywords
        if 'x-ray' in service_lower or 'xray' in service_lower or 'radiograph' in service_lower:
            return 'X-Ray'

        # Ultrasound keywords
        if 'ultrasound' in service_lower or 'sonograph' in service_lower:
            return 'Ultrasound'

        # IME keywords
        if 'ime' in service_lower or 'independent medical' in service_lower:
            return 'IME'

        # FCE keywords
        if 'fce' in service_lower or 'functional capacity' in service_lower:
            return 'FCE'

        # Chiropractic keywords
        if 'chiro' in service_lower:
            return 'Chiropractic'

        # Occupational Therapy keywords
        if 'ot ' in service_lower or 'occupational therapy' in service_lower:
            return 'OT Treatment'

        return None


def get_reference_data_service(session: Session) -> ReferenceDataService:
    """Factory function to create a ReferenceDataService."""
    return ReferenceDataService(session)
