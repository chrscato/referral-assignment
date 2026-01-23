"""
CLI interface for Referral CRM.
Uses Typer for commands and Rich for beautiful output.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from referral_crm.config import get_settings
from referral_crm.models import init_db, session_scope, ReferralStatus, Priority
from referral_crm.services.referral_service import ReferralService, CarrierService
from referral_crm.services.provider_service import ProviderService, RateService

app = typer.Typer(
    name="referral-crm",
    help="Workers' Compensation Referral Assignment CRM",
    no_args_is_help=True,
)

console = Console()


# ============================================================================
# Database Commands
# ============================================================================
@app.command("init")
def init_database():
    """Initialize the database (creates tables if they don't exist)."""
    settings = get_settings()
    console.print(f"[blue]Initializing database:[/blue] {settings.database_url}")
    init_db()
    console.print("[green]Database initialized successfully![/green]")


@app.command("status")
def show_status():
    """Show CRM status and statistics."""
    settings = get_settings()

    console.print(Panel.fit(
        f"[bold]Referral CRM[/bold]\n"
        f"Database: {settings.get_db_path()}\n"
        f"Graph API: {'[green]Configured[/green]' if settings.graph_client_id else '[yellow]Not configured[/yellow]'}\n"
        f"Claude API: {'[green]Configured[/green]' if settings.anthropic_api_key else '[yellow]Not configured[/yellow]'}",
        title="System Status",
        border_style="blue",
    ))

    with session_scope() as session:
        service = ReferralService(session)
        counts = service.count_by_status()

        if counts:
            table = Table(title="Referral Counts by Status", box=box.ROUNDED)
            table.add_column("Status", style="cyan")
            table.add_column("Count", justify="right", style="green")

            for status, count in sorted(counts.items()):
                table.add_row(status.replace("_", " ").title(), str(count))

            table.add_row("─" * 20, "─" * 5, style="dim")
            table.add_row("[bold]Total[/bold]", f"[bold]{sum(counts.values())}[/bold]")

            console.print(table)
        else:
            console.print("[dim]No referrals in the system yet.[/dim]")


# ============================================================================
# Referral Commands
# ============================================================================
referral_app = typer.Typer(help="Manage referrals")
app.add_typer(referral_app, name="referral")


@referral_app.command("list")
def list_referrals(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="Filter by priority"),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search term"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results"),
):
    """List referrals with optional filtering."""
    with session_scope() as session:
        service = ReferralService(session)

        # Parse filters
        status_filter = None
        if status:
            try:
                status_filter = ReferralStatus(status.lower())
            except ValueError:
                console.print(f"[red]Invalid status: {status}[/red]")
                raise typer.Exit(1)

        priority_filter = None
        if priority:
            try:
                priority_filter = Priority(priority.lower())
            except ValueError:
                console.print(f"[red]Invalid priority: {priority}[/red]")
                raise typer.Exit(1)

        referrals = service.list(
            status=status_filter,
            priority=priority_filter,
            search=search,
            limit=limit,
        )

        if not referrals:
            console.print("[dim]No referrals found.[/dim]")
            return

        table = Table(title="Referrals", box=box.ROUNDED, show_lines=True)
        table.add_column("ID", style="dim", width=5)
        table.add_column("Priority", width=8)
        table.add_column("Claimant", width=20)
        table.add_column("Carrier", width=15)
        table.add_column("Claim #", width=15)
        table.add_column("Status", width=12)
        table.add_column("Received", width=12)

        for ref in referrals:
            priority_style = {
                Priority.URGENT: "red bold",
                Priority.HIGH: "red",
                Priority.MEDIUM: "yellow",
                Priority.LOW: "dim",
            }.get(ref.priority, "white")

            status_style = {
                ReferralStatus.PENDING: "yellow",
                ReferralStatus.IN_REVIEW: "blue",
                ReferralStatus.NEEDS_INFO: "magenta",
                ReferralStatus.APPROVED: "green",
                ReferralStatus.SUBMITTED_TO_FILEMAKER: "cyan",
                ReferralStatus.COMPLETED: "green dim",
                ReferralStatus.REJECTED: "red",
            }.get(ref.status, "white")

            received = ref.received_at.strftime("%Y-%m-%d") if ref.received_at else "-"

            table.add_row(
                str(ref.id),
                Text(ref.priority.value.upper(), style=priority_style),
                ref.claimant_name or "-",
                ref.carrier.name if ref.carrier else (ref.carrier_name_raw or "-"),
                ref.claim_number or "-",
                Text(ref.status.value.replace("_", " ").title(), style=status_style),
                received,
            )

        console.print(table)


