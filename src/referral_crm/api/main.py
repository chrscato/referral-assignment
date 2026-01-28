"""
FastAPI application for Referral CRM web interface.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from referral_crm.config import get_settings
from referral_crm.models import init_db, get_session, ReferralStatus, Priority, QueueType
from referral_crm.services.referral_service import ReferralService, CarrierService
from referral_crm.services.provider_service import ProviderService
from referral_crm.services.storage_service import get_storage_service
from referral_crm.services.workflow_service import WorkflowService
from referral_crm.services.line_item_service import LineItemService

# Setup templates
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ============================================================================
# Pydantic Schemas
# ============================================================================
class ReferralBase(BaseModel):
    """Base schema for referral data."""

    # Patient demographics
    patient_first_name: Optional[str] = None
    patient_last_name: Optional[str] = None
    patient_dob: Optional[str] = None
    patient_doi: Optional[str] = None
    patient_gender: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_email: Optional[str] = None
    patient_ssn: Optional[str] = None
    # Patient address
    patient_address_1: Optional[str] = None
    patient_address_2: Optional[str] = None
    patient_city: Optional[str] = None
    patient_state: Optional[str] = None
    patient_zip: Optional[str] = None
    # Claim info
    claim_number: Optional[str] = None
    jurisdiction_state: Optional[str] = None
    order_type: Optional[str] = None
    authorization_number: Optional[str] = None
    # Carrier
    carrier_name_raw: Optional[str] = None
    carrier_id: Optional[int] = None
    # Adjuster
    adjuster_name: Optional[str] = None
    adjuster_email: Optional[str] = None
    adjuster_phone: Optional[str] = None
    # Employer
    employer_name: Optional[str] = None
    employer_job_title: Optional[str] = None
    employer_address: Optional[str] = None
    # Referring physician
    referring_physician_name: Optional[str] = None
    referring_physician_npi: Optional[str] = None
    # Service info
    body_parts: Optional[str] = None
    service_summary: Optional[str] = None
    suggested_providers: Optional[str] = None
    special_requirements: Optional[str] = None
    rx_attachment_id: Optional[int] = None
    # Other
    notes: Optional[str] = None
    priority: Optional[str] = None


class ReferralCreate(ReferralBase):
    """Schema for creating a referral."""

    pass


class ReferralUpdate(ReferralBase):
    """Schema for updating a referral."""

    pass


class ReferralResponse(ReferralBase):
    """Schema for referral response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    priority: str
    received_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Email info
    email_id: Optional[int] = None
    email_web_link: Optional[str] = None
    email_subject: Optional[str] = None
    # Carrier
    carrier_name: Optional[str] = None
    # Extraction metadata
    extraction_confidence: Optional[float] = None
    needs_human_review: Optional[bool] = None
    extraction_data: Optional[dict] = None
    # RX Attachment
    rx_attachment_id: Optional[int] = None
    rx_attachment_filename: Optional[str] = None
    # Line item count
    line_item_count: int = 0


class StatusUpdate(BaseModel):
    """Schema for status update."""

    status: str
    notes: Optional[str] = None


class ProviderAssignment(BaseModel):
    """Schema for provider assignment."""

    provider_id: int
    rate_amount: Optional[float] = None


class CarrierResponse(BaseModel):
    """Schema for carrier response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: Optional[str] = None
    is_active: bool


class ProviderResponse(BaseModel):
    """Schema for provider response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    npi: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    accepting_new: bool
    avg_wait_days: Optional[int] = None


class ProviderMatch(BaseModel):
    """Schema for provider match result."""

    provider: ProviderResponse
    score: float
    wait_days: Optional[int] = None


class DashboardStats(BaseModel):
    """Schema for dashboard statistics."""

    counts_by_status: dict[str, int]
    total: int


class IngestionRequest(BaseModel):
    """Request body for email ingestion."""

    max_emails: int = 50
    since_hours: int = 24
    mark_as_read: bool = True
    use_llm: bool = True


class QueueItemResponse(BaseModel):
    """Schema for queue item response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    referral_id: Optional[int] = None
    status: str
    priority: str
    assigned_to: Optional[str] = None
    entered_queue_at: datetime
    due_at: Optional[datetime] = None
    is_overdue: bool = False
    wait_time_minutes: float = 0.0
    # Denormalized for display
    patient_name: Optional[str] = None
    claim_number: Optional[str] = None
    carrier_name: Optional[str] = None
    service_summary: Optional[str] = None
    extraction_confidence: Optional[float] = None


class QueueStatsResponse(BaseModel):
    """Schema for queue statistics."""

    queue_name: str
    queue_type: str
    pending: int
    in_progress: int
    overdue: int
    sla_minutes: Optional[int] = None


class LineItemCreate(BaseModel):
    """Schema for creating a line item."""

    service_description: str
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    procedure_code: Optional[str] = None
    procedure_description: Optional[str] = None
    laterality: Optional[str] = None
    with_contrast: Optional[bool] = False


class LineItemUpdate(BaseModel):
    """Schema for updating a line item."""

    service_description: Optional[str] = None
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    procedure_code: Optional[str] = None
    procedure_description: Optional[str] = None
    laterality: Optional[str] = None
    with_contrast: Optional[bool] = None


class LineItemResponse(BaseModel):
    """Schema for line item response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    line_number: int
    service_description: str
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    procedure_code: Optional[str] = None
    procedure_description: Optional[str] = None
    laterality: Optional[str] = None
    with_contrast: bool = False
    status: Optional[str] = None
    confidence: float = 0.0
    source: Optional[str] = None


