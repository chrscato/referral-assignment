"""
LLM-based extraction service for parsing referral emails.
Uses Claude API to extract structured data from unstructured text.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from referral_crm.config import get_settings

# Lazy import to avoid startup issues if anthropic not installed
anthropic = None


def get_anthropic_client():
    """Lazily initialize the Anthropic client."""
    global anthropic
    if anthropic is None:
        import anthropic as _anthropic

        anthropic = _anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class ExtractedField:
    """A field extracted from the email with confidence score."""

    value: Any
    confidence: int  # 0-100
    source: str  # "email_body", "attachment", "signature"
    raw_match: Optional[str] = None


@dataclass
class ExtractionResult:
    """Complete extraction result from an email."""

    adjuster_name: Optional[ExtractedField] = None
    adjuster_email: Optional[ExtractedField] = None
    adjuster_phone: Optional[ExtractedField] = None
    insurance_carrier: Optional[ExtractedField] = None
    claim_number: Optional[ExtractedField] = None
    claimant_name: Optional[ExtractedField] = None
    claimant_dob: Optional[ExtractedField] = None
    claimant_phone: Optional[ExtractedField] = None
    claimant_address: Optional[ExtractedField] = None
    employer_name: Optional[ExtractedField] = None
    date_of_injury: Optional[ExtractedField] = None
    body_parts: Optional[ExtractedField] = None
    service_requested: Optional[ExtractedField] = None
    authorization_number: Optional[ExtractedField] = None
    priority: Optional[ExtractedField] = None
    notes: Optional[ExtractedField] = None

    def to_dict(self) -> dict:
        """Convert to dictionary format for storage."""
        result = {}
        for field in [
            "adjuster_name",
            "adjuster_email",
            "adjuster_phone",
            "insurance_carrier",
            "claim_number",
            "claimant_name",
            "claimant_dob",
            "claimant_phone",
            "claimant_address",
            "employer_name",
            "date_of_injury",
            "body_parts",
            "service_requested",
            "authorization_number",
            "priority",
            "notes",
        ]:
            extracted = getattr(self, field)
            if extracted:
                result[field] = {
                    "value": extracted.value,
                    "confidence": extracted.confidence,
                    "source": extracted.source,
                    "raw_match": extracted.raw_match,
                }
        return result

    def get_value(self, field: str) -> Any:
        """Get the value of a field if it exists."""
        extracted = getattr(self, field, None)
        return extracted.value if extracted else None

    def get_confidence(self, field: str) -> int:
        """Get the confidence score for a field."""
        extracted = getattr(self, field, None)
        return extracted.confidence if extracted else 0


EXTRACTION_PROMPT = """You are a workers' compensation intake specialist. Extract structured data from the following referral email and any attachment contents.

**Source Email:**
From: {from_email}
Subject: {subject}

Body:
{email_body}

{attachment_section}

**Extract the following fields. If not found, return null. Include a confidence score (0-100) for each field based on clarity and certainty.**

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "adjuster_name": {{ "value": "", "confidence": 0, "source": "email_body|attachment|signature", "raw_match": "the text that matched" }},
  "adjuster_phone": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "insurance_carrier": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "claim_number": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "claimant_name": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "claimant_dob": {{ "value": "YYYY-MM-DD or null", "confidence": 0, "source": "", "raw_match": "" }},
  "claimant_phone": {{ "value": "(XXX) XXX-XXXX", "confidence": 0, "source": "", "raw_match": "" }},
  "claimant_address": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "employer_name": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "date_of_injury": {{ "value": "YYYY-MM-DD or null", "confidence": 0, "source": "", "raw_match": "" }},
  "body_parts": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "service_requested": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "authorization_number": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }},
  "priority": {{ "value": "low|medium|high|urgent", "confidence": 0, "source": "", "raw_match": "" }},
  "notes": {{ "value": "", "confidence": 0, "source": "", "raw_match": "" }}
}}

