# Referral Assignment System
## Strategic Implementation Plan

**Purpose:** Transform unstructured workers' compensation referral emails into standardized intake records for FileMaker order submission, with human-in-the-loop validation.

**Core Philosophy:** Automate the tedious, validate the critical, empower the adjuster.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REFERRAL ASSIGNMENT FLOW                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐  │
│   │ Adjuster │───▶│ Intake Email │───▶│  LLM Parse   │───▶│  CRM Queue  │  │
│   │  Email   │    │   Mailbox    │    │  + Extract   │    │  (Pending)  │  │
│   └──────────┘    └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                                             │
│                                              │                              │
│                                              ▼                              │
│                                                                             │
│   ┌──────────┐    ┌──────────────┐    ┌──────────────┐                     │
│   │ FileMaker│◀───│   Approved   │◀───│Human Review &│                     │
│   │  Submit  │    │    Record    │    │  Validation  │                     │
│   └──────────┘    └──────────────┘    └──────────────┘                     │
│                           │                  │                              │
│                           │                  ▼                              │
│                           │          ┌──────────────┐                      │
│                           │          │ Reply/Follow │                      │
│                           │          │  Up (Outlook)│                      │
│                           │          └──────────────┘                      │
│                           ▼                                                 │
│                   ┌──────────────┐                                         │
│                   │  Rate Lookup │                                         │
│                   │  & Pre-Map   │                                         │
│                   └──────────────┘                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Model

### 2.1 Referral Record (Core Entity)

| Field | Source | Confidence | Editable |
|-------|--------|------------|----------|
| `referral_id` | System Generated | 100% | No |
| `email_id` | Graph API | 100% | No |
| `email_web_link` | Graph API | 100% | No |
| `received_at` | Graph API | 100% | No |
| `adjuster_name` | LLM Extracted | Variable | Yes |
| `adjuster_email` | Graph API (From) | 100% | Yes |
| `adjuster_phone` | LLM Extracted | Variable | Yes |
| `insurance_carrier` | LLM Extracted | Variable | Yes |
| `claim_number` | LLM Extracted | Variable | Yes |
| `claimant_name` | LLM Extracted | Variable | Yes |
| `claimant_dob` | LLM Extracted | Variable | Yes |
| `claimant_phone` | LLM Extracted | Variable | Yes |
| `claimant_address` | LLM Extracted | Variable | Yes |
| `employer_name` | LLM Extracted | Variable | Yes |
| `date_of_injury` | LLM Extracted | Variable | Yes |
| `body_parts` | LLM Extracted | Variable | Yes |
| `service_requested` | LLM Extracted | Variable | Yes |
| `authorization_number` | LLM Extracted | Variable | Yes |
| `priority` | LLM Inferred | Variable | Yes |
| `notes` | LLM Extracted | Variable | Yes |
| `status` | System | 100% | Yes |
| `assigned_provider` | Rate Lookup / Manual | Variable | Yes |
| `rate_schedule` | Rate Lookup | Variable | Yes |

### 2.2 Status Workflow

```
PENDING → IN_REVIEW → APPROVED → SUBMITTED_TO_FILEMAKER → COMPLETED
                   ↘ NEEDS_INFO (sends reply) → back to IN_REVIEW
                   ↘ REJECTED (with reason)
```

### 2.3 Attachment Records

| Field | Description |
|-------|-------------|
| `attachment_id` | System Generated |
| `referral_id` | FK to Referral |
| `filename` | Original filename |
| `content_type` | MIME type |
| `size_bytes` | File size |
| `storage_path` | Local/cloud storage path |
| `extracted_text` | OCR/parsed content |
| `document_type` | LLM classified (auth letter, medical records, etc.) |

---

## 3. Technical Architecture

### 3.1 Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **Frontend** | React / Next.js | Fast, component-based, good form handling |
| **Backend API** | Node.js / Python FastAPI | Async-friendly for LLM calls |
| **Database** | PostgreSQL | Relational integrity, JSON support for flexibility |
| **Email Integration** | Microsoft Graph API | Native O365/Outlook support |
| **LLM Processing** | Claude API | Superior extraction from unstructured text |
| **File Storage** | Azure Blob / S3 | Scalable attachment storage |
| **FileMaker Integration** | FileMaker Data API | REST-based record creation |

### 3.2 Microsoft Graph API Integration

#### Required Permissions
```
Mail.Read
Mail.ReadWrite
Mail.Send
User.Read
```

#### Key Endpoints
```
GET  /me/messages                          # List inbox
GET  /me/messages/{id}                     # Get specific email
GET  /me/messages/{id}/attachments         # Get attachments
POST /me/messages/{id}/reply               # Send reply
POST /me/messages/{id}/forward             # Forward email
```

