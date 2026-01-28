# FileMaker Field Mapping & Extraction Strategy

## Overview
Map the multi-stage extraction pipeline to your FileMaker intake form fields. These are the exact fields we need to extract and populate.

---

## FileMaker Intake Fields (from your schema)

### Core Identifiers
```
ID_Intake                    [Text, Indexed, Auto-enter Calculation]
PrimaryKey                   [Text, Indexed, Auto-enter, Unique]
CreatedBy                    [Text, Creation Account, Required]
CreationTimestamp            [Timestamp, Required, 4-Digit Year]
ModifiedBy                   [Text, Modification Account, Required]
ModificationTimestamp        [Timestamp, Required, 4-Digit Year]
```

### Client/Patient Information
```
Intake Client First Name     [Text, Indexed]
Intake Client Last Name      [Text, Indexed]
Intake Client Phone          [Text, Indexed]
Intake Client Email          [Text, Indexed]
Intake Client Company        [Text, Indexed]
Intake DOB                   [Text]
Intake DOI                   [Text]                    ← Date of Injury
Intake Recurrent Client      [Text, Indexed]
Patient First Name           [Text, Indexed]
Patient Last Name            [Text, Indexed]
Patient Phone                [Text, Indexed]
Patient Email                [Text, Indexed]
Patient Employer             [Text, Indexed]
Patient Address 1            [Text]
Patient Address 2            [Text]
Patient Address City         [Text]
Patient Address State        [Text, Indexed]
Patient Address ZIP          [Number, Indexed]
```

### Employer Information
```
Employer Address 1           [Text]
Employer Address 2           [Text]
Employer Address City        [Text]
Employer Address State       [Text, Indexed]
Employer Address ZIP         [Number, Indexed]
Employer Email               [Text, Indexed]
id_employer                  [Text]
Patient Employer             [Text, Indexed]
```

### Claim Information
```
Intake Claim Number          [Text]
Intake Client Company        [Text, Indexed]          ← Insurance Carrier/Company
Injury Description           [Text, Indexed]
Intake Instructions          [Text]
```

### Intake Metadata
```
__Status Intakes             [Calculation]             ← Cancelled or Complete
__Count Status Intakes       [Summary]                 ← Total count
_Status Intakes              [Calculation]
Status                       [Text, By Value List, Required, Allow Override]
```

### Additional Fields
```
Attachment URLs              [Text]
id_company                   [Text, Indexed]
id_constant                  [Text, Indexed, Auto-enter]
id_contact                   [Text, Indexed]
id_employer_sales_rep        [Text]
```

---

## Extraction Field Mapping

Map your extraction fields to FileMaker intake fields:

| Extraction Field | Source | FileMaker Target | Priority | Notes |
|------------------|--------|------------------|----------|-------|
| **claimant_name** | Email/PDF | Intake Client First Name + Last Name | CRITICAL | Split first/last |
| claimant_first | Extract | Intake Client First Name | HIGH | Split from full name |
| claimant_last | Extract | Intake Client Last Name | HIGH | Split from full name |
| **claim_number** | Email/PDF | Intake Claim Number | CRITICAL | WC-YYYY-XXXXXX format |
| **claimant_dob** | Email/PDF | Intake DOB | HIGH | YYYY-MM-DD format |
| **date_of_injury** | Email/PDF | Intake DOI | HIGH | YYYY-MM-DD format |
| **claimant_phone** | Email/PDF | Intake Client Phone | MEDIUM | Normalize (XXX) XXX-XXXX |
| **claimant_email** | Email/PDF | Intake Client Email | MEDIUM | Valid email format |
| **claimant_address** | Email/PDF | Patient Address 1 | MEDIUM | Parse street address |
| claimant_city | Extract | Patient Address City | MEDIUM | Extract city |
| claimant_state | Extract | Patient Address State | MEDIUM | 2-letter state code |
| claimant_zip | Extract | Patient Address ZIP | MEDIUM | 5 or 9 digit ZIP |
| **body_parts** | Email/PDF | Injury Description | HIGH | Medical terminology |
| **service_requested** | Email/PDF | Intake Instructions | HIGH | PT, MRI, IME, etc |
| **carrier** | Email/PDF | Intake Client Company | CRITICAL | Insurance company name |
| **adjuster_name** | Email | (Metadata) | LOW | For audit trail |
| **adjuster_email** | Email | (Metadata) | LOW | For audit trail |
| employer_name | Email/PDF | Patient Employer | MEDIUM | Employer company name |
| employer_address | Email/PDF | Employer Address 1-2 | MEDIUM | If provided |
| employer_city | Extract | Employer Address City | LOW | If provided |
| employer_state | Extract | Employer Address State | LOW | If provided |
| employer_zip | Extract | Employer Address ZIP | LOW | If provided |
| authorization_number | Email/PDF | (Custom field needed) | MEDIUM | Auth # for reference |

