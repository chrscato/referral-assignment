"""
LLM-based extraction service for parsing referral emails.
Uses Claude API to extract structured data from unstructured text.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from referral_crm.config import get_settings

# Lazy import to avoid startup issues if anthropic not installed
anthropic = None


def get_anthropic_client():
    """Lazily initialize the Anthropic client."""
    global anthropic
    if anthropic is None:
        import anthropic as _anthropic

        anthropic = _anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class ExtractedField:
    """A field extracted from the email with confidence score."""

    value: Any
    confidence: int  # 0-100
    source: str  # "email_body", "attachment", "signature"
    raw_match: Optional[str] = None


@dataclass
class ExtractionResult:
    """Complete extraction result from an email."""

    # ==========================================================================
    # STEP 1: DIRECT EXTRACTION FIELDS
    # ==========================================================================

    # Referring Physician info
    referring_physician_name: Optional[ExtractedField] = None
    referring_physician_npi: Optional[ExtractedField] = None

    # Adjuster/Assigning Party info
    adjuster_name: Optional[ExtractedField] = None
    adjuster_email: Optional[ExtractedField] = None
    adjuster_phone: Optional[ExtractedField] = None

    # Carrier/Claim info
    insurance_carrier: Optional[ExtractedField] = None
    claim_number: Optional[ExtractedField] = None
    jurisdiction_state: Optional[ExtractedField] = None
    order_type: Optional[ExtractedField] = None

    # Claimant/Patient info - now with separate first/last name
    claimant_name: Optional[ExtractedField] = None  # Full name (legacy)
    claimant_first_name: Optional[ExtractedField] = None
    claimant_last_name: Optional[ExtractedField] = None
    claimant_dob: Optional[ExtractedField] = None
    claimant_phone: Optional[ExtractedField] = None
    claimant_email: Optional[ExtractedField] = None
    claimant_ssn: Optional[ExtractedField] = None
    claimant_gender: Optional[ExtractedField] = None

    # Claimant address - now with components
    claimant_address: Optional[ExtractedField] = None  # Full address (legacy)
    claimant_address_1: Optional[ExtractedField] = None
    claimant_address_2: Optional[ExtractedField] = None
    claimant_city: Optional[ExtractedField] = None
    claimant_state: Optional[ExtractedField] = None
    claimant_zip: Optional[ExtractedField] = None

    # Employer info
    employer_name: Optional[ExtractedField] = None
    employer_address: Optional[ExtractedField] = None
    claimant_job_title: Optional[ExtractedField] = None

    # Injury/Service info
    date_of_injury: Optional[ExtractedField] = None
    body_parts: Optional[ExtractedField] = None
    service_requested: Optional[ExtractedField] = None
    authorization_number: Optional[ExtractedField] = None

    # ICD-10 / Diagnosis info
    icd10_code: Optional[ExtractedField] = None
    icd10_description: Optional[ExtractedField] = None

    # Preferences and special instructions
    suggested_providers: Optional[ExtractedField] = None
    special_requirements: Optional[ExtractedField] = None

    # Metadata
    priority: Optional[ExtractedField] = None
    notes: Optional[ExtractedField] = None

    # ==========================================================================
    # STEP 2: REASONING/DERIVED FIELDS
    # ==========================================================================

    # Derived from reference data lookups
    associated_procedure_code: Optional[ExtractedField] = None
    validated_icd10: Optional[ExtractedField] = None
    icd10_category: Optional[ExtractedField] = None
    icd10_body_region: Optional[ExtractedField] = None

    # All extraction fields for iteration
    _ALL_FIELDS = [
        # Referring Physician
        "referring_physician_name",
        "referring_physician_npi",
        # Adjuster
        "adjuster_name",
        "adjuster_email",
        "adjuster_phone",
        # Carrier/Claim
        "insurance_carrier",
        "claim_number",
        "jurisdiction_state",
        "order_type",
        # Claimant
        "claimant_name",
        "claimant_first_name",
        "claimant_last_name",
        "claimant_dob",
        "claimant_phone",
        "claimant_email",
        "claimant_ssn",
        "claimant_gender",
        # Claimant Address
        "claimant_address",
        "claimant_address_1",
        "claimant_address_2",
        "claimant_city",
        "claimant_state",
        "claimant_zip",
        # Employer
        "employer_name",
        "employer_address",
        "claimant_job_title",
        # Injury/Service
        "date_of_injury",
        "body_parts",
        "service_requested",
        "authorization_number",
        # ICD-10
        "icd10_code",
        "icd10_description",
        # Preferences
        "suggested_providers",
        "special_requirements",
        # Metadata
        "priority",
        "notes",
        # Step 2 derived fields
        "associated_procedure_code",
        "validated_icd10",
        "icd10_category",
        "icd10_body_region",
    ]

    def to_dict(self) -> dict:
        """Convert to dictionary format for storage."""
        result = {}
        for field in self._ALL_FIELDS:
            extracted = getattr(self, field)
            if extracted:
                result[field] = {
                    "value": extracted.value,
                    "confidence": extracted.confidence,
                    "source": extracted.source,
                    "raw_match": extracted.raw_match,
                }
        return result

    def get_value(self, field: str) -> Any:
        """Get the value of a field if it exists."""
        extracted = getattr(self, field, None)
        return extracted.value if extracted else None

    def get_confidence(self, field: str) -> int:
        """Get the confidence score for a field."""
        extracted = getattr(self, field, None)
        return extracted.confidence if extracted else 0

    def get_overall_confidence(self) -> float:
        """Calculate overall extraction confidence."""
        confidences = []
        for field in self._ALL_FIELDS:
            extracted = getattr(self, field, None)
            if extracted and extracted.confidence > 0:
                confidences.append(extracted.confidence)
        return sum(confidences) / len(confidences) if confidences else 0.0


EXTRACTION_PROMPT = """You are a workers' compensation intake specialist. Your job is to extract structured data from a referral email for intake form submission.

