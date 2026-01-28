# FileMaker Integration: Step-by-Step Implementation Guide

## Quick Start (30 minutes)

### Step 1: Update Extraction Prompt (5 minutes)

In `src/referral_crm/services/extraction_service.py`:

```python
# Replace the current EXTRACTION_PROMPT with the FileMaker version
# Copy from: filemaker_extraction_prompt.py

# Then add this method to ExtractionService:

def extract_from_email_for_filemaker(
    self,
    from_email: str,
    subject: str,
    body: str,
    attachment_texts: Optional[list[str]] = None,
) -> ExtractionResult:
    """
    Extract data optimized for FileMaker intake form fields.
    """
    clean_body = self._strip_html(body)
    
    attachment_section = ""
    if attachment_texts:
        attachment_section = "\nATTACHMENT CONTENTS:\n"
        for i, text in enumerate(attachment_texts, 1):
            attachment_section += f"\n--- Attachment {i} ---\n{text[:3000]}\n"
    
    prompt = FILEMAKER_EXTRACTION_PROMPT.format(
        document_text=f"{subject}\n\n{clean_body}{attachment_section}"[:10000]
    )
    
    try:
        client = get_anthropic_client()
        response = client.messages.create(
            model=self.settings.claude_model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        
        response_text = response.content[0].text
        return self._parse_extraction_response(response_text)
    
    except Exception as e:
        print(f"Extraction error: {e}")
        return ExtractionResult()
```

### Step 2: Add FileMaker Conversion Module (10 minutes)

Create `src/referral_crm/services/filemaker_conversion.py`:

```python
# Copy the entire FileMAkerExtraction and converter classes from:
# filemaker_extraction_implementation.py

# Use just the data models and conversion logic, not the API submission yet
```

### Step 3: Test Extraction → FileMaker Conversion (5 minutes)

```python
# In your test file or CLI:

from referral_crm.services.extraction_service import ExtractionService
from referral_crm.services.filemaker_conversion import (
    ExtractionToFileMAkerConverter,
    FileMAkerPayloadValidator
)

# Extract from email
extraction_service = ExtractionService()
extraction = extraction_service.extract_from_email_for_filemaker(
    from_email="adjuster@carrier.com",
    subject="New PT Referral",
    body="Patient: John Smith, Claim: WC-2025-001234..."
)

# Convert to FileMaker fields
converter = ExtractionToFileMAkerConverter()
fm_extraction = converter.convert(extraction.to_dict())

# Validate
validator = FileMAkerPayloadValidator()
errors = validator.validate(fm_extraction)

if not errors:
    print("✓ Ready for FileMaker submission!")
    print(f"Name: {fm_extraction.intake_client_first_name} {fm_extraction.intake_client_last_name}")
    print(f"Claim: {fm_extraction.intake_claim_number}")
    print(f"Confidence: {fm_extraction.extraction_confidence:.0f}%")
else:
    print("✗ Validation errors:")
    for error in errors:
        print(f"  - {error}")
```

### Step 4: Configure FileMaker API Credentials

In `.env`:

```env
# FileMaker Configuration
FILEMAKER_SERVER=https://your-filemaker-server.com
FILEMAKER_DATABASE=your_database_name
FILEMAKER_LAYOUT=Intake  # or whatever your intake layout is called
FILEMAKER_USERNAME=api_user
FILEMAKER_PASSWORD=api_password
```

In `src/referral_crm/config.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # FileMaker API (for intake submission)
    filemaker_server: Optional[str] = None
    filemaker_database: Optional[str] = None
    filemaker_layout: Optional[str] = None
    filemaker_username: Optional[str] = None
    filemaker_password: Optional[str] = None
```

### Step 5: Add FileMaker Submission Service

Create `src/referral_crm/services/filemaker_submission.py`:

```python
# Copy the FileMAkerIntakeSubmission class from:
# filemaker_extraction_implementation.py

# Update to use your config settings:

class FileMAkerIntakeSubmission:
    """Submit extracted referrals to FileMaker Data API."""
    
    def __init__(self, settings):
        self.fm_server = settings.filemaker_server
        self.fm_database = settings.filemaker_database
        self.fm_layout = settings.filemaker_layout
        self.fm_username = settings.filemaker_username
        self.fm_password = settings.filemaker_password
        self.token = None
        self.token_expires = None
    
    # ... rest of class remains the same ...
```