class AttachmentResponse(BaseModel):
    """Schema for attachment response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    document_type: Optional[str] = None
    s3_key: Optional[str] = None
    view_url: Optional[str] = None
    download_url: Optional[str] = None
    is_rx_attachment: bool = False


class SetRxAttachmentRequest(BaseModel):
    """Schema for setting the RX attachment."""

    attachment_id: int


# ============================================================================
# Application Setup
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup: Initialize database
    init_db()
    yield
    # Shutdown: cleanup if needed


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Referral CRM API",
        description="Workers' Compensation Referral Assignment System",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = create_app()


# ============================================================================
# Dependencies
# ============================================================================
def get_referral_service(session=Depends(get_session)) -> ReferralService:
    """Dependency for referral service."""
    return ReferralService(session)


def get_carrier_service(session=Depends(get_session)) -> CarrierService:
    """Dependency for carrier service."""
    return CarrierService(session)


def get_provider_service(session=Depends(get_session)) -> ProviderService:
    """Dependency for provider service."""
    return ProviderService(session)


def get_workflow_service(session=Depends(get_session)) -> WorkflowService:
    """Dependency for workflow service."""
    return WorkflowService(session)


def get_line_item_service(session=Depends(get_session)) -> LineItemService:
    """Dependency for line item service."""
    return LineItemService(session)


# ============================================================================
# API Routes - Dashboard
# ============================================================================
@app.get("/api/dashboard", response_model=DashboardStats)
def get_dashboard(service: ReferralService = Depends(get_referral_service)):
    """Get dashboard statistics."""
    counts = service.count_by_status()
    return DashboardStats(
        counts_by_status=counts,
        total=sum(counts.values()),
    )


# ============================================================================
# API Routes - Referrals
# ============================================================================
@app.get("/api/referrals", response_model=list[ReferralResponse])
def list_referrals(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    service: ReferralService = Depends(get_referral_service),
):
    """List referrals with optional filtering."""
    status_filter = None
    if status:
        try:
            status_filter = ReferralStatus(status.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    priority_filter = None
    if priority:
        try:
            priority_filter = Priority(priority.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid priority: {priority}")

    referrals = service.list(
        status=status_filter,
        priority=priority_filter,
        search=search,
        limit=limit,
        offset=offset,
    )

    return [_referral_to_response(r) for r in referrals]


@app.get("/api/referrals/{referral_id}", response_model=ReferralResponse)
def get_referral(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Get a specific referral."""
    referral = service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")
    return _referral_to_response(referral)


@app.post("/api/referrals", response_model=ReferralResponse)
def create_referral(
    data: ReferralCreate,
    service: ReferralService = Depends(get_referral_service),
    carrier_service: CarrierService = Depends(get_carrier_service),
):
    """Create a new referral."""
    # Find or create carrier if specified
    carrier_id = data.carrier_id
    if data.carrier_name_raw and not carrier_id:
        carrier = carrier_service.find_or_create(data.carrier_name_raw)
        carrier_id = carrier.id

    # Parse priority
    priority = Priority.MEDIUM
    if data.priority:
        try:
            priority = Priority(data.priority.lower())
        except ValueError:
            pass

    referral = service.create(
        # Patient demographics
        patient_first_name=data.patient_first_name,
        patient_last_name=data.patient_last_name,
        patient_dob=_parse_date(data.patient_dob),
        patient_doi=_parse_date(data.patient_doi),
        patient_gender=data.patient_gender,
        patient_phone=data.patient_phone,
        patient_email=data.patient_email,
        patient_ssn=data.patient_ssn,
        # Patient address
        patient_address_1=data.patient_address_1,
        patient_address_2=data.patient_address_2,
        patient_city=data.patient_city,
        patient_state=data.patient_state,
        patient_zip=data.patient_zip,
        # Claim info
        claim_number=data.claim_number,
        jurisdiction_state=data.jurisdiction_state,
        order_type=data.order_type,
        authorization_number=data.authorization_number,
        # Carrier
        carrier_id=carrier_id,
        carrier_name_raw=data.carrier_name_raw,
        # Adjuster
        adjuster_name=data.adjuster_name,
        adjuster_email=data.adjuster_email,
        adjuster_phone=data.adjuster_phone,
        # Employer
        employer_name=data.employer_name,
        employer_job_title=data.employer_job_title,
        employer_address=data.employer_address,
        # Referring physician
        referring_physician_name=data.referring_physician_name,
        referring_physician_npi=data.referring_physician_npi,
        # Service info
        body_parts=data.body_parts,
        service_summary=data.service_summary,
        suggested_providers=data.suggested_providers,
        special_requirements=data.special_requirements,
        # Other
        notes=data.notes,
        priority=priority,
        received_at=datetime.utcnow(),
    )

    return _referral_to_response(referral)


