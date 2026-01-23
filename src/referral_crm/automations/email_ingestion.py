"""
Email ingestion pipeline - fetches emails and creates referrals.
"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from referral_crm.config import get_settings
from referral_crm.models import session_scope, ReferralStatus, Priority
from referral_crm.services.email_service import EmailService, EmailMessage
from referral_crm.services.extraction_service import (
    ExtractionService,
    extract_text_from_pdf,
    extract_text_from_image,
)
from referral_crm.services.referral_service import ReferralService, CarrierService
from referral_crm.services.storage_service import get_storage_service

console = Console()


class EmailIngestionPipeline:
    """
    Pipeline for ingesting referral emails.

    Flow:
    1. Fetch unread emails from inbox
    2. For each email:
       a. Check if already processed (by email_id)
       b. Extract data using LLM
       c. Create referral record
       d. Download and process attachments
       e. Mark email as read (optional)
    """

    def __init__(
        self,
        mark_as_read: bool = True,
        extract_attachments: bool = True,
        use_llm: bool = True,
    ):
        self.settings = get_settings()
        self.email_service = EmailService()
        self.extraction_service = ExtractionService() if use_llm else None
        self.mark_as_read = mark_as_read
        self.extract_attachments = extract_attachments
        self.use_llm = use_llm

    def run(
        self,
        max_emails: int = 50,
        since_hours: Optional[int] = 24,
    ) -> dict:
        """
        Run the ingestion pipeline.

        Args:
            max_emails: Maximum number of emails to process
            since_hours: Only process emails received in the last N hours

        Returns:
            dict with processing statistics
        """
        stats = {
            "processed": 0,
            "created": 0,
            "skipped": 0,
            "errors": 0,
        }

        if not self.email_service.is_configured():
            console.print("[yellow]Email service not configured. Skipping ingestion.[/yellow]")
            return stats

        console.print("[blue]Starting email ingestion pipeline...[/blue]")

        # Build filter query
        filter_query = None
        if since_hours:
            since_date = datetime.utcnow() - timedelta(hours=since_hours)
            filter_query = f"receivedDateTime ge {since_date.isoformat()}Z"

        # Fetch emails
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching emails...", total=None)

            try:
                messages = self.email_service.list_messages(
                    folder=self.settings.email_inbox_folder,
                    top=max_emails,
                    filter_query=filter_query,
                )
            except Exception as e:
                console.print(f"[red]Error fetching emails: {e}[/red]")
                return stats

            progress.update(task, description=f"Found {len(messages)} emails")

        # Process each email
        for message in messages:
            try:
                result = self._process_email(message)
                stats["processed"] += 1

                if result == "created":
                    stats["created"] += 1
                elif result == "skipped":
                    stats["skipped"] += 1

            except Exception as e:
                console.print(f"[red]Error processing email {message.id}: {e}[/red]")
                stats["errors"] += 1

        console.print()
        console.print(f"[green]Ingestion complete:[/green] "
                      f"{stats['created']} created, "
                      f"{stats['skipped']} skipped, "
                      f"{stats['errors']} errors")

        return stats

    def _process_email(self, message: EmailMessage) -> str:
        """
        Process a single email.

        Returns:
            "created" if new referral created
            "skipped" if already processed
        """
        with session_scope() as session:
            referral_service = ReferralService(session)
            carrier_service = CarrierService(session)

            # Check if already processed
            existing = referral_service.get_by_email_id(message.id)
            if existing:
                return "skipped"

            console.print(f"  Processing: {message.subject[:50]}...")

            # Extract data using LLM
            extraction_data = {}
            if self.use_llm and self.extraction_service:
                attachment_texts = []

                # Get attachment texts if enabled
                if self.extract_attachments and message.has_attachments:
                    attachment_texts = self._get_attachment_texts(message.id)

                result = self.extraction_service.extract_from_email(
                    from_email=message.from_email,
                    subject=message.subject,
                    body=message.body_content,
                    attachment_texts=attachment_texts,
                )
                extraction_data = result.to_dict()

            # Find or create carrier
            carrier_id = None
            carrier_name_raw = None
            if extraction_data.get("insurance_carrier"):
                carrier_name_raw = extraction_data["insurance_carrier"]["value"]
                if carrier_name_raw:
                    carrier = carrier_service.find_or_create(carrier_name_raw)
                    carrier_id = carrier.id

            # Determine priority
            priority = Priority.MEDIUM
            if extraction_data.get("priority"):
                try:
                    priority = Priority(extraction_data["priority"]["value"])
                except ValueError:
                    pass

            # Parse dates
            claimant_dob = None
            date_of_injury = None
            if extraction_data.get("claimant_dob"):
                dob_str = extraction_data["claimant_dob"]["value"]
                claimant_dob = self._parse_date(dob_str)
            if extraction_data.get("date_of_injury"):
                doi_str = extraction_data["date_of_injury"]["value"]
                date_of_injury = self._parse_date(doi_str)

            # Create referral
            referral = referral_service.create(
                # Email metadata
                email_id=message.id,
                email_internet_message_id=message.internet_message_id,
                email_web_link=message.web_link,
                email_conversation_id=message.conversation_id,
                email_subject=message.subject,
                email_body_preview=message.body_preview,
                email_body_html=message.body_content,
                received_at=message.received_datetime,
                # Adjuster info
                adjuster_name=self._get_extracted_value(extraction_data, "adjuster_name"),
                adjuster_email=message.from_email,
                adjuster_phone=self._get_extracted_value(extraction_data, "adjuster_phone"),
                # Carrier
                carrier_id=carrier_id,
                carrier_name_raw=carrier_name_raw,
                # Claim info
                claim_number=self._get_extracted_value(extraction_data, "claim_number"),
                # Claimant info
                claimant_name=self._get_extracted_value(extraction_data, "claimant_name"),
                claimant_dob=claimant_dob,
                claimant_phone=self._get_extracted_value(extraction_data, "claimant_phone"),
                claimant_address=self._get_extracted_value(extraction_data, "claimant_address"),
                # Employer
                employer_name=self._get_extracted_value(extraction_data, "employer_name"),
                # Injury/Service
                date_of_injury=date_of_injury,
                body_parts=self._get_extracted_value(extraction_data, "body_parts"),
                service_requested=self._get_extracted_value(extraction_data, "service_requested"),
                authorization_number=self._get_extracted_value(extraction_data, "authorization_number"),
                # Status
                status=ReferralStatus.PENDING,
                priority=priority,
                # Extraction metadata
                extraction_data=extraction_data,
                extraction_timestamp=datetime.utcnow(),
            )

            # Upload email content and extraction data to S3
            s3_keys = self._upload_to_s3(
                referral.id,
                message,
                extraction_data,
                referral_service,
            )

            # Update referral with S3 keys
            if s3_keys:
                referral_service.update(
                    referral.id,
                    user="ingestion",
                    s3_email_key=s3_keys.get("email_html_key"),
                    s3_extraction_key=s3_keys.get("extraction_key"),
                )

            # Download and save attachments (local + S3)
            if self.extract_attachments and message.has_attachments:
                self._save_attachments(referral.id, message.id, referral_service)

            # Mark as read
            if self.mark_as_read:
                try:
                    self.email_service.mark_as_read(message.id)
                except Exception:
                    pass  # Non-critical

            console.print(f"    [green]Created referral #{referral.id}[/green]")
            return "created"

    def _upload_to_s3(
        self,
        referral_id: int,
        message: EmailMessage,
        extraction_data: dict,
        referral_service: ReferralService,
    ) -> Optional[dict]:
        """Upload email and extraction data to S3."""
        storage = get_storage_service()
        if not storage.is_configured():
            return None

        try:
            # Build email metadata
            email_metadata = {
                "id": message.id,
                "subject": message.subject,
                "from_email": message.from_email,
                "from_name": message.from_name,
                "received_datetime": message.received_datetime.isoformat(),
                "web_link": message.web_link,
                "internet_message_id": message.internet_message_id,
                "conversation_id": message.conversation_id,
                "has_attachments": message.has_attachments,
            }

            # Upload email content
            result = storage.upload_email(
                referral_id,
                email_html=message.body_content,
                email_metadata=email_metadata,
            )

            # Upload extraction data
            if extraction_data:
                result["extraction_key"] = storage.upload_extraction(
                    referral_id,
                    extraction_data,
                )

            console.print(f"    [dim]Uploaded to S3[/dim]")
            return result

        except Exception as e:
            console.print(f"    [yellow]S3 upload warning: {e}[/yellow]")
            return None

    def _get_extracted_value(self, data: dict, field: str) -> Optional[str]:
        """Get a value from extraction data."""
        if field in data and data[field]:
            return data[field].get("value")
        return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse a date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

    def _get_attachment_texts(self, message_id: str) -> list[str]:
        """Get extracted text from email attachments."""
        texts = []
        try:
            attachments = self.email_service.get_attachments(message_id)
            for att in attachments:
                if att.content_bytes:
                    # Save to temp and extract
                    temp_dir = Path("/tmp/referral_crm_attachments")
                    temp_dir.mkdir(exist_ok=True)
                    temp_path = temp_dir / att.name

                    temp_path.write_bytes(att.content_bytes)

                    # Extract text based on type
                    if att.content_type == "application/pdf" or att.name.lower().endswith(".pdf"):
                        text = extract_text_from_pdf(str(temp_path))
                        if text:
                            texts.append(text)
                    elif att.content_type.startswith("image/"):
                        text = extract_text_from_image(str(temp_path))
                        if text:
                            texts.append(text)

                    # Cleanup
                    temp_path.unlink(missing_ok=True)

        except Exception as e:
            console.print(f"    [yellow]Warning: Could not extract attachments: {e}[/yellow]")

        return texts

    def _save_attachments(
        self,
        referral_id: int,
        message_id: str,
        referral_service: ReferralService,
    ) -> None:
        """Download and save attachments for a referral (local + S3)."""
        storage = get_storage_service()
        s3_enabled = storage.is_configured()

        try:
            attachments = self.email_service.get_attachments(message_id)
            attachments_dir = self.settings.attachments_dir / str(referral_id)
            attachments_dir.mkdir(parents=True, exist_ok=True)

            for att in attachments:
                if att.content_bytes:
                    # Save locally
                    filepath = attachments_dir / att.name
                    filepath.write_bytes(att.content_bytes)

                    # Extract text for certain types
                    extracted_text = None
                    if att.content_type == "application/pdf" or att.name.lower().endswith(".pdf"):
                        extracted_text = extract_text_from_pdf(str(filepath))
                    elif att.content_type and att.content_type.startswith("image/"):
                        extracted_text = extract_text_from_image(str(filepath))

                    # Upload to S3 if configured
                    s3_key = None
                    s3_text_key = None
                    if s3_enabled:
                        try:
                            s3_result = storage.upload_attachment(
                                referral_id=referral_id,
                                filename=att.name,
                                content=att.content_bytes,
                                content_type=att.content_type,
                                extracted_text=extracted_text,
                            )
                            s3_key = s3_result.get("s3_key")
                            s3_text_key = s3_result.get("text_s3_key")
                        except Exception as e:
                            console.print(f"    [yellow]S3 attachment upload warning: {e}[/yellow]")

                    # Add to database with S3 keys
                    referral_service.add_attachment(
                        referral_id=referral_id,
                        filename=att.name,
                        content_type=att.content_type,
                        size_bytes=att.size,
                        storage_path=str(filepath),
                        graph_attachment_id=att.id,
                        extracted_text=extracted_text,
                        s3_key=s3_key,
                        s3_text_key=s3_text_key,
                    )

            att_count = len(attachments)
            if att_count > 0:
                console.print(f"    [dim]Saved {att_count} attachment(s)[/dim]")

        except Exception as e:
            console.print(f"    [yellow]Warning: Could not save attachments: {e}[/yellow]")


class EmailPoller:
    """
    Continuous email polling daemon.
    Runs the ingestion pipeline at regular intervals.
    """

    def __init__(self, pipeline: Optional[EmailIngestionPipeline] = None):
        self.settings = get_settings()
        self.pipeline = pipeline or EmailIngestionPipeline()
        self.running = False

    def start(self, interval_seconds: Optional[int] = None):
        """
        Start the polling loop.

        Args:
            interval_seconds: Override the default poll interval
        """
        interval = interval_seconds or self.settings.email_poll_interval_seconds
        self.running = True

        console.print(f"[blue]Starting email poller (interval: {interval}s)[/blue]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        console.print()

        while self.running:
            try:
                self.pipeline.run(max_emails=20, since_hours=1)
            except KeyboardInterrupt:
                self.stop()
                break
            except Exception as e:
                console.print(f"[red]Polling error: {e}[/red]")

            # Wait for next interval
            if self.running:
                time.sleep(interval)

    def stop(self):
        """Stop the polling loop."""
        self.running = False
        console.print("\n[yellow]Email poller stopped.[/yellow]")


def run_ingestion(
    max_emails: int = 50,
    since_hours: int = 24,
    mark_as_read: bool = True,
    use_llm: bool = True,
):
    """
    Convenience function to run a single ingestion pass.
    Can be called from scripts or CLI.
    """
    pipeline = EmailIngestionPipeline(
        mark_as_read=mark_as_read,
        use_llm=use_llm,
    )
    return pipeline.run(max_emails=max_emails, since_hours=since_hours)
