# Referral CRM

Workers' Compensation Referral Assignment System - A robust CRM for managing referrals with local SQLite database, S3 storage, Python automations, and an interactive human-in-the-loop review interface.

## Features

| Feature | Description |
|---------|-------------|
| **Local SQLite Database** | Portable, zero-configuration database file |
| **S3 Storage** | Emails, attachments, and extraction data stored in S3 for access anywhere |
| **Rich CLI Interface** | Beautiful terminal UI with colors, tables, and progress indicators |
| **Interactive Review UI** | Side-by-side view of source email and extracted data for human validation |
| **Outlook Integration** | Click to open original emails in Outlook Web, reply with templates |
| **LLM Email Extraction** | Claude API parses unstructured emails with confidence scoring |
| **Attachment Processing** | PDF/image text extraction, S3 storage, inline previews |
| **Provider Matching** | Automatic provider suggestions based on service type and location |
| **Workflow Automation** | Auto-escalation, batch processing, scheduled tasks |
| **Full Audit Trail** | Complete history of all changes to every referral |

## Quick Start

```bash
# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys (see Configuration section)

# Initialize database
uv run python run.py cli init

# Import demo data (optional)
uv run python run.py cli import demo-data

# View CLI dashboard
uv run python run.py cli dashboard

# Start web server
uv run python run.py cli serve
# Open http://localhost:8000
```

## Configuration

Copy `.env.example` to `.env` and configure the following:

```env
# Database (SQLite by default)
DATABASE_URL=sqlite:///referral_crm.db

# Microsoft Graph API (for email ingestion)
MS_CLIENT_ID=your_client_id
MS_CLIENT_SECRET=your_client_secret
MS_TENANT_ID=your_tenant_id

# Claude API (for LLM extraction)
ANTHROPIC_API_KEY=your_anthropic_key

# S3 Storage (for emails and attachments)
S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
# For S3-compatible services (MinIO, etc.):
# AWS_ENDPOINT_URL=http://localhost:9000

# FileMaker Integration (optional)
FILEMAKER_SERVER=https://your-server.com
FILEMAKER_DATABASE=your_database
FILEMAKER_USERNAME=your_username
FILEMAKER_PASSWORD=your_password
```

## Web Interface

### Dashboard (`/`)
- Overview of referral counts by status
- Clickable queue of all referrals
- Auto-refreshes every 30 seconds

### Review Page (`/review/{id}`)
The interactive human-in-the-loop review interface:

**Left Panel - Source Email:**
- Original email content (rendered HTML)
- Email metadata (from, subject, received date)
- "Open in Outlook" button to view in Outlook Web
- Attachments list with View/Download/Text buttons

**Right Panel - Extracted Data:**
- All fields extracted by the LLM
- Color-coded confidence indicators:
  - 🟢 Green (90%+): High confidence, minimal review needed
  - 🟡 Yellow (70-89%): Review recommended
  - 🔴 Red (<70%): Requires verification
- Click any field to edit inline
- Provider assignment section

**Quick Actions:**
- **Open in Outlook** - View the original email in Outlook Web
- **Reply to Adjuster** - Open reply modal with templates
- **Approve** - Move referral to approved status
- **Reject** - Reject with reason

**Reply Templates:**
- Referral Received
- Missing Authorization
- Need Date of Birth
- Clarify Service Type

## CLI Commands

### System Commands
```bash
uv run python run.py cli init              # Initialize database
uv run python run.py cli status            # Show system status
uv run python run.py cli dashboard         # Interactive queue dashboard
uv run python run.py cli serve             # Start web server
```

### Referral Commands
```bash
uv run python run.py cli referral list                    # List all referrals
uv run python run.py cli referral list --status pending   # Filter by status
uv run python run.py cli referral list --priority high    # Filter by priority
uv run python run.py cli referral list --search "smith"   # Search by name/claim#
uv run python run.py cli referral show 1                  # Show referral details
uv run python run.py cli referral create                  # Create interactively
uv run python run.py cli referral approve 1               # Approve referral
uv run python run.py cli referral reject 1 "Duplicate"    # Reject with reason
uv run python run.py cli referral history 1               # View audit history
```

### Carrier & Provider Commands
```bash
uv run python run.py cli carrier list                     # List carriers
uv run python run.py cli carrier create "ACE Insurance"   # Create carrier
uv run python run.py cli provider list                    # List providers
uv run python run.py cli provider list --state IL         # Filter by state
uv run python run.py cli provider find "PT Evaluation"    # Find matching providers
```

### Automation Commands
```bash
uv run python run.py cli auto ingest           # Run email ingestion once
uv run python run.py cli auto ingest --max 100 # Process up to 100 emails
uv run python run.py cli auto poll             # Start continuous polling
uv run python run.py cli auto poll -i 120      # Poll every 2 minutes
uv run python run.py cli auto assign-providers # Auto-assign providers
uv run python run.py cli auto escalate         # Escalate stale referrals
uv run python run.py cli auto report           # Generate daily report
uv run python run.py cli auto cleanup --days 90 --dry-run  # Preview cleanup
```