@referral_app.command("show")
def show_referral(
    referral_id: int = typer.Argument(..., help="Referral ID to show"),
):
    """Show detailed information about a referral."""
    with session_scope() as session:
        service = ReferralService(session)
        referral = service.get(referral_id)

        if not referral:
            console.print(f"[red]Referral {referral_id} not found.[/red]")
            raise typer.Exit(1)

        # Build the display
        console.print()
        console.print(Panel.fit(
            f"[bold]Referral #{referral.id}[/bold] - {referral.claimant_name or 'Unknown Claimant'}",
            border_style="blue",
        ))

        # Status and priority
        status_colors = {
            ReferralStatus.PENDING: "yellow",
            ReferralStatus.IN_REVIEW: "blue",
            ReferralStatus.NEEDS_INFO: "magenta",
            ReferralStatus.APPROVED: "green",
            ReferralStatus.SUBMITTED_TO_FILEMAKER: "cyan",
            ReferralStatus.COMPLETED: "green",
            ReferralStatus.REJECTED: "red",
        }
        status_color = status_colors.get(referral.status, "white")
        console.print(f"Status: [{status_color}]{referral.status.value.replace('_', ' ').title()}[/{status_color}]")
        console.print(f"Priority: {referral.priority.value.upper()}")
        console.print()

        # Claimant Information
        console.print("[bold cyan]Claimant Information[/bold cyan]")
        console.print(f"  Name: {referral.claimant_name or '-'}")
        console.print(f"  DOB: {referral.claimant_dob or '-'}")
        console.print(f"  Phone: {referral.claimant_phone or '-'}")
        console.print(f"  Address: {referral.claimant_address or '-'}")
        console.print()

        # Claim Information
        console.print("[bold cyan]Claim Information[/bold cyan]")
        carrier_name = referral.carrier.name if referral.carrier else (referral.carrier_name_raw or "-")
        console.print(f"  Carrier: {carrier_name}")
        console.print(f"  Claim #: {referral.claim_number or '-'}")
        console.print(f"  Date of Injury: {referral.date_of_injury or '-'}")
        console.print(f"  Body Parts: {referral.body_parts or '-'}")
        console.print(f"  Service Requested: {referral.service_requested or '-'}")
        console.print(f"  Auth #: {referral.authorization_number or '-'}")
        console.print()

        # Adjuster Information
        console.print("[bold cyan]Adjuster Information[/bold cyan]")
        console.print(f"  Name: {referral.adjuster_name or '-'}")
        console.print(f"  Email: {referral.adjuster_email or '-'}")
        console.print(f"  Phone: {referral.adjuster_phone or '-'}")
        console.print()

        # Provider Assignment
        if referral.provider:
            console.print("[bold cyan]Assigned Provider[/bold cyan]")
            console.print(f"  Name: {referral.provider.name}")
            console.print(f"  Phone: {referral.provider.phone or '-'}")
            console.print(f"  Rate: ${referral.rate_amount:.2f}" if referral.rate_amount else "  Rate: -")
            console.print()

        # Attachments
        if referral.attachments:
            console.print("[bold cyan]Attachments[/bold cyan]")
            for att in referral.attachments:
                console.print(f"  - {att.filename} ({att.document_type or 'Unknown type'})")
            console.print()

        # Notes
        if referral.notes:
            console.print("[bold cyan]Notes[/bold cyan]")
            console.print(f"  {referral.notes}")
            console.print()

        # Timestamps
        console.print("[dim]Created: " + referral.created_at.strftime("%Y-%m-%d %H:%M:%S") + "[/dim]")
        console.print("[dim]Updated: " + referral.updated_at.strftime("%Y-%m-%d %H:%M:%S") + "[/dim]")


@referral_app.command("create")
def create_referral():
    """Create a new referral interactively."""
    console.print("[bold]Create New Referral[/bold]")
    console.print()

    # Gather information interactively
    claimant_name = Prompt.ask("Claimant Name")
    claim_number = Prompt.ask("Claim Number", default="")
    carrier_name = Prompt.ask("Insurance Carrier", default="")
    adjuster_email = Prompt.ask("Adjuster Email", default="")
    service_requested = Prompt.ask("Service Requested", default="")

    priority = Prompt.ask(
        "Priority",
        choices=["low", "medium", "high", "urgent"],
        default="medium",
    )

    with session_scope() as session:
        service = ReferralService(session)
        carrier_service = CarrierService(session)

        # Find or create carrier if specified
        carrier_id = None
        if carrier_name:
            carrier = carrier_service.find_or_create(carrier_name)
            carrier_id = carrier.id

        referral = service.create(
            claimant_name=claimant_name,
            claim_number=claim_number or None,
            carrier_id=carrier_id,
            carrier_name_raw=carrier_name or None,
            adjuster_email=adjuster_email or None,
            service_requested=service_requested or None,
            priority=Priority(priority),
            received_at=datetime.utcnow(),
        )

        console.print()
        console.print(f"[green]Referral #{referral.id} created successfully![/green]")


