"""
Service layer for Referral CRM.
"""

from referral_crm.services.referral_service import ReferralService, CarrierService
from referral_crm.services.extraction_service import ExtractionService, ExtractionResult, ExtractedField
from referral_crm.services.email_service import EmailService
from referral_crm.services.provider_service import ProviderService
from referral_crm.services.storage_service import StorageService, get_storage_service
from referral_crm.services.reference_data import ReferenceDataService, get_reference_data_service
from referral_crm.services.reasoning_service import (
    ReasoningService,
    TwoStepExtractionPipeline,
    get_reasoning_service,
    get_extraction_pipeline,
)
from referral_crm.services.filemaker_conversion import (
    FileMakerExtraction,
    ExtractionToFileMakerConverter,
    FileMakerPayloadValidator,
    FieldTransformer,
)
from referral_crm.services.workflow_service import (
    WorkflowService,
    get_workflow_service,
    seed_queues,
)
from referral_crm.services.line_item_service import (
    LineItemService,
    ServiceLineItemParser,
    get_line_item_service,
    seed_service_types,
)

__all__ = [
    # Core services
    "ReferralService",
    "CarrierService",
    "ExtractionService",
    "EmailService",
    "ProviderService",
    "StorageService",
    "get_storage_service",
    # Extraction types
    "ExtractionResult",
    "ExtractedField",
    # Reference data
    "ReferenceDataService",
    "get_reference_data_service",
    # Reasoning/enrichment
    "ReasoningService",
    "TwoStepExtractionPipeline",
    "get_reasoning_service",
    "get_extraction_pipeline",
    # FileMaker conversion
    "FileMakerExtraction",
    "ExtractionToFileMakerConverter",
    "FileMakerPayloadValidator",
    "FieldTransformer",
    # Workflow management
    "WorkflowService",
    "get_workflow_service",
    "seed_queues",
    # Line item management
    "LineItemService",
    "ServiceLineItemParser",
    "get_line_item_service",
    "seed_service_types",
]
