"""
Email ingestion pipeline - fetches emails and creates referrals.

Updated to use the new normalized schema:
- Creates Email records first
- Uses WorkflowService for queue management
- Uses ServiceLineItemParser for line items
"""

import time
from datetime import datetime, timedelta
import tempfile
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from referral_crm.config import get_settings
from referral_crm.models import (
    session_scope,
    Email,
    EmailStatus,
    Attachment,
    ExtractionResult,
    Referral,
    ReferralStatus,
    ReferralLineItem,
    Priority,
    DocumentType,
)
from referral_crm.services.email_service import EmailService, EmailMessage
from referral_crm.services.extraction_service import (
    ExtractionService,
    extract_text_from_pdf,
    extract_text_from_image,
)
from referral_crm.services.referral_service import CarrierService
from referral_crm.services.storage_service import get_storage_service
from referral_crm.services.workflow_service import WorkflowService
from referral_crm.services.line_item_service import LineItemService
from referral_crm.services.filemaker_conversion import FieldTransformer

console = Console()


class EmailIngestionPipeline:
    """
    Pipeline for ingesting referral emails.

    New Flow:
    1. Fetch unread emails from inbox
    2. For each email:
       a. Check if already processed (by graph_id)
       b. Create Email record
       c. Queue for extraction
       d. Extract data using LLM
       e. Create Referral + LineItems
       f. Queue for intake validation
       g. Download and process attachments
       h. Mark email as read (optional)
    """

    def __init__(
        self,
        mark_as_read: bool = True,
        extract_attachments: bool = True,
        use_llm: bool = True,
        log_callback: Optional[callable] = None,
    ):
        self.settings = get_settings()
        self.email_service = EmailService()
        self.extraction_service = ExtractionService() if use_llm else None
        self.mark_as_read = mark_as_read
        self.extract_attachments = extract_attachments
        self.use_llm = use_llm
        self.log_callback = log_callback

    def _log(self, message: str):
        """Log a message to console and callback if available."""
        # Strip rich markup for callback
        plain_message = message.replace("[blue]", "").replace("[/blue]", "") \
                               .replace("[green]", "").replace("[/green]", "") \
                               .replace("[yellow]", "").replace("[/yellow]", "") \
                               .replace("[red]", "").replace("[/red]", "") \
                               .replace("[bold]", "").replace("[/bold]", "")
        if self.log_callback:
            self.log_callback(plain_message)
        console.print(message)

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
            self._log("[yellow]Email service not configured. Skipping ingestion.[/yellow]")
            return stats

        self._log("[blue]Starting email ingestion pipeline...[/blue]")

        # Build filter query
        filter_query = None
        if since_hours:
            since_date = datetime.utcnow().replace(microsecond=0) - timedelta(hours=since_hours)
            filter_query = f"receivedDateTime ge {since_date.isoformat()}Z"

        # Fetch emails
        self._log("Fetching emails from inbox...")
        try:
            messages = self.email_service.list_messages(
                folder=self.settings.email_inbox_folder,
                top=max_emails,
                filter_query=filter_query,
                mailbox=self.settings.shared_mailbox or self.settings.graph_mailbox,
            )
        except Exception as e:
            self._log(f"[red]Error fetching emails: {e}[/red]")
            return stats

        self._log(f"Found {len(messages)} emails to process")

        # Process each email
        for i, message in enumerate(messages, 1):
            try:
                self._log(f"[{i}/{len(messages)}] Processing: {message.subject[:60]}...")
                result = self._process_email(message)
                stats["processed"] += 1

                if result == "created":
                    stats["created"] += 1
                    self._log(f"  -> Created new referral")
                elif result == "skipped":
                    stats["skipped"] += 1
                    self._log(f"  -> Skipped (already processed)")

            except Exception as e:
                self._log(f"[red]Error processing email: {e}[/red]")
                stats["errors"] += 1

        self._log(f"[green]Ingestion complete:[/green] "
                  f"{stats['created']} created, "
                  f"{stats['skipped']} skipped, "
                  f"{stats['errors']} errors")

        return stats

    def _process_email(self, message: EmailMessage) -> str:
        """
        Process a single email using the new schema.

        Returns:
            "created" if new referral created
            "skipped" if already processed
        """
        with session_scope() as session:
            workflow_service = WorkflowService(session)
            line_item_service = LineItemService(session)
            carrier_service = CarrierService(session)

            # Check if already processed (by graph_id)
            existing_email = session.query(Email).filter(
                Email.graph_id == message.id
            ).first()
            if existing_email:
                return "skipped"

            # ================================================================
            # STEP 1: Create Email record
            # ================================================================
            email = Email(
                graph_id=message.id,
                internet_message_id=message.internet_message_id,
                conversation_id=message.conversation_id,
                web_link=message.web_link,
                subject=message.subject,
                from_email=message.from_email,
                from_name=message.from_name,
                body_preview=message.body_preview,
                body_html=message.body_content,
                has_attachments=message.has_attachments,
                received_at=message.received_datetime,
                status=EmailStatus.RECEIVED,
            )
            session.add(email)
            session.flush()  # Get email.id

            # ================================================================
            # STEP 2: Download and save attachments to Email
            # ================================================================
            attachment_texts = []
            if self.extract_attachments and message.has_attachments:
                attachment_texts = self._save_attachments_to_email(
                    email, message.id, session
                )

            # ================================================================
            # STEP 3: Queue for extraction and run LLM extraction
            # ================================================================
            workflow_service.queue_email_for_extraction(email)
            workflow_service.start_extraction(email)

            extraction_data = {}
            extraction_confidence = 0.0

            if self.use_llm and self.extraction_service:
                try:
                    start_time = datetime.utcnow()
                    result = self.extraction_service.extract_from_email(
                        from_email=message.from_email,
                        subject=message.subject,
                        body=message.body_content,
                        attachment_texts=attachment_texts,
                    )
                    extraction_data = result.to_dict()
                    extraction_confidence = result.get_overall_confidence()
                    duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                    # Save extraction result
                    extraction_result = ExtractionResult(
                        email_id=email.id,
                        raw_extraction=extraction_data,
                        overall_confidence=extraction_confidence,
                        field_confidences={
                            k: v.get("confidence", 0) for k, v in extraction_data.items()
                        },
                        model_used=self.settings.claude_model,
                        extraction_duration_ms=duration_ms,
                    )
                    session.add(extraction_result)

                except Exception as e:
                    console.print(f"    [yellow]Extraction warning: {e}[/yellow]")
                    workflow_service.fail_extraction(email, str(e))
                    return "created"  # Email created but extraction failed

            # ================================================================
            # STEP 4: Create Referral from extracted data
            # ================================================================

            # Find or create carrier
            carrier_id = None
            carrier_name_raw = self._get_extracted_value(extraction_data, "insurance_carrier")
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
            patient_dob = self._parse_date(
                self._get_extracted_value(extraction_data, "claimant_dob")
            )
            patient_doi = self._parse_date(
                self._get_extracted_value(extraction_data, "date_of_injury")
            )

            # Get name components
            first_name = self._get_extracted_value(extraction_data, "claimant_first_name")
            last_name = self._get_extracted_value(extraction_data, "claimant_last_name")
            if not first_name and not last_name:
                full_name = self._get_extracted_value(extraction_data, "claimant_name")
                if full_name:
                    parts = full_name.split(None, 1)
                    first_name = parts[0] if parts else None
                    last_name = parts[1] if len(parts) > 1 else None

            # Get address components
            address_1 = self._get_extracted_value(extraction_data, "claimant_address_1")
            city = self._get_extracted_value(extraction_data, "claimant_city")
            state = self._get_extracted_value(extraction_data, "claimant_state")
            zip_code = self._get_extracted_value(extraction_data, "claimant_zip")

            # Parse full address if components missing
            if not city:
                full_address = self._get_extracted_value(extraction_data, "claimant_address")
                if full_address:
                    parsed = FieldTransformer.parse_address(full_address)
                    address_1 = address_1 or parsed.get("address_1")
                    city = parsed.get("city")
                    state = FieldTransformer.normalize_state(parsed.get("state", ""))
                    zip_code = FieldTransformer.normalize_zip(parsed.get("zip", ""))

            # Normalize fields
            if state:
                state = FieldTransformer.normalize_state(state)
            if zip_code:
                zip_code = FieldTransformer.normalize_zip(zip_code)

            phone = self._get_extracted_value(extraction_data, "claimant_phone")
            if phone:
                phone = FieldTransformer.normalize_phone(phone)

            # Create referral
            referral = Referral(
                email_id=email.id,
                # Adjuster info
                adjuster_name=self._get_extracted_value(extraction_data, "adjuster_name"),
                adjuster_email=message.from_email,
                adjuster_phone=self._get_extracted_value(extraction_data, "adjuster_phone"),
                # Carrier
                carrier_id=carrier_id,
                carrier_name_raw=carrier_name_raw,
                # Claim info
                claim_number=self._get_extracted_value(extraction_data, "claim_number"),
                jurisdiction_state=self._get_extracted_value(extraction_data, "jurisdiction_state"),
                order_type=self._get_extracted_value(extraction_data, "order_type"),
                authorization_number=self._get_extracted_value(extraction_data, "authorization_number"),
                # Patient demographics
                patient_first_name=first_name,
                patient_last_name=last_name,
                patient_dob=patient_dob,
                patient_doi=patient_doi,
                patient_gender=self._get_extracted_value(extraction_data, "claimant_gender"),
                patient_phone=phone,
                patient_email=self._get_extracted_value(extraction_data, "claimant_email"),
                patient_ssn=self._get_extracted_value(extraction_data, "claimant_ssn"),
                # Patient address
                patient_address_1=address_1,
                patient_address_2=self._get_extracted_value(extraction_data, "claimant_address_2"),
                patient_city=city,
                patient_state=state,
                patient_zip=zip_code,
                # Employer info
                employer_name=self._get_extracted_value(extraction_data, "employer_name"),
                employer_job_title=self._get_extracted_value(extraction_data, "claimant_job_title"),
                employer_address=self._get_extracted_value(extraction_data, "employer_address"),
                # Referring physician
                referring_physician_name=self._get_extracted_value(extraction_data, "referring_physician_name"),
                referring_physician_npi=self._get_extracted_value(extraction_data, "referring_physician_npi"),
                # Service info (summary - details in line items)
                service_summary=self._get_extracted_value(extraction_data, "service_requested"),
                body_parts=self._get_extracted_value(extraction_data, "body_parts"),
                # Preferences
                suggested_providers=self._get_extracted_value(extraction_data, "suggested_providers"),
                special_requirements=self._get_extracted_value(extraction_data, "special_requirements"),
                # Status & priority
                status=ReferralStatus.DRAFT,
                priority=priority,
                # Extraction metadata
                extraction_confidence=extraction_confidence,
                extraction_data=extraction_data,
                needs_human_review=extraction_confidence < 0.8,
                # Timestamps
                received_at=message.received_datetime,
            )

            # ================================================================
            # STEP 5: Parse service_requested into line items
            # ================================================================
            service_requested = self._get_extracted_value(extraction_data, "service_requested")
            icd10_code = self._get_extracted_value(extraction_data, "icd10_code")
            icd10_desc = self._get_extracted_value(extraction_data, "icd10_description")

            line_items = line_item_service.create_line_items_from_extraction(
                service_requested=service_requested or "",
                icd10_code=icd10_code,
                icd10_description=icd10_desc,
                confidence=extraction_confidence,
            )

            # If no line items parsed but we have service_requested, create one
            if not line_items and service_requested:
                line_items = [
                    ReferralLineItem(
                        service_description=service_requested,
                        icd10_code=icd10_code,
                        icd10_description=icd10_desc,
                        confidence=extraction_confidence,
                        source="extraction",
                    )
                ]

            # ================================================================
            # STEP 6: Complete extraction and queue for intake
            # ================================================================
            workflow_service.complete_extraction_and_queue_for_intake(
                email=email,
                referral=referral,
                line_items=line_items,
            )

            # ================================================================
            # STEP 7: Upload to S3
            # ================================================================
            self._upload_to_s3(email, referral, extraction_data)

            # ================================================================
            # STEP 8: Mark email as read
            # ================================================================
            if self.mark_as_read:
                try:
                    self.email_service.mark_as_read(
                        message.id,
                        mailbox=self.settings.shared_mailbox or self.settings.graph_mailbox,
                    )
                except Exception:
                    pass  # Non-critical

            console.print(f"    [green]Created referral #{referral.id} with {len(line_items)} line item(s)[/green]")
            return "created"

    def _save_attachments_to_email(
        self,
        email: Email,
        message_id: str,
        session,
    ) -> list[str]:
        """
        Download and save attachments to the Email record.
        Returns list of extracted text from documents.
        """
        storage = get_storage_service()
        s3_enabled = storage.is_configured()
        texts = []

        # Image extensions to skip for text extraction (likely logos)
        LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg"}
        LOGO_CONTENT_TYPES = {
            "image/png", "image/jpeg", "image/gif", "image/bmp",
            "image/x-icon", "image/webp", "image/svg+xml"
        }

        try:
            attachments = self.email_service.get_attachments(
                message_id,
                mailbox=self.settings.shared_mailbox or self.settings.graph_mailbox,
            )
            attachments_dir = self.settings.attachments_dir / str(email.id)
            attachments_dir.mkdir(parents=True, exist_ok=True)

            for att in attachments:
                if att.content_bytes:
                    filename_lower = att.name.lower()
                    extension = Path(filename_lower).suffix
                    is_logo = (
                        extension in LOGO_EXTENSIONS or
                        (att.content_type and att.content_type.lower() in LOGO_CONTENT_TYPES)
                    )

                    # Save locally
                    filepath = attachments_dir / att.name
                    filepath.write_bytes(att.content_bytes)

                    # Determine document type and extract text
                    extracted_text = None
                    doc_type = None

                    if is_logo:
                        doc_type = DocumentType.LOGO
                    elif att.content_type == "application/pdf" or filename_lower.endswith(".pdf"):
                        extracted_text = extract_text_from_pdf(str(filepath))
                        doc_type = DocumentType.REFERRAL_FORM
                        if extracted_text:
                            texts.append(extracted_text)
                    elif att.content_type and att.content_type.startswith("image/"):
                        extracted_text = extract_text_from_image(str(filepath))
                        doc_type = DocumentType.OTHER
                        if extracted_text:
                            texts.append(extracted_text)

                    # Upload to S3 if configured
                    s3_key = None
                    s3_text_key = None
                    if s3_enabled:
                        try:
                            s3_result = storage.upload_attachment(
                                referral_id=email.id,  # Using email.id for now
                                filename=att.name,
                                content=att.content_bytes,
                                content_type=att.content_type,
                                extracted_text=extracted_text,
                            )
                            s3_key = s3_result.get("s3_key")
                            s3_text_key = s3_result.get("text_s3_key")
                        except Exception as e:
                            console.print(f"    [yellow]S3 upload warning: {e}[/yellow]")

                    # Create Attachment record linked to Email
                    attachment = Attachment(
                        email_id=email.id,
                        filename=att.name,
                        content_type=att.content_type,
                        size_bytes=att.size,
                        graph_attachment_id=att.id,
                        storage_path=str(filepath),
                        s3_key=s3_key,
                        s3_text_key=s3_text_key,
                        document_type=doc_type,
                        extracted_text=extracted_text,
                        is_relevant=not is_logo,
                    )
                    session.add(attachment)

            if attachments:
                console.print(f"    [dim]Saved {len(attachments)} attachment(s)[/dim]")

        except Exception as e:
            console.print(f"    [yellow]Warning: Could not save attachments: {e}[/yellow]")

        return texts

    def _upload_to_s3(
        self,
        email: Email,
        referral: Referral,
        extraction_data: dict,
    ) -> None:
        """Upload email and extraction data to S3."""
        storage = get_storage_service()
        if not storage.is_configured():
            return

        try:
            # Build email metadata
            email_metadata = {
                "id": email.graph_id,
                "subject": email.subject,
                "from_email": email.from_email,
                "from_name": email.from_name,
                "received_datetime": email.received_at.isoformat() if email.received_at else None,
                "web_link": email.web_link,
                "internet_message_id": email.internet_message_id,
                "conversation_id": email.conversation_id,
                "has_attachments": email.has_attachments,
            }

            # Upload email content
            result = storage.upload_email(
                referral.id,
                email_html=email.body_html,
                email_metadata=email_metadata,
            )

            # Update Email with S3 keys
            email.s3_html_key = result.get("email_html_key")

            # Upload extraction data
            if extraction_data:
                extraction_key = storage.upload_extraction(
                    referral.id,
                    extraction_data,
                )
                email.s3_extraction_key = extraction_key

            console.print(f"    [dim]Uploaded to S3[/dim]")

        except Exception as e:
            console.print(f"    [yellow]S3 upload warning: {e}[/yellow]")

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
