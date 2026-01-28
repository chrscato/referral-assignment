# Referral CRM Implementation Plan

## System Overview

A workers' compensation referral processing system that:
1. Ingests referral emails from Outlook
2. Extracts data using LLM (Claude)
3. Routes through a queue-based workflow for human validation
4. Submits validated records to FileMaker

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           REFERRAL WORKFLOW                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  [OUTLOOK INBOX]                                                         │
│        │                                                                 │
│        ▼                                                                 │
│  ┌──────────────┐     ┌──────────────────┐                              │
│  │ EMAILS TABLE │────▶│ EXTRACTION QUEUE │  (15 min SLA)                │
│  └──────────────┘     └────────┬─────────┘                              │
│        │                       │                                         │
│        │              LLM extracts data                                  │
│        │              Creates Referral + LineItems                       │
│        │                       │                                         │
│        ▼                       ▼                                         │
│  ┌──────────────┐     ┌──────────────────┐                              │
│  │  REFERRALS   │◀────│   INTAKE QUEUE   │  (60 min SLA)                │
│  │  LINE ITEMS  │     │  (Intake Worker) │                              │
│  └──────────────┘     └────────┬─────────┘                              │
│                                │                                         │
│                       Worker validates data                              │
│                       Corrects fields, sets RX flag                      │
│                       Clicks "Approve"                                   │
│                                │                                         │
│                                ▼                                         │
│                       ┌──────────────────────┐                          │
│                       │ CARE COORDINATION Q  │  (240 min SLA)           │
│                       │ (Care Coordinator)   │                          │
│                       └────────┬─────────────┘                          │
│                                │                                         │
│                       Assigns provider                                   │
│                       Schedules appointment                              │
│                       Sends confirmation                                 │
│                                │                                         │
│                                ▼                                         │
│                       ┌──────────────────┐                              │
│                       │    FILEMAKER     │                              │
│                       │    SUBMISSION    │                              │
│                       └──────────────────┘                              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Status

### Stage 1: Data Infrastructure ✅ COMPLETE

| Component | Status | Evidence |
|-----------|--------|----------|
| Database schema redesign | ✅ Done | `src/referral_crm/models/` - Email, Referral, LineItem, Queue models |
| Email/Referral separation | ✅ Done | `models/email.py` - Email table with attachments |
| Line items for services | ✅ Done | `models/referral.py` - ReferralLineItem model |
| Queue system | ✅ Done | `models/queue.py` - Queue, QueueItem models |
| Dimension tables | ✅ Done | `models/dimensions.py` - DimICD10, DimProcedureCode, DimServiceType, DimBodyRegion |
| Enum definitions | ✅ Done | `models/enums.py` - EmailStatus, ReferralStatus, QueueType, etc. |

**Database Tables:**
- `emails` - Raw email records with Graph API IDs
- `attachments` - Linked to emails, document classification
- `extraction_results` - LLM extraction output stored as JSON
- `referrals` - Patient/claim data aligned with field_list.csv
- `referral_line_items` - Individual services with ICD-10/CPT codes
- `queues` - Queue definitions with SLA
- `queue_items` - Work items in each queue
- `dim_icd10`, `dim_procedure_codes`, `dim_service_types`, `dim_body_regions`

### Stage 2: Email Ingestion ✅ COMPLETE

| Component | Status | Evidence |
|-----------|--------|----------|
| MS Graph API integration | ✅ Done | `services/email_service.py` |
| Email polling | ✅ Done | `automations/email_ingestion.py` - EmailPoller class |
| Attachment handling | ✅ Done | Downloads, extracts text from PDFs/images |
| S3 storage | ✅ Done | `services/storage_service.py` |
| Duplicate detection | ✅ Done | Checks by `graph_id` before processing |

**Capabilities:**
- Polls Outlook inbox at configurable interval
- Creates Email records with full metadata
- Downloads attachments (skips logos/images)
- Extracts text from PDFs using PyMuPDF
- Stores raw email HTML and extraction results in S3

### Stage 3: LLM Extraction ✅ COMPLETE

| Component | Status | Evidence |
|-----------|--------|----------|
| Extraction prompt | ✅ Done | `services/extraction_service.py` |
| Field definitions | ✅ Done | `services/extraction_fields.py` - 30+ fields with metadata |
| Confidence scoring | ✅ Done | Per-field confidence 0-100 |
| Step 2 reasoning | ✅ Done | `services/reasoning_service.py` - ICD-10 validation, procedure code lookup |
| Line item parsing | ✅ Done | `services/line_item_service.py` - Parses service_requested into structured items |

