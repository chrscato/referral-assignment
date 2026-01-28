"""
FileMaker Intake Form Field Extraction & Submission
====================================================

Extract referral data and populate FileMaker intake form fields.
Handles transformation, validation, and submission to FileMaker Data API.
"""

import re
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
import httpx
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS FOR FILEMAKER FIELDS
# ============================================================================

@dataclass
class FileMAkerExtraction:
    """
    Extraction result mapped to exact FileMaker field names.
    These correspond directly to your intake form.
    """
    
    # IDENTIFIERS (auto-populated by FileMaker, don't set)
    # id_intake: str  # Auto-generated
    # primary_key: str  # Auto-generated
    # created_by: str  # Auto-populated
    # creation_timestamp: str  # Auto-populated
    
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
    
    # EMPLOYER INFORMATION
    employer_address_1: Optional[str] = None
    employer_address_2: Optional[str] = None
    employer_address_city: Optional[str] = None
    employer_address_state: Optional[str] = None
    employer_address_zip: Optional[str] = None
    employer_email: Optional[str] = None
    
    # STATUS
    status: str = "Pending"  # Default new intake status
    
    # METADATA (audit trail)
    source_email_id: Optional[str] = None
    adjuster_name: Optional[str] = None
    adjuster_email: Optional[str] = None
    extraction_confidence: float = 0.0
    extraction_timestamp: Optional[str] = None
    
    # CONFIDENCE SCORES (for review)
    confidence_scores: Dict[str, int] = None
    validation_flags: List[Dict] = None
    extraction_warnings: List[str] = None
    
    def __post_init__(self):
        if self.confidence_scores is None:
            self.confidence_scores = {}
        if self.validation_flags is None:
            self.validation_flags = []
        if self.extraction_warnings is None:
            self.extraction_warnings = []


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
        "California" → "CA"
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
        - 1/15/2025 → 2025-01-15
        - January 15, 2025 → 2025-01-15
        - 01-15-2025 → 2025-01-15
        - 2025-01-15 → 2025-01-15
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
    def split_full_name(full_name: str) -> tuple[str, str]:
        """
        Split full name into first and last.
        
        "John Q Smith" → ("John Q", "Smith")
        "John Smith" → ("John", "Smith")
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
            # "John Q Smith" → first: "John", last: "Q Smith"
            # Or could do: first: "John Q", last: "Smith" (split on last space)
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

class ExtractionToFileMAkerConverter:
    """Convert extraction result to FileMaker intake form."""
    
    def __init__(self):
        self.transformer = FieldTransformer()
    
    def convert(self, extraction: Dict[str, Any]) -> FileMAkerExtraction:
        """
        Convert extraction result to FileMaker fields.
        
        Args:
            extraction: Dict from Stage 3 LLM extraction
        
        Returns:
            FileMAkerExtraction with all fields populated
        """
        
        fm = FileMAkerExtraction()
        
        # ---- CRITICAL FIELDS ----
        
        # Claimant Name (split into first/last)
        claimant_name = extraction.get("claimant_name", {}).get("value")
        if claimant_name:
            first, last = self.transformer.split_full_name(claimant_name)
            fm.intake_client_first_name = first
            fm.intake_client_last_name = last
            fm.patient_first_name = first
            fm.patient_last_name = last
            fm.confidence_scores["claimant_name"] = extraction.get("claimant_name", {}).get("confidence", 0)
        
        # Claim Number
        claim_num = extraction.get("claim_number", {}).get("value")
        if claim_num:
            fm.intake_claim_number = claim_num
            fm.confidence_scores["claim_number"] = extraction.get("claim_number", {}).get("confidence", 0)
        
        # Carrier/Company
        carrier = extraction.get("carrier", {}).get("value") or extraction.get("insurance_carrier", {}).get("value")
        if carrier:
            fm.intake_client_company = carrier
            fm.confidence_scores["carrier"] = extraction.get("carrier", {}).get("confidence", 0)
        
        # Service Type → Instructions
        service = extraction.get("service_requested", {}).get("value")
        if service:
            fm.intake_instructions = service
            fm.confidence_scores["service"] = extraction.get("service_requested", {}).get("confidence", 0)
        
        # Body Parts → Injury Description
        body_parts = extraction.get("body_parts", {}).get("value")
        if body_parts:
            fm.injury_description = body_parts
            fm.confidence_scores["body_parts"] = extraction.get("body_parts", {}).get("confidence", 0)
        
        # ---- DATES ----
        
        # Date of Birth
        dob = extraction.get("claimant_dob", {}).get("value")
        if dob:
            fm.intake_dob = self.transformer.normalize_date(dob)
            fm.confidence_scores["dob"] = extraction.get("claimant_dob", {}).get("confidence", 0)
        
        # Date of Injury
        doi = extraction.get("date_of_injury", {}).get("value")
        if doi:
            fm.intake_doi = self.transformer.normalize_date(doi)
            fm.confidence_scores["doi"] = extraction.get("date_of_injury", {}).get("confidence", 0)
        
        # ---- CONTACT INFORMATION ----
        
        # Phone (normalize)
        phone = extraction.get("claimant_phone", {}).get("value")
        if phone:
            fm.intake_client_phone = self.transformer.normalize_phone(phone)
            fm.patient_phone = fm.intake_client_phone
            fm.confidence_scores["phone"] = extraction.get("claimant_phone", {}).get("confidence", 0)
        
        # Email
        email = extraction.get("claimant_email", {}).get("value")
        if email:
            fm.intake_client_email = email
            fm.patient_email = email
            fm.confidence_scores["email"] = extraction.get("claimant_email", {}).get("confidence", 0)
        
        # ---- ADDRESS ----
        
        # Parse address if available
        address = extraction.get("claimant_address", {}).get("value")
        if address:
            parsed = self.transformer.parse_address(address)
            fm.patient_address_1 = parsed.get("address_1")
            fm.patient_address_2 = parsed.get("address_2", "")
            fm.patient_address_city = parsed.get("city")
            if parsed.get("state"):
                fm.patient_address_state = self.transformer.normalize_state(parsed["state"])
            if parsed.get("zip"):
                fm.patient_address_zip = self.transformer.normalize_zip(parsed["zip"])
        
        # Or use individual components if available
        if extraction.get("claimant_address_1", {}).get("value"):
            fm.patient_address_1 = extraction["claimant_address_1"]["value"]
        if extraction.get("claimant_address_2", {}).get("value"):
            fm.patient_address_2 = extraction["claimant_address_2"]["value"]
        if extraction.get("claimant_city", {}).get("value"):
            fm.patient_address_city = extraction["claimant_city"]["value"]
        if extraction.get("claimant_state", {}).get("value"):
            fm.patient_address_state = self.transformer.normalize_state(
                extraction["claimant_state"]["value"]
            )
        if extraction.get("claimant_zip", {}).get("value"):
            fm.patient_address_zip = self.transformer.normalize_zip(
                extraction["claimant_zip"]["value"]
            )
        
        # ---- EMPLOYER ----
        
        employer = extraction.get("employer_name", {}).get("value")
        if employer:
            fm.patient_employer = employer
        
        employer_addr = extraction.get("employer_address", {}).get("value")
        if employer_addr:
            parsed = self.transformer.parse_address(employer_addr)
            fm.employer_address_1 = parsed.get("address_1", "")
            fm.employer_address_city = parsed.get("city", "")
            if parsed.get("state"):
                fm.employer_address_state = self.transformer.normalize_state(parsed["state"])
            if parsed.get("zip"):
                fm.employer_address_zip = self.transformer.normalize_zip(parsed["zip"])
        
        # ---- METADATA ----
        
        fm.adjuster_name = extraction.get("adjuster_name", {}).get("value")
        fm.adjuster_email = extraction.get("adjuster_email", {}).get("value")
        fm.extraction_timestamp = datetime.utcnow().isoformat()
        
        # Calculate overall confidence
        if fm.confidence_scores:
            fm.extraction_confidence = sum(fm.confidence_scores.values()) / len(fm.confidence_scores)
        
        return fm


# ============================================================================
# FILEMAKER API SUBMISSION
# ============================================================================

class FileMAkerIntakeSubmission:
    """Submit extracted referrals to FileMaker Data API."""
    
    def __init__(
        self,
        fm_server: str,
        fm_database: str,
        fm_layout: str,
        fm_username: str,
        fm_password: str
    ):
        self.fm_server = fm_server
        self.fm_database = fm_database
        self.fm_layout = fm_layout
        self.fm_username = fm_username
        self.fm_password = fm_password
        self.token = None
        self.token_expires = None
    
    def _authenticate(self) -> str:
        """Get FileMaker API authentication token."""
        
        url = f"{self.fm_server}/fmi/data/v1/databases/{self.fm_database}/sessions"
        
        auth = httpx.BasicAuth(self.fm_username, self.fm_password)
        
        response = httpx.post(url, auth=auth, timeout=10.0)
        response.raise_for_status()
        
        data = response.json()
        token = data["response"]["token"]
        
        logger.info(f"FileMaker authentication successful. Token: {token[:20]}...")
        
        return token
    
    def _get_token(self) -> str:
        """Get valid token, refreshing if needed."""
        
        # Check if we need a new token
        if not self.token or (self.token_expires and datetime.now() > self.token_expires):
            self.token = self._authenticate()
            # Tokens expire in 15 minutes, refresh after 10
            self.token_expires = datetime.now() + pd.Timedelta(minutes=10)
        
        return self.token
    
    def submit_intake(self, fm_extraction: FileMAkerExtraction) -> Dict[str, Any]:
        """
        Submit a single intake to FileMaker.
        """
        
        token = self._get_token()
        
        # Build payload - map to exact FileMaker field names
        payload = {
            "fieldData": {
                "Intake Client First Name": fm_extraction.intake_client_first_name or "",
                "Intake Client Last Name": fm_extraction.intake_client_last_name or "",
                "Intake Claim Number": fm_extraction.intake_claim_number or "",
                "Intake Client Company": fm_extraction.intake_client_company or "",
                "Intake DOB": fm_extraction.intake_dob or "",
                "Intake DOI": fm_extraction.intake_doi or "",
                "Intake Client Phone": fm_extraction.intake_client_phone or "",
                "Intake Client Email": fm_extraction.intake_client_email or "",
                "Intake Instructions": fm_extraction.intake_instructions or "",
                "Injury Description": fm_extraction.injury_description or "",
                
                "Patient First Name": fm_extraction.patient_first_name or "",
                "Patient Last Name": fm_extraction.patient_last_name or "",
                "Patient Phone": fm_extraction.patient_phone or "",
                "Patient Email": fm_extraction.patient_email or "",
                "Patient Employer": fm_extraction.patient_employer or "",
                "Patient Address 1": fm_extraction.patient_address_1 or "",
                "Patient Address 2": fm_extraction.patient_address_2 or "",
                "Patient Address City": fm_extraction.patient_address_city or "",
                "Patient Address State": fm_extraction.patient_address_state or "",
                "Patient Address ZIP": fm_extraction.patient_address_zip or "",
                
                "Employer Address 1": fm_extraction.employer_address_1 or "",
                "Employer Address 2": fm_extraction.employer_address_2 or "",
                "Employer Address City": fm_extraction.employer_address_city or "",
                "Employer Address State": fm_extraction.employer_address_state or "",
                "Employer Address ZIP": fm_extraction.employer_address_zip or "",
                "Employer Email": fm_extraction.employer_email or "",
                
                "Status": fm_extraction.status,
            }
        }
        
        url = f"{self.fm_server}/fmi/data/v1/databases/{self.fm_database}/layouts/{self.fm_layout}/records"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()
            
            result = response.json()
            record_id = result["response"]["recordId"]
            
            logger.info(f"✓ FileMaker record created: {record_id}")
            
            return {
                "status": "success",
                "filemaker_record_id": record_id,
                "filemaker_mod_id": result["response"]["modId"],
            }
        
        except httpx.HTTPError as e:
            logger.error(f"✗ FileMaker submission failed: {e}")
            return {
                "status": "error",
                "error": str(e),
            }
    
    def batch_submit(
        self,
        fm_extractions: List[FileMAkerExtraction],
        max_batch: int = 50
    ) -> List[Dict[str, Any]]:
        """Submit multiple intakes to FileMaker."""
        
        results = []
        
        for i, fm_extraction in enumerate(fm_extractions, 1):
            logger.info(f"Submitting intake {i}/{len(fm_extractions)}...")
            
            result = self.submit_intake(fm_extraction)
            results.append({
                "extraction_index": i,
                "result": result,
            })
            
            # Rate limiting
            if i % max_batch == 0:
                logger.info(f"Pausing after {max_batch} submissions...")
                time.sleep(1)
        
        # Summary
        successful = sum(1 for r in results if r["result"]["status"] == "success")
        failed = len(results) - successful
        logger.info(f"Submission complete: {successful} success, {failed} failed")
        
        return results


# ============================================================================
# VALIDATION
# ============================================================================

class FileMAkerPayloadValidator:
    """Validate payload before submission to FileMaker."""
    
    @staticmethod
    def validate(fm_extraction: FileMAkerExtraction) -> List[str]:
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
            if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', fm_extraction.intake_client_email):
                errors.append(f"Invalid email: {fm_extraction.intake_client_email}")
        
        # Date format (YYYY-MM-DD)
        if fm_extraction.intake_dob:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', fm_extraction.intake_dob):
                errors.append(f"Invalid DOB format: {fm_extraction.intake_dob} (must be YYYY-MM-DD)")
        
        if fm_extraction.intake_doi:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', fm_extraction.intake_doi):
                errors.append(f"Invalid DOI format: {fm_extraction.intake_doi} (must be YYYY-MM-DD)")
        
        return errors


# ============================================================================
# DEMO/TESTING
# ============================================================================

def demo_conversion():
    """Demo extracting and converting to FileMaker fields."""
    
    print("\n" + "="*70)
    print("FILEMAKER INTAKE FIELD CONVERSION DEMO")
    print("="*70 + "\n")
    
    # Sample extraction from LLM
    sample_extraction = {
        "claimant_name": {
            "value": "John Q Smith",
            "confidence": 95,
            "source": "Email body"
        },
        "claim_number": {
            "value": "WC-2025-001234",
            "confidence": 98,
            "source": "Email header"
        },
        "carrier": {
            "value": "ACE Insurance",
            "confidence": 90,
            "source": "Email signature"
        },
        "service_requested": {
            "value": "PT Evaluation",
            "confidence": 85,
            "source": "Email body"
        },
        "body_parts": {
            "value": "Right shoulder",
            "confidence": 88,
            "source": "Email body"
        },
        "claimant_dob": {
            "value": "1985-03-15",
            "confidence": 75,
            "source": "Email body"
        },
        "date_of_injury": {
            "value": "01/15/2025",
            "confidence": 92,
            "source": "Email body"
        },
        "claimant_phone": {
            "value": "555-123-4567",
            "confidence": 80,
            "source": "Email body"
        },
        "claimant_email": {
            "value": "john.smith@example.com",
            "confidence": 85,
            "source": "Email body"
        },
        "claimant_address": {
            "value": "123 Main Street, Springfield, IL 62701",
            "confidence": 70,
            "source": "Email body"
        },
    }
    
    # Convert to FileMaker
    converter = ExtractionToFileMAkerConverter()
    fm_extraction = converter.convert(sample_extraction)
    
    print("CONVERTED TO FILEMAKER FIELDS:")
    print("-" * 70)
    print(f"Intake Client First Name: {fm_extraction.intake_client_first_name}")
    print(f"Intake Client Last Name: {fm_extraction.intake_client_last_name}")
    print(f"Intake Claim Number: {fm_extraction.intake_claim_number}")
    print(f"Intake Client Company: {fm_extraction.intake_client_company}")
    print(f"Intake DOB: {fm_extraction.intake_dob}")
    print(f"Intake DOI: {fm_extraction.intake_doi}")
    print(f"Intake Client Phone: {fm_extraction.intake_client_phone}")
    print(f"Intake Client Email: {fm_extraction.intake_client_email}")
    print(f"Injury Description: {fm_extraction.injury_description}")
    print(f"Intake Instructions: {fm_extraction.intake_instructions}")
    
    print()
    print("PATIENT ADDRESS:")
    print(f"  Address 1: {fm_extraction.patient_address_1}")
    print(f"  City: {fm_extraction.patient_address_city}")
    print(f"  State: {fm_extraction.patient_address_state}")
    print(f"  ZIP: {fm_extraction.patient_address_zip}")
    
    print()
    print("VALIDATION:")
    validator = FileMAkerPayloadValidator()
    errors = validator.validate(fm_extraction)
    if errors:
        for error in errors:
            print(f"  ✗ {error}")
    else:
        print("  ✓ All validations passed!")
    
    print()
    print(f"Overall Confidence: {fm_extraction.extraction_confidence:.0f}%")
    print(f"Extraction Timestamp: {fm_extraction.extraction_timestamp}")


if __name__ == "__main__":
    demo_conversion()