### Import Commands
```bash
uv run python run.py cli import demo-data      # Import sample data for testing
```

## Project Structure

```
referral-assignment/
├── pyproject.toml              # Project config & dependencies
├── requirements.txt            # Pip requirements (alternative)
├── .env.example                # Environment template
├── run.py                      # Convenience runner script
├── referral_crm.db             # SQLite database (created on init)
└── src/referral_crm/
    ├── __init__.py
    ├── config.py               # Configuration management
    ├── cli.py                  # Rich CLI interface (Typer)
    ├── models/
    │   ├── base.py             # SQLAlchemy base & session management
    │   └── referral.py         # All database models
    ├── services/
    │   ├── referral_service.py # Referral CRUD & business logic
    │   ├── extraction_service.py # Claude LLM email extraction
    │   ├── email_service.py    # Microsoft Graph API integration
    │   ├── provider_service.py # Provider matching & rate lookup
    │   └── storage_service.py  # S3 storage for emails & attachments
    ├── automations/
    │   ├── email_ingestion.py  # Email polling & ingestion pipeline
    │   └── batch_processor.py  # Bulk operations & workflow automation
    ├── api/
    │   └── main.py             # FastAPI web backend
    └── templates/
        └── review.html         # Interactive review page template
```

## Data Model

### Referral (Core Entity)
| Field | Source | Description |
|-------|--------|-------------|
| `referral_id` | System | Auto-generated ID |
| `email_id` | Graph API | Microsoft Graph message ID |
| `email_web_link` | Graph API | Link to open in Outlook Web |
| `claimant_name` | LLM Extracted | Patient/claimant name |
| `claimant_dob` | LLM Extracted | Date of birth |
| `claim_number` | LLM Extracted | Workers' comp claim number |
| `insurance_carrier` | LLM Extracted | Carrier name |
| `adjuster_email` | Graph API | Adjuster's email address |
| `service_requested` | LLM Extracted | PT, MRI, IME, etc. |
| `body_parts` | LLM Extracted | Injured body parts |
| `authorization_number` | LLM Extracted | Auth # if provided |
| `status` | System | Workflow status |
| `priority` | LLM Inferred | Urgency level |
| `extraction_data` | LLM | Full extraction with confidence scores |

### Status Workflow
```
PENDING → IN_REVIEW → APPROVED → SUBMITTED_TO_FILEMAKER → COMPLETED
                   ↘ NEEDS_INFO (sends reply) → back to IN_REVIEW
                   ↘ REJECTED (with reason)
```

## S3 Storage Structure

When S3 is configured, all referral data is stored with this structure:

```
s3://{bucket}/
  referrals/{referral_id}/
    email.html              # Original email HTML content
    email.json              # Email metadata (from, subject, etc.)
    extraction.json         # LLM extraction results with confidence
    attachments/
      {filename}            # Original attachment files
      {filename}.txt        # Extracted text (for PDFs/images)
```

Benefits:
- Access emails and attachments from anywhere
- Presigned URLs for secure, temporary access
- No need to store large files in the database
- Works with AWS S3 or S3-compatible services (MinIO, Backblaze, etc.)

## API Endpoints

### Dashboard
- `GET /api/dashboard` - Get status counts

### Referrals
- `GET /api/referrals` - List referrals (with filters)
- `GET /api/referrals/{id}` - Get referral details
- `POST /api/referrals` - Create new referral
- `PATCH /api/referrals/{id}` - Update referral fields
- `POST /api/referrals/{id}/status` - Update status
- `POST /api/referrals/{id}/approve` - Approve referral
- `POST /api/referrals/{id}/reject?reason=...` - Reject referral
- `GET /api/referrals/{id}/attachments` - List attachments with URLs
- `GET /api/referrals/{id}/history` - Get audit history

### Providers
- `GET /api/providers` - List providers
- `GET /api/providers/find?service_type=...` - Find matching providers

### Carriers
- `GET /api/carriers` - List carriers
- `POST /api/carriers` - Create carrier

### Email Integration
- `GET /api/referrals/{id}/email-link` - Get Outlook Web link
- `GET /open-email/{id}` - Redirect to email in Outlook

## Email Ingestion Pipeline

The ingestion pipeline performs these steps:

1. **Fetch emails** from configured inbox via Microsoft Graph API
2. **Check for duplicates** by email ID
3. **Extract text** from PDF/image attachments (OCR)
4. **Call Claude API** to extract structured data with confidence scores
5. **Upload to S3** (email HTML, metadata, extraction data, attachments)
6. **Create referral** in database with all extracted fields
7. **Mark email as read** (optional)

Run manually:
```bash
uv run python run.py cli auto ingest
```

Run continuously:
```bash
uv run python run.py cli auto poll --interval 60
```

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check src/
```

## License

MIT