**Extracted Fields (from field_list.csv):**
- Referring physician (name, NPI)
- Adjuster info (name, phone, email, company)
- Claim info (number, jurisdiction state, order type)
- Patient demographics (name, DOB, DOI, gender, phone, email, SSN)
- Patient address (address 1/2, city, state, ZIP)
- Employer info (name, job title, address)
- Service info (service_requested, ICD-10 code/desc, suggested providers, special requirements)

**Step 2 Reasoning (automatic, no LLM):**
- Validates ICD-10 codes against `dim_icd10` table
- Looks up procedure codes in `dim_procedure_codes` based on service type
- Adds category/body region metadata

### Stage 4: FileMaker Integration ⚠️ PARTIALLY COMPLETE

| Component | Status | Evidence |
|-----------|--------|----------|
| Field mapping documentation | ✅ Done | `implementations/llm-extract/filemaker_field_mapping.md` |
| Conversion classes | ✅ Done | `services/filemaker_conversion.py` - FieldTransformer, validator |
| Field normalization | ✅ Done | Phone, date, state, ZIP, name splitting |
| Payload validation | ✅ Done | FileMakerPayloadValidator class |
| FileMaker API submission | ❌ TODO | Need FileMaker Data API integration |

**What's built:**
- `FileMakerExtraction` dataclass matching FileMaker fields
- `FieldTransformer` with normalization methods
- `ExtractionToFileMakerConverter` to map extraction → FileMaker
- `FileMakerPayloadValidator` to validate before submission

**What's missing:**
- `FileMakerIntakeSubmission` class (API client)
- Actual FileMaker credentials/connection
- Batch submission capability
- Error handling/retry logic

### Stage 5: Queue Workflow ⚠️ PARTIALLY COMPLETE

| Component | Status | Evidence |
|-----------|--------|----------|
| Queue definitions | ✅ Done | 3 queues seeded: extraction (15min), intake (60min), care_coordination (240min) |
| WorkflowService | ✅ Done | `services/workflow_service.py` - queue transitions |
| Queue API endpoints | ❌ TODO | Need endpoints to list/claim queue items |
| Worker assignment | ❌ TODO | No user authentication or assignment system |
| SLA tracking | ⚠️ Partial | Schema supports it, no alerts/dashboards |

**WorkflowService Methods:**
- `queue_email_for_extraction(email)` - Add to extraction queue
- `start_extraction(email)` - Mark as in progress
- `complete_extraction_and_queue_for_intake(email, referral, line_items)` - Create referral, queue for intake
- `validate_and_queue_for_scheduling(referral)` - Move to care coordination queue
- `complete_scheduling(referral)` - Mark as scheduled

### Stage 6: Human Review UI ❌ NOT STARTED

| Component | Status | Evidence |
|-----------|--------|----------|
| Intake worker dashboard | ❌ TODO | Basic dashboard exists but not role-specific |
| Field editing form | ❌ TODO | Need editable form for extracted fields |
| Attachment viewer | ⚠️ Partial | S3 URLs generated but UI incomplete |
| RX flag assignment | ❌ TODO | Field exists but no UI |
| Approve/Reject workflow | ⚠️ Partial | API exists (`/validate`, `/reject`) |

**Current UI:**
- Basic dashboard at `/` showing referral counts
- Review page at `/review/{id}` showing referral details
- Missing: field editing, line item editing, RX flag, document viewer

### Stage 7: Care Coordination ❌ NOT STARTED

| Component | Status | Evidence |
|-----------|--------|----------|
| Care coordinator queue UI | ❌ TODO | |
| Provider matching | ⚠️ Partial | `services/provider_service.py` exists |
| Scheduling workflow | ❌ TODO | |
| Appointment confirmation | ❌ TODO | |

---

## Remaining Work

### Priority 1: Complete Intake Workflow (Stage 1 from original plan)

1. **Intake Worker UI**
   - [ ] Queue dashboard showing items assigned to current worker
   - [ ] Editable form for all extracted fields
   - [ ] Side-by-side view: extracted data | original email/attachments
   - [ ] Line item editor (add/edit/remove services)
   - [ ] RX flag checkbox per line item or referral
   - [ ] Approve button → moves to care coordination queue
   - [ ] Reject button with reason → marks as rejected

2. **Worker Assignment System**
   - [ ] User authentication (simple user table or OAuth)
   - [ ] Queue item claiming (assign to user)
   - [ ] Unclaim/reassign functionality
   - [ ] SLA warnings (item approaching due time)