**Source Email:**
From: {from_email}
Subject: {subject}

Body:
{email_body}

{attachment_section}

IMPORTANT: Return ONLY valid JSON with no additional text, markdown, or explanations.

================================================================================
FIELDS TO EXTRACT
================================================================================

CRITICAL FIELDS [REQUIRED]:
---------------------------
1. claimant_first_name: Patient/claimant first name
   - Where to look: Patient demographics section, labeled 'Patient', 'Claimant', or 'Injured Worker'

2. claimant_last_name: Patient/claimant last name
   - Where to look: Patient demographics section

3. claim_number: Workers' comp claim number
   - Where to look: Subject line, headers, prominently displayed
   - Patterns: WC-YYYY-XXXXXX, YYYY-XXXXXX, 6-8 digit numbers

4. insurance_carrier: Insurance company/carrier name
   - Where to look: Email domain, letterhead, signature block
   - Examples: ACE Insurance, Travelers, Liberty Mutual

5. service_requested: Type of service requested (can include multiple services)
   - Where to look: Main body, 'Services Requested', 'Order' section
   - Include details: body part, with/without contrast, etc.
   - Examples: PT Evaluation, MRI lumbar spine without contrast, CT scan right shoulder

HIGH PRIORITY FIELDS:
--------------------
6. claimant_dob: Date of birth (format as YYYY-MM-DD)
   - Where to look: Patient demographics, 'DOB', 'Date of Birth'

7. date_of_injury: Date injury occurred (format as YYYY-MM-DD)
   - Where to look: 'DOI', 'Date of Injury', 'Injury Date', claim description

8. body_parts: Injured body parts using proper anatomical terms
   - Where to look: Injury description, near ICD-10 codes
   - Use: "left shoulder" not "L shoulder", specify sides

9. claimant_phone: Phone number (normalize to (XXX) XXX-XXXX)
   - Where to look: Patient contact information section