#### Storing Email References
```javascript
// When ingesting email, store these for later linking
const emailRecord = {
  graph_message_id: message.id,              // For API operations
  internet_message_id: message.internetMessageId, // For threading
  web_link: message.webLink,                 // For user click-through
  conversation_id: message.conversationId    // For grouping threads
};
```

### 3.3 LLM Extraction Prompt Strategy

```markdown
## Extraction Prompt Template

You are a workers' compensation intake specialist. Extract structured data 
from the following referral email and attachments.

**Source Email:**
{email_body}

**Attachment Contents:**
{attachment_texts}

**Extract the following fields. If not found, return null. Include a 
confidence score (0-100) for each field.**

Return JSON in this exact format:
{
  "adjuster_name": { "value": "", "confidence": 0, "source": "email|attachment" },
  "claim_number": { "value": "", "confidence": 0, "source": "" },
  // ... etc
}

**Extraction Rules:**
- Claim numbers often follow patterns like: XX-XXXXX, XXXX-XXXXXX
- Phone numbers: normalize to (XXX) XXX-XXXX
- Dates: normalize to YYYY-MM-DD
- Body parts: use standard medical terminology
- If multiple values found, choose most recent/authoritative
```

---

## 4. User Interface Design

### 4.1 Main Queue View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  REFERRAL ASSIGNMENT QUEUE                              [Filter ▼] [Search] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─ Pending (12) ──────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  ⚡ HIGH  │ John Smith      │ ACE Insurance   │ 2 min ago  │ [Open] │   │
│  │  ── MED  │ Jane Doe        │ Travelers       │ 15 min ago │ [Open] │   │
│  │  ── LOW  │ Bob Johnson     │ Liberty Mutual  │ 1 hr ago   │ [Open] │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─ In Review (3) ─────────────────────────────────────────────────────┐   │
│  │  ...                                                                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Referral Detail / Review Screen

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  REFERRAL: John Smith - Claim #WC-2024-12345                    [← Back]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─ Email Actions ─────────────────────────────────────────────────────┐   │
│  │  [📧 View Original Email]  [↩️ Reply to Adjuster]  [➡️ Forward]      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─ LEFT PANEL: Source ────────────┐  ┌─ RIGHT PANEL: Extracted ───────┐  │
│  │                                  │  │                                │  │
│  │  📧 Original Email               │  │  Claimant Information          │  │
│  │  ─────────────────────           │  │  ─────────────────────         │  │
│  │  From: adjuster@carrier.com      │  │  Name: [John Smith      ] ✓95% │  │
│  │  Subject: New Referral - Smith   │  │  DOB:  [1985-03-15      ] ✓90% │  │
│  │                                  │  │  Phone:[(555) 123-4567  ] ✓85% │  │
│  │  Please schedule PT eval for     │  │  Address: [123 Main St  ] ⚠️60% │  │
│  │  John Smith, DOB 3/15/85...      │  │                                │  │
│  │                                  │  │  Claim Information             │  │
│  │  ─────────────────────           │  │  ─────────────────────         │  │
│  │  📎 Attachments (3)              │  │  Claim #: [WC-2024-12345] ✓99% │  │
│  │  • Authorization.pdf  [View]     │  │  DOI:     [2024-01-10   ] ✓95% │  │
│  │  • MedRecords.pdf     [View]     │  │  Carrier: [ACE Insurance] ✓98% │  │
│  │  • Script.jpg         [View]     │  │  Body Parts: [L Shoulder ] ✓88%│  │
│  │                                  │  │                                │  │
│  │                                  │  │  Service Request               │  │
│  │                                  │  │  ─────────────────────         │  │
│  │                                  │  │  Type: [PT Evaluation ▼] ✓92%  │  │
│  │                                  │  │  Auth#: [AUTH-9876     ] ✓97%  │  │
│  │                                  │  │                                │  │
│  │                                  │  │  Provider Assignment           │  │
│  │                                  │  │  ─────────────────────         │  │
│  │                                  │  │  Provider: [Select...    ▼]    │  │
│  │                                  │  │  Rate: $XXX (auto-populated)   │  │
│  │                                  │  │                                │  │
│  └──────────────────────────────────┘  └────────────────────────────────┘  │
│                                                                             │
│  ┌─ Actions ───────────────────────────────────────────────────────────┐   │
│  │  [✅ Approve & Submit to FileMaker]  [❓ Request Info]  [❌ Reject]  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Confidence Indicators

| Score | Display | Action |
|-------|---------|--------|
| 90-100% | ✓ Green | Auto-filled, minimal review needed |
| 70-89% | ⚠️ Yellow | Review recommended, may need correction |
| Below 70% | ❌ Red | Requires manual entry/verification |

---

## 5. Email Integration Features

### 5.1 View Original Email