@referral_app.command("update-status")
def update_referral_status(
    referral_id: int = typer.Argument(..., help="Referral ID"),
    status: str = typer.Argument(..., help="New status"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Status change notes"),
):
    """Update the status of a referral."""
    try:
        new_status = ReferralStatus(status.lower())
    except ValueError:
        valid = ", ".join([s.value for s in ReferralStatus])
        console.print(f"[red]Invalid status. Valid options: {valid}[/red]")
        raise typer.Exit(1)

    with session_scope() as session:
        service = ReferralService(session)
        referral = service.update_status(referral_id, new_status, notes=notes)

        if not referral:
            console.print(f"[red]Referral {referral_id} not found.[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Referral #{referral_id} status updated to {new_status.value}[/green]")


@referral_app.command("approve")
def approve_referral(
    referral_id: int = typer.Argument(..., help="Referral ID to approve"),
):
    """Approve a referral."""
    with session_scope() as session:
        service = ReferralService(session)
        referral = service.approve(referral_id)

        if not referral:
            console.print(f"[red]Referral {referral_id} not found.[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Referral #{referral_id} approved![/green]")


@referral_app.command("reject")
def reject_referral(
    referral_id: int = typer.Argument(..., help="Referral ID to reject"),
    reason: str = typer.Argument(..., help="Rejection reason"),
):
    """Reject a referral with a reason."""
    with session_scope() as session:
        service = ReferralService(session)
        referral = service.reject(referral_id, reason)

        if not referral:
            console.print(f"[red]Referral {referral_id} not found.[/red]")
            raise typer.Exit(1)

        console.print(f"[red]Referral #{referral_id} rejected: {reason}[/red]")


@referral_app.command("history")
def show_referral_history(
    referral_id: int = typer.Argument(..., help="Referral ID"),
):
    """Show the audit history for a referral."""
    with session_scope() as session:
        service = ReferralService(session)
        logs = service.get_audit_log(referral_id)

        if not logs:
            console.print(f"[dim]No history found for referral {referral_id}.[/dim]")
            return

        table = Table(title=f"History for Referral #{referral_id}", box=box.ROUNDED)
        table.add_column("Timestamp", style="dim", width=20)
        table.add_column("Action", width=15)
        table.add_column("Field", width=15)
        table.add_column("Old Value", width=20)
        table.add_column("New Value", width=20)
        table.add_column("User", width=12)

        for log in logs:
            table.add_row(
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                log.action,
                log.field_name or "-",
                log.old_value or "-",
                log.new_value or "-",
                log.user or "-",
            )

        console.print(table)


# ============================================================================
# Carrier Commands
# ============================================================================
carrier_app = typer.Typer(help="Manage carriers")
app.add_typer(carrier_app, name="carrier")


@carrier_app.command("list")
def list_carriers():
    """List all carriers."""
    with session_scope() as session:
        service = CarrierService(session)
        carriers = service.list(active_only=False)

        if not carriers:
            console.print("[dim]No carriers found.[/dim]")
            return

        table = Table(title="Carriers", box=box.ROUNDED)
        table.add_column("ID", style="dim", width=5)
        table.add_column("Name", width=30)
        table.add_column("Code", width=10)
        table.add_column("Active", width=8)

        for carrier in carriers:
            active = "[green]Yes[/green]" if carrier.is_active else "[red]No[/red]"
            table.add_row(
                str(carrier.id),
                carrier.name,
                carrier.code or "-",
                active,
            )

        console.print(table)


@carrier_app.command("create")
def create_carrier(
    name: str = typer.Argument(..., help="Carrier name"),
    code: Optional[str] = typer.Option(None, "--code", "-c", help="Short code"),
):
    """Create a new carrier."""
    with session_scope() as session:
        service = CarrierService(session)
        carrier = service.create(name=name, code=code)
        console.print(f"[green]Carrier '{carrier.name}' (ID: {carrier.id}) created![/green]")


# ============================================================================
# Provider Commands
# ============================================================================
provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


@provider_app.command("list")
def list_providers(
    service_type: Optional[str] = typer.Option(None, "--service", "-s", help="Filter by service type"),
    state: Optional[str] = typer.Option(None, "--state", help="Filter by state"),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of results"),
):
    """List providers with optional filtering."""
    with session_scope() as session:
        service = ProviderService(session)
        providers = service.list(
            service_type=service_type,
            state=state,
            limit=limit,
        )

        if not providers:
            console.print("[dim]No providers found.[/dim]")
            return

        table = Table(title="Providers", box=box.ROUNDED)
        table.add_column("ID", style="dim", width=5)
        table.add_column("Name", width=25)
        table.add_column("NPI", width=12)
        table.add_column("City", width=15)
        table.add_column("State", width=6)
        table.add_column("Phone", width=15)
        table.add_column("Accepting", width=10)

        for provider in providers:
            accepting = "[green]Yes[/green]" if provider.accepting_new else "[red]No[/red]"
            table.add_row(
                str(provider.id),
                provider.name,
                provider.npi or "-",
                provider.city or "-",
                provider.state or "-",
                provider.phone or "-",
                accepting,
            )

        console.print(table)


@provider_app.command("create")
def create_provider(
    name: str = typer.Argument(..., help="Provider name"),
    npi: Optional[str] = typer.Option(None, "--npi", help="NPI number"),
    state: Optional[str] = typer.Option(None, "--state", help="State (2-letter)"),
    phone: Optional[str] = typer.Option(None, "--phone", help="Phone number"),
):
    """Create a new provider."""
    with session_scope() as session:
        service = ProviderService(session)
        provider = service.create(
            name=name,
            npi=npi,
            state=state.upper() if state else None,
            phone=phone,
        )
        console.print(f"[green]Provider '{provider.name}' (ID: {provider.id}) created![/green]")


@provider_app.command("find")
def find_providers(
    service_type: str = typer.Argument(..., help="Service type to match"),
    state: Optional[str] = typer.Option(None, "--state", help="Claimant state"),
    zip_code: Optional[str] = typer.Option(None, "--zip", help="Claimant ZIP code"),
):
    """Find matching providers for a service type."""
    with session_scope() as session:
        service = ProviderService(session)
        matches = service.find_matching_providers(
            service_type=service_type,
            state=state,
            zip_code=zip_code,
        )

        if not matches:
            console.print("[dim]No matching providers found.[/dim]")
            return

        table = Table(title=f"Matching Providers for {service_type}", box=box.ROUNDED)
        table.add_column("Score", width=7)
        table.add_column("Name", width=25)
        table.add_column("City", width=15)
        table.add_column("State", width=6)
        table.add_column("Wait (days)", width=12)

        for match in matches:
            provider = match["provider"]
            table.add_row(
                f"{match['score']:.0f}",
                provider.name,
                provider.city or "-",
                provider.state or "-",
                str(match["wait_days"]) if match["wait_days"] else "-",
            )

        console.print(table)


# ============================================================================
# Import Commands
# ============================================================================
import_app = typer.Typer(help="Import data from files")
app.add_typer(import_app, name="import")


@import_app.command("sample-email")
def import_sample_email(
    folder: str = typer.Option("Inbox/Assigned", "--folder", "-f", help="Folder path to pull from"),
):
    """Pull sample email data from the shared mailbox (first email in a chain)."""
    from referral_crm.services.email_service import EmailService

    settings = get_settings()

    if not settings.shared_mailbox:
        console.print("[red]SHARED_MAILBOX environment variable not set.[/red]")
        console.print("[dim]Set it in your .env file or environment.[/dim]")
        raise typer.Exit(1)

    email_service = EmailService()

    if not email_service.is_configured():
        console.print("[red]Microsoft Graph API not configured.[/red]")
        console.print("[dim]Set GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, and GRAPH_TENANT_ID.[/dim]")
        raise typer.Exit(1)

    console.print(f"[blue]Fetching from:[/blue] {settings.shared_mailbox}")
    console.print(f"[blue]Folder:[/blue] {folder}")
    console.print()

    with console.status("Fetching emails..."):
        try:
            messages = email_service.list_messages_from_shared_mailbox(
                mailbox=settings.shared_mailbox,
                folder_path=folder,
                top=1,
            )
        except Exception as e:
            console.print(f"[red]Error fetching emails: {e}[/red]")
            raise typer.Exit(1)

    if not messages:
        console.print("[yellow]No messages found in folder.[/yellow]")
        raise typer.Exit(0)

    # Get the first email in the chain
    message = messages[0]
    console.print(f"[dim]Found message: {message.subject}[/dim]")

    with console.status("Finding first message in chain..."):
        try:
            first_message = email_service.get_first_message_in_chain(
                message,
                mailbox=settings.shared_mailbox,
                folder_path=folder,
            )
        except Exception as e:
            console.print(f"[yellow]Could not get chain, using current message: {e}[/yellow]")
            first_message = message

    # Display the email
    console.print()
    console.print(Panel.fit(
        f"[bold]{first_message.subject}[/bold]",
        title="First Email in Chain",
        border_style="green",
    ))

    console.print(f"[cyan]From:[/cyan] {first_message.from_name} <{first_message.from_email}>")
    console.print(f"[cyan]Date:[/cyan] {first_message.received_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    console.print(f"[cyan]Has Attachments:[/cyan] {'Yes' if first_message.has_attachments else 'No'}")
    console.print()

    # Show body preview
    console.print("[cyan]Body Preview:[/cyan]")
    console.print(Panel(
        first_message.body_preview[:500] + ("..." if len(first_message.body_preview) > 500 else ""),
        border_style="dim",
    ))

    # Fetch attachments if present
    if first_message.has_attachments:
        console.print()
        with console.status("Fetching attachments..."):
            try:
                attachments = email_service.get_attachments_from_shared_mailbox(
                    first_message.id,
                    settings.shared_mailbox,
                )
                console.print(f"[cyan]Attachments ({len(attachments)}):[/cyan]")
                for att in attachments:
                    size_kb = att.size / 1024
                    console.print(f"  - {att.name} ({size_kb:.1f} KB, {att.content_type})")
            except Exception as e:
                console.print(f"[yellow]Could not fetch attachments: {e}[/yellow]")

    console.print()
    console.print(f"[dim]Message ID: {first_message.id}[/dim]")
    console.print(f"[dim]Conversation ID: {first_message.conversation_id}[/dim]")


@import_app.command("sample-referral")
def import_sample_referral(
    folder: str = typer.Option("Inbox/Assigned", "--folder", "-f", help="Folder path to pull from"),
    use_llm: bool = typer.Option(True, "--llm/--no-llm", help="Use LLM for extraction"),
    skip_attachments: bool = typer.Option(False, "--skip-attachments", help="Skip downloading attachments"),
    force: bool = typer.Option(False, "--force", help="Skip duplicate check and create anyway"),
):
    """Fetch a sample email from shared mailbox and create a referral in the database."""
    from pathlib import Path
    from referral_crm.services.email_service import EmailService, EmailMessage
    from referral_crm.services.referral_service import ReferralService, CarrierService

    settings = get_settings()

    # Validate configuration
    if not settings.shared_mailbox:
        console.print("[red]SHARED_MAILBOX environment variable not set.[/red]")
        raise typer.Exit(1)

    email_service = EmailService()
    if not email_service.is_configured():
        console.print("[red]Microsoft Graph API not configured.[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        "[bold]Sample Referral Import[/bold]\n"
        f"Mailbox: {settings.shared_mailbox}\n"
        f"Folder: {folder}\n"
        f"LLM Extraction: {'Yes' if use_llm else 'No'}",
        border_style="blue",
    ))
    console.print()

    # Step 1: Fetch email
    with console.status("[bold blue]Step 1/4:[/bold blue] Fetching email from shared mailbox..."):
        try:
            messages = email_service.list_messages_from_shared_mailbox(
                mailbox=settings.shared_mailbox,
                folder_path=folder,
                top=1,
            )
        except Exception as e:
            console.print(f"[red]Error fetching emails: {e}[/red]")
            raise typer.Exit(1)

    if not messages:
        console.print("[yellow]No messages found in folder.[/yellow]")
        raise typer.Exit(0)

    message = messages[0]
    console.print(f"[green]OK[/green] Found: {message.subject[:60]}...")

    # Step 2: Check if already processed
    with session_scope() as session:
        referral_service = ReferralService(session)
        carrier_service = CarrierService(session)

        existing = referral_service.get_by_email_id(message.id)
        if existing:
            console.print(f"[yellow]! Email already processed as Referral #{existing.id}[/yellow]")
            if not force and not Confirm.ask("Create a duplicate referral anyway?"):
                raise typer.Exit(0)
            # Clear the email_id to allow duplicate
            message_id_for_db = None
        else:
            message_id_for_db = message.id

        # Step 3: Extract data with LLM (optional)
        extraction_data = {}
        if use_llm:
            with console.status("[bold blue]Step 2/4:[/bold blue] Extracting data with LLM..."):
                try:
                    from referral_crm.services.extraction_service import ExtractionService
                    extraction_service = ExtractionService()

                    # Get attachment texts for better extraction
                    attachment_texts = []
                    if message.has_attachments and not skip_attachments:
                        try:
                            from referral_crm.services.extraction_service import extract_text_from_pdf
                            attachments = email_service.get_attachments_from_shared_mailbox(
                                message.id,
                                settings.shared_mailbox,
                            )
                            for att in attachments:
                                if att.content_bytes and att.name.lower().endswith('.pdf'):
                                    # Save temp and extract
                                    temp_path = Path(settings.attachments_dir) / "temp" / att.name
                                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                                    temp_path.write_bytes(att.content_bytes)
                                    text = extract_text_from_pdf(str(temp_path))
                                    if text:
                                        attachment_texts.append(text)
                                    temp_path.unlink(missing_ok=True)
                        except Exception as e:
                            console.print(f"[yellow]  Warning extracting attachments: {e}[/yellow]")

                    result = extraction_service.extract_from_email(
                        from_email=message.from_email,
                        subject=message.subject,
                        body=message.body_content,
                        attachment_texts=attachment_texts,
                    )
                    extraction_data = result.to_dict()
                    console.print("[green]OK[/green] LLM extraction complete")
                except Exception as e:
                    console.print(f"[yellow]! LLM extraction failed: {e}[/yellow]")
                    console.print("[dim]  Continuing without extraction...[/dim]")
        else:
            console.print("[dim]Step 2/4: Skipping LLM extraction[/dim]")

        # Step 4: Create referral
        with console.status("[bold blue]Step 3/4:[/bold blue] Creating referral in database..."):
            # Helper to get extracted values
            def get_value(field: str) -> Optional[str]:
                if field in extraction_data and extraction_data[field]:
                    return extraction_data[field].get("value")
                return None

            # Find or create carrier
            carrier_id = None
            carrier_name_raw = get_value("insurance_carrier")
            if carrier_name_raw:
                carrier = carrier_service.find_or_create(carrier_name_raw)
                carrier_id = carrier.id

            # Parse dates
            claimant_dob = None
            date_of_injury = None
            try:
                if get_value("claimant_dob"):
                    claimant_dob = datetime.strptime(get_value("claimant_dob"), "%Y-%m-%d")
                if get_value("date_of_injury"):
                    date_of_injury = datetime.strptime(get_value("date_of_injury"), "%Y-%m-%d")
            except ValueError:
                pass

            # Determine priority
            priority = Priority.MEDIUM
            if get_value("priority"):
                try:
                    priority = Priority(get_value("priority"))
                except ValueError:
                    pass

            # Create the referral
            referral = referral_service.create(
                # Email metadata
                email_id=message_id_for_db,
                email_internet_message_id=message.internet_message_id,
                email_web_link=message.web_link,
                email_conversation_id=message.conversation_id,
                email_subject=message.subject,
                email_body_preview=message.body_preview,
                email_body_html=message.body_content,
                received_at=message.received_datetime,
                # Adjuster info
                adjuster_name=get_value("adjuster_name"),
                adjuster_email=message.from_email,
                adjuster_phone=get_value("adjuster_phone"),
                # Carrier
                carrier_id=carrier_id,
                carrier_name_raw=carrier_name_raw,
                # Claim info
                claim_number=get_value("claim_number"),
                # Claimant info
                claimant_name=get_value("claimant_name"),
                claimant_dob=claimant_dob,
                claimant_phone=get_value("claimant_phone"),
                claimant_address=get_value("claimant_address"),
                # Employer
                employer_name=get_value("employer_name"),
                # Injury/Service
                date_of_injury=date_of_injury,
                body_parts=get_value("body_parts"),
                service_requested=get_value("service_requested"),
                authorization_number=get_value("authorization_number"),
                # Priority (status defaults to PENDING in create())
                priority=priority,
                # Extraction metadata
                extraction_data=extraction_data if extraction_data else None,
                extraction_timestamp=datetime.utcnow() if extraction_data else None,
            )
            console.print(f"[green]OK[/green] Created Referral #{referral.id}")

            # Upload email to S3 if configured
            from referral_crm.services.storage_service import get_storage_service
            storage = get_storage_service()
            if storage.is_configured():
                try:
                    email_metadata = {
                        "id": message.id,
                        "subject": message.subject,
                        "from_email": message.from_email,
                        "from_name": message.from_name,
                        "received_datetime": message.received_datetime.isoformat(),
                        "conversation_id": message.conversation_id,
                    }
                    s3_result = storage.upload_email(
                        referral.id,
                        email_html=message.body_content,
                        email_metadata=email_metadata,
                    )
                    # Update referral with S3 key
                    referral_service.update(
                        referral.id,
                        user="sample-import",
                        s3_email_key=s3_result.get("email_html_key"),
                    )
                    console.print(f"[green]OK[/green] Uploaded email to S3")
                except Exception as e:
                    console.print(f"[yellow]! S3 email upload failed: {e}[/yellow]")

        # Step 5: Save attachments (local + S3)
        if message.has_attachments and not skip_attachments:
            with console.status("[bold blue]Step 4/4:[/bold blue] Downloading attachments..."):
                try:
                    from referral_crm.services.storage_service import get_storage_service

                    attachments = email_service.get_attachments_from_shared_mailbox(
                        message.id,
                        settings.shared_mailbox,
                    )
                    attachments_dir = Path(settings.attachments_dir) / str(referral.id)
                    attachments_dir.mkdir(parents=True, exist_ok=True)

                    # Check if S3 is configured
                    storage = get_storage_service()
                    s3_enabled = storage.is_configured()
                    if s3_enabled:
                        console.print(f"[dim]  S3 bucket: {storage.bucket}[/dim]")

                    saved_count = 0
                    s3_count = 0
                    for att in attachments:
                        if att.content_bytes:
                            # Save locally
                            filepath = attachments_dir / att.name
                            filepath.write_bytes(att.content_bytes)

                            # Upload to S3 if configured
                            s3_key = None
                            s3_url = None
                            if s3_enabled:
                                try:
                                    s3_result = storage.upload_attachment(
                                        referral_id=referral.id,
                                        filename=att.name,
                                        content=att.content_bytes,
                                        content_type=att.content_type,
                                    )
                                    s3_key = s3_result.get("s3_key")
                                    # Generate a presigned URL (1 hour expiry)
                                    s3_url = storage.get_attachment_url(
                                        referral.id,
                                        att.name,
                                        expires_in=3600,
                                    )
                                    s3_count += 1
                                except Exception as e:
                                    console.print(f"[yellow]  S3 upload failed for {att.name}: {e}[/yellow]")

                            # Add to database
                            referral_service.add_attachment(
                                referral_id=referral.id,
                                filename=att.name,
                                content_type=att.content_type,
                                size_bytes=att.size,
                                storage_path=str(filepath),
                                graph_attachment_id=att.id,
                                s3_key=s3_key,
                            )
                            saved_count += 1

                    console.print(f"[green]OK[/green] Saved {saved_count} attachment(s) locally")
                    if s3_enabled:
                        console.print(f"[green]OK[/green] Uploaded {s3_count} attachment(s) to S3")
                except Exception as e:
                    console.print(f"[yellow]! Error saving attachments: {e}[/yellow]")
        else:
            console.print("[dim]Step 4/4: Skipping attachments[/dim]")

        # Save data needed for summary before session closes
        referral_id = referral.id
        referral_claimant_name = referral.claimant_name
        referral_claim_number = referral.claim_number
        referral_service_requested = referral.service_requested
        referral_priority = referral.priority.value
        referral_status = referral.status.value

    # Summary (outside session context)
    console.print()

    # Check S3 status for summary
    from referral_crm.services.storage_service import get_storage_service
    storage = get_storage_service()
    s3_status = "[green]Enabled[/green]" if storage.is_configured() else "[yellow]Not configured[/yellow]"

    console.print(Panel.fit(
        f"[bold green]Referral #{referral_id} created successfully![/bold green]\n\n"
        f"Claimant: {referral_claimant_name or 'Unknown'}\n"
        f"Claim #: {referral_claim_number or 'Unknown'}\n"
        f"Carrier: {carrier_name_raw or 'Unknown'}\n"
        f"Service: {referral_service_requested or 'Unknown'}\n"
        f"Priority: {referral_priority.upper()}\n"
        f"Status: {referral_status}\n"
        f"S3 Storage: {s3_status}",
        title="Summary",
        border_style="green",
    ))

    # Show S3 URLs if available
    if storage.is_configured():
        console.print()
        console.print("[cyan]S3 Access URLs:[/cyan]")
        email_url = storage.get_email_html_url(referral_id, expires_in=3600)
        if email_url:
            console.print(f"  Email: {email_url[:80]}...")

        # List attachment URLs
        s3_attachments = storage.list_attachments(referral_id)
        for att in s3_attachments[:3]:  # Show first 3
            url = storage.get_attachment_url(referral_id, att["filename"], expires_in=3600)
            if url:
                console.print(f"  {att['filename']}: {url[:60]}...")
        if len(s3_attachments) > 3:
            console.print(f"  [dim]... and {len(s3_attachments) - 3} more[/dim]")

    console.print()
    console.print(f"[dim]View details: uv run python run.py cli referral show {referral_id}[/dim]")


@import_app.command("demo-data")
def import_demo_data():
    """Import demo/sample data for testing."""
    if not Confirm.ask("This will add sample data to the database. Continue?"):
        raise typer.Exit()

    with session_scope() as session:
        carrier_service = CarrierService(session)
        provider_service = ProviderService(session)
        rate_service = RateService(session)
        referral_service = ReferralService(session)

        # Create sample carriers
        carriers = [
            ("ACE Insurance", "ACE"),
            ("Travelers Insurance", "TRV"),
            ("Liberty Mutual", "LM"),
            ("Hartford Insurance", "HART"),
            ("Zurich Insurance", "ZUR"),
        ]

        carrier_map = {}
        for name, code in carriers:
            carrier = carrier_service.find_or_create(name, code=code)
            carrier_map[name] = carrier
            console.print(f"  Created carrier: {name}")

        # Create sample providers
        providers_data = [
            ("ABC Physical Therapy", "1234567890", "Chicago", "IL", "(312) 555-0100", ["PT Evaluation", "PT Treatment"]),
            ("Midwest Imaging Center", "2345678901", "Springfield", "IL", "(217) 555-0200", ["MRI", "CT Scan", "X-Ray"]),
            ("Premier Ortho Group", "3456789012", "Naperville", "IL", "(630) 555-0300", ["IME", "Orthopedic Consult"]),
            ("Valley PT & Rehab", "4567890123", "Aurora", "IL", "(331) 555-0400", ["PT Evaluation", "PT Treatment"]),
            ("Central Pain Management", "5678901234", "Peoria", "IL", "(309) 555-0500", ["Pain Management", "Injection"]),
        ]

        for name, npi, city, state, phone, services in providers_data:
            provider = provider_service.create(
                name=name,
                npi=npi,
                city=city,
                state=state,
                phone=phone,
                avg_wait_days=5,
            )
            for service_type in services:
                provider_service.add_service(provider.id, service_type)
            console.print(f"  Created provider: {name}")

        # Create sample rate schedules
        console.print("  Created rate schedules")
        for carrier in carrier_map.values():
            rate_service.create(carrier_id=carrier.id, service_type="PT Evaluation", rate_amount=150.00, state="IL")
            rate_service.create(carrier_id=carrier.id, service_type="PT Treatment", rate_amount=125.00, state="IL")
            rate_service.create(carrier_id=carrier.id, service_type="MRI", rate_amount=800.00, state="IL")
            rate_service.create(carrier_id=carrier.id, service_type="IME", rate_amount=1200.00, state="IL")

        # Create sample referrals
        referrals_data = [
            ("John Smith", "WC-2025-001234", "ACE Insurance", Priority.HIGH, ReferralStatus.PENDING),
            ("Jane Doe", "WC-2025-005678", "Travelers Insurance", Priority.MEDIUM, ReferralStatus.IN_REVIEW),
            ("Bob Johnson", "WC-2025-009012", "Liberty Mutual", Priority.LOW, ReferralStatus.APPROVED),
            ("Mary Williams", "WC-2025-003456", "Hartford Insurance", Priority.URGENT, ReferralStatus.PENDING),
        ]

        for name, claim, carrier_name, priority, status in referrals_data:
            carrier = carrier_map[carrier_name]
            referral_service.create(
                claimant_name=name,
                claim_number=claim,
                carrier_id=carrier.id,
                carrier_name_raw=carrier_name,
                adjuster_email=f"adjuster@{carrier_name.lower().replace(' ', '')}.com",
                service_requested="PT Evaluation",
                priority=priority,
                status=status,
                received_at=datetime.utcnow(),
            )
            console.print(f"  Created referral: {name}")

    console.print()
    console.print("[green]Demo data imported successfully![/green]")


# ============================================================================
# Queue Dashboard
# ============================================================================
@app.command("dashboard")
def show_dashboard():
    """Show an interactive queue dashboard."""
    with session_scope() as session:
        service = ReferralService(session)

        # Get counts
        counts = service.count_by_status()
        total = sum(counts.values())

        # Header
        console.print()
        console.print(Panel.fit(
            "[bold white]REFERRAL ASSIGNMENT QUEUE[/bold white]",
            border_style="blue",
        ))
        console.print()

        # Status summary
        pending = counts.get("pending", 0)
        in_review = counts.get("in_review", 0)
        needs_info = counts.get("needs_info", 0)
        approved = counts.get("approved", 0)

        console.print(f"  [yellow]Pending:[/yellow] {pending}  "
                      f"[blue]In Review:[/blue] {in_review}  "
                      f"[magenta]Needs Info:[/magenta] {needs_info}  "
                      f"[green]Approved:[/green] {approved}  "
                      f"[dim]Total:[/dim] {total}")
        console.print()

        # Pending referrals (urgent first)
        pending_refs = service.list(
            status=ReferralStatus.PENDING,
            limit=10,
            order_by="priority",
        )

        if pending_refs:
            console.print("[bold yellow]Pending Referrals[/bold yellow]")
            table = Table(box=box.SIMPLE)
            table.add_column("ID", style="dim", width=5)
            table.add_column("Pri", width=4)
            table.add_column("Claimant", width=20)
            table.add_column("Carrier", width=15)
            table.add_column("Service", width=15)
            table.add_column("Received", width=12)

            for ref in pending_refs:
                pri_icon = {
                    Priority.URGENT: "[red bold]!![/red bold]",
                    Priority.HIGH: "[red]![/red]",
                    Priority.MEDIUM: "[yellow]-[/yellow]",
                    Priority.LOW: "[dim].[/dim]",
                }.get(ref.priority, "-")

                received = ref.received_at.strftime("%H:%M") if ref.received_at else "-"

                table.add_row(
                    str(ref.id),
                    pri_icon,
                    ref.claimant_name or "-",
                    ref.carrier.name if ref.carrier else "-",
                    ref.service_requested or "-",
                    received,
                )

            console.print(table)
        else:
            console.print("[dim]No pending referrals.[/dim]")

        console.print()
        console.print("[dim]Use 'referral-crm referral show <id>' to view details[/dim]")


# ============================================================================
# Automation Commands
# ============================================================================
auto_app = typer.Typer(help="Automation and batch processing")
app.add_typer(auto_app, name="auto")


@auto_app.command("ingest")
def run_email_ingestion(
    max_emails: int = typer.Option(50, "--max", "-n", help="Maximum emails to process"),
    since_hours: int = typer.Option(24, "--since", "-s", help="Process emails from last N hours"),
    no_mark_read: bool = typer.Option(False, "--no-mark-read", help="Don't mark emails as read"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM extraction"),
):
    """Run email ingestion pipeline."""
    from referral_crm.automations.email_ingestion import EmailIngestionPipeline

    pipeline = EmailIngestionPipeline(
        mark_as_read=not no_mark_read,
        use_llm=not no_llm,
    )
    pipeline.run(max_emails=max_emails, since_hours=since_hours)


@auto_app.command("poll")
def start_email_polling(
    interval: int = typer.Option(60, "--interval", "-i", help="Poll interval in seconds"),
):
    """Start continuous email polling."""
    from referral_crm.automations.email_ingestion import EmailPoller

    poller = EmailPoller()
    poller.start(interval_seconds=interval)


@auto_app.command("assign-providers")
def auto_assign_providers(
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Preview without making changes"),
):
    """Auto-assign providers to approved referrals."""
    from referral_crm.automations.batch_processor import BatchProcessor

    processor = BatchProcessor()
    processor.auto_assign_providers(dry_run=dry_run)


@auto_app.command("escalate")
def escalate_stale(
    hours: int = typer.Option(24, "--hours", "-h", help="Hours threshold for escalation"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Preview without making changes"),
):
    """Escalate stale pending referrals."""
    from referral_crm.automations.batch_processor import BatchProcessor

    processor = BatchProcessor()
    processor.escalate_stale_referrals(hours_threshold=hours, dry_run=dry_run)


@auto_app.command("report")
def generate_report():
    """Generate daily summary report."""
    from referral_crm.automations.batch_processor import BatchProcessor

    processor = BatchProcessor()
    processor.generate_daily_report()


@auto_app.command("cleanup")
def cleanup_old(
    days: int = typer.Option(90, "--days", "-d", help="Age threshold in days"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Dry run by default"),
):
    """Archive/delete old completed referrals."""
    from referral_crm.automations.batch_processor import BatchProcessor

    processor = BatchProcessor()
    processor.cleanup_old_referrals(days_old=days, dry_run=dry_run)


# ============================================================================
# Server Commands
# ============================================================================
@app.command("serve")
def start_server(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload"),
):
    """Start the FastAPI web server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[/red]")
        raise typer.Exit(1)

    console.print(f"[blue]Starting server at http://{host}:{port}[/blue]")
    uvicorn.run(
        "referral_crm.api:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