**Extraction Rules:**
- Claim numbers often follow patterns like: XX-XXXXX, XXXX-XXXXXX, WC-YYYY-XXXXX
- Phone numbers: normalize to (XXX) XXX-XXXX format
- Dates: normalize to YYYY-MM-DD format
- Body parts: use standard medical terminology (e.g., "left shoulder" not "L shoulder")
- If multiple values found, choose the most authoritative/recent
- Adjuster info is often in email signature
- Priority: infer from urgency language (ASAP, urgent, rush = high/urgent)
- Carrier may be in email domain or signature block
"""


class ExtractionService:
    """Service for extracting structured data from referral emails."""

    def __init__(self):
        self.settings = get_settings()

    def extract_from_email(
        self,
        from_email: str,
        subject: str,
        body: str,
        attachment_texts: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """
        Extract structured data from an email using Claude.

        Args:
            from_email: The sender's email address
            subject: Email subject line
            body: Plain text or HTML body of the email
            attachment_texts: List of extracted text from attachments

        Returns:
            ExtractionResult with all extracted fields and confidence scores
        """
        # Clean HTML from body if present
        clean_body = self._strip_html(body)

        # Build attachment section
        attachment_section = ""
        if attachment_texts:
            attachment_section = "**Attachment Contents:**\n"
            for i, text in enumerate(attachment_texts, 1):
                attachment_section += f"\n--- Attachment {i} ---\n{text[:5000]}\n"

        # Build the prompt
        prompt = EXTRACTION_PROMPT.format(
            from_email=from_email,
            subject=subject,
            email_body=clean_body[:10000],  # Limit body length
            attachment_section=attachment_section,
        )

        # Call Claude
        try:
            client = get_anthropic_client()
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse the response
            response_text = response.content[0].text
            return self._parse_extraction_response(response_text)

        except Exception as e:
            # Return empty result on error, log it
            print(f"Extraction error: {e}")
            return ExtractionResult()

    def extract_from_email_sync(
        self,
        from_email: str,
        subject: str,
        body: str,
        attachment_texts: Optional[list[str]] = None,
    ) -> ExtractionResult:
        """Synchronous version of extract_from_email."""
        return self.extract_from_email(from_email, subject, body, attachment_texts)

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        if not text:
            return ""
        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", " ", text)
        # Remove extra whitespace
        clean = re.sub(r"\s+", " ", clean)
        # Decode common HTML entities
        clean = (
            clean.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        return clean.strip()

    def _parse_extraction_response(self, response_text: str) -> ExtractionResult:
        """Parse the JSON response from Claude into an ExtractionResult."""
        try:
            # Try to extract JSON from the response
            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if not json_match:
                return ExtractionResult()

            data = json.loads(json_match.group())
            result = ExtractionResult()

            for field in [
                "adjuster_name",
                "adjuster_phone",
                "insurance_carrier",
                "claim_number",
                "claimant_name",
                "claimant_dob",
                "claimant_phone",
                "claimant_address",
                "employer_name",
                "date_of_injury",
                "body_parts",
                "service_requested",
                "authorization_number",
                "priority",
                "notes",
            ]:
                if field in data and data[field] and data[field].get("value"):
                    field_data = data[field]
                    extracted = ExtractedField(
                        value=field_data.get("value"),
                        confidence=field_data.get("confidence", 50),
                        source=field_data.get("source", "email_body"),
                        raw_match=field_data.get("raw_match"),
                    )
                    setattr(result, field, extracted)

            return result

        except json.JSONDecodeError:
            return ExtractionResult()

    def normalize_phone(self, phone: str) -> str:
        """Normalize a phone number to (XXX) XXX-XXXX format."""
        if not phone:
            return ""
        # Extract digits
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return phone

    def normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize a date string to YYYY-MM-DD format."""
        if not date_str:
            return None

        # Common date formats to try
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%m-%d-%Y",
            "%m-%d-%y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file using pypdf."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""


def extract_text_from_image(image_path: str) -> str:
    """Extract text from an image using Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        print(f"OCR extraction error: {e}")
        return ""
