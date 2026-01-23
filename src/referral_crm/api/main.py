"""
FastAPI application for Referral CRM web interface.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from referral_crm.config import get_settings
from referral_crm.models import init_db, get_session, ReferralStatus, Priority
from referral_crm.services.referral_service import ReferralService, CarrierService
from referral_crm.services.provider_service import ProviderService
from referral_crm.services.storage_service import get_storage_service

# Setup templates
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ============================================================================
# Pydantic Schemas
# ============================================================================
class ReferralBase(BaseModel):
    """Base schema for referral data."""

    claimant_name: Optional[str] = None
    claimant_dob: Optional[str] = None
    claimant_phone: Optional[str] = None
    claimant_address: Optional[str] = None
    claimant_city: Optional[str] = None
    claimant_state: Optional[str] = None
    claimant_zip: Optional[str] = None
    claim_number: Optional[str] = None
    carrier_name_raw: Optional[str] = None
    carrier_id: Optional[int] = None
    adjuster_name: Optional[str] = None
    adjuster_email: Optional[str] = None
    adjuster_phone: Optional[str] = None
    employer_name: Optional[str] = None
    date_of_injury: Optional[str] = None
    body_parts: Optional[str] = None
    service_requested: Optional[str] = None
    authorization_number: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None


class ReferralCreate(ReferralBase):
    """Schema for creating a referral."""

    pass


class ReferralUpdate(ReferralBase):
    """Schema for updating a referral."""

    provider_id: Optional[int] = None
    rate_amount: Optional[float] = None


class ReferralResponse(ReferralBase):
    """Schema for referral response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    priority: str
    received_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    email_web_link: Optional[str] = None
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    carrier_name: Optional[str] = None
    rate_amount: Optional[float] = None
    extraction_data: Optional[dict] = None


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
        claimant_name=data.claimant_name,
        claimant_dob=_parse_date(data.claimant_dob),
        claimant_phone=data.claimant_phone,
        claimant_address=data.claimant_address,
        claimant_city=data.claimant_city,
        claimant_state=data.claimant_state,
        claimant_zip=data.claimant_zip,
        claim_number=data.claim_number,
        carrier_id=carrier_id,
        carrier_name_raw=data.carrier_name_raw,
        adjuster_name=data.adjuster_name,
        adjuster_email=data.adjuster_email,
        adjuster_phone=data.adjuster_phone,
        employer_name=data.employer_name,
        date_of_injury=_parse_date(data.date_of_injury),
        body_parts=data.body_parts,
        service_requested=data.service_requested,
        authorization_number=data.authorization_number,
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
    if "claimant_dob" in update_data:
        update_data["claimant_dob"] = _parse_date(update_data["claimant_dob"])
    if "date_of_injury" in update_data:
        update_data["date_of_injury"] = _parse_date(update_data["date_of_injury"])

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