@app.patch("/api/referrals/{referral_id}", response_model=ReferralResponse)
def update_referral(
    referral_id: int,
    data: ReferralUpdate,
    service: ReferralService = Depends(get_referral_service),
):
    """Update a referral."""
    update_data = data.model_dump(exclude_unset=True)

    # Handle date parsing
    if "patient_dob" in update_data:
        update_data["patient_dob"] = _parse_date(update_data["patient_dob"])
    if "patient_doi" in update_data:
        update_data["patient_doi"] = _parse_date(update_data["patient_doi"])

    # Handle priority
    if "priority" in update_data and update_data["priority"]:
        try:
            update_data["priority"] = Priority(update_data["priority"].lower())
        except ValueError:
            del update_data["priority"]

    referral = service.update(referral_id, user="api", **update_data)
    if not referral:
        raise HTTPException(404, "Referral not found")

    return _referral_to_response(referral)


@app.post("/api/referrals/{referral_id}/status", response_model=ReferralResponse)
def update_status(
    referral_id: int,
    data: StatusUpdate,
    service: ReferralService = Depends(get_referral_service),
):
    """Update referral status."""
    try:
        new_status = ReferralStatus(data.status.lower())
    except ValueError:
        raise HTTPException(400, f"Invalid status: {data.status}")

    referral = service.update_status(
        referral_id,
        new_status,
        user="api",
        notes=data.notes,
    )
    if not referral:
        raise HTTPException(404, "Referral not found")

    return _referral_to_response(referral)