---

## Extraction Flow to FileMaker

```
┌─────────────────────────────────────────────────────────────┐
│           EXTRACTION → FILEMAKER INTAKE MAPPING             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Email/PDF Input                                             │
│      │                                                       │
│      ▼                                                       │
│  Stage 1: Ingest & Extract Text                             │
│      │                                                       │
│      ▼                                                       │
│  Stage 2: Extract Text (OCR if needed)                      │
│      │                                                       │
│      ▼                                                       │
│  Stage 3: LLM Extraction                                    │
│    └─ claimant_name, claim_number, etc.                    │
│      │                                                       │
│      ▼                                                       │
│  Stage 4: Confidence Scoring                                │
│    └─ Flag low-confidence fields                           │
│      │                                                       │
│      ▼                                                       │
│  Stage 5: Human Review (if needed)                          │
│    └─ Corrections applied                                  │
│      │                                                       │
│      ▼                                                       │
│  FIELD MAPPING & TRANSFORMATION                             │
│    ├─ Split claimant_name into First/Last                  │
│    ├─ Validate phone format                                │
│    ├─ Normalize state codes                                │
│    ├─ Format dates to YYYY-MM-DD                           │
│    ├─ Extract ZIP from full address                        │
│    └─ Create PrimaryKey identifier                         │
│      │                                                       │
│      ▼                                                       │
│  FileMaker Intake Record                                    │
│    ├─ ID_Intake (auto-generated)                           │
│    ├─ Intake Client First Name                             │
│    ├─ Intake Client Last Name                              │
│    ├─ Intake Claim Number                                  │
│    ├─ Intake Client Phone                                  │
│    ├─ Patient Address 1, 2, City, State, ZIP               │
│    ├─ Injury Description                                   │
│    ├─ Intake Instructions                                  │
│    ├─ Intake Client Company (Carrier)                      │
│    └─ Status (auto-set to "Pending" or similar)            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## FileMaker Field Constraints & Rules

### Auto-Calculated Fields (Handle Carefully)
```
ID_Intake
  └─ Auto-enter Calculation: generates unique ID
  └─ DON'T try to set manually - let FileMaker generate

PrimaryKey
  └─ Indexed, Auto-enter, Unique
  └─ May be auto-generated from ID_Intake
  └─ Check with FileMaker admin on format

__Status Intakes
  └─ Calculation field: = Case ( Status = "Cancelled"; 0 ; Status = "Complete"; 0 ; 1 )
  └─ Shows count of non-cancelled, non-complete intakes

Status
  └─ By Value List (dropdown with specific options)
  └─ Must match one of the allowed values
  └─ Options: "Pending", "In Progress", "Complete", "Cancelled", "On Hold", etc.
```

### Timestamps
```
CreationTimestamp / ModificationTimestamp
  └─ Auto-populated by FileMaker
  └─ 4-Digit Year required (not 2-digit)
  └─ Can't modify directly via API
```

### Indexed Fields (Searchable)
```
HIGH PERFORMANCE - use for filtering:
  - Intake Client Last Name
  - Intake Client Phone
  - Intake Client Email
  - Patient First/Last Name
  - Patient Phone, Email, State, ZIP
  - Employer Address State, ZIP
  - Status, Intake Claim Number
```

### Required Fields (Can't be empty)
```
MUST POPULATE:
  - CreatedBy (auto-populated)
  - CreationTimestamp (auto-populated)
  - ModifiedBy (auto-populated)
  - ModificationTimestamp (auto-populated)
  - Status (must have valid value)
  - PrimaryKey (may be auto-calculated)