3. **Document Handling**
   - [ ] Encrypted PDF detection
   - [ ] Password entry UI for encrypted documents
   - [ ] Re-extraction after password applied

### Priority 2: Care Coordination (Stage 2 from original plan)

1. **Care Coordinator Queue UI**
   - [ ] Different view than intake (scheduling-focused)
   - [ ] Provider selection/search
   - [ ] Appointment scheduling interface
   - [ ] Confirmation email generation

2. **Provider Matching Enhancements**
   - [ ] Filter by service type, location, availability
   - [ ] Rate schedule lookup
   - [ ] Provider preference tracking

### Priority 3: FileMaker Submission

1. **FileMaker API Integration**
   - [ ] Add FileMaker credentials to config
   - [ ] Implement `FileMakerIntakeSubmission` class
   - [ ] Add submission endpoint/command
   - [ ] Track `filemaker_record_id` on referral

2. **Submission Workflow**
   - [ ] Auto-submit high-confidence (>90%) records
   - [ ] Manual submit for reviewed records
   - [ ] Error handling with retry

### Priority 4: Monitoring & Operations

1. **Dashboard Enhancements**
   - [ ] Real-time queue counts by status
   - [ ] SLA breach alerts
   - [ ] Extraction confidence trends
   - [ ] Daily/weekly processing stats

2. **Admin Functions**
   - [ ] Manual referral creation
   - [ ] Bulk operations (approve multiple, reassign)
   - [ ] Audit log viewer

---

## File Reference

### Models (`src/referral_crm/models/`)
| File | Purpose |
|------|---------|
| `base.py` | SQLAlchemy base, session management |
| `enums.py` | All enum definitions |
| `email.py` | Email, Attachment, ExtractionResult |
| `referral.py` | Referral, ReferralLineItem, Carrier, Provider, AuditLog |
| `queue.py` | Queue, QueueItem |
| `dimensions.py` | DimICD10, DimProcedureCode, DimServiceType, DimBodyRegion |

### Services (`src/referral_crm/services/`)
| File | Purpose |
|------|---------|
| `email_service.py` | MS Graph API integration |
| `extraction_service.py` | LLM extraction with Claude |
| `extraction_fields.py` | Field definitions for extraction |
| `reasoning_service.py` | Step 2 ICD-10/procedure enrichment |
| `reference_data.py` | ICD-10 and procedure code lookups |
| `line_item_service.py` | Parse services into line items |
| `workflow_service.py` | Queue management and transitions |
| `filemaker_conversion.py` | Convert extraction → FileMaker format |
| `referral_service.py` | Referral CRUD operations |
| `storage_service.py` | S3 storage for emails/attachments |
| `provider_service.py` | Provider lookup and matching |

### Automations (`src/referral_crm/automations/`)
| File | Purpose |
|------|---------|
| `email_ingestion.py` | EmailIngestionPipeline, EmailPoller |

### API (`src/referral_crm/api/`)
| File | Purpose |
|------|---------|
| `main.py` | FastAPI application with all endpoints |

---

## Configuration

### Required Environment Variables
```env
# Database
DATABASE_URL=sqlite:///./referral_crm.db

# MS Graph API (Outlook)
GRAPH_CLIENT_ID=xxx
GRAPH_CLIENT_SECRET=xxx
GRAPH_TENANT_ID=xxx
GRAPH_MAILBOX=referrals@company.com

# Claude API
ANTHROPIC_API_KEY=xxx
CLAUDE_MODEL=claude-sonnet-4-20250514

# AWS S3 (optional)
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
S3_BUCKET_NAME=referral-crm

# FileMaker (TODO)
FILEMAKER_SERVER=https://server.com
FILEMAKER_DATABASE=database
FILEMAKER_LAYOUT=Intake
FILEMAKER_USERNAME=user
FILEMAKER_PASSWORD=pass
```

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Email → Extraction time | <30 sec | ~5 sec |
| Extraction accuracy | >90% | Unknown (needs testing) |
| Auto-validation rate | >70% | N/A (no auto-validate yet) |
| Human review time | <2 min | N/A |
| FileMaker sync success | >99% | N/A |

---

## Next Steps

1. **Immediate**: Build intake worker review UI with editable fields
2. **Short-term**: Add worker authentication and queue claiming
3. **Medium-term**: Care coordination scheduling workflow
4. **Later**: FileMaker API integration when credentials available
