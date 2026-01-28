"""
Step 2 Reasoning Service for extraction enrichment.

This service takes Step 1 extraction results and enriches them with:
- Validated ICD-10 codes from reference data
- Derived procedure codes based on service requested
- Additional metadata (category, body region)

The reasoning is entirely programmatic (no additional LLM calls).
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from referral_crm.services.extraction_service import ExtractedField, ExtractionResult
from referral_crm.services.reference_data import (
    ReferenceDataService,
    ValidationResult,
    ProcedureLookupResult,
)

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentMetadata:
    """Metadata about the enrichment process."""
    icd10_validated: bool = False
    icd10_validation_message: Optional[str] = None
    procedure_codes_found: int = 0
    procedure_lookup_message: Optional[str] = None
    enrichment_warnings: List[str] = None

    def __post_init__(self):
        if self.enrichment_warnings is None:
            self.enrichment_warnings = []


class ReasoningService:
    """
    Step 2 reasoning service for extraction enrichment.

    Takes raw extraction results from Step 1 and:
    1. Validates extracted ICD-10 codes against reference database
    2. Derives procedure codes from service_requested
    3. Adds category/body region metadata from reference data
    """

    def __init__(self, session: Session):
        self.session = session
        self.reference = ReferenceDataService(session)

    def enrich(self, extraction: ExtractionResult) -> tuple[ExtractionResult, EnrichmentMetadata]:
        """
        Enrich an extraction result with Step 2 reasoning.

        Args:
            extraction: ExtractionResult from Step 1

        Returns:
            Tuple of (enriched ExtractionResult, EnrichmentMetadata)
        """
        metadata = EnrichmentMetadata()

        # Validate and enrich ICD-10 code
        self._enrich_icd10(extraction, metadata)

        # Derive procedure codes from service_requested
        self._derive_procedure_codes(extraction, metadata)

        return extraction, metadata

    def _enrich_icd10(
        self,
        extraction: ExtractionResult,
        metadata: EnrichmentMetadata
    ) -> None:
        """
        Validate ICD-10 code and add enrichment fields.

        Sets:
        - validated_icd10: The validated/normalized ICD-10 code
        - icd10_category: Category from reference data
        - icd10_body_region: Body region from reference data
        """
        icd10_field = extraction.icd10_code
        if not icd10_field or not icd10_field.value:
            metadata.icd10_validated = False
            metadata.icd10_validation_message = "No ICD-10 code extracted"
            return

        code = icd10_field.value
        validation = self.reference.validate_icd10(code)

        if validation.is_valid:
            metadata.icd10_validated = True
            metadata.icd10_validation_message = validation.message

            # Set validated_icd10
            extraction.validated_icd10 = ExtractedField(
                value=validation.normalized_code,
                confidence=min(icd10_field.confidence + 5, 100),  # Boost confidence for validated
                source="reference_validation",
                raw_match=f"Validated against ICD-10 database: {validation.description}"
            )

            # Set icd10_category if available
            if validation.category:
                extraction.icd10_category = ExtractedField(
                    value=validation.category,
                    confidence=95,  # High confidence from reference data
                    source="reference_data",
                    raw_match=f"Category from ICD-10 reference: {validation.category}"
                )

            # Set icd10_body_region if available
            if validation.body_region:
                extraction.icd10_body_region = ExtractedField(
                    value=validation.body_region,
                    confidence=95,  # High confidence from reference data
                    source="reference_data",
                    raw_match=f"Body region from ICD-10 reference: {validation.body_region}"
                )

            logger.info(f"ICD-10 validated: {code} -> {validation.normalized_code} ({validation.description})")

        else:
            metadata.icd10_validated = False
            metadata.icd10_validation_message = validation.message
            metadata.enrichment_warnings.append(
                f"ICD-10 validation failed: {validation.message}"
            )
            logger.warning(f"ICD-10 validation failed for {code}: {validation.message}")

    def _derive_procedure_codes(
        self,
        extraction: ExtractionResult,
        metadata: EnrichmentMetadata
    ) -> None:
        """
        Derive procedure codes from the service_requested field.

        Sets:
        - associated_procedure_code: CPT/procedure code from reference data
        """
        service_field = extraction.service_requested
        if not service_field or not service_field.value:
            metadata.procedure_codes_found = 0
            metadata.procedure_lookup_message = "No service requested extracted"
            return

        service = service_field.value
        lookup_result = self.reference.lookup_procedures_for_service(service)

        if lookup_result.found and lookup_result.codes:
            metadata.procedure_codes_found = len(lookup_result.codes)
            metadata.procedure_lookup_message = lookup_result.message

            # Use the first (most relevant) procedure code
            primary_code = lookup_result.codes[0]

            extraction.associated_procedure_code = ExtractedField(
                value=primary_code.code,
                confidence=85,  # Good confidence from reference lookup
                source="reference_lookup",
                raw_match=f"Derived from service '{service}': {primary_code.code} - {primary_code.description}"
            )

            # If multiple codes found, add info to notes
            if len(lookup_result.codes) > 1:
                other_codes = [c.code for c in lookup_result.codes[1:4]]  # Up to 3 more
                metadata.enrichment_warnings.append(
                    f"Multiple procedure codes available for '{lookup_result.service_type}': {', '.join(other_codes)}"
                )

            logger.info(
                f"Procedure code derived: {service} -> {primary_code.code} ({primary_code.description})"
            )

        else:
            metadata.procedure_codes_found = 0
            metadata.procedure_lookup_message = lookup_result.message
            logger.info(f"No procedure codes found for service: {service}")


class TwoStepExtractionPipeline:
    """
    Complete two-step extraction pipeline.

    Step 1: LLM-based extraction (ExtractionService)
    Step 2: Reference-based reasoning (ReasoningService)
    """

    def __init__(self, session: Session):
        from referral_crm.services.extraction_service import ExtractionService
        self.extraction_service = ExtractionService()
        self.reasoning_service = ReasoningService(session)

    def extract_and_enrich(
        self,
        from_email: str,
        subject: str,
        body: str,
        attachment_texts: Optional[list[str]] = None,
    ) -> tuple[ExtractionResult, EnrichmentMetadata]:
        """
        Run the complete two-step extraction pipeline.

        Args:
            from_email: The sender's email address
            subject: Email subject line
            body: Plain text or HTML body of the email
            attachment_texts: List of extracted text from attachments

        Returns:
            Tuple of (enriched ExtractionResult, EnrichmentMetadata)
        """
        # Step 1: LLM-based extraction
        logger.info("Step 1: Running LLM extraction...")
        extraction = self.extraction_service.extract_from_email(
            from_email=from_email,
            subject=subject,
            body=body,
            attachment_texts=attachment_texts,
        )

        # Step 2: Reference-based reasoning/enrichment
        logger.info("Step 2: Running reasoning enrichment...")
        enriched, metadata = self.reasoning_service.enrich(extraction)

        logger.info(
            f"Pipeline complete. ICD-10 validated: {metadata.icd10_validated}, "
            f"Procedure codes found: {metadata.procedure_codes_found}"
        )

        return enriched, metadata


def get_reasoning_service(session: Session) -> ReasoningService:
    """Factory function to create a ReasoningService."""
    return ReasoningService(session)


def get_extraction_pipeline(session: Session) -> TwoStepExtractionPipeline:
    """Factory function to create a TwoStepExtractionPipeline."""
    return TwoStepExtractionPipeline(session)