---

## Full Integration Flow

### Option A: Manual Review Then Submit

```python
# In your CLI or web endpoint

from referral_crm.services.extraction_service import ExtractionService
from referral_crm.services.filemaker_conversion import (
    ExtractionToFileMAkerConverter,
    FileMAkerPayloadValidator
)
from referral_crm.services.confidence_validator import ConfidenceValidator

def process_referral_for_filemaker(email_dict):
    """
    Process email → extract → validate → present for review.
    """
    
    # Stage 1: Extract
    extraction_service = ExtractionService()
    extraction = extraction_service.extract_from_email_for_filemaker(
        from_email=email_dict["from"]["address"],
        subject=email_dict.get("subject", ""),
        body=email_dict.get("body", "")
    )
    
    # Stage 2: Convert to FileMaker
    converter = ExtractionToFileMAkerConverter()
    fm_extraction = converter.convert(extraction.to_dict())
    
    # Stage 3: Validate
    validator = FileMAkerPayloadValidator()
    errors = validator.validate(fm_extraction)
    
    # Stage 4: Check confidence (should we auto-submit?)
    conf_validator = ConfidenceValidator()
    confidence_assessment = conf_validator.assess_extraction(None)  # Adapt for FM format
    
    # Stage 5: Return result
    if errors:
        return {
            "status": "validation_error",
            "errors": errors,
            "extraction": fm_extraction,
            "action": "requires_correction"
        }
    
    elif fm_extraction.extraction_confidence >= 90:
        return {
            "status": "ready",
            "extraction": fm_extraction,
            "action": "auto_submit",  # Or require human approval
            "confidence": fm_extraction.extraction_confidence
        }
    
    else:
        return {
            "status": "ready",
            "extraction": fm_extraction,
            "action": "human_review",
            "confidence": fm_extraction.extraction_confidence
        }
```

### Option B: Auto-Submit High-Confidence Records

```python
# In your CLI command:
# uv run python run.py cli auto submit-to-filemaker

from referral_crm.config import get_settings
from referral_crm.services.filemaker_submission import FileMAkerIntakeSubmission
from referral_crm.models import session_scope, Referral, ReferralStatus

def submit_to_filemaker_auto(confidence_threshold=85):
    """
    Automatically submit high-confidence referrals to FileMaker.
    """
    
    settings = get_settings()
    submission = FileMAkerIntakeSubmission(settings)
    
    with session_scope() as session:
        # Get referrals ready for FileMaker submission
        pending_refs = session.query(Referral).filter(
            Referral.status == ReferralStatus.APPROVED,
            Referral.extraction_confidence >= confidence_threshold,
            Referral.filemaker_record_id == None  # Not yet submitted
        ).limit(50).all()
        
        converter = ExtractionToFileMAkerConverter()
        validator = FileMAkerPayloadValidator()
        
        results = []
        
        for ref in pending_refs:
            # Convert extraction to FileMaker format
            fm_extraction = converter.convert(ref.extraction_data)
            
            # Validate
            errors = validator.validate(fm_extraction)
            if errors:
                print(f"✗ Referral #{ref.id} validation errors: {errors}")
                continue
            
            # Submit
            print(f"Submitting referral #{ref.id} to FileMaker...")
            fm_result = submission.submit_intake(fm_extraction)
            
            if fm_result["status"] == "success":
                # Update referral with FileMaker record ID
                ref.filemaker_record_id = fm_result["filemaker_record_id"]
                ref.status = ReferralStatus.SUBMITTED_TO_FILEMAKER
                session.commit()
                
                print(f"  ✓ FileMaker record: {fm_result['filemaker_record_id']}")
                results.append({"referral_id": ref.id, "status": "success"})
            else:
                print(f"  ✗ Error: {fm_result['error']}")
                results.append({"referral_id": ref.id, "status": "error"})
        
        print(f"\nSubmission complete: {len([r for r in results if r['status'] == 'success'])}/{len(results)} successful")
        return results
```

### Option C: Batch Submit with Review

