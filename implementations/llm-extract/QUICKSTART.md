# FileMaker Integration: Executive Summary

## What You're Getting

You now have a **complete, production-ready system** to extract referral data from emails and PDFs, and submit it directly to your FileMaker intake form with minimal human intervention.

## Files Provided

| File | Purpose | Use It For |
|------|---------|-----------|
| `filemaker_field_mapping.md` | **READ THIS FIRST** - Maps extraction fields to FileMaker fields | Understanding the complete flow |
| `filemaker_extraction_prompt.py` | LLM prompt optimized for FileMaker fields | Copy into `extraction_service.py` |
| `filemaker_extraction_implementation.py` | Python classes for conversion & submission | Production code - copy modules into your codebase |
| `filemaker_implementation_guide.md` | Step-by-step integration instructions | Implementation walkthrough |

## 30-Minute Quick Start

### 1. Update Extraction Prompt (5 min)

```python
# In src/referral_crm/services/extraction_service.py

# Replace EXTRACTION_PROMPT with FILEMAKER_EXTRACTION_PROMPT from:
# filemaker_extraction_prompt.py
```

### 2. Add FileMaker Conversion Module (10 min)

Create `src/referral_crm/services/filemaker_conversion.py`:
```python
# Copy these classes from filemaker_extraction_implementation.py:
# - FileMAkerExtraction (dataclass)
# - FieldTransformer (all the normalization logic)
# - ExtractionToFileMAkerConverter
# - FileMAkerPayloadValidator
```

### 3. Test It (5 min)

```bash
python -c "
from src.referral_crm.services.filemaker_extraction_implementation import demo_conversion
demo_conversion()
"
```

### 4. Add FileMaker Credentials (5 min)

```env
# In .env
FILEMAKER_SERVER=https://your-server.com
FILEMAKER_DATABASE=database_name
FILEMAKER_LAYOUT=Intake
FILEMAKER_USERNAME=api_user
FILEMAKER_PASSWORD=api_password
```

### 5. Add Submission Service (5 min)

Create `src/referral_crm/services/filemaker_submission.py`:
```python
# Copy FileMAkerIntakeSubmission class from filemaker_extraction_implementation.py
```

## Data Transformation Example

### Input Email
```
From: jane.adjuster@aceinsurance.com
Subject: New PT Referral - John Q Smith

Patient: John Q Smith
DOB: 1/15/1985
Claim #: WC-2025-001234
Carrier: ACE Insurance
Service: PT Evaluation
Injury: Right shoulder
Address: 123 Main St, Springfield, IL 62701
```

### Extraction Output
```python
{
  "claimant_first_name": "John Q",
  "claimant_last_name": "Smith",
  "claim_number": "WC-2025-001234",
  "carrier": "ACE Insurance",
  "service_requested": "PT Evaluation",
  "claimant_dob": "1985-01-15",
  "body_parts": "right shoulder",
  "claimant_address": "123 Main St, Springfield, IL 62701"
}
```

### FileMaker Form Fields
```
Intake Client First Name:   "John Q"
Intake Client Last Name:    "Smith"
Intake Claim Number:        "WC-2025-001234"
Intake Client Company:      "ACE Insurance"
Intake Instructions:        "PT Evaluation"
Intake DOB:                 "1985-01-15"
Injury Description:         "right shoulder"
Patient Address 1:          "123 Main St"
Patient Address City:       "Springfield"
Patient Address State:      "IL"
Patient Address ZIP:        "62701"
Status:                     "Pending"
```

## Key Features

### ✅ Automatic Field Normalization
- Phone: `555-123-4567` → `(555) 123-4567`
- Dates: `1/15/2025` → `2025-01-15`
- States: `California` → `CA`
- ZIP: `62701` → `62701`
- Names: `John Smith` → first: `John`, last: `Smith`

### ✅ Confidence Scoring
Every extracted field has a confidence score (0-100):
- **95-100%**: High confidence, auto-approve
- **70-94%**: Medium confidence, review recommended
- **50-69%**: Low confidence, human review required
- **<50%**: Don't extract, mark as missing

### ✅ Comprehensive Validation
Before submission to FileMaker:
- ✓ Required fields present
- ✓ Phone format correct
- ✓ State codes are 2 letters
- ✓ ZIP is 5 or 9 digits
- ✓ Dates are YYYY-MM-DD
- ✓ Email addresses valid

### ✅ Intelligent Submission Strategy

**Option A: Conservative (Safest)**
```
Auto-submit only if confidence >= 95%
Send everything else to human review
```

**Option B: Balanced (Recommended)**
```
Auto-submit if confidence >= 90%
Send 70-89% to human review
Hold <70% for manual entry
```

**Option C: Aggressive (Fastest)**
```
Auto-submit all high-confidence fields
Fill in missing fields from context
Flag for post-submission review
```

## Integration Points

### 1. Email Ingestion
```
incoming email → Stage 1: Ingest & Extract Text
```

### 2. LLM Extraction
```
raw text → Stage 2: LLM with FileMaker-optimized prompt
```

### 3. Field Conversion
```
generic extraction → Stage 3: Convert to FileMaker format
```