10. icd10_code: ICD-10 diagnosis code
    - Where to look: 'ICD-10', 'Diagnosis Code', 'Dx' sections, near body parts
    - Format: Letter + digits + optional decimal (e.g., M54.5, S43.001A)

11. icd10_description: Description associated with ICD-10 code
    - Where to look: Adjacent to or following the ICD-10 code

MEDIUM PRIORITY FIELDS:
----------------------
12. claimant_email: Claimant's email address
13. claimant_address_1: Street address line 1
14. claimant_address_2: Address line 2 (apt, suite, etc.)
15. claimant_city: City
16. claimant_state: State (2-letter code only: CA, IL, NY, TX)
17. claimant_zip: ZIP code (5 or 9 digits)

18. claimant_gender: Patient gender
    - Where to look: Patient demographics, often abbreviated M/F
    - Output: "Male" or "Female"

19. claimant_ssn: Social security number
    - Where to look: Patient demographics, 'SSN', 'Social Security'
    - May be masked: XXX-XX-1234

20. jurisdiction_state: State governing the WC claim (may differ from patient address)
    - Where to look: 'Jurisdiction', 'State of injury', near claim number

21. order_type: Type of order/referral category
    - Where to look: Subject line, headers
    - Examples: Initial Evaluation, Follow-up, Expedited, Urgent

LOW PRIORITY FIELDS:
-------------------
22. employer_name: Patient's employer company name
    - Where to look: 'Employer', 'Company', injury description context

23. claimant_job_title: Patient's job title/occupation
    - Where to look: Near employer info, injury description

24. employer_address: Full employer address

25. authorization_number: Authorization/pre-approval number
    - Where to look: 'Auth #', 'Authorization', 'Pre-approval', 'UR number'

26. referring_physician_name: Referring physician who ordered the service
    - Where to look: Headers, letterhead, 'Ordered by', 'Referring physician'

27. referring_physician_npi: 10-digit NPI number for referring physician
    - Where to look: Near physician name, labeled 'NPI' or 'Provider ID'
    - Format: Exactly 10 digits (e.g., 1234567890)

28. adjuster_name: Name of person sending the referral
    - Where to look: Email signature block, 'From' header

29. adjuster_email: Adjuster's email (from "From" field)

30. adjuster_phone: Adjuster's phone number
    - Where to look: Signature block, contact info

31. suggested_providers: Any provider preferences from adjuster/patient
    - Where to look: 'Preferred provider', 'Please schedule with', patient preferences

32. special_requirements: Special notes/accommodations for the injured worker
    - Where to look: 'Special instructions', 'Notes', 'Accommodations'
    - Examples: wheelchair, interpreter needed, morning appointments only

33. priority: Urgency level (infer from language)
    - ASAP, urgent, rush = "urgent" or "high"
    - Standard/routine = "medium"

34. notes: Any other special instructions

================================================================================
CONFIDENCE SCORING (0-100)
================================================================================
- 95-100%: Field is explicitly and clearly stated
- 85-94%: Field is clearly stated or obvious from context
- 70-84%: Field is fairly clear but some ambiguity
- 50-69%: Field has significant uncertainty
- <50%: Do NOT include field (return null instead)

================================================================================
EXTRACTION RULES
================================================================================

NAMES:
- Always split into first and last name
- "John Q Smith" → first: "John", last: "Q Smith"
- "Dr. John Smith" → first: "John", last: "Smith" (remove titles)

DATES:
- Always convert to YYYY-MM-DD format
- "1/15/2025" → "2025-01-15"
- "January 15, 2025" → "2025-01-15"

PHONE:
- Normalize to (XXX) XXX-XXXX format
- "555-123-4567" → "(555) 123-4567"

STATE:
- Always use 2-letter codes: "California" → "CA"

NPI:
- Must be exactly 10 digits
- Remove any formatting: "123-456-7890" → "1234567890"