```python
# In your CLI:
# uv run python run.py cli auto batch-submit --review-first

def batch_submit_with_review(dry_run=False):
    """
    Review pending referrals, then batch submit to FileMaker.
    """
    
    with session_scope() as session:
        pending = session.query(Referral).filter(
            Referral.status == ReferralStatus.APPROVED,
            Referral.filemaker_record_id == None
        ).all()
        
        converter = ExtractionToFileMAkerConverter()
        validator = FileMAkerPayloadValidator()
        
        print(f"\n{len(pending)} referrals ready for FileMaker submission")
        print("\nReview Summary:")
        print("-" * 70)
        
        valid_count = 0
        for i, ref in enumerate(pending, 1):
            fm_extraction = converter.convert(ref.extraction_data)
            errors = validator.validate(fm_extraction)
            
            status_icon = "✓" if not errors else "✗"
            print(f"{i}. Referral #{ref.id} {status_icon}")
            print(f"   {ref.claimant_name or 'Unknown'} - Claim: {ref.claim_number}")
            print(f"   Confidence: {fm_extraction.extraction_confidence:.0f}%")
            
            if errors:
                for error in errors:
                    print(f"   ⚠️  {error}")
            else:
                valid_count += 1
            print()
        
        print(f"Valid for submission: {valid_count}/{len(pending)}")
        
        if not dry_run and valid_count > 0:
            if input("\nProceed with submission? (y/n): ").lower() == 'y':
                submission = FileMAkerIntakeSubmission(get_settings())
                results = submission.batch_submit([
                    converter.convert(ref.extraction_data)
                    for ref in pending
                    if not validator.validate(converter.convert(ref.extraction_data))
                ])
                print(f"\nSubmitted {len(results)} referrals to FileMaker")
```

---

## Data Flow Diagram

```
Email Input
    │
    ├─ Stage 1: Ingest & Extract Text
    │
    ├─ Stage 2: LLM Extraction (FileMaker-optimized prompt)
    │  └─ Returns: {claimant_name, claim_number, carrier, ...}
    │
    ├─ Stage 3: Convert to FileMaker Fields
    │  └─ Transforms:
    │     • Split names (claimant_name → first_name + last_name)
    │     • Normalize phone: "555-123-4567" → "(555) 123-4567"
    │     • Convert dates: "1/15/2025" → "2025-01-15"
    │     • Convert states: "California" → "CA"
    │     • Parse addresses
    │
    ├─ Stage 4: Validate Against FileMaker Constraints
    │  └─ Checks:
    │     • Required fields present
    │     • Phone format matches
    │     • State codes are 2 letters
    │     • ZIP is 5 or 9 digits
    │     • Dates are YYYY-MM-DD
    │     • Emails have @
    │
    ├─ Stage 5: Confidence Assessment
    │  └─ Decides:
    │     • Auto-submit if confidence >= 90%?
    │     • Send to human review?
    │     • Escalate for manual entry?
    │
    └─ Stage 6: Submit to FileMaker
       └─ FileMaker Data API POST
          └─ Create intake record
             └─ Return FileMaker record ID
                └─ Update CRM referral with FM ID
                   └─ Mark as "Submitted to FileMaker"
```

---

## Testing Checklist

### Unit Tests

```python
# test_filemaker_conversion.py

def test_name_splitting():
    """Test name splitting."""
    transformer = FieldTransformer()
    
    assert transformer.split_full_name("John Smith") == ("John", "Smith")
    assert transformer.split_full_name("John Q Smith") == ("John", "Q Smith")
    assert transformer.split_full_name("John") == ("", "John")

def test_phone_normalization():
    """Test phone normalization."""
    transformer = FieldTransformer()
    
    assert transformer.normalize_phone("555-123-4567") == "(555) 123-4567"
    assert transformer.normalize_phone("5551234567") == "(555) 123-4567"
    assert transformer.normalize_phone("(555) 123-4567") == "(555) 123-4567"

def test_state_normalization():
    """Test state code conversion."""
    transformer = FieldTransformer()
    
    assert transformer.normalize_state("California") == "CA"
    assert transformer.normalize_state("california") == "CA"
    assert transformer.normalize_state("CA") == "CA"
    assert transformer.normalize_state("IL") == "IL"

def test_date_normalization():
    """Test date format conversion."""
    transformer = FieldTransformer()
    
    assert transformer.normalize_date("1/15/2025") == "2025-01-15"
    assert transformer.normalize_date("January 15, 2025") == "2025-01-15"
    assert transformer.normalize_date("2025-01-15") == "2025-01-15"

def test_zip_normalization():
    """Test ZIP validation."""
    transformer = FieldTransformer()
    
    assert transformer.normalize_zip("62701") == "62701"
    assert transformer.normalize_zip("62701-1234") == "62701-1234"
    assert transformer.normalize_zip("IL 62701") == "62701"
```