@app.post("/api/referrals/{referral_id}/validate", response_model=ReferralResponse)
def validate_referral(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Validate a referral (move from intake queue)."""
    referral = service.validate(referral_id, user="api")
    if not referral:
        raise HTTPException(404, "Referral not found")
    return _referral_to_response(referral)


@app.post("/api/referrals/{referral_id}/reject", response_model=ReferralResponse)
def reject_referral(
    referral_id: int,
    reason: str = Query(...),
    service: ReferralService = Depends(get_referral_service),
):
    """Reject a referral."""
    referral = service.reject(referral_id, reason, user="api")
    if not referral:
        raise HTTPException(404, "Referral not found")
    return _referral_to_response(referral)


@app.get("/api/referrals/{referral_id}/line-items")
def get_referral_line_items(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Get all line items for a referral."""
    referral = service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    line_items = service.get_line_items(referral_id)
    return [
        {
            "id": li.id,
            "line_number": li.line_number,
            "service_description": li.service_description,
            "service_type": li.service_type.name if li.service_type else None,
            "body_region": li.body_region.name if li.body_region else None,
            "modality": li.modality.value if li.modality else None,
            "laterality": li.laterality,
            "with_contrast": li.with_contrast,
            "icd10_code": li.icd10_code,
            "icd10_description": li.icd10_description,
            "procedure_code": li.procedure_code,
            "procedure_description": li.procedure_description,
            "status": li.status.value if li.status else None,
            "confidence": li.confidence,
            "source": li.source,
        }
        for li in line_items
    ]


@app.get("/api/referrals/{referral_id}/history")
def get_referral_history(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Get audit history for a referral."""
    logs = service.get_audit_log(referral_id)
    return [
        {
            "id": log.id,
            "action": log.action,
            "field_name": log.field_name,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "user": log.user,
            "timestamp": log.timestamp.isoformat(),
            "notes": log.notes,
        }
        for log in logs
    ]


@app.post("/api/ingest")
def run_email_ingestion(
    data: IngestionRequest,
    background_tasks: BackgroundTasks,
):
    """Kick off email ingestion in the background."""
    def _run():
        from referral_crm.automations.email_ingestion import EmailIngestionPipeline

        pipeline = EmailIngestionPipeline(
            mark_as_read=data.mark_as_read,
            use_llm=data.use_llm,
        )
        pipeline.run(max_emails=data.max_emails, since_hours=data.since_hours)

    background_tasks.add_task(_run)
    return {"status": "started"}


@app.delete("/api/referrals/{referral_id}")
def delete_referral(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Delete a referral."""
    if not service.delete(referral_id):
        raise HTTPException(404, "Referral not found")
    return {"status": "deleted"}


# ============================================================================
# API Routes - Carriers
# ============================================================================
@app.get("/api/carriers", response_model=list[CarrierResponse])
def list_carriers(service: CarrierService = Depends(get_carrier_service)):
    """List all carriers."""
    return service.list(active_only=False)


@app.post("/api/carriers", response_model=CarrierResponse)
def create_carrier(
    name: str = Query(...),
    code: Optional[str] = Query(None),
    service: CarrierService = Depends(get_carrier_service),
):
    """Create a new carrier."""
    return service.create(name=name, code=code)


# ============================================================================
# API Routes - Providers
# ============================================================================
@app.get("/api/providers", response_model=list[ProviderResponse])
def list_providers(
    service_type: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    accepting: Optional[bool] = Query(None),
    limit: int = Query(100, le=500),
    service: ProviderService = Depends(get_provider_service),
):
    """List providers with optional filtering."""
    return service.list(
        service_type=service_type,
        state=state,
        accepting_new=accepting,
        limit=limit,
    )


@app.get("/api/providers/find", response_model=list[ProviderMatch])
def find_providers(
    service_type: str = Query(...),
    state: Optional[str] = Query(None),
    zip_code: Optional[str] = Query(None),
    carrier_id: Optional[int] = Query(None),
    limit: int = Query(10, le=50),
    service: ProviderService = Depends(get_provider_service),
):
    """Find matching providers for a service request."""
    matches = service.find_matching_providers(
        service_type=service_type,
        state=state,
        zip_code=zip_code,
        carrier_id=carrier_id,
        limit=limit,
    )

    return [
        ProviderMatch(
            provider=ProviderResponse.model_validate(m["provider"]),
            score=m["score"],
            wait_days=m["wait_days"],
        )
        for m in matches
    ]


# ============================================================================
# Web UI Route (serves simple dashboard HTML)
# ============================================================================
@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serve a simple dashboard HTML page."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Referral CRM</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <nav class="bg-blue-600 text-white p-4">
        <div class="container mx-auto">
            <h1 class="text-2xl font-bold">Referral CRM</h1>
        </div>
    </nav>

    <main class="container mx-auto p-6">
        <div id="stats" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"
             hx-get="/api/dashboard"
             hx-trigger="load, every 30s, refresh"
             hx-swap="innerHTML">
            <div class="bg-white p-4 rounded shadow">Loading...</div>
        </div>

        <div class="bg-white rounded shadow mb-6">
            <div class="p-4 border-b flex items-center justify-between">
                <h2 class="text-xl font-semibold">Email Ingestion</h2>
                <div class="text-sm text-gray-500">Run a quick sample pull from Outlook</div>
            </div>
            <div class="p-4 grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Max emails</label>
                    <select id="ingest-max" class="w-full border rounded px-2 py-1">
                        <option value="10">10</option>
                        <option value="25">25</option>
                        <option value="50" selected>50</option>
                        <option value="100">100</option>
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Since (hours)</label>
                    <select id="ingest-since" class="w-full border rounded px-2 py-1">
                        <option value="1">1</option>
                        <option value="6">6</option>
                        <option value="12">12</option>
                        <option value="24" selected>24</option>
                        <option value="48">48</option>
                        <option value="72">72</option>
                    </select>
                </div>
                <div class="flex items-center gap-2">
                    <input id="ingest-mark-read" type="checkbox" class="h-4 w-4" checked>
                    <label for="ingest-mark-read" class="text-sm text-gray-700">Mark as read</label>
                </div>
                <div class="flex items-center gap-2">
                    <input id="ingest-use-llm" type="checkbox" class="h-4 w-4" checked>
                    <label for="ingest-use-llm" class="text-sm text-gray-700">Use LLM</label>
                </div>
                <div>
                    <button id="ingest-run" class="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
                        Run Ingestion
                    </button>
                </div>
            </div>
            <div class="px-4 pb-4 text-sm text-gray-500" id="ingest-status">Ready.</div>
        </div>

        <div class="bg-white rounded shadow">
            <div class="p-4 border-b">
                <h2 class="text-xl font-semibold">Referral Queue</h2>
            </div>
            <div id="referrals"
                 hx-get="/api/referrals?limit=20"
                 hx-trigger="load, refresh"
                 class="p-4">
                <p class="text-gray-500">Loading referrals...</p>
            </div>
        </div>
    </main>

    <script>
        // Transform API responses for display
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            if (evt.detail.target.id === 'stats') {
                const data = JSON.parse(evt.detail.xhr.responseText);
                evt.detail.target.innerHTML = `
                    <div class="bg-yellow-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-yellow-600">${data.counts_by_status.pending_validation || 0}</div>
                        <div class="text-sm text-yellow-800">Intake Queue</div>
                    </div>
                    <div class="bg-blue-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-blue-600">${data.counts_by_status.validated || 0}</div>
                        <div class="text-sm text-blue-800">Validated</div>
                    </div>
                    <div class="bg-purple-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-purple-600">${data.counts_by_status.pending_scheduling || 0}</div>
                        <div class="text-sm text-purple-800">Care Coord</div>
                    </div>
                    <div class="bg-green-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-green-600">${data.counts_by_status.scheduled || 0}</div>
                        <div class="text-sm text-green-800">Scheduled</div>
                    </div>
                `;
            }
            if (evt.detail.target.id === 'referrals') {
                const referrals = JSON.parse(evt.detail.xhr.responseText);
                if (referrals.length === 0) {
                    evt.detail.target.innerHTML = '<p class="text-gray-500">No referrals found.</p>';
                    return;
                }
                let html = '<table class="w-full"><thead><tr class="border-b">';
                html += '<th class="text-left p-2">ID</th>';
                html += '<th class="text-left p-2">Patient</th>';
                html += '<th class="text-left p-2">Carrier</th>';
                html += '<th class="text-left p-2">Claim #</th>';
                html += '<th class="text-left p-2">Status</th>';
                html += '<th class="text-left p-2">Priority</th>';
                html += '<th class="text-left p-2">Action</th>';
                html += '</tr></thead><tbody>';
                referrals.forEach(r => {
                    const statusColors = {
                        draft: 'bg-gray-100 text-gray-800',
                        pending_validation: 'bg-yellow-100 text-yellow-800',
                        validated: 'bg-blue-100 text-blue-800',
                        pending_scheduling: 'bg-purple-100 text-purple-800',
                        scheduled: 'bg-green-100 text-green-800',
                        completed: 'bg-green-200 text-green-900',
                        rejected: 'bg-red-100 text-red-800'
                    };
                    const priorityColors = {
                        urgent: 'text-red-600 font-bold',
                        high: 'text-red-500',
                        medium: 'text-yellow-600',
                        low: 'text-gray-500'
                    };
                    const patientName = [r.patient_first_name, r.patient_last_name].filter(Boolean).join(' ') || '-';
                    html += `<tr class="border-b hover:bg-gray-50 cursor-pointer" onclick="window.location='/review/${r.id}'">`;
                    html += `<td class="p-2">${r.id}</td>`;
                    html += `<td class="p-2">${patientName}</td>`;
                    html += `<td class="p-2">${r.carrier_name || r.carrier_name_raw || '-'}</td>`;
                    html += `<td class="p-2">${r.claim_number || '-'}</td>`;
                    html += `<td class="p-2"><span class="px-2 py-1 rounded text-xs ${statusColors[r.status] || ''}">${r.status}</span></td>`;
                    html += `<td class="p-2 ${priorityColors[r.priority] || ''}">${r.priority.toUpperCase()}</td>`;
                    html += `<td class="p-2"><a href="/review/${r.id}" class="text-blue-600 hover:text-blue-800">Review &rarr;</a></td>`;
                    html += `</tr>`;
                });
                html += '</tbody></table>';
                evt.detail.target.innerHTML = html;
            }
        });

        const ingestButton = document.getElementById('ingest-run');
        const ingestStatus = document.getElementById('ingest-status');
        ingestButton.addEventListener('click', async () => {
            ingestButton.disabled = true;
            ingestButton.classList.add('opacity-60');
            ingestStatus.textContent = 'Starting ingestion...';

            const payload = {
                max_emails: parseInt(document.getElementById('ingest-max').value, 10),
                since_hours: parseInt(document.getElementById('ingest-since').value, 10),
                mark_as_read: document.getElementById('ingest-mark-read').checked,
                use_llm: document.getElementById('ingest-use-llm').checked,
            };

            try {
                const resp = await fetch('/api/ingest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!resp.ok) {
                    throw new Error('Request failed');
                }
                ingestStatus.textContent = 'Ingestion started. Refreshing queue...';
                htmx.trigger(document.getElementById('stats'), 'refresh');
                htmx.trigger(document.getElementById('referrals'), 'refresh');
            } catch (err) {
                ingestStatus.textContent = 'Failed to start ingestion. Check server logs.';
            } finally {
                ingestButton.disabled = false;
                ingestButton.classList.remove('opacity-60');
            }
        });
    </script>