```

---

## LLM Extraction Prompt (Updated for FileMaker)

```python
FILEMAKER_EXTRACTION_PROMPT = """You are a workers' compensation intake specialist.
Extract structured data from a referral email/document for FileMaker intake form.

DOCUMENT:
{document_text}

EXTRACT EXACTLY THESE FIELDS (FileMaker mapping):

PRIMARY FIELDS (CRITICAL - must extract):
1. claimant_first_name: First name of patient (split from full name if needed)
2. claimant_last_name: Last name of patient
3. claim_number: Workers' comp claim number (WC-YYYY-XXXXXX format)
4. carrier_name: Insurance company/carrier name (Intake Client Company)
5. service_type: Type of service requested (PT, MRI, IME, etc.)

PATIENT INFORMATION:
6. claimant_dob: Date of birth (YYYY-MM-DD)
7. date_of_injury: Date of injury (YYYY-MM-DD)
8. claimant_phone: Phone number ((XXX) XXX-XXXX format)
9. claimant_email: Email address

PATIENT ADDRESS:
10. patient_address_1: Street address (line 1)
11. patient_address_2: Street address (line 2, if applicable)
12. patient_address_city: City
13. patient_address_state: State (2-letter code: CA, NY, TX, etc.)
14. patient_address_zip: ZIP code (5 or 9 digits)

INJURY/SERVICE:
15. injury_description: Detailed description of injury/body parts injured
16. intake_instructions: Special instructions or notes

EMPLOYER INFORMATION (if provided):
17. employer_name: Employer company name
18. employer_address_1: Employer street address
19. employer_address_state: Employer state
20. employer_address_zip: Employer ZIP code

CONFIDENCE SCORES:
For EACH field, provide a confidence score (0-100):
- 95-100: Direct statement, clearly stated
- 85-94: Clear from context, one reasonable interpretation
- 70-84: Somewhat ambiguous but best interpretation
- 50-69: Multiple possible interpretations, uncertainty
- <50: Guessing or inferred

RESPONSE FORMAT (JSON ONLY):
{{
  "extraction": {{
    "claimant_first_name": {{
      "value": "John",
      "confidence": 95,
      "source": "Email paragraph 2",
      "reasoning": "Patient name stated clearly in referral"
    }},
    "claimant_last_name": {{
      "value": "Smith",
      "confidence": 95,
      "source": "Email paragraph 2",
      "reasoning": "Patient last name in referral"
    }},
    "claim_number": {{
      "value": "WC-2025-001234",
      "confidence": 98,
      "source": "Email header",
      "reasoning": "Standard format found in email header"
    }},
    ...
  }},
  "warnings": [
    "Missing DOB - not found in email",
    "Address incomplete - city/state found but no ZIP"
  ]
}}

CRITICAL RULES:
1. NAMES: Split full names into first + last (if only full name given, "John Smith" → first: "John", last: "Smith")
2. CLAIM NUMBERS: Look for patterns WC-YYYY-XXXXXX, YYYY-XXXXXX, or carrier-specific formats
3. DATES: Convert to YYYY-MM-DD (e.g., "January 15, 2025" → "2025-01-15")
4. PHONE: Normalize to (XXX) XXX-XXXX format
5. STATE: Use 2-letter codes (not full names - "California" → "CA")
6. ZIP: 5 or 9 digits only, no letters
7. SERVICE TYPES: PT Evaluation, PT Treatment, IME, MRI, CT Scan, X-Ray, etc.
8. BODY PARTS: Use medical terminology (e.g., "right shoulder" not "R shoulder", "lower back" not "lower back pain")

Return ONLY valid JSON with no additional text or markdown.
"""
```

---

## FileMaker API Integration

### Record Creation Payload

```python
def build_filemaker_payload(extraction: ExtractionResult) -> dict:
    """
    Build payload for FileMaker Data API to create intake record.
    """
    
    # Format the data according to FileMaker requirements
    payload = {
        "fieldData": {
            # Auto-generated by FileMaker (don't include):
            # "ID_Intake": ...,
            # "PrimaryKey": ...,
            # "CreatedBy": ...,
            # "CreationTimestamp": ...,
            
            # PATIENT INFORMATION
            "Intake Client First Name": extraction.claimant_first_name,
            "Intake Client Last Name": extraction.claimant_last_name,
            "Intake Client Phone": extract_phone(extraction.claimant_phone),
            "Intake Client Email": extraction.claimant_email,
            "Intake Client Company": extraction.carrier_name,  # Insurance company
            "Intake DOB": format_date(extraction.claimant_dob),  # YYYY-MM-DD
            "Intake DOI": format_date(extraction.date_of_injury),  # YYYY-MM-DD
            "Intake Recurrent Client": "No",  # Default, can be corrected later
            
            # PATIENT ADDRESS
            "Patient First Name": extraction.claimant_first_name,
            "Patient Last Name": extraction.claimant_last_name,
            "Patient Phone": extract_phone(extraction.claimant_phone),
            "Patient Email": extraction.claimant_email,
            "Patient Employer": extraction.employer_name,
            "Patient Address 1": extraction.patient_address_1,
            "Patient Address 2": extraction.patient_address_2 or "",
            "Patient Address City": extraction.patient_address_city,
            "Patient Address State": extraction.patient_address_state,
            "Patient Address ZIP": extraction.patient_address_zip,
            
            # EMPLOYER INFORMATION
            "Employer Address 1": extraction.employer_address_1 or "",
            "Employer Address 2": extraction.employer_address_2 or "",
            "Employer Address City": extraction.employer_address_city or "",
            "Employer Address State": extraction.employer_address_state or "",
            "Employer Address ZIP": extraction.employer_address_zip or "",
            "Employer Email": extraction.employer_email or "",
            
            # CLAIM/SERVICE INFORMATION
            "Intake Claim Number": extraction.claim_number,
            "Injury Description": extraction.injury_description,
            "Intake Instructions": extraction.service_instructions,
            
            # STATUS
            "Status": "Pending",  # Default new intake status
        }
    }
    
    return payload


