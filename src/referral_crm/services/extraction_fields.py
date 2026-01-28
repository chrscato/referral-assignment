"""
Field definitions for the two-step extraction framework.

This module defines all extraction fields with metadata including:
- Step (1=extraction, 2=reasoning/derived)
- Guidance notes for the LLM
- Source hints (where to look in documents)
- Validation types
- Required status
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List


class ExtractionStep(Enum):
    """Which step of extraction handles this field."""
    EXTRACTION = 1  # Direct extraction from document
    REASONING = 2   # Derived/enriched from reference data


class ValidationType(Enum):
    """Type of validation to apply to the field."""
    NONE = "none"
    NPI = "npi"              # 10-digit NPI number
    ICD10 = "icd10"          # ICD-10 diagnosis code
    CPT = "cpt"              # CPT/procedure code
    SSN = "ssn"              # Social security number
    PHONE = "phone"          # Phone number
    EMAIL = "email"          # Email address
    DATE = "date"            # Date format
    STATE = "state"          # US state code
    ZIP = "zip"              # ZIP code


@dataclass
class FieldDefinition:
    """Definition of an extraction field with metadata."""

    name: str                           # Field name (snake_case)
    step: ExtractionStep                # Which step handles this field
    guidance: str                       # LLM helper notes
    source_hint: str                    # Where to look in document
    validation_type: ValidationType     # Type of validation
    required: bool                      # Is this field required
    filemaker_field: Optional[str] = None  # Corresponding FileMaker field name
    examples: Optional[List[str]] = None   # Example values


# =============================================================================
# STEP 1: DIRECT EXTRACTION FIELDS
# =============================================================================

EXTRACTION_FIELDS: List[FieldDefinition] = [
    # --- Referring Physician ---
    FieldDefinition(
        name="referring_physician_name",
        step=ExtractionStep.EXTRACTION,
        guidance="Name of the referring physician who ordered the service",
        source_hint="Look in headers, letterhead, or 'Ordered by' / 'Referring physician' sections",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Referring Physician Name",
        examples=["Dr. John Smith", "Jane Doe, MD"]
    ),
    FieldDefinition(
        name="referring_physician_npi",
        step=ExtractionStep.EXTRACTION,
        guidance="10-digit NPI number for the referring physician",
        source_hint="Usually near the referring physician name, may be labeled 'NPI' or 'Provider ID'",
        validation_type=ValidationType.NPI,
        required=False,
        filemaker_field="Referring Physician NPI",
        examples=["1234567890", "9876543210"]
    ),

    # --- Adjuster/Assigning Party ---
    FieldDefinition(
        name="assigning_adjuster_name",
        step=ExtractionStep.EXTRACTION,
        guidance="Name of the adjuster or person sending/assigning the referral",
        source_hint="Typically in the email 'From' field, signature block, or letterhead",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Adjuster Name",
        examples=["Jane Adjuster", "Bob Claims Handler"]
    ),
    FieldDefinition(
        name="assigning_adjuster_phone",
        step=ExtractionStep.EXTRACTION,
        guidance="Phone number of the assigning adjuster",
        source_hint="Look in email signature, contact info block, or near adjuster name",
        validation_type=ValidationType.PHONE,
        required=False,
        filemaker_field="Adjuster Phone",
        examples=["(555) 123-4567", "555-123-4567"]
    ),
    FieldDefinition(
        name="assigning_adjuster_email",
        step=ExtractionStep.EXTRACTION,
        guidance="Email address of the assigning adjuster",
        source_hint="Email 'From' field or signature block",
        validation_type=ValidationType.EMAIL,
        required=False,
        filemaker_field="Adjuster Email",
        examples=["adjuster@insurance.com"]
    ),
    FieldDefinition(
        name="assigning_company",
        step=ExtractionStep.EXTRACTION,
        guidance="Company/carrier name of the assigning party (insurance company)",
        source_hint="Email domain, letterhead, signature block, or explicitly stated carrier",
        validation_type=ValidationType.NONE,
        required=True,
        filemaker_field="Intake Client Company",
        examples=["ACE Insurance", "Travelers", "Liberty Mutual"]
    ),

    # --- Claim Information ---
    FieldDefinition(
        name="claim_number",
        step=ExtractionStep.EXTRACTION,
        guidance="Workers' compensation claim number",
        source_hint="Often in subject line, headers, or prominently displayed. Patterns: WC-YYYY-XXXXXX, YYYY-XXXXXX, or 6-8 digit numbers",
        validation_type=ValidationType.NONE,
        required=True,
        filemaker_field="Intake Claim Number",
        examples=["WC-2025-001234", "2025-001234", "12345678"]
    ),
    FieldDefinition(
        name="jurisdiction_state",
        step=ExtractionStep.EXTRACTION,
        guidance="State that has jurisdiction over the workers' comp claim (may differ from patient address)",
        source_hint="Look for 'Jurisdiction', 'State of injury', or claim filing location. Often near claim number.",
        validation_type=ValidationType.STATE,
        required=False,
        filemaker_field="Jurisdiction State",
        examples=["CA", "TX", "NY", "IL"]
    ),
    FieldDefinition(
        name="order_type",
        step=ExtractionStep.EXTRACTION,
        guidance="Type of order or referral category",
        source_hint="May be in subject line, headers, or explicitly stated. Examples: Initial, Follow-up, Expedited",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Order Type",
        examples=["Initial Evaluation", "Follow-up", "Expedited", "Urgent"]
    ),

    # --- Patient/Claimant Information ---
    FieldDefinition(
        name="patient_first_name",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient/claimant first name",
        source_hint="Patient demographics section, often labeled 'Patient', 'Claimant', or 'Injured Worker'",
        validation_type=ValidationType.NONE,
        required=True,
        filemaker_field="Patient First Name",
        examples=["John", "Jane", "Robert"]
    ),
    FieldDefinition(
        name="patient_last_name",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient/claimant last name",
        source_hint="Patient demographics section, often labeled 'Patient', 'Claimant', or 'Injured Worker'",
        validation_type=ValidationType.NONE,
        required=True,
        filemaker_field="Patient Last Name",
        examples=["Smith", "Doe", "Johnson"]
    ),
    FieldDefinition(
        name="patient_dob",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient date of birth. Convert to YYYY-MM-DD format.",
        source_hint="Patient demographics, often labeled 'DOB', 'Date of Birth', or 'Birthdate'",
        validation_type=ValidationType.DATE,
        required=False,
        filemaker_field="Intake DOB",
        examples=["1985-03-15", "1990-12-01"]
    ),
    FieldDefinition(
        name="patient_doi",
        step=ExtractionStep.EXTRACTION,
        guidance="Date of injury. Convert to YYYY-MM-DD format.",
        source_hint="Look for 'DOI', 'Date of Injury', 'Injury Date', or in claim description",
        validation_type=ValidationType.DATE,
        required=False,
        filemaker_field="Intake DOI",
        examples=["2025-01-10", "2024-11-15"]
    ),
    FieldDefinition(
        name="patient_gender",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient gender (Male or Female)",
        source_hint="Patient demographics section, often abbreviated as M/F",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Patient Gender",
        examples=["Male", "Female"]
    ),
    FieldDefinition(
        name="patient_phone",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient phone number. Normalize to (XXX) XXX-XXXX format.",
        source_hint="Patient contact information section",
        validation_type=ValidationType.PHONE,
        required=False,
        filemaker_field="Patient Phone",
        examples=["(555) 123-4567"]
    ),
    FieldDefinition(
        name="patient_email",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient email address",
        source_hint="Patient contact information section",
        validation_type=ValidationType.EMAIL,
        required=False,
        filemaker_field="Patient Email",
        examples=["patient@email.com"]
    ),
    FieldDefinition(
        name="patient_ssn",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient social security number. May be partial or masked (XXX-XX-1234).",
        source_hint="Patient demographics, often labeled 'SSN', 'Social Security', or 'SS#'",
        validation_type=ValidationType.SSN,
        required=False,
        filemaker_field="Patient SSN",
        examples=["123-45-6789", "XXX-XX-6789"]
    ),

    # --- Patient Address ---
    FieldDefinition(
        name="patient_address_1",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient street address line 1",
        source_hint="Patient address section",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Patient Address 1",
        examples=["123 Main Street", "456 Oak Avenue"]
    ),
    FieldDefinition(
        name="patient_address_2",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient street address line 2 (apartment, suite, etc.)",
        source_hint="Patient address section, if applicable",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Patient Address 2",
        examples=["Apt 4B", "Suite 100"]
    ),
    FieldDefinition(
        name="patient_city",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient city",
        source_hint="Patient address section",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Patient Address City",
        examples=["Springfield", "Los Angeles"]
    ),
    FieldDefinition(
        name="patient_state",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient state (2-letter code)",
        source_hint="Patient address section",
        validation_type=ValidationType.STATE,
        required=False,
        filemaker_field="Patient Address State",
        examples=["CA", "IL", "TX"]
    ),
    FieldDefinition(
        name="patient_zip",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient ZIP code (5 or 9 digits)",
        source_hint="Patient address section",
        validation_type=ValidationType.ZIP,
        required=False,
        filemaker_field="Patient Address ZIP",
        examples=["62701", "90210-1234"]
    ),

    # --- Employer Information ---
    FieldDefinition(
        name="patient_employer",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient's employer company name",
        source_hint="Look for 'Employer', 'Company', or in injury description context",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Patient Employer",
        examples=["Acme Corporation", "City of Springfield"]
    ),
    FieldDefinition(
        name="patient_job_title",
        step=ExtractionStep.EXTRACTION,
        guidance="Patient's job title or occupation",
        source_hint="Near employer info or in injury description",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Patient Job Title",
        examples=["Warehouse Worker", "Nurse", "Construction Foreman"]
    ),
    FieldDefinition(
        name="patient_employer_address",
        step=ExtractionStep.EXTRACTION,
        guidance="Employer's full address",
        source_hint="Employer section, if provided",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Employer Address 1",
        examples=["500 Industrial Blvd, Chicago, IL 60601"]
    ),

    # --- Service/Medical Information ---
    FieldDefinition(
        name="service_requested",
        step=ExtractionStep.EXTRACTION,
        guidance="Type of service requested (can be multiple). Include details like body part, with/without contrast, etc.",
        source_hint="Main body of referral, often in 'Services Requested', 'Order', or explicit instructions",
        validation_type=ValidationType.NONE,
        required=True,
        filemaker_field="Intake Instructions",
        examples=["PT Evaluation", "MRI lumbar spine without contrast", "CT scan right shoulder", "X-ray bilateral knees"]
    ),
    FieldDefinition(
        name="icd10_code",
        step=ExtractionStep.EXTRACTION,
        guidance="ICD-10 diagnosis code(s). Format: letter + digits + optional decimal (e.g., M54.5)",
        source_hint="Look for 'ICD-10', 'Diagnosis Code', 'Dx', near body parts or injury description",
        validation_type=ValidationType.ICD10,
        required=False,
        filemaker_field="ICD10 Code",
        examples=["M54.5", "S43.001A", "M75.100"]
    ),
    FieldDefinition(
        name="icd10_description",
        step=ExtractionStep.EXTRACTION,
        guidance="Description associated with the ICD-10 code",
        source_hint="Usually adjacent to or following the ICD-10 code",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="ICD10 Description",
        examples=["Low back pain", "Rotator cuff tear", "Shoulder pain"]
    ),
    FieldDefinition(
        name="body_parts",
        step=ExtractionStep.EXTRACTION,
        guidance="Injured body parts. Use proper anatomical terms, specify left/right.",
        source_hint="Injury description, near ICD-10 codes, or service request details",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Injury Description",
        examples=["left shoulder", "lower back", "right knee and ankle"]
    ),

    # --- Preferences and Special Instructions ---
    FieldDefinition(
        name="suggested_providers",
        step=ExtractionStep.EXTRACTION,
        guidance="Any provider preferences from adjuster or patient",
        source_hint="Look for 'Preferred provider', 'Please schedule with', or patient/adjuster preferences",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Suggested Providers",
        examples=["ABC Imaging Center", "Dr. Smith at Springfield PT"]
    ),
    FieldDefinition(
        name="special_requirements",
        step=ExtractionStep.EXTRACTION,
        guidance="Any special notes, accommodations, or considerations for the injured worker",
        source_hint="Look for 'Special instructions', 'Notes', 'Accommodations', or specific patient needs",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Special Requirements",
        examples=["Patient uses wheelchair", "Interpreter needed - Spanish", "Morning appointments only"]
    ),
    FieldDefinition(
        name="authorization_number",
        step=ExtractionStep.EXTRACTION,
        guidance="Authorization or pre-approval number if provided",
        source_hint="Look for 'Auth #', 'Authorization', 'Pre-approval', 'UR number'",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Authorization Number",
        examples=["AUTH-2025-12345", "UR123456"]
    ),
]


# =============================================================================
# STEP 2: REASONING/DERIVED FIELDS
# =============================================================================

REASONING_FIELDS: List[FieldDefinition] = [
    FieldDefinition(
        name="associated_procedure_code",
        step=ExtractionStep.REASONING,
        guidance="CPT/procedure code derived from service_requested via lookup table",
        source_hint="Derived from procedure_codes table based on service type",
        validation_type=ValidationType.CPT,
        required=False,
        filemaker_field="Procedure Code",
        examples=["97110", "72148", "73221"]
    ),
    FieldDefinition(
        name="validated_icd10",
        step=ExtractionStep.REASONING,
        guidance="ICD-10 code validated against reference table",
        source_hint="Validated from icd10_codes table",
        validation_type=ValidationType.ICD10,
        required=False,
        filemaker_field=None,
        examples=["M54.5", "S43.001A"]
    ),
    FieldDefinition(
        name="icd10_category",
        step=ExtractionStep.REASONING,
        guidance="Category derived from validated ICD-10 code",
        source_hint="Derived from icd10_codes table category field",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="ICD10 Category",
        examples=["Musculoskeletal", "Injury", "Nervous System"]
    ),
    FieldDefinition(
        name="icd10_body_region",
        step=ExtractionStep.REASONING,
        guidance="Body region derived from validated ICD-10 code",
        source_hint="Derived from icd10_codes table body_region field",
        validation_type=ValidationType.NONE,
        required=False,
        filemaker_field="Body Region",
        examples=["Back", "Shoulder", "Knee"]
    ),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_fields() -> List[FieldDefinition]:
    """Get all field definitions (extraction + reasoning)."""
    return EXTRACTION_FIELDS + REASONING_FIELDS


def get_extraction_fields() -> List[FieldDefinition]:
    """Get only Step 1 extraction fields."""
    return EXTRACTION_FIELDS


def get_reasoning_fields() -> List[FieldDefinition]:
    """Get only Step 2 reasoning/derived fields."""
    return REASONING_FIELDS


def get_required_fields() -> List[FieldDefinition]:
    """Get all required fields."""
    return [f for f in get_all_fields() if f.required]


def get_field_by_name(name: str) -> Optional[FieldDefinition]:
    """Get a field definition by name."""
    for field in get_all_fields():
        if field.name == name:
            return field
    return None


def generate_extraction_prompt_section() -> str:
    """
    Generate the field extraction section of the LLM prompt.
    This creates detailed guidance for each field based on the definitions.
    """
    lines = ["FIELDS TO EXTRACT:", "=" * 50, ""]

    for field in EXTRACTION_FIELDS:
        required_marker = " [REQUIRED]" if field.required else ""
        lines.append(f"FIELD: {field.name}{required_marker}")
        lines.append(f"  Description: {field.guidance}")
        lines.append(f"  Where to look: {field.source_hint}")
        if field.examples:
            lines.append(f"  Examples: {', '.join(field.examples)}")
        if field.validation_type != ValidationType.NONE:
            lines.append(f"  Format: {field.validation_type.value}")
        lines.append("")

    return "\n".join(lines)