</body>
</html>
    """


# ============================================================================
# Review Page (Interactive Human-in-the-Loop)
# ============================================================================
@app.get("/review/{referral_id}", response_class=HTMLResponse)
def serve_review_page(
    request: Request,
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Serve the interactive referral review page."""
    referral = service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    # Get storage service for S3 URLs
    storage = get_storage_service()
    email_html_url = None
    if storage.is_configured() and referral.source_email and referral.source_email.s3_html_key:
        email_html_url = storage.get_email_html_url(referral_id)

    # Build attachment data with URLs (attachments are now on Email)
    attachments = []
    email_attachments = referral.source_email.attachments if referral.source_email else []
    for att in email_attachments:
        if att.filename and att.filename.lower().endswith(".png"):
            continue
        att_data = {
            "id": att.id,
            "filename": att.filename,
            "content_type": att.content_type,
            "size_bytes": att.size_bytes or 0,
            "document_type": att.document_type.value if att.document_type else None,
            "extracted_text": att.extracted_text,
            "view_url": None,
            "download_url": None,
            "text_url": None,
        }

        # Generate S3 URLs if available
        if storage.is_configured() and att.s3_key:
            att_data["view_url"] = storage.get_attachment_url(
                referral_id, att.filename, inline=True
            )
            att_data["download_url"] = storage.get_attachment_url(
                referral_id, att.filename, inline=False
            )
            if att.s3_text_key:
                att_data["text_url"] = storage.get_attachment_text_url(
                    referral_id, att.filename
                )

        attachments.append(att_data)

    # Get audit logs
    audit_logs = service.get_audit_log(referral_id)

    # Get line items and convert to JSON-serializable dicts
    line_items_raw = service.get_line_items(referral_id)
    line_items = [
        {
            "id": li.id,
            "line_number": li.line_number,
            "service_description": li.service_description,
            "icd10_code": li.icd10_code,
            "icd10_description": li.icd10_description,
            "procedure_code": li.procedure_code,
            "procedure_description": li.procedure_description,
            "laterality": li.laterality,
            "with_contrast": li.with_contrast,
            "status": li.status.value if li.status else None,
            "confidence": li.confidence,
            "source": li.source,
        }
        for li in line_items_raw
    ]

    # Render template
    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "referral": referral,
            "attachments": attachments,
            "audit_logs": audit_logs,
            "line_items": line_items,
            "email_html_url": email_html_url,
            "extraction_data": referral.extraction_data or {},
        },
    )