def extract_phone(phone_str: str) -> str:
    """Normalize phone to FileMaker format."""
    import re
    digits = re.sub(r'\D', '', phone_str or '')
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return phone_str or ""


def format_date(date_str: str) -> str:
    """Format date for FileMaker (YYYY-MM-DD)."""
    if not date_str:
        return ""
    # Assumes date_str is already in YYYY-MM-DD format from extraction
    # If not, add parsing logic here
    return date_str
```

### Batch Creation Example

```python
class FileMAkerIntakeSubmission:
    """Submit extracted referrals to FileMaker."""
    
    def __init__(self, fm_server: str, fm_db: str, fm_layout: str):
        self.fm_server = fm_server
        self.fm_db = fm_db
        self.fm_layout = fm_layout
        self.token = self._get_auth_token()
    
    def submit_referral(self, extraction: ExtractionResult) -> dict:
        """Submit a single extracted referral to FileMaker."""
        
        payload = build_filemaker_payload(extraction)
        
        url = f"{self.fm_server}/fmi/data/v1/databases/{self.fm_db}/layouts/{self.fm_layout}/records"
        
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code == 201:
            result = response.json()
            return {
                "status": "success",
                "filemaker_record_id": result["response"]["id"],
                "filemaker_mod_id": result["response"]["modId"],
            }
        else:
            return {
                "status": "error",
                "error": response.text,
            }
    
    def batch_submit_referrals(
        self,
        extractions: List[ExtractionResult],
        max_batch: int = 50
    ) -> List[dict]:
        """Submit multiple referrals to FileMaker."""
        
        results = []
        
        for extraction in extractions:
            result = self.submit_referral(extraction)
            results.append({
                "extraction_id": extraction.id,
                "filemaker_result": result,
            })
            
            # Respect rate limits
            if len(results) % max_batch == 0:
                time.sleep(1)
        
        return results
```

---

## Testing Extraction Against FileMaker Fields

```python
def test_extraction_completeness():
    """Verify extraction captures all required FileMaker fields."""
    
    required_fields = [
        "claimant_first_name",
        "claimant_last_name",
        "claim_number",
        "carrier_name",
        "service_type",
        "claimant_dob",
        "date_of_injury",
    ]
    
    high_priority_fields = required_fields + [
        "claimant_phone",
        "claimant_email",
        "patient_address_1",
        "patient_address_city",
        "patient_address_state",
        "patient_address_zip",
        "injury_description",
    ]
    
    # Sample extraction
    extraction = ExtractionResult()
    # ... populate with extracted data ...
    
    # Check completeness
    missing_required = [
        f for f in required_fields
        if not getattr(extraction, f, None)
    ]
    
    missing_high_priority = [
        f for f in high_priority_fields
        if not getattr(extraction, f, None)
    ]
    
    print(f"Missing Required: {missing_required}")
    print(f"Missing High Priority: {missing_high_priority}")
    
    # Confidence check
    for field in high_priority_fields:
        field_obj = getattr(extraction, field, None)
        if field_obj:
            confidence = field_obj.confidence if hasattr(field_obj, 'confidence') else 0
            if confidence < 70:
                print(f"⚠️  Low confidence: {field} ({confidence}%)")