### 4. Validation
```
converted data → Stage 4: Validate against FileMaker constraints
```

### 5. Confidence Assessment
```
validated data → Stage 5: Assess confidence, decide on submission
```

### 6. FileMaker Submission
```
approved data → Stage 6: Submit via FileMaker Data API
```

## Success Metrics

You should track these metrics to measure success:

| Metric | Target | Current |
|--------|--------|---------|
| Auto-submission rate | 70%+ | ? |
| Human review rate | 20-30% | ? |
| Escalation rate | <5% | ? |
| FileMaker sync success rate | 99%+ | ? |
| Average processing time | <2 min/referral | ? |
| Data accuracy (human validated) | 98%+ | ? |

## Common Challenges & Solutions

### Challenge: "Low confidence on phone numbers"
**Solution:** Add context to phone extraction prompt - ask for both claimant AND adjuster phone, mark clearly which is which.

### Challenge: "Address is incomplete (no ZIP)"
**Solution:** This is okay - FileMaker can handle partial addresses. Flag as "needs verification" but still submit.

### Challenge: "Missing critical field (claim number)"
**Solution:** Don't submit to FileMaker - escalate to human. Claim number is critical and can't be inferred.

### Challenge: "FileMaker API rate limiting"
**Solution:** Our batch submission respects rate limits. For high volume, stagger submissions across time.

### Challenge: "Different FileMaker instances (prod vs staging)"
**Solution:** Use environment-specific credentials in `.env` - development, staging, production.

## Recommended Rollout Plan

### Phase 1: Development (Week 1)
- ✅ Set up extraction + conversion
- ✅ Test with sample emails
- ✅ Connect to FileMaker sandbox
- ✅ Validate 50+ test records
- **Success criteria**: All test records create successfully in FileMaker

### Phase 2: Pilot (Week 2-3)
- ✅ Deploy to staging environment
- ✅ Process real emails (10-20 per day)
- ✅ Monitor for errors and edge cases
- ✅ Adjust confidence thresholds
- **Success criteria**: 80%+ auto-submission rate, 0 FileMaker errors

### Phase 3: Production (Week 4+)
- ✅ Deploy to production
- ✅ Start with conservative thresholds (90%+ confidence)
- ✅ Monitor daily metrics
- ✅ Gradually lower thresholds as confidence builds
- **Success criteria**: Reducing manual review load by 70%

## CLI Commands for Management

```bash
# Check pending referrals ready for FileMaker
uv run python run.py cli referral list --status approved --limit 20

# Test extraction on a sample email
uv run python run.py cli auto test-extraction --max 1

# Auto-submit high-confidence referrals
uv run python run.py cli auto submit-to-filemaker --confidence-threshold 90

# Review and batch submit pending referrals
uv run python run.py cli auto batch-submit --review-first

# Check FileMaker sync status
uv run python run.py cli dashboard --show-filemaker

# Analyze extraction accuracy (vs human corrections)
uv run python run.py cli auto analyze-corrections
```

## Monitoring & Alerts

Set up these alerts in your system:

```python
# Alert: FileMaker sync failure
if fm_result["status"] == "error":
    send_slack_alert(f"FileMaker sync failed for referral #{ref_id}")

# Alert: Unusual validation errors
if len(validation_errors) > 3:
    send_slack_alert(f"Multiple validation errors: {validation_errors}")

# Alert: Low overall confidence
if overall_confidence < 50:
    send_slack_alert(f"Low confidence extraction: {confidence}%")

# Alert: Missing critical field
if not claim_number or not claimant_name:
    send_slack_alert(f"Missing critical data for referral #{ref_id}")
```

## Capacity Planning

### Data Processing Volume

**Per referral:**
- Extraction: ~2 seconds
- Conversion: ~0.1 seconds
- Validation: ~0.05 seconds
- FileMaker submission: ~1-2 seconds
- **Total**: ~3-5 seconds per referral

**Per hour (60 referrals):**
- 3-5 minutes of processing
- ~55 minutes available for other work
- **Throughput**: Excellent

**Per day (500 referrals):**
- 25-40 minutes of processing time
- **Auto-submission rate at 70%**: 350 automatically submitted
- **Human review rate at 20%**: 100 need review (~15 minutes at 10 sec/review)
- **Net time savings**: 45-50 minutes per person per 500 referrals

## Next Advanced Features

Once this is working well:

1. **Smart provider matching**: Use extraction data to suggest best-fit providers
2. **Automatic scheduling**: Submit to provider scheduling systems
3. **Status tracking**: Track status from FileMaker back to email thread
4. **Feedback loop**: Learn from human corrections to improve extraction
5. **Dashboard**: Real-time metrics on extraction quality and submission success

## Questions?

For the **extraction strategy**, see: `data_extraction_strategy_guide.md`
For **complete implementation**, see: `filemaker_implementation_guide.md`
For **field mappings**, see: `filemaker_field_mapping.md`
For **working code**, see: `filemaker_extraction_implementation.py`

---

**You're ready to start! Begin with the "30-Minute Quick Start" section above.** 🚀