@app.get("/api/referrals/{referral_id}/attachments")
def list_referral_attachments(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Get all attachments for a referral with download URLs."""
    referral = service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    storage = get_storage_service()
    attachments = []

    # Attachments are now on Email, not Referral
    email_attachments = referral.source_email.attachments if referral.source_email else []
    for att in email_attachments:
        att_data = {
            "id": att.id,
            "filename": att.filename,
            "content_type": att.content_type,
            "size_bytes": att.size_bytes,
            "document_type": att.document_type.value if att.document_type else None,
            "has_extracted_text": bool(att.extracted_text),
        }

        # Add S3 URLs if configured
        if storage.is_configured() and att.s3_key:
            att_data["view_url"] = storage.get_attachment_url(
                referral_id, att.filename, inline=True
            )
            att_data["download_url"] = storage.get_attachment_url(
                referral_id, att.filename, inline=False
            )

        attachments.append(att_data)

    return attachments


@app.get("/api/referrals/{referral_id}/email-link")
def get_email_outlook_link(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Get the Outlook Web link for the original email."""
    referral = service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    if not referral.source_email or not referral.source_email.web_link:
        raise HTTPException(404, "No email link available")

    return {
        "outlook_link": referral.source_email.web_link,
        "email_id": referral.email_id,
    }


@app.get("/open-email/{referral_id}")
def redirect_to_email(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Redirect to open the email in Outlook Web."""
    referral = service.get(referral_id)
    if not referral or not referral.source_email or not referral.source_email.web_link:
        raise HTTPException(404, "Email not found")

    return RedirectResponse(url=referral.source_email.web_link)


# ============================================================================
# API Routes - Queue Operations
# ============================================================================
@app.get("/api/queues/{queue_type}/items", response_model=list[QueueItemResponse])
def list_queue_items(
    queue_type: str,
    limit: int = Query(50, le=200),
    overdue_only: bool = Query(False),
    priority: Optional[str] = Query(None),
    workflow_service: WorkflowService = Depends(get_workflow_service),
):
    """List items in a queue."""
    try:
        qt = QueueType(queue_type)
    except ValueError:
        raise HTTPException(400, f"Invalid queue type: {queue_type}")

    if overdue_only:
        items = workflow_service.get_overdue_items(qt)
    else:
        items = workflow_service.get_pending_items(qt, limit=limit)

    # Filter by priority if specified
    if priority:
        try:
            priority_filter = Priority(priority.lower())
            items = [i for i in items if i.priority == priority_filter]
        except ValueError:
            pass

    result = []
    for item in items:
        referral = item.referral
        patient_name = None
        claim_number = None
        carrier_name = None
        service_summary = None
        extraction_confidence = None

        if referral:
            patient_name = " ".join(filter(None, [referral.patient_first_name, referral.patient_last_name]))
            claim_number = referral.claim_number
            carrier_name = referral.carrier.name if referral.carrier else referral.carrier_name_raw
            service_summary = referral.service_summary
            extraction_confidence = referral.extraction_confidence

        result.append(QueueItemResponse(
            id=item.id,
            referral_id=item.referral_id,
            status=item.status.value,
            priority=item.priority.value,
            assigned_to=item.assigned_to,
            entered_queue_at=item.entered_queue_at,
            due_at=item.due_at,
            is_overdue=item.is_overdue,
            wait_time_minutes=item.wait_time_minutes,
            patient_name=patient_name or None,
            claim_number=claim_number,
            carrier_name=carrier_name,
            service_summary=service_summary,
            extraction_confidence=extraction_confidence,
        ))

    return result


@app.get("/api/queues/{queue_type}/stats", response_model=QueueStatsResponse)
def get_queue_stats(
    queue_type: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
):
    """Get statistics for a queue."""
    try:
        qt = QueueType(queue_type)
    except ValueError:
        raise HTTPException(400, f"Invalid queue type: {queue_type}")

    stats = workflow_service.get_queue_stats(qt)
    if not stats:
        raise HTTPException(404, f"Queue not found: {queue_type}")

    return QueueStatsResponse(**stats)


@app.post("/api/queue-items/{item_id}/claim", response_model=QueueItemResponse)
def claim_queue_item(
    item_id: int,
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Claim a queue item for processing."""
    user = request.headers.get("X-User-Id", "anonymous")

    # Get the queue item first
    from referral_crm.models import QueueItem
    session = workflow_service.session
    queue_item = session.query(QueueItem).filter(QueueItem.id == item_id).first()

    if not queue_item:
        raise HTTPException(404, "Queue item not found")

    # Determine queue type and claim
    queue = queue_item.queue
    if queue.queue_type == QueueType.INTAKE:
        result = workflow_service.claim_intake_item(queue_item.referral_id, user)
    elif queue.queue_type == QueueType.CARE_COORDINATION:
        result = workflow_service.claim_care_coordination_item(queue_item.referral_id, user)
    else:
        raise HTTPException(400, "Cannot claim items from this queue type")

    if not result:
        raise HTTPException(400, "Unable to claim item - may already be claimed")

    # Get referral info for response
    referral = queue_item.referral
    patient_name = None
    if referral:
        patient_name = " ".join(filter(None, [referral.patient_first_name, referral.patient_last_name]))

    return QueueItemResponse(
        id=result.id,
        referral_id=result.referral_id,
        status=result.status.value,
        priority=result.priority.value,
        assigned_to=result.assigned_to,
        entered_queue_at=result.entered_queue_at,
        due_at=result.due_at,
        is_overdue=result.is_overdue,
        wait_time_minutes=result.wait_time_minutes,
        patient_name=patient_name or None,
        claim_number=referral.claim_number if referral else None,
        carrier_name=referral.carrier.name if referral and referral.carrier else None,
        service_summary=referral.service_summary if referral else None,
        extraction_confidence=referral.extraction_confidence if referral else None,
    )


@app.post("/api/queue-items/{item_id}/release")
def release_queue_item(
    item_id: int,
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service),
):
    """Release a claimed queue item back to pending."""
    user = request.headers.get("X-User-Id", "anonymous")

    success = workflow_service.release_queue_item(item_id, user)
    if not success:
        raise HTTPException(400, "Unable to release item - may not be assigned to you")

    return {"status": "released"}


# ============================================================================
# API Routes - Line Items
# ============================================================================
@app.post("/api/referrals/{referral_id}/line-items", response_model=LineItemResponse)
def create_line_item(
    referral_id: int,
    data: LineItemCreate,
    request: Request,
    line_item_service: LineItemService = Depends(get_line_item_service),
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Create a new line item for a referral."""
    user = request.headers.get("X-User-Id", "api")

    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    line_item = line_item_service.create(
        referral_id=referral_id,
        service_description=data.service_description,
        icd10_code=data.icd10_code,
        icd10_description=data.icd10_description,
        procedure_code=data.procedure_code,
        procedure_description=data.procedure_description,
        laterality=data.laterality,
        with_contrast=data.with_contrast or False,
        source="manual",
        user=user,
    )

    return LineItemResponse(
        id=line_item.id,
        line_number=line_item.line_number,
        service_description=line_item.service_description,
        icd10_code=line_item.icd10_code,
        icd10_description=line_item.icd10_description,
        procedure_code=line_item.procedure_code,
        procedure_description=line_item.procedure_description,
        laterality=line_item.laterality,
        with_contrast=line_item.with_contrast,
        status=line_item.status.value if line_item.status else None,
        confidence=line_item.confidence,
        source=line_item.source,
    )


@app.patch("/api/referrals/{referral_id}/line-items/{line_item_id}", response_model=LineItemResponse)
def update_line_item(
    referral_id: int,
    line_item_id: int,
    data: LineItemUpdate,
    request: Request,
    line_item_service: LineItemService = Depends(get_line_item_service),
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Update a line item."""
    user = request.headers.get("X-User-Id", "api")

    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    update_data = data.model_dump(exclude_unset=True)
    line_item = line_item_service.update(line_item_id, user=user, **update_data)

    if not line_item:
        raise HTTPException(404, "Line item not found")

    return LineItemResponse(
        id=line_item.id,
        line_number=line_item.line_number,
        service_description=line_item.service_description,
        icd10_code=line_item.icd10_code,
        icd10_description=line_item.icd10_description,
        procedure_code=line_item.procedure_code,
        procedure_description=line_item.procedure_description,
        laterality=line_item.laterality,
        with_contrast=line_item.with_contrast,
        status=line_item.status.value if line_item.status else None,
        confidence=line_item.confidence,
        source=line_item.source,
    )


@app.delete("/api/referrals/{referral_id}/line-items/{line_item_id}")
def delete_line_item(
    referral_id: int,
    line_item_id: int,
    request: Request,
    line_item_service: LineItemService = Depends(get_line_item_service),
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Delete a line item."""
    user = request.headers.get("X-User-Id", "api")

    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    success = line_item_service.delete(line_item_id, user=user)
    if not success:
        raise HTTPException(404, "Line item not found")

    return {"status": "deleted"}


# ============================================================================
# API Routes - Attachments
# ============================================================================
@app.get("/api/referrals/{referral_id}/all-attachments", response_model=list[AttachmentResponse])
def list_all_referral_attachments(
    referral_id: int,
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Get all attachments for a referral (from email + directly uploaded)."""
    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    storage = get_storage_service()
    attachments = []

    # Get attachments from source email
    if referral.source_email:
        for att in referral.source_email.attachments:
            if att.filename and att.filename.lower().endswith(".png"):
                continue  # Skip inline images
            att_data = AttachmentResponse(
                id=att.id,
                filename=att.filename,
                content_type=att.content_type,
                size_bytes=att.size_bytes,
                document_type=att.document_type.value if att.document_type else None,
                s3_key=att.s3_key,
                view_url=storage.get_attachment_url(referral_id, att.filename, inline=True) if storage.is_configured() and att.s3_key else None,
                download_url=storage.get_attachment_url(referral_id, att.filename, inline=False) if storage.is_configured() and att.s3_key else None,
                is_rx_attachment=att.id == referral.rx_attachment_id,
            )
            attachments.append(att_data)

    # Get directly uploaded attachments
    for att in referral.uploaded_attachments:
        att_data = AttachmentResponse(
            id=att.id,
            filename=att.filename,
            content_type=att.content_type,
            size_bytes=att.size_bytes,
            document_type=att.document_type.value if att.document_type else None,
            s3_key=att.s3_key,
            view_url=storage.get_attachment_url(referral_id, att.filename, inline=True) if storage.is_configured() and att.s3_key else None,
            download_url=storage.get_attachment_url(referral_id, att.filename, inline=False) if storage.is_configured() and att.s3_key else None,
            is_rx_attachment=att.id == referral.rx_attachment_id,
        )
        attachments.append(att_data)

    return attachments


@app.post("/api/referrals/{referral_id}/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    referral_id: int,
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    referral_service: ReferralService = Depends(get_referral_service),
    session=Depends(get_session),
):
    """Upload an attachment directly to a referral."""
    from referral_crm.models import Attachment

    user = x_user_id or "api"

    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    # Read file content
    content = await file.read()
    filename = file.filename or "uploaded_file"
    content_type = file.content_type

    # Upload to S3
    storage = get_storage_service()
    s3_result = {}
    if storage.is_configured():
        s3_result = storage.upload_attachment(
            referral_id=referral_id,
            filename=filename,
            content=content,
            content_type=content_type,
        )

    # Create attachment record
    attachment = Attachment(
        referral_id=referral_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        s3_key=s3_result.get("s3_key"),
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)

    return AttachmentResponse(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        document_type=None,
        s3_key=attachment.s3_key,
        view_url=storage.get_attachment_url(referral_id, filename, inline=True) if storage.is_configured() and attachment.s3_key else None,
        download_url=storage.get_attachment_url(referral_id, filename, inline=False) if storage.is_configured() and attachment.s3_key else None,
        is_rx_attachment=False,
    )


@app.post("/api/referrals/{referral_id}/rx-attachment")
def set_rx_attachment(
    referral_id: int,
    data: SetRxAttachmentRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Set an attachment as the RX (prescription) attachment for a referral."""
    user = x_user_id or "api"

    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    # Verify the attachment exists and belongs to this referral
    from referral_crm.models import Attachment
    session = referral_service.session
    attachment = session.query(Attachment).filter(Attachment.id == data.attachment_id).first()

    if not attachment:
        raise HTTPException(404, "Attachment not found")

    # Check attachment belongs to this referral (either via email or direct upload)
    is_valid = False
    if attachment.referral_id == referral_id:
        is_valid = True
    elif attachment.email_id and referral.source_email and attachment.email_id == referral.source_email.id:
        is_valid = True

    if not is_valid:
        raise HTTPException(400, "Attachment does not belong to this referral")

    # Set the RX attachment
    referral_service.update(referral_id, user=user, rx_attachment_id=data.attachment_id)

    return {"status": "success", "rx_attachment_id": data.attachment_id, "filename": attachment.filename}


@app.delete("/api/referrals/{referral_id}/rx-attachment")
def clear_rx_attachment(
    referral_id: int,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    referral_service: ReferralService = Depends(get_referral_service),
):
    """Clear the RX attachment for a referral."""
    user = x_user_id or "api"

    referral = referral_service.get(referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")

    referral_service.update(referral_id, user=user, rx_attachment_id=None)

    return {"status": "success"}


# ============================================================================
# Intake Queue Dashboard Route
# ============================================================================
@app.get("/intake", response_class=HTMLResponse)
def serve_intake_queue(request: Request, user: str = Query("anonymous")):
    """Serve the intake queue dashboard."""
    return templates.TemplateResponse("intake_queue.html", {
        "request": request,
        "current_user": user,
    })


# ============================================================================
# Helpers
# ============================================================================
def _referral_to_response(referral) -> ReferralResponse:
    """Convert a referral model to response schema."""
    # Get email info if available
    email_web_link = None
    email_subject = None
    if referral.source_email:
        email_web_link = referral.source_email.web_link
        email_subject = referral.source_email.subject

    return ReferralResponse(
        id=referral.id,
        status=referral.status.value,
        priority=referral.priority.value,
        # Patient demographics
        patient_first_name=referral.patient_first_name,
        patient_last_name=referral.patient_last_name,
        patient_dob=referral.patient_dob.isoformat() if referral.patient_dob else None,
        patient_doi=referral.patient_doi.isoformat() if referral.patient_doi else None,
        patient_gender=referral.patient_gender,
        patient_phone=referral.patient_phone,
        patient_email=referral.patient_email,
        patient_ssn=referral.patient_ssn,
        # Patient address
        patient_address_1=referral.patient_address_1,
        patient_address_2=referral.patient_address_2,
        patient_city=referral.patient_city,
        patient_state=referral.patient_state,
        patient_zip=referral.patient_zip,
        # Claim info
        claim_number=referral.claim_number,
        jurisdiction_state=referral.jurisdiction_state,
        order_type=referral.order_type,
        authorization_number=referral.authorization_number,
        # Carrier
        carrier_id=referral.carrier_id,
        carrier_name_raw=referral.carrier_name_raw,
        carrier_name=referral.carrier.name if referral.carrier else None,
        # Adjuster
        adjuster_name=referral.adjuster_name,
        adjuster_email=referral.adjuster_email,
        adjuster_phone=referral.adjuster_phone,
        # Employer
        employer_name=referral.employer_name,
        employer_job_title=referral.employer_job_title,
        employer_address=referral.employer_address,
        # Referring physician
        referring_physician_name=referral.referring_physician_name,
        referring_physician_npi=referral.referring_physician_npi,
        # Service info
        body_parts=referral.body_parts,
        service_summary=referral.service_summary,
        suggested_providers=referral.suggested_providers,
        special_requirements=referral.special_requirements,
        rx_attachment_id=referral.rx_attachment_id,
        rx_attachment_filename=referral.rx_attachment.filename if referral.rx_attachment else None,
        # Other
        notes=referral.notes,
        received_at=referral.received_at,
        created_at=referral.created_at,
        updated_at=referral.updated_at,
        # Email info
        email_id=referral.email_id,
        email_web_link=email_web_link,
        email_subject=email_subject,
        # Extraction metadata
        extraction_confidence=referral.extraction_confidence,
        needs_human_review=referral.needs_human_review,
        extraction_data=referral.extraction_data,
        # Line items
        line_item_count=len(referral.line_items) if referral.line_items else 0,
    )


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