@app.post("/api/referrals/{referral_id}/approve", response_model=ReferralResponse)
def approve_referral(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Approve a referral."""
    referral = service.approve(referral_id, user="api")
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


@app.post("/api/referrals/{referral_id}/assign-provider", response_model=ReferralResponse)
def assign_provider(
    referral_id: int,
    data: ProviderAssignment,
    service: ReferralService = Depends(get_referral_service),
):
    """Assign a provider to a referral."""
    referral = service.update(
        referral_id,
        user="api",
        provider_id=data.provider_id,
        rate_amount=data.rate_amount,
    )
    if not referral:
        raise HTTPException(404, "Referral not found")
    return _referral_to_response(referral)


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
        <div id="stats" class="grid grid-cols-4 gap-4 mb-6"
             hx-get="/api/dashboard"
             hx-trigger="load, every 30s"
             hx-swap="innerHTML">
            <div class="bg-white p-4 rounded shadow">Loading...</div>
        </div>

        <div class="bg-white rounded shadow">
            <div class="p-4 border-b">
                <h2 class="text-xl font-semibold">Referral Queue</h2>
            </div>
            <div id="referrals"
                 hx-get="/api/referrals?limit=20"
                 hx-trigger="load"
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
                        <div class="text-3xl font-bold text-yellow-600">${data.counts_by_status.pending || 0}</div>
                        <div class="text-sm text-yellow-800">Pending</div>
                    </div>
                    <div class="bg-blue-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-blue-600">${data.counts_by_status.in_review || 0}</div>
                        <div class="text-sm text-blue-800">In Review</div>
                    </div>
                    <div class="bg-green-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-green-600">${data.counts_by_status.approved || 0}</div>
                        <div class="text-sm text-green-800">Approved</div>
                    </div>
                    <div class="bg-gray-100 p-4 rounded shadow text-center">
                        <div class="text-3xl font-bold text-gray-600">${data.total}</div>
                        <div class="text-sm text-gray-800">Total</div>
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
                html += '<th class="text-left p-2">Claimant</th>';
                html += '<th class="text-left p-2">Carrier</th>';
                html += '<th class="text-left p-2">Claim #</th>';
                html += '<th class="text-left p-2">Status</th>';
                html += '<th class="text-left p-2">Priority</th>';
                html += '<th class="text-left p-2">Action</th>';
                html += '</tr></thead><tbody>';
                referrals.forEach(r => {
                    const statusColors = {
                        pending: 'bg-yellow-100 text-yellow-800',
                        in_review: 'bg-blue-100 text-blue-800',
                        approved: 'bg-green-100 text-green-800',
                        rejected: 'bg-red-100 text-red-800'
                    };
                    const priorityColors = {
                        urgent: 'text-red-600 font-bold',
                        high: 'text-red-500',
                        medium: 'text-yellow-600',
                        low: 'text-gray-500'
                    };
                    html += `<tr class="border-b hover:bg-gray-50 cursor-pointer" onclick="window.location='/review/${r.id}'">`;
                    html += `<td class="p-2">${r.id}</td>`;
                    html += `<td class="p-2">${r.claimant_name || '-'}</td>`;
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
    if storage.is_configured() and referral.s3_email_key:
        email_html_url = storage.get_email_html_url(referral_id)

    # Build attachment data with URLs
    attachments = []
    for att in referral.attachments:
        att_data = {
            "id": att.id,
            "filename": att.filename,
            "content_type": att.content_type,
            "size_bytes": att.size_bytes or 0,
            "document_type": att.document_type,
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

    # Render template
    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "referral": referral,
            "attachments": attachments,
            "audit_logs": audit_logs,
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

    for att in referral.attachments:
        att_data = {
            "id": att.id,
            "filename": att.filename,
            "content_type": att.content_type,
            "size_bytes": att.size_bytes,
            "document_type": att.document_type,
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

    if not referral.email_web_link:
        raise HTTPException(404, "No email link available")

    return {
        "outlook_link": referral.email_web_link,
        "email_id": referral.email_id,
    }


@app.get("/open-email/{referral_id}")
def redirect_to_email(
    referral_id: int,
    service: ReferralService = Depends(get_referral_service),
):
    """Redirect to open the email in Outlook Web."""
    referral = service.get(referral_id)
    if not referral or not referral.email_web_link:
        raise HTTPException(404, "Email not found")

    return RedirectResponse(url=referral.email_web_link)


# ============================================================================
# Helpers
# ============================================================================
def _referral_to_response(referral) -> ReferralResponse:
    """Convert a referral model to response schema."""
    return ReferralResponse(
        id=referral.id,
        status=referral.status.value,
        priority=referral.priority.value,
        claimant_name=referral.claimant_name,
        claimant_dob=referral.claimant_dob.isoformat() if referral.claimant_dob else None,
        claimant_phone=referral.claimant_phone,
        claimant_address=referral.claimant_address,
        claimant_city=referral.claimant_city,
        claimant_state=referral.claimant_state,
        claimant_zip=referral.claimant_zip,
        claim_number=referral.claim_number,
        carrier_id=referral.carrier_id,
        carrier_name_raw=referral.carrier_name_raw,
        carrier_name=referral.carrier.name if referral.carrier else None,
        adjuster_name=referral.adjuster_name,
        adjuster_email=referral.adjuster_email,
        adjuster_phone=referral.adjuster_phone,
        employer_name=referral.employer_name,
        date_of_injury=referral.date_of_injury.isoformat() if referral.date_of_injury else None,
        body_parts=referral.body_parts,
        service_requested=referral.service_requested,
        authorization_number=referral.authorization_number,
        notes=referral.notes,
        received_at=referral.received_at,
        created_at=referral.created_at,
        updated_at=referral.updated_at,
        email_web_link=referral.email_web_link,
        provider_id=referral.provider_id,
        provider_name=referral.provider.name if referral.provider else None,
        rate_amount=referral.rate_amount,
        extraction_data=referral.extraction_data,
    )


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
