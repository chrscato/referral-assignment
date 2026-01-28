"""
FileMaker Intake Form Field Conversion & Validation
====================================================

Transforms extracted referral data into FileMaker-compatible format.
Handles field normalization, validation, and payload building.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS FOR FILEMAKER FIELDS
# ============================================================================

@dataclass
class FileMakerExtraction:
    """
    Extraction result mapped to exact FileMaker field names.
    These correspond directly to your intake form.
    """

    # PATIENT/CLAIMANT INFORMATION (CRITICAL)
    intake_client_first_name: Optional[str] = None
    intake_client_last_name: Optional[str] = None
    intake_claim_number: Optional[str] = None
    intake_client_company: Optional[str] = None  # Insurance carrier
    intake_dob: Optional[str] = None
    intake_doi: Optional[str] = None  # Date of injury
    intake_client_phone: Optional[str] = None
    intake_client_email: Optional[str] = None
    intake_instructions: Optional[str] = None  # Service type + special instructions
    injury_description: Optional[str] = None  # Body parts

    # PATIENT ADDRESS
    patient_first_name: Optional[str] = None
    patient_last_name: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_email: Optional[str] = None
    patient_employer: Optional[str] = None
    patient_address_1: Optional[str] = None
    patient_address_2: Optional[str] = None
    patient_address_city: Optional[str] = None
    patient_address_state: Optional[str] = None
    patient_address_zip: Optional[str] = None

    # NEW PATIENT FIELDS
    patient_gender: Optional[str] = None
    patient_ssn: Optional[str] = None
    patient_job_title: Optional[str] = None

    # EMPLOYER INFORMATION
    employer_address_1: Optional[str] = None
    employer_address_2: Optional[str] = None
    employer_address_city: Optional[str] = None
    employer_address_state: Optional[str] = None
    employer_address_zip: Optional[str] = None
    employer_email: Optional[str] = None

    # REFERRING PHYSICIAN
    referring_physician_name: Optional[str] = None
    referring_physician_npi: Optional[str] = None

    # CLAIM/JURISDICTION
    jurisdiction_state: Optional[str] = None
    order_type: Optional[str] = None

    # ICD-10 / DIAGNOSIS
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    icd10_category: Optional[str] = None  # Derived from reference data

    # PROCEDURE CODE (derived)
    associated_procedure_code: Optional[str] = None

    # PREFERENCES/SPECIAL INSTRUCTIONS
    suggested_providers: Optional[str] = None
    special_requirements: Optional[str] = None

    # STATUS
    status: str = "Pending"  # Default new intake status

    # METADATA (audit trail)
    source_email_id: Optional[str] = None
    adjuster_name: Optional[str] = None
    adjuster_email: Optional[str] = None
    adjuster_phone: Optional[str] = None
    extraction_confidence: float = 0.0
    extraction_timestamp: Optional[str] = None

    # CONFIDENCE SCORES (for review)
    confidence_scores: Dict[str, int] = field(default_factory=dict)
    validation_flags: List[Dict] = field(default_factory=list)
    extraction_warnings: List[str] = field(default_factory=list)

    def to_filemaker_payload(self) -> Dict[str, Any]:
        """Build payload for FileMaker Data API."""
        return {
            "fieldData": {
                # Intake/Client Information
                "Intake Client First Name": self.intake_client_first_name or "",
                "Intake Client Last Name": self.intake_client_last_name or "",
                "Intake Claim Number": self.intake_claim_number or "",
                "Intake Client Company": self.intake_client_company or "",
                "Intake DOB": self.intake_dob or "",
                "Intake DOI": self.intake_doi or "",
                "Intake Client Phone": self.intake_client_phone or "",
                "Intake Client Email": self.intake_client_email or "",
                "Intake Instructions": self.intake_instructions or "",
                "Injury Description": self.injury_description or "",

                # Patient Information
                "Patient First Name": self.patient_first_name or "",
                "Patient Last Name": self.patient_last_name or "",
                "Patient Phone": self.patient_phone or "",
                "Patient Email": self.patient_email or "",
                "Patient Employer": self.patient_employer or "",
                "Patient Address 1": self.patient_address_1 or "",
                "Patient Address 2": self.patient_address_2 or "",
                "Patient Address City": self.patient_address_city or "",
                "Patient Address State": self.patient_address_state or "",
                "Patient Address ZIP": self.patient_address_zip or "",
                "Patient Gender": self.patient_gender or "",
                "Patient SSN": self.patient_ssn or "",
                "Patient Job Title": self.patient_job_title or "",

                # Employer Information
                "Employer Address 1": self.employer_address_1 or "",
                "Employer Address 2": self.employer_address_2 or "",
                "Employer Address City": self.employer_address_city or "",
                "Employer Address State": self.employer_address_state or "",
                "Employer Address ZIP": self.employer_address_zip or "",
                "Employer Email": self.employer_email or "",

                # Referring Physician
                "Referring Physician Name": self.referring_physician_name or "",
                "Referring Physician NPI": self.referring_physician_npi or "",

                # Claim/Jurisdiction
                "Jurisdiction State": self.jurisdiction_state or "",
                "Order Type": self.order_type or "",

                # ICD-10/Diagnosis
                "ICD10 Code": self.icd10_code or "",
                "ICD10 Description": self.icd10_description or "",
                "ICD10 Category": self.icd10_category or "",

                # Procedure Code (derived)
                "Procedure Code": self.associated_procedure_code or "",

                # Preferences
                "Suggested Providers": self.suggested_providers or "",
                "Special Requirements": self.special_requirements or "",

                # Adjuster Information
                "Adjuster Name": self.adjuster_name or "",
                "Adjuster Email": self.adjuster_email or "",
                "Adjuster Phone": self.adjuster_phone or "",

                # Status
                "Status": self.status,
            }
        }


# ============================================================================
# FIELD TRANSFORMATION & NORMALIZATION
# ============================================================================

class FieldTransformer:
    """Transform extracted data to FileMaker field requirements."""

    # State code mapping
    STATE_MAPPING = {
        "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
        "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
        "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
        "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
        "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
        "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
        "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
        "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
        "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
        "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
        "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
        "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
        "wisconsin": "WI", "wyoming": "WY", "dc": "DC", "district of columbia": "DC",
    }

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """
        Normalize phone to FileMaker format: (XXX) XXX-XXXX
        """
        if not phone:
            return ""

        # Extract digits only
        digits = re.sub(r'\D', '', phone)

        # Handle 10-digit (US standard)
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

        # Handle 11-digit (with leading 1)
        elif len(digits) == 11 and digits[0] == '1':
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

        # Return original if can't normalize
        return phone

    @staticmethod
    def normalize_state(state: str) -> str:
        """
        Convert state name to 2-letter code.
        "California" -> "CA"
        """
        if not state:
            return ""

        # Already 2 letters?
        if len(state) == 2:
            return state.upper()

        # Look up full name
        state_lower = state.lower().strip()
        return FieldTransformer.STATE_MAPPING.get(state_lower, state.upper()[:2])

    @staticmethod
    def normalize_zip(zip_code: str) -> str:
        """
        Validate and normalize ZIP code.
        Must be 5 or 9 digits.
        """
        if not zip_code:
            return ""

        # Extract digits only
        digits = re.sub(r'\D', '', str(zip_code))

        # Validate length
        if len(digits) in [5, 9]:
            return digits

        # If we got extra digits, try first 5
        if len(digits) > 5:
            return digits[:5]

        # Too short - return as is (FileMaker validation will catch it)
        return zip_code

    @staticmethod
    def normalize_date(date_str: str) -> str:
        """
        Convert various date formats to FileMaker format: YYYY-MM-DD

        Handles:
        - 1/15/2025 -> 2025-01-15
        - January 15, 2025 -> 2025-01-15
        - 01-15-2025 -> 2025-01-15
        - 2025-01-15 -> 2025-01-15
        """
        if not date_str:
            return ""

        # Already normalized?
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str

        # Common formats to try
        formats = [
            "%m/%d/%Y",      # 1/15/2025
            "%m/%d/%y",      # 1/15/25
            "%m-%d-%Y",      # 1-15-2025
            "%B %d, %Y",     # January 15, 2025
            "%b %d, %Y",     # Jan 15, 2025
            "%Y-%m-%d",      # 2025-01-15
            "%d %B %Y",      # 15 January 2025
            "%d %b %Y",      # 15 Jan 2025
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return date_str

    @staticmethod
    def split_full_name(full_name: str) -> tuple:
        """
        Split full name into first and last.

        "John Q Smith" -> ("John Q", "Smith")
        "John Smith" -> ("John", "Smith")
        """
        if not full_name:
            return "", ""

        parts = full_name.strip().split()

        if len(parts) == 1:
            # Only one name given - use as last name
            return "", parts[0]
        elif len(parts) == 2:
            # Simple case
            return parts[0], parts[1]
        else:
            # Multiple parts - assume first is first name, rest is last name
            return parts[0], " ".join(parts[1:])

    @staticmethod
    def parse_address(address_str: str) -> Dict[str, str]:
        """
        Parse full address into components.

        Input: "123 Main St, Springfield, IL 62701"
        Output: {
            "address_1": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701"
        }
        """
        if not address_str:
            return {}

        result = {}

        # Simple parse: split by comma
        parts = [p.strip() for p in address_str.split(",")]

        if len(parts) >= 1:
            result["address_1"] = parts[0]

        if len(parts) >= 2:
            # City is typically second part
            result["city"] = parts[1]

        if len(parts) >= 3:
            # State and ZIP typically in last part: "IL 62701"
            last_part = parts[2]
            # Try to extract state and ZIP
            match = re.search(r'(\w{2})\s+(\d{5}(?:-\d{4})?)', last_part)
            if match:
                result["state"] = match.group(1)
                result["zip"] = match.group(2)
            else:
                result["state"] = last_part

        return result


# ============================================================================
# EXTRACTION TO FILEMAKER CONVERSION
# ============================================================================

class ExtractionToFileMakerConverter:
    """Convert extraction result to FileMaker intake form."""

    def __init__(self):
        self.transformer = FieldTransformer()

    def convert(self, extraction: Dict[str, Any]) -> FileMakerExtraction:
        """
        Convert extraction result to FileMaker fields.

        Args:
            extraction: Dict from LLM extraction (the to_dict() output)

        Returns:
            FileMakerExtraction with all fields populated
        """

        fm = FileMakerExtraction()

        # ---- CRITICAL FIELDS ----

        # Claimant First Name
        first_name = self._get_value(extraction, "claimant_first_name")
        if first_name:
            fm.intake_client_first_name = first_name
            fm.patient_first_name = first_name
            fm.confidence_scores["first_name"] = self._get_confidence(extraction, "claimant_first_name")
        elif self._get_value(extraction, "claimant_name"):
            # Fall back to splitting full name
            full_name = self._get_value(extraction, "claimant_name")
            first, last = self.transformer.split_full_name(full_name)
            fm.intake_client_first_name = first
            fm.patient_first_name = first
            fm.confidence_scores["first_name"] = self._get_confidence(extraction, "claimant_name") - 5

        # Claimant Last Name
        last_name = self._get_value(extraction, "claimant_last_name")
        if last_name:
            fm.intake_client_last_name = last_name
            fm.patient_last_name = last_name
            fm.confidence_scores["last_name"] = self._get_confidence(extraction, "claimant_last_name")
        elif self._get_value(extraction, "claimant_name"):
            full_name = self._get_value(extraction, "claimant_name")
            first, last = self.transformer.split_full_name(full_name)
            fm.intake_client_last_name = last
            fm.patient_last_name = last
            fm.confidence_scores["last_name"] = self._get_confidence(extraction, "claimant_name") - 5

        # Claim Number
        claim_num = self._get_value(extraction, "claim_number")
        if claim_num:
            fm.intake_claim_number = claim_num
            fm.confidence_scores["claim_number"] = self._get_confidence(extraction, "claim_number")

        # Carrier/Company
        carrier = self._get_value(extraction, "insurance_carrier")
        if carrier:
            fm.intake_client_company = carrier
            fm.confidence_scores["carrier"] = self._get_confidence(extraction, "insurance_carrier")

        # Service Type -> Instructions
        service = self._get_value(extraction, "service_requested")
        if service:
            fm.intake_instructions = service
            fm.confidence_scores["service"] = self._get_confidence(extraction, "service_requested")

        # Body Parts -> Injury Description
        body_parts = self._get_value(extraction, "body_parts")
        if body_parts:
            fm.injury_description = body_parts
            fm.confidence_scores["body_parts"] = self._get_confidence(extraction, "body_parts")

        # ---- DATES ----

        # Date of Birth
        dob = self._get_value(extraction, "claimant_dob")
        if dob:
            fm.intake_dob = self.transformer.normalize_date(dob)
            fm.confidence_scores["dob"] = self._get_confidence(extraction, "claimant_dob")

        # Date of Injury
        doi = self._get_value(extraction, "date_of_injury")
        if doi:
            fm.intake_doi = self.transformer.normalize_date(doi)
            fm.confidence_scores["doi"] = self._get_confidence(extraction, "date_of_injury")

        # ---- CONTACT INFORMATION ----

        # Phone (normalize)
        phone = self._get_value(extraction, "claimant_phone")
        if phone:
            fm.intake_client_phone = self.transformer.normalize_phone(phone)
            fm.patient_phone = fm.intake_client_phone
            fm.confidence_scores["phone"] = self._get_confidence(extraction, "claimant_phone")

        # Email
        email = self._get_value(extraction, "claimant_email")
        if email:
            fm.intake_client_email = email
            fm.patient_email = email
            fm.confidence_scores["email"] = self._get_confidence(extraction, "claimant_email")

        # ---- ADDRESS ----

        # Use individual components if available
        addr1 = self._get_value(extraction, "claimant_address_1")
        if addr1:
            fm.patient_address_1 = addr1
            fm.confidence_scores["address_1"] = self._get_confidence(extraction, "claimant_address_1")

        addr2 = self._get_value(extraction, "claimant_address_2")
        if addr2:
            fm.patient_address_2 = addr2

        city = self._get_value(extraction, "claimant_city")
        if city:
            fm.patient_address_city = city
            fm.confidence_scores["city"] = self._get_confidence(extraction, "claimant_city")

        state = self._get_value(extraction, "claimant_state")
        if state:
            fm.patient_address_state = self.transformer.normalize_state(state)
            fm.confidence_scores["state"] = self._get_confidence(extraction, "claimant_state")

        zip_code = self._get_value(extraction, "claimant_zip")
        if zip_code:
            fm.patient_address_zip = self.transformer.normalize_zip(zip_code)
            fm.confidence_scores["zip"] = self._get_confidence(extraction, "claimant_zip")

        # Fall back to parsing full address if components not available
        full_address = self._get_value(extraction, "claimant_address")
        if full_address and not fm.patient_address_1:
            parsed = self.transformer.parse_address(full_address)
            if parsed.get("address_1") and not fm.patient_address_1:
                fm.patient_address_1 = parsed["address_1"]
            if parsed.get("city") and not fm.patient_address_city:
                fm.patient_address_city = parsed["city"]
            if parsed.get("state") and not fm.patient_address_state:
                fm.patient_address_state = self.transformer.normalize_state(parsed["state"])
            if parsed.get("zip") and not fm.patient_address_zip:
                fm.patient_address_zip = self.transformer.normalize_zip(parsed["zip"])

        # ---- EMPLOYER ----

        employer = self._get_value(extraction, "employer_name")
        if employer:
            fm.patient_employer = employer

        employer_addr = self._get_value(extraction, "employer_address")
        if employer_addr:
            parsed = self.transformer.parse_address(employer_addr)
            fm.employer_address_1 = parsed.get("address_1", "")
            fm.employer_address_city = parsed.get("city", "")
            if parsed.get("state"):
                fm.employer_address_state = self.transformer.normalize_state(parsed["state"])
            if parsed.get("zip"):
                fm.employer_address_zip = self.transformer.normalize_zip(parsed["zip"])

        # ---- NEW PATIENT FIELDS ----

        gender = self._get_value(extraction, "claimant_gender")
        if gender:
            fm.patient_gender = gender
            fm.confidence_scores["gender"] = self._get_confidence(extraction, "claimant_gender")

        ssn = self._get_value(extraction, "claimant_ssn")
        if ssn:
            fm.patient_ssn = ssn
            fm.confidence_scores["ssn"] = self._get_confidence(extraction, "claimant_ssn")

        job_title = self._get_value(extraction, "claimant_job_title")
        if job_title:
            fm.patient_job_title = job_title
            fm.confidence_scores["job_title"] = self._get_confidence(extraction, "claimant_job_title")

        # ---- REFERRING PHYSICIAN ----

        ref_physician_name = self._get_value(extraction, "referring_physician_name")
        if ref_physician_name:
            fm.referring_physician_name = ref_physician_name
            fm.confidence_scores["referring_physician_name"] = self._get_confidence(extraction, "referring_physician_name")

        ref_physician_npi = self._get_value(extraction, "referring_physician_npi")
        if ref_physician_npi:
            # Normalize NPI (remove any formatting, ensure 10 digits)
            npi_digits = ''.join(filter(str.isdigit, ref_physician_npi))
            if len(npi_digits) == 10:
                fm.referring_physician_npi = npi_digits
                fm.confidence_scores["referring_physician_npi"] = self._get_confidence(extraction, "referring_physician_npi")

        # ---- CLAIM/JURISDICTION ----

        jurisdiction = self._get_value(extraction, "jurisdiction_state")
        if jurisdiction:
            fm.jurisdiction_state = self.transformer.normalize_state(jurisdiction)
            fm.confidence_scores["jurisdiction_state"] = self._get_confidence(extraction, "jurisdiction_state")

        order_type = self._get_value(extraction, "order_type")
        if order_type:
            fm.order_type = order_type
            fm.confidence_scores["order_type"] = self._get_confidence(extraction, "order_type")

        # ---- ICD-10 / DIAGNOSIS ----

        icd10_code = self._get_value(extraction, "icd10_code")
        if icd10_code:
            fm.icd10_code = icd10_code.upper().strip()
            fm.confidence_scores["icd10_code"] = self._get_confidence(extraction, "icd10_code")

        icd10_desc = self._get_value(extraction, "icd10_description")
        if icd10_desc:
            fm.icd10_description = icd10_desc
            fm.confidence_scores["icd10_description"] = self._get_confidence(extraction, "icd10_description")

        # Derived ICD-10 category (from Step 2 reasoning)
        icd10_category = self._get_value(extraction, "icd10_category")
        if icd10_category:
            fm.icd10_category = icd10_category

        # ---- PROCEDURE CODE (derived from Step 2) ----

        procedure_code = self._get_value(extraction, "associated_procedure_code")
        if procedure_code:
            fm.associated_procedure_code = procedure_code

        # ---- PREFERENCES/SPECIAL INSTRUCTIONS ----

        suggested_providers = self._get_value(extraction, "suggested_providers")
        if suggested_providers:
            fm.suggested_providers = suggested_providers
            fm.confidence_scores["suggested_providers"] = self._get_confidence(extraction, "suggested_providers")

        special_requirements = self._get_value(extraction, "special_requirements")
        if special_requirements:
            fm.special_requirements = special_requirements
            fm.confidence_scores["special_requirements"] = self._get_confidence(extraction, "special_requirements")

        # ---- METADATA ----

        fm.adjuster_name = self._get_value(extraction, "adjuster_name")
        fm.adjuster_email = self._get_value(extraction, "adjuster_email")
        fm.adjuster_phone = self._get_value(extraction, "adjuster_phone")
        fm.extraction_timestamp = datetime.utcnow().isoformat()

        # Calculate overall confidence
        if fm.confidence_scores:
            fm.extraction_confidence = sum(fm.confidence_scores.values()) / len(fm.confidence_scores)

        return fm

    def _get_value(self, extraction: Dict, field: str) -> Optional[str]:
        """Get value from extraction data."""
        if field in extraction and extraction[field]:
            return extraction[field].get("value")
        return None

    def _get_confidence(self, extraction: Dict, field: str) -> int:
        """Get confidence from extraction data."""
        if field in extraction and extraction[field]:
            return extraction[field].get("confidence", 0)
        return 0


# ============================================================================
# VALIDATION
# ============================================================================

class FileMakerPayloadValidator:
    """Validate payload before submission to FileMaker."""

    @staticmethod
    def validate(fm_extraction: FileMakerExtraction) -> List[str]:
        """
        Validate extraction against FileMaker field constraints.

        Returns:
            List of validation errors (empty if valid)
        """

        errors = []

        # Required fields
        if not fm_extraction.intake_client_first_name:
            errors.append("Missing: Intake Client First Name")
        if not fm_extraction.intake_client_last_name:
            errors.append("Missing: Intake Client Last Name")
        if not fm_extraction.intake_claim_number:
            errors.append("Missing: Intake Claim Number")
        if not fm_extraction.status:
            errors.append("Missing: Status")

        # Field format validation

        # Phone format
        if fm_extraction.intake_client_phone:
            if not re.match(r'^\(\d{3}\) \d{3}-\d{4}$', fm_extraction.intake_client_phone):
                errors.append(f"Invalid phone format: {fm_extraction.intake_client_phone}")

        # State code (must be 2 letters)
        if fm_extraction.patient_address_state:
            if len(fm_extraction.patient_address_state) != 2:
                errors.append(f"Invalid state code: {fm_extraction.patient_address_state}")

        # ZIP code (5 or 9 digits)
        if fm_extraction.patient_address_zip:
            zip_digits = re.sub(r'\D', '', fm_extraction.patient_address_zip)
            if len(zip_digits) not in [5, 9]:
                errors.append(f"Invalid ZIP: {fm_extraction.patient_address_zip}")

        # Email format
        if fm_extraction.intake_client_email:
            if not re.match(r'^[\w\.\-\+]+@[\w\.-]+\.\w+$', fm_extraction.intake_client_email):
                errors.append(f"Invalid email: {fm_extraction.intake_client_email}")

        # Date format (YYYY-MM-DD)
        if fm_extraction.intake_dob:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', fm_extraction.intake_dob):
                errors.append(f"Invalid DOB format: {fm_extraction.intake_dob} (must be YYYY-MM-DD)")

        if fm_extraction.intake_doi:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', fm_extraction.intake_doi):
                errors.append(f"Invalid DOI format: {fm_extraction.intake_doi} (must be YYYY-MM-DD)")

        return errors

    @staticmethod
    def get_missing_critical_fields(fm_extraction: FileMakerExtraction) -> List[str]:
        """Get list of missing critical fields."""
        missing = []
        if not fm_extraction.intake_client_first_name:
            missing.append("First Name")
        if not fm_extraction.intake_client_last_name:
            missing.append("Last Name")
        if not fm_extraction.intake_claim_number:
            missing.append("Claim Number")
        if not fm_extraction.intake_client_company:
            missing.append("Insurance Carrier")
        if not fm_extraction.intake_instructions:
            missing.append("Service Requested")
        return missing

    @staticmethod
    def get_completeness_score(fm_extraction: FileMakerExtraction) -> float:
        """
        Calculate how complete the extraction is (0-100).
        Based on presence of all expected fields.
        """
        fields = [
            fm_extraction.intake_client_first_name,
            fm_extraction.intake_client_last_name,
            fm_extraction.intake_claim_number,
            fm_extraction.intake_client_company,
            fm_extraction.intake_instructions,
            fm_extraction.intake_dob,
            fm_extraction.intake_doi,
            fm_extraction.injury_description,
            fm_extraction.intake_client_phone,
            fm_extraction.intake_client_email,
            fm_extraction.patient_address_1,
            fm_extraction.patient_address_city,
            fm_extraction.patient_address_state,
            fm_extraction.patient_address_zip,
            fm_extraction.patient_employer,
        ]
        filled = sum(1 for f in fields if f)
        return (filled / len(fields)) * 100


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def should_auto_submit(fm_extraction: FileMakerExtraction, threshold: int = 85) -> bool:
    """
    Determine if extraction is high-confidence enough for auto-submission.

    Args:
        fm_extraction: The FileMaker extraction to evaluate
        threshold: Minimum confidence percentage (default 85)

    Returns:
        True if extraction meets auto-submit criteria
    """
    validator = FileMakerPayloadValidator()
    errors = validator.validate(fm_extraction)

    if errors:
        return False

    if fm_extraction.extraction_confidence < threshold:
        return False

    # Check critical fields have high confidence
    critical_fields = ["first_name", "last_name", "claim_number", "carrier"]
    for field in critical_fields:
        if fm_extraction.confidence_scores.get(field, 0) < 70:
            return False

    return True


def get_review_status(fm_extraction: FileMakerExtraction) -> str:
    """
    Determine review status based on extraction quality.

    Returns:
        "auto_submit" - High confidence, ready for FileMaker
        "human_review" - Needs human verification
        "manual_entry" - Too low confidence, needs manual input
    """
    validator = FileMakerPayloadValidator()
    errors = validator.validate(fm_extraction)
    missing_critical = validator.get_missing_critical_fields(fm_extraction)

    if missing_critical:
        return "manual_entry"

    if errors:
        return "human_review"

    if fm_extraction.extraction_confidence >= 90:
        return "auto_submit"
    elif fm_extraction.extraction_confidence >= 70:
        return "human_review"
    else:
        return "manual_entry"