ICD-10:
- Format: Letter + 2 digits + optional decimal + more characters
- Examples: M54.5, S43.001A, M75.100

================================================================================
RESPONSE FORMAT (MUST BE VALID JSON)
================================================================================
{{
  "claimant_first_name": {{ "value": "John", "confidence": 95, "source": "email_body", "raw_match": "Patient: John Smith" }},
  "claimant_last_name": {{ "value": "Smith", "confidence": 95, "source": "email_body", "raw_match": "Patient: John Smith" }},
  "claim_number": {{ "value": "WC-2025-001234", "confidence": 98, "source": "email_body", "raw_match": "Claim #: WC-2025-001234" }},
  "insurance_carrier": {{ "value": "ACE Insurance", "confidence": 90, "source": "signature", "raw_match": "ACE Insurance Company" }},
  "service_requested": {{ "value": "MRI lumbar spine without contrast", "confidence": 85, "source": "email_body", "raw_match": "requesting MRI lumbar spine w/o contrast" }},
  "claimant_dob": {{ "value": "1985-03-15", "confidence": 80, "source": "email_body", "raw_match": "DOB: 3/15/85" }},
  "date_of_injury": {{ "value": "2025-01-10", "confidence": 90, "source": "email_body", "raw_match": "DOI: January 10, 2025" }},
  "body_parts": {{ "value": "lower back", "confidence": 85, "source": "email_body", "raw_match": "lumbar spine injury" }},
  "icd10_code": {{ "value": "M54.5", "confidence": 92, "source": "email_body", "raw_match": "ICD-10: M54.5" }},
  "icd10_description": {{ "value": "Low back pain", "confidence": 88, "source": "email_body", "raw_match": "Low back pain" }},
  "claimant_phone": {{ "value": "(555) 123-4567", "confidence": 75, "source": "email_body", "raw_match": "555-123-4567" }},
  "claimant_email": {{ "value": "john.smith@example.com", "confidence": 80, "source": "email_body", "raw_match": "Email: john.smith@example.com" }},
  "claimant_gender": {{ "value": "Male", "confidence": 85, "source": "email_body", "raw_match": "Gender: M" }},
  "claimant_ssn": {{ "value": "XXX-XX-6789", "confidence": 70, "source": "email_body", "raw_match": "SSN: ***-**-6789" }},
  "claimant_address_1": {{ "value": "123 Main Street", "confidence": 70, "source": "email_body", "raw_match": "123 Main Street" }},
  "claimant_address_2": {{ "value": null, "confidence": 0, "source": "", "raw_match": "" }},
  "claimant_city": {{ "value": "Springfield", "confidence": 75, "source": "email_body", "raw_match": "Springfield, IL" }},
  "claimant_state": {{ "value": "IL", "confidence": 80, "source": "email_body", "raw_match": "Springfield, IL" }},
  "claimant_zip": {{ "value": "62701", "confidence": 78, "source": "email_body", "raw_match": "62701" }},
  "jurisdiction_state": {{ "value": "IL", "confidence": 85, "source": "email_body", "raw_match": "Illinois WC claim" }},
  "order_type": {{ "value": "Initial Evaluation", "confidence": 70, "source": "inferred", "raw_match": "" }},
  "employer_name": {{ "value": "Acme Corp", "confidence": 65, "source": "email_body", "raw_match": "Employer: Acme Corp" }},
  "claimant_job_title": {{ "value": "Warehouse Worker", "confidence": 60, "source": "email_body", "raw_match": "occupation: warehouse worker" }},
  "employer_address": {{ "value": null, "confidence": 0, "source": "", "raw_match": "" }},
  "authorization_number": {{ "value": null, "confidence": 0, "source": "", "raw_match": "" }},
  "referring_physician_name": {{ "value": "Dr. Jane Doctor", "confidence": 90, "source": "email_body", "raw_match": "Referring: Dr. Jane Doctor" }},
  "referring_physician_npi": {{ "value": "1234567890", "confidence": 88, "source": "email_body", "raw_match": "NPI: 1234567890" }},
  "adjuster_name": {{ "value": "Jane Adjuster", "confidence": 95, "source": "signature", "raw_match": "Jane Adjuster" }},
  "adjuster_email": {{ "value": "jane.adjuster@aceinsurance.com", "confidence": 100, "source": "from_field", "raw_match": "From: jane.adjuster@aceinsurance.com" }},
  "adjuster_phone": {{ "value": "(555) 987-6543", "confidence": 85, "source": "signature", "raw_match": "Phone: 555-987-6543" }},
  "suggested_providers": {{ "value": "ABC Imaging Center", "confidence": 75, "source": "email_body", "raw_match": "prefer ABC Imaging" }},
  "special_requirements": {{ "value": "Patient uses wheelchair", "confidence": 80, "source": "email_body", "raw_match": "Note: wheelchair access needed" }},
  "priority": {{ "value": "medium", "confidence": 70, "source": "inferred", "raw_match": "" }},
  "notes": {{ "value": "Patient prefers morning appointments", "confidence": 80, "source": "email_body", "raw_match": "prefers morning appointments" }},
  "claimant_name": {{ "value": "John Smith", "confidence": 95, "source": "email_body", "raw_match": "Patient: John Smith" }},
  "claimant_address": {{ "value": "123 Main Street, Springfield, IL 62701", "confidence": 70, "source": "email_body", "raw_match": "" }}
}}