```javascript
// Store webLink from Graph API during ingestion
const openEmail = (webLink) => {
  window.open(webLink, '_blank');
};

// Button component
<button onClick={() => openEmail(referral.email_web_link)}>
  📧 View Original Email
</button>
```

### 5.2 Reply to Adjuster

**Option A: Open Outlook with Pre-filled Reply**
```javascript
const replyToAdjuster = (referral) => {
  const subject = encodeURIComponent(`RE: ${referral.original_subject}`);
  const body = encodeURIComponent(`
Hi ${referral.adjuster_name},

Thank you for the referral for ${referral.claimant_name}.

[Your message here]

Best regards,
[Your Network Name]
  `);
  
  // Opens Outlook Web compose
  const url = `https://outlook.office.com/mail/deeplink/compose?to=${referral.adjuster_email}&subject=${subject}&body=${body}`;
  window.open(url, '_blank');
};
```

**Option B: Send via Graph API (keeps in thread)**
```javascript
// POST /me/messages/{id}/reply
const sendReply = async (messageId, replyBody) => {
  await graphClient
    .api(`/me/messages/${messageId}/reply`)
    .post({
      comment: replyBody
    });
};
```

**Option C: In-App Reply Modal**
```
┌─────────────────────────────────────────────────────────────────┐
│  Reply to Adjuster                                    [X Close] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  To: adjuster@carrier.com                                       │
│  Subject: RE: New Referral - John Smith                         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Hi [Adjuster Name],                                      │   │
│  │                                                          │   │
│  │ Thank you for the referral. We need the following        │   │
│  │ additional information:                                  │   │
│  │                                                          │   │
│  │ • [Template options / free text]                         │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [📎 Attach Files]                                              │
│                                                                 │
│  Quick Templates:                                               │
│  [Missing Auth] [Need DOB] [Clarify Body Part] [Custom...]      │
│                                                                 │
│  [Send Reply]  [Send & Mark as Needs Info]                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Reply Templates

Pre-built templates for common scenarios:

```javascript
const replyTemplates = {
  missing_auth: {
    label: "Missing Authorization",
    body: `We've received your referral for {claimant_name}. To proceed, we'll need a copy of the authorization letter. Please reply with this document attached.`
  },
  clarify_service: {
    label: "Clarify Service Type",
    body: `Thank you for the referral. Could you please clarify the specific service being requested? We want to ensure we match {claimant_name} with the appropriate provider.`
  },
  need_dob: {
    label: "Missing Date of Birth",
    body: `We're processing the referral for {claimant_name}. We need the claimant's date of birth to proceed. Could you please provide this?`
  },
  confirmation: {
    label: "Referral Received",
    body: `This confirms receipt of your referral for {claimant_name} (Claim #{claim_number}). We're processing this and will have scheduling information shortly.`
  }
};
```

---

## 6. Rate Lookup & Provider Mapping

### 6.1 Rate Tables

```sql
-- Example rate table structure
CREATE TABLE rate_schedules (
  id SERIAL PRIMARY KEY,
  carrier_id INTEGER REFERENCES carriers(id),
  service_type VARCHAR(50),
  body_region VARCHAR(50),
  state VARCHAR(2),
  rate_amount DECIMAL(10,2),
  effective_date DATE,
  expiration_date DATE
);

-- Provider capabilities
CREATE TABLE provider_services (
  provider_id INTEGER REFERENCES providers(id),
  service_type VARCHAR(50),
  accepting_new BOOLEAN,
  avg_wait_days INTEGER
);
```

### 6.2 Auto-Matching Logic

```python
def suggest_provider(referral):
    """
    Match referral to best available provider based on:
    1. Service type capability
    2. Geographic proximity to claimant
    3. Carrier network participation
    4. Current availability/wait times
    5. Rate schedule compatibility
    """
    candidates = Provider.query.filter(
        Provider.services.contains(referral.service_requested),
        Provider.accepting_new == True,
        Provider.state == referral.claimant_state
    ).all()
    
    # Score and rank
    scored = [(p, score_provider(p, referral)) for p in candidates]
    return sorted(scored, key=lambda x: x[1], reverse=True)[:5]