### Integration Tests

```python
def test_extraction_to_filemaker():
    """Test full extraction → FileMaker conversion."""
    
    sample_extraction = {
        "claimant_name": {"value": "John Smith", "confidence": 95},
        "claim_number": {"value": "WC-2025-001234", "confidence": 98},
        "carrier": {"value": "ACE Insurance", "confidence": 90},
        "service_requested": {"value": "PT Evaluation", "confidence": 85},
        "claimant_dob": {"value": "1/15/1985", "confidence": 80},
        "claimant_phone": {"value": "555-123-4567", "confidence": 85},
        "claimant_address": {"value": "123 Main, Springfield, IL 62701", "confidence": 70},
    }
    
    converter = ExtractionToFileMAkerConverter()
    fm = converter.convert(sample_extraction)
    
    assert fm.intake_client_first_name == "John"
    assert fm.intake_client_last_name == "Smith"
    assert fm.intake_claim_number == "WC-2025-001234"
    assert fm.intake_client_phone == "(555) 123-4567"
    assert fm.intake_dob == "1985-01-15"
    assert fm.patient_address_state == "IL"
    assert fm.patient_address_zip == "62701"

def test_filemaker_validation():
    """Test FileMaker payload validation."""
    
    fm = FileMAkerExtraction(
        intake_client_first_name="John",
        intake_client_last_name="Smith",
        intake_claim_number="WC-2025-001234",
        intake_client_company="ACE Insurance",
        intake_client_phone="(555) 123-4567",
        patient_address_state="IL",
        patient_address_zip="62701",
        status="Pending"
    )
    
    validator = FileMAkerPayloadValidator()
    errors = validator.validate(fm)
    
    assert len(errors) == 0, f"Validation errors: {errors}"
```

---

## Troubleshooting

### Issue: "Invalid phone format"
**Solution:** Ensure phone is normalized to `(XXX) XXX-XXXX`
```python
fm.intake_client_phone = FieldTransformer.normalize_phone(phone)
```

### Issue: "Invalid state code"
**Solution:** State must be exactly 2 letters (uppercase)
```python
fm.patient_address_state = FieldTransformer.normalize_state(state)
```

### Issue: "Invalid ZIP"
**Solution:** ZIP must be 5 or 9 digits, no letters
```python
fm.patient_address_zip = FieldTransformer.normalize_zip(zip_code)
```

### Issue: "FileMaker authentication failed"
**Solution:** Check credentials in `.env`
```python
# Debug in Python:
submission = FileMAkerIntakeSubmission(settings)
token = submission._authenticate()  # This will raise if invalid
```

### Issue: "Field not created in FileMaker"
**Solution:** Verify field names match exactly
```python
# Check field names against FileMaker schema
# They are case-sensitive!
```

---

## Performance Optimization

### Batch Processing
```python
# Process multiple referrals efficiently
fm_extractions = [
    converter.convert(ref.extraction_data)
    for ref in referrals
]

# Filter invalid ones
valid = [
    fm for fm in fm_extractions
    if not validator.validate(fm)
]

# Batch submit (respects rate limits)
submission.batch_submit(valid, max_batch=50)
```

### Caching
```python
# Cache successful submissions
ref.filemaker_record_id = fm_result["filemaker_record_id"]
ref.status = ReferralStatus.SUBMITTED_TO_FILEMAKER
# Don't resubmit the same referral
```

### Rate Limiting
```python
# FileMaker API has rate limits
# Default: 1 request every 100ms = 10/sec = 600/min
# Our batch submission includes delays:
time.sleep(0.1)  # Between requests
```

---

## Next Steps

1. ✅ Update extraction prompt
2. ✅ Add FileMaker conversion module
3. ✅ Create FileMaker submission service
4. ✅ Update config with FileMaker credentials
5. ✅ Test with sample data
6. ✅ Deploy to staging
7. ✅ Test with actual FileMaker instance
8. ✅ Monitor submissions for errors
9. ✅ Add error notifications to admin
10. ✅ Go live with auto-submission for high-confidence records