RETURN ONLY THE JSON. NO OTHER TEXT.
"""


class ExtractionService:
    """Service for extracting structured data from referral emails."""

    def __init__(self):
        self.settings = get_settings()

    def extract_from_email(
        self,
        from_email: str,
        subject: str,
        body: str,
        attachment_texts: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """
        Extract structured data from an email using Claude.

        Args:
            from_email: The sender's email address
            subject: Email subject line
            body: Plain text or HTML body of the email
            attachment_texts: List of extracted text from attachments

        Returns:
            ExtractionResult with all extracted fields and confidence scores
        """
        # Clean HTML from body if present
        clean_body = self._strip_html(body)

        # Build attachment section
        attachment_section = ""
        if attachment_texts:
            attachment_section = "**Attachment Contents:**\n"
            for i, text in enumerate(attachment_texts, 1):
                attachment_section += f"\n--- Attachment {i} ---\n{text[:5000]}\n"

        # Build the prompt
        prompt = EXTRACTION_PROMPT.format(
            from_email=from_email,
            subject=subject,
            email_body=clean_body[:10000],  # Limit body length
            attachment_section=attachment_section,
        )

        # Call Claude
        try:
            client = get_anthropic_client()
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse the response
            response_text = response.content[0].text
            return self._parse_extraction_response(response_text)

        except Exception as e:
            # Return empty result on error, log it
            print(f"Extraction error: {e}")
            return ExtractionResult()

    def extract_from_email_sync(
        self,
        from_email: str,
        subject: str,
        body: str,
        attachment_texts: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """Synchronous version of extract_from_email."""
        return self.extract_from_email(from_email, subject, body, attachment_texts)

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        if not text:
            return ""
        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", " ", text)
        # Remove extra whitespace
        clean = re.sub(r"\s+", " ", clean)
        # Decode common HTML entities
        clean = (
            clean.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        return clean.strip()

    def _parse_extraction_response(self, response_text: str) -> ExtractionResult:
        """Parse the JSON response from Claude into an ExtractionResult."""
        try:
            # Try to extract JSON from the response
            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if not json_match:
                return ExtractionResult()

            data = json.loads(json_match.group())
            result = ExtractionResult()

            # Parse all fields from the extraction
            for field in ExtractionResult._ALL_FIELDS:
                if field in data and data[field] and data[field].get("value"):
                    field_data = data[field]
                    extracted = ExtractedField(
                        value=field_data.get("value"),
                        confidence=field_data.get("confidence", 50),
                        source=field_data.get("source", "email_body"),
                        raw_match=field_data.get("raw_match"),
                    )
                    setattr(result, field, extracted)

            # If we have claimant_name but not first/last, try to split it
            if result.claimant_name and not result.claimant_first_name:
                full_name = result.claimant_name.value
                first, last = self._split_name(full_name)
                if first:
                    result.claimant_first_name = ExtractedField(
                        value=first,
                        confidence=result.claimant_name.confidence - 5,
                        source=result.claimant_name.source,
                        raw_match=result.claimant_name.raw_match,
                    )
                if last:
                    result.claimant_last_name = ExtractedField(
                        value=last,
                        confidence=result.claimant_name.confidence - 5,
                        source=result.claimant_name.source,
                        raw_match=result.claimant_name.raw_match,
                    )

            # If we have claimant_address but not components, try to parse it
            if result.claimant_address and not result.claimant_city:
                parsed = self._parse_address(result.claimant_address.value)
                base_confidence = result.claimant_address.confidence - 10
                if parsed.get("address_1"):
                    result.claimant_address_1 = ExtractedField(
                        value=parsed["address_1"],
                        confidence=base_confidence,
                        source=result.claimant_address.source,
                        raw_match=result.claimant_address.raw_match,
                    )
                if parsed.get("city"):
                    result.claimant_city = ExtractedField(
                        value=parsed["city"],
                        confidence=base_confidence,
                        source=result.claimant_address.source,
                        raw_match=result.claimant_address.raw_match,
                    )
                if parsed.get("state"):
                    result.claimant_state = ExtractedField(
                        value=self._normalize_state(parsed["state"]),
                        confidence=base_confidence,
                        source=result.claimant_address.source,
                        raw_match=result.claimant_address.raw_match,
                    )
                if parsed.get("zip"):
                    result.claimant_zip = ExtractedField(
                        value=parsed["zip"],
                        confidence=base_confidence,
                        source=result.claimant_address.source,
                        raw_match=result.claimant_address.raw_match,
                    )

            return result

        except json.JSONDecodeError:
            return ExtractionResult()

    def _split_name(self, full_name: str) -> tuple[str, str]:
        """Split full name into first and last name."""
        if not full_name:
            return "", ""
        parts = full_name.strip().split()
        if len(parts) == 1:
            return "", parts[0]
        elif len(parts) == 2:
            return parts[0], parts[1]
        else:
            # Multiple parts - first word is first name, rest is last name
            return parts[0], " ".join(parts[1:])

    def _parse_address(self, address: str) -> dict:
        """Parse address string into components."""
        if not address:
            return {}
        result = {}
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 1:
            result["address_1"] = parts[0]
        if len(parts) >= 2:
            result["city"] = parts[1]
        if len(parts) >= 3:
            # Last part may have state and zip: "IL 62701"
            last_part = parts[2].strip()
            match = re.search(r"([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)", last_part)
            if match:
                result["state"] = match.group(1).upper()
                result["zip"] = match.group(2)
            else:
                result["state"] = last_part
        return result

    def _normalize_state(self, state: str) -> str:
        """Normalize state to 2-letter code."""
        if not state:
            return ""
        if len(state) == 2:
            return state.upper()
        # Common state name mappings
        state_map = {
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
        return state_map.get(state.lower().strip(), state.upper()[:2])

    def normalize_phone(self, phone: str) -> str:
        """Normalize a phone number to (XXX) XXX-XXXX format."""
        if not phone:
            return ""
        # Extract digits
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return phone

    def normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize a date string to YYYY-MM-DD format."""
        if not date_str:
            return None

        # Common date formats to try
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%m-%d-%Y",
            "%m-%d-%y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file using pypdf."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""


def extract_text_from_image(image_path: str) -> str:
    """Extract text from an image using Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        print(f"OCR extraction error: {e}")
        return ""