def validate_filemaker_payload(payload: dict) -> List[str]:
    """Validate payload against FileMaker constraints."""
    
    errors = []
    
    # Check required fields
    required = ["Status"]
    for field in required:
        if not payload.get("fieldData", {}).get(field):
            errors.append(f"Missing required field: {field}")
    
    # Validate State codes (must be 2 letters)
    state = payload.get("fieldData", {}).get("Patient Address State", "")
    if state and len(state) != 2:
        errors.append(f"Invalid state code: {state} (must be 2 letters)")
    
    # Validate ZIP (must be 5 or 9 digits)
    zip_code = str(payload.get("fieldData", {}).get("Patient Address ZIP", ""))
    if zip_code and not (len(zip_code) == 5 or len(zip_code) == 9):
        errors.append(f"Invalid ZIP: {zip_code} (must be 5 or 9 digits)")
    
    # Validate email format
    email = payload.get("fieldData", {}).get("Intake Client Email", "")
    if email and "@" not in email:
        errors.append(f"Invalid email: {email}")
    
    # Validate date format (YYYY-MM-DD)
    import re
    dob = payload.get("fieldData", {}).get("Intake DOB", "")
    if dob and not re.match(r"^\d{4}-\d{2}-\d{2}$", dob):
        errors.append(f"Invalid DOB format: {dob} (must be YYYY-MM-DD)")
    
    return errors
```

---

## Implementation Checklist

- [ ] Update extraction prompt to use FileMaker field names
- [ ] Create `FileMakerPayloadBuilder` class
- [ ] Add field transformation logic (name splitting, phone normalization, etc.)
- [ ] Create `FileMAkerIntakeSubmission` class for API integration
- [ ] Add payload validation before submission
- [ ] Update CRM to track FileMaker record IDs
- [ ] Add batch submission capability
- [ ] Create error handling for FileMaker API failures
- [ ] Add retry logic with exponential backoff
- [ ] Test with actual FileMaker sandbox instance
- [ ] Set up audit logging for submissions
- [ ] Create dashboard showing FileMaker submission status

---

## Key Differences from Previous Approach

### Before (Generic Referral Model)
- Generic field names
- Single extraction target
- Flexible structure

### After (FileMaker-Specific)
- ✅ Map exactly to FileMaker field names
- ✅ Handle auto-calculated fields
- ✅ Respect field constraints (ZIP format, state codes, etc.)
- ✅ Proper value list handling (Status field)
- ✅ Normalize all data to FileMaker requirements
- ✅ Batch submission capability
- ✅ Error tracking per FileMaker record

---

## Data Transformation Examples

```python
# Example 1: Name Splitting
Extraction: claimant_name = "John Q Smith"
FileMaker Submission:
  - Intake Client First Name = "John Q"  (or just "John" if we split on last space)
  - Intake Client Last Name = "Smith"

# Example 2: Phone Normalization
Extraction: claimant_phone = "555-123-4567"
FileMaker: Intake Client Phone = "(555) 123-4567"

# Example 3: State Code
Extraction: state = "California"
FileMaker: Patient Address State = "CA"

# Example 4: ZIP Extraction
Extraction: address = "123 Main St, Springfield, IL 62701"
FileMaker:
  - Patient Address 1 = "123 Main St"
  - Patient Address City = "Springfield"
  - Patient Address State = "IL"
  - Patient Address ZIP = "62701"

# Example 5: Date Formatting
Extraction: date_of_injury = "1/15/2025"
FileMaker: Intake DOI = "2025-01-15"
```

---

## Next Steps

1. **Map your actual FileMaker instance** - confirm field names and constraints
2. **Test extraction output** - run sample emails through pipeline
3. **Validate transformation logic** - ensure all data formats match FileMaker requirements
4. **Create FileMaker API credentials** - get server, database, layout names
5. **Build submission flow** - integrate with your pipeline
6. **Test batch submissions** - confirm records create properly in FileMaker
7. **Add error handling** - retry logic, notification on failures
8. **Monitor sync** - track which referrals have been submitted to FileMaker