```

---

## 7. FileMaker Integration

### 7.1 FileMaker Data API

```javascript
// Authentication
const fmAuth = await fetch(`${FM_SERVER}/fmi/data/v1/databases/${DB}/sessions`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Basic ${base64Credentials}`
  }
});
const { token } = await fmAuth.json();

// Create Record
const createOrder = async (referral) => {
  const response = await fetch(
    `${FM_SERVER}/fmi/data/v1/databases/${DB}/layouts/${LAYOUT}/records`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        fieldData: mapReferralToFileMaker(referral)
      })
    }
  );
  return response.json();
};
```

### 7.2 Field Mapping

```javascript
const mapReferralToFileMaker = (referral) => ({
  // FileMaker Field: CRM Field
  'Claimant_Name': referral.claimant_name,
  'Claimant_DOB': referral.claimant_dob,
  'Claimant_Phone': referral.claimant_phone,
  'Claim_Number': referral.claim_number,
  'Carrier_Name': referral.insurance_carrier,
  'Adjuster_Name': referral.adjuster_name,
  'Adjuster_Email': referral.adjuster_email,
  'Date_of_Injury': referral.date_of_injury,
  'Body_Parts': referral.body_parts,
  'Service_Type': referral.service_requested,
  'Auth_Number': referral.authorization_number,
  'Provider_ID': referral.assigned_provider?.id,
  'Rate_Amount': referral.rate_schedule?.rate_amount,
  'Source_Email_ID': referral.email_id,
  'Created_From': 'Referral_Assignment_CRM'
});
```

---

## 8. Implementation Phases

### Phase 1: Foundation (Weeks 1-3)
- [ ] Set up project structure and database
- [ ] Implement Microsoft Graph API integration
- [ ] Build email ingestion pipeline (polling/webhooks)
- [ ] Create basic queue UI

### Phase 2: LLM Integration (Weeks 4-5)
- [ ] Design and test extraction prompts
- [ ] Implement attachment processing (OCR for images/PDFs)
- [ ] Build confidence scoring system
- [ ] Create extracted data review UI

### Phase 3: Human Review Interface (Weeks 6-7)
- [ ] Build side-by-side source/extracted view
- [ ] Implement inline editing with validation
- [ ] Add email action buttons (view, reply, forward)
- [ ] Create reply templates system

### Phase 4: Provider & Rate Mapping (Week 8)
- [ ] Import rate schedules
- [ ] Build provider matching algorithm
- [ ] Create provider selection UI
- [ ] Auto-populate rates

### Phase 5: FileMaker Integration (Weeks 9-10)
- [ ] Implement FileMaker Data API connection
- [ ] Build field mapping configuration
- [ ] Create submission workflow
- [ ] Add error handling and retry logic

### Phase 6: Polish & Launch (Weeks 11-12)
- [ ] User acceptance testing
- [ ] Performance optimization
- [ ] Documentation and training
- [ ] Staged rollout

---

## 9. Success Metrics

| Metric | Current State | Target |
|--------|---------------|--------|
| Avg. time to process referral | 15-30 min | < 5 min |
| Manual data entry fields | 20+ fields | < 5 fields |
| Error rate (data entry) | ~5% | < 1% |
| Referrals processed per day per person | 20-30 | 60-80 |
| Time to first provider contact | Hours | Minutes |

---

## 10. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| LLM extraction accuracy | Confidence scoring + human review required for low scores |
| Email API rate limits | Implement queuing, caching, incremental sync |
| PHI/HIPAA concerns | Encrypt at rest, audit logging, role-based access |
| FileMaker sync failures | Retry queue, manual fallback, sync status dashboard |
| Adjuster email format changes | Flexible extraction prompts, feedback loop for retraining |

---

## 11. Future Enhancements

- **Auto-scheduling:** Direct calendar integration with providers
- **Status updates:** Automated emails to adjusters at milestones
- **Analytics dashboard:** Referral volume, turnaround times, carrier patterns
- **Mobile app:** Quick approvals on the go
- **Carrier portal:** Self-service referral submission for high-volume adjusters
- **ML improvements:** Learn from corrections to improve extraction over time

---

## Appendix A: Sample API Responses

### Graph API Message Object
```json
{
  "id": "AAMkAGI2...",
  "subject": "New PT Referral - John Smith",
  "bodyPreview": "Please schedule PT evaluation for...",
  "body": {
    "contentType": "html",
    "content": "<html>..."
  },
  "from": {
    "emailAddress": {
      "name": "Jane Adjuster",
      "address": "jane.adjuster@aceinsurance.com"
    }
  },
  "receivedDateTime": "2024-01-15T10:30:00Z",
  "webLink": "https://outlook.office365.com/owa/?ItemID=...",
  "internetMessageId": "<abc123@mail.aceinsurance.com>",
  "conversationId": "AAQkAGI2...",
  "hasAttachments": true
}
```

### LLM Extraction Response
```json
{
  "claimant_name": {
    "value": "John Smith",
    "confidence": 95,
    "source": "email_body",
    "raw_match": "PT evaluation for John Smith"
  },
  "claim_number": {
    "value": "WC-2024-12345",
    "confidence": 99,
    "source": "attachment",
    "raw_match": "Claim #: WC-2024-12345"
  },
  "date_of_birth": {
    "value": "1985-03-15",
    "confidence": 90,
    "source": "email_body",
    "raw_match": "DOB 3/15/85"
  }
}
```

---

*Document Version: 1.0*  
*Last Updated: January 2025*  
*Status: Planning*
