#!/usr/bin/env python
"""
Test script for LLM extraction and FileMaker conversion.
Run with: uv run python test_extraction.py
"""

import json
from datetime import datetime

# Sample email content for testing
SAMPLE_EMAIL = """
From: jane.adjuster@aceinsurance.com
Subject: New PT Referral - John Q Smith - WC-2025-001234

Good morning,

Please schedule a PT Evaluation for the following claimant:

Patient Information:
- Name: John Q Smith
- Date of Birth: 03/15/1985
- Phone: 555-123-4567
- Email: john.smith@email.com
- Address: 123 Main Street, Springfield, IL 62701

Claim Information:
- Claim Number: WC-2025-001234
- Date of Injury: 01/10/2025
- Employer: Acme Manufacturing Inc.
- Body Part: Right shoulder and upper back

Service Requested: PT Evaluation - 1 visit

Please schedule at your earliest convenience. This is a priority referral.

Thank you,

Jane Adjuster
Claims Specialist
ACE Insurance Company
Phone: (555) 987-6543
Email: jane.adjuster@aceinsurance.com
"""

SAMPLE_PDF_TEXT = """
WORKERS' COMPENSATION REFERRAL FORM

Claim Number: WC-2025-001234
Insurance Carrier: ACE Insurance Company
Adjuster: Jane Adjuster

CLAIMANT INFORMATION
Name: John Q Smith
DOB: 03/15/1985
SSN: XXX-XX-1234
Address: 123 Main Street
City: Springfield
State: IL
ZIP: 62701
Phone: (555) 123-4567

EMPLOYER INFORMATION
Employer Name: Acme Manufacturing Inc.
Address: 456 Industrial Blvd, Springfield, IL 62702

INJURY INFORMATION
Date of Injury: 01/10/2025
Body Parts Injured: Right shoulder, upper back
Description: Employee injured shoulder while lifting heavy equipment

SERVICE REQUESTED
Type: Physical Therapy Evaluation
Authorization #: AUTH-2025-5678
"""


def test_extraction_service():
    """Test the extraction service with sample data."""
    print("\n" + "=" * 70)
    print("TEST 1: ExtractionService with Sample Email")
    print("=" * 70 + "\n")

    try:
        from referral_crm.services.extraction_service import ExtractionService

        service = ExtractionService()

        print("Extracting data from sample email...")
        print("-" * 70)

        result = service.extract_from_email(
            from_email="jane.adjuster@aceinsurance.com",
            subject="New PT Referral - John Q Smith - WC-2025-001234",
            body=SAMPLE_EMAIL,
            attachment_texts=[SAMPLE_PDF_TEXT],
        )

        extraction_dict = result.to_dict()

        print("\nExtracted Fields:")
        print("-" * 70)
        for field, data in extraction_dict.items():
            value = data.get("value", "N/A")
            confidence = data.get("confidence", 0)
            conf_color = "green" if confidence >= 80 else "yellow" if confidence >= 60 else "red"
            print(f"  {field:25} = {str(value):30} (confidence: {confidence}%)")

        print(f"\nOverall Confidence: {result.get_overall_confidence():.1f}%")
        return extraction_dict

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_filemaker_conversion(extraction_dict):
    """Test FileMaker conversion with extraction data."""
    print("\n" + "=" * 70)
    print("TEST 2: FileMaker Conversion")
    print("=" * 70 + "\n")

    if not extraction_dict:
        print("Skipping - no extraction data available")
        return None

    try:
        from referral_crm.services.filemaker_conversion import (
            ExtractionToFileMakerConverter,
            FileMakerPayloadValidator,
            FieldTransformer,
        )

        converter = ExtractionToFileMakerConverter()
        fm_extraction = converter.convert(extraction_dict)

        print("Converted to FileMaker Fields:")
        print("-" * 70)
        print(f"  Intake Client First Name:  {fm_extraction.intake_client_first_name}")
        print(f"  Intake Client Last Name:   {fm_extraction.intake_client_last_name}")
        print(f"  Intake Claim Number:       {fm_extraction.intake_claim_number}")
        print(f"  Intake Client Company:     {fm_extraction.intake_client_company}")
        print(f"  Intake DOB:                {fm_extraction.intake_dob}")
        print(f"  Intake DOI:                {fm_extraction.intake_doi}")
        print(f"  Intake Client Phone:       {fm_extraction.intake_client_phone}")
        print(f"  Intake Client Email:       {fm_extraction.intake_client_email}")
        print(f"  Intake Instructions:       {fm_extraction.intake_instructions}")
        print(f"  Injury Description:        {fm_extraction.injury_description}")

        print("\nPatient Address:")
        print(f"  Address 1:                 {fm_extraction.patient_address_1}")
        print(f"  City:                      {fm_extraction.patient_address_city}")
        print(f"  State:                     {fm_extraction.patient_address_state}")
        print(f"  ZIP:                       {fm_extraction.patient_address_zip}")

        print("\nEmployer:")
        print(f"  Patient Employer:          {fm_extraction.patient_employer}")

        print("\nMetadata:")
        print(f"  Adjuster Name:             {fm_extraction.adjuster_name}")
        print(f"  Adjuster Email:            {fm_extraction.adjuster_email}")
        print(f"  Extraction Confidence:     {fm_extraction.extraction_confidence:.1f}%")
        print(f"  Status:                    {fm_extraction.status}")

        # Validate
        print("\n" + "-" * 70)
        print("Validation Results:")
        validator = FileMakerPayloadValidator()
        errors = validator.validate(fm_extraction)

        if errors:
            print("  ERRORS:")
            for error in errors:
                print(f"    - {error}")
        else:
            print("  All validations passed!")

        missing = validator.get_missing_critical_fields(fm_extraction)
        if missing:
            print(f"\n  Missing Critical Fields: {', '.join(missing)}")

        completeness = validator.get_completeness_score(fm_extraction)
        print(f"\n  Completeness Score: {completeness:.1f}%")

        return fm_extraction

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_field_transformer():
    """Test individual field transformations."""
    print("\n" + "=" * 70)
    print("TEST 3: Field Transformer")
    print("=" * 70 + "\n")

    try:
        from referral_crm.services.filemaker_conversion import FieldTransformer

        print("Phone Normalization:")
        phones = ["555-123-4567", "5551234567", "(555) 123-4567", "1-555-123-4567"]
        for phone in phones:
            normalized = FieldTransformer.normalize_phone(phone)
            print(f"  {phone:20} -> {normalized}")

        print("\nState Normalization:")
        states = ["California", "california", "CA", "IL", "new york", "NY"]
        for state in states:
            normalized = FieldTransformer.normalize_state(state)
            print(f"  {state:20} -> {normalized}")

        print("\nDate Normalization:")
        dates = ["1/15/2025", "01-15-2025", "January 15, 2025", "2025-01-15"]
        for date in dates:
            normalized = FieldTransformer.normalize_date(date)
            print(f"  {date:20} -> {normalized}")

        print("\nZIP Normalization:")
        zips = ["62701", "62701-1234", "IL 62701", "627011234"]
        for zip_code in zips:
            normalized = FieldTransformer.normalize_zip(zip_code)
            print(f"  {zip_code:20} -> {normalized}")

        print("\nName Splitting:")
        names = ["John Smith", "John Q Smith", "John Smith Jr", "John"]
        for name in names:
            first, last = FieldTransformer.split_full_name(name)
            print(f"  {name:20} -> First: '{first}', Last: '{last}'")

        print("\nAddress Parsing:")
        addresses = [
            "123 Main St, Springfield, IL 62701",
            "456 Oak Ave, Chicago, IL",
            "789 Pine Rd",
        ]
        for addr in addresses:
            parsed = FieldTransformer.parse_address(addr)
            print(f"  {addr}")
            print(f"    -> {parsed}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


def test_without_llm():
    """Test conversion without making LLM API calls."""
    print("\n" + "=" * 70)
    print("TEST 4: FileMaker Conversion (Mock Data - No LLM)")
    print("=" * 70 + "\n")

    try:
        from referral_crm.services.filemaker_conversion import (
            ExtractionToFileMakerConverter,
            FileMakerPayloadValidator,
        )

        # Mock extraction data (simulates LLM output)
        mock_extraction = {
            "claimant_first_name": {"value": "John", "confidence": 95, "source": "email_body"},
            "claimant_last_name": {"value": "Smith", "confidence": 95, "source": "email_body"},
            "claim_number": {"value": "WC-2025-001234", "confidence": 98, "source": "email_body"},
            "insurance_carrier": {"value": "ACE Insurance", "confidence": 90, "source": "signature"},
            "service_requested": {"value": "PT Evaluation", "confidence": 85, "source": "email_body"},
            "claimant_dob": {"value": "1985-03-15", "confidence": 80, "source": "email_body"},
            "date_of_injury": {"value": "2025-01-10", "confidence": 88, "source": "email_body"},
            "body_parts": {"value": "right shoulder, upper back", "confidence": 85, "source": "email_body"},
            "claimant_phone": {"value": "555-123-4567", "confidence": 75, "source": "email_body"},
            "claimant_email": {"value": "john.smith@email.com", "confidence": 80, "source": "email_body"},
            "claimant_address_1": {"value": "123 Main Street", "confidence": 70, "source": "email_body"},
            "claimant_city": {"value": "Springfield", "confidence": 75, "source": "email_body"},
            "claimant_state": {"value": "IL", "confidence": 80, "source": "email_body"},
            "claimant_zip": {"value": "62701", "confidence": 78, "source": "email_body"},
            "employer_name": {"value": "Acme Manufacturing Inc.", "confidence": 70, "source": "email_body"},
            "adjuster_name": {"value": "Jane Adjuster", "confidence": 95, "source": "signature"},
            "adjuster_email": {"value": "jane.adjuster@aceinsurance.com", "confidence": 100, "source": "from_field"},
        }

        converter = ExtractionToFileMakerConverter()
        fm_extraction = converter.convert(mock_extraction)

        print("Converted FileMaker Fields:")
        print("-" * 70)
        print(f"  First Name:     {fm_extraction.intake_client_first_name}")
        print(f"  Last Name:      {fm_extraction.intake_client_last_name}")
        print(f"  Claim Number:   {fm_extraction.intake_claim_number}")
        print(f"  Carrier:        {fm_extraction.intake_client_company}")
        print(f"  DOB:            {fm_extraction.intake_dob}")
        print(f"  DOI:            {fm_extraction.intake_doi}")
        print(f"  Phone:          {fm_extraction.intake_client_phone}")
        print(f"  Service:        {fm_extraction.intake_instructions}")
        print(f"  Body Parts:     {fm_extraction.injury_description}")
        print(f"  City:           {fm_extraction.patient_address_city}")
        print(f"  State:          {fm_extraction.patient_address_state}")
        print(f"  ZIP:            {fm_extraction.patient_address_zip}")
        print(f"  Confidence:     {fm_extraction.extraction_confidence:.1f}%")

        # Generate FileMaker payload
        print("\n" + "-" * 70)
        print("FileMaker API Payload:")
        payload = fm_extraction.to_filemaker_payload()
        print(json.dumps(payload, indent=2))

        # Validate
        validator = FileMakerPayloadValidator()
        errors = validator.validate(fm_extraction)
        print("\n" + "-" * 70)
        print(f"Validation: {'PASSED' if not errors else 'FAILED'}")
        if errors:
            for error in errors:
                print(f"  - {error}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("LLM EXTRACTION & FILEMAKER CONVERSION TEST SUITE")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Test 1: Field Transformer (no API calls)
    test_field_transformer()

    # Test 2: FileMaker conversion with mock data (no API calls)
    test_without_llm()

    # Test 3 & 4: Full extraction with LLM (requires API key)
    print("\n" + "=" * 70)
    print("OPTIONAL: Full LLM Extraction Test")
    print("=" * 70)
    print("\nThis test requires ANTHROPIC_API_KEY to be set.")
    user_input = input("Run LLM extraction test? (y/n): ").strip().lower()

    if user_input == 'y':
        extraction_dict = test_extraction_service()
        if extraction_dict:
            test_filemaker_conversion(extraction_dict)
    else:
        print("Skipped LLM extraction test.")

    print("\n" + "=" * 70)
    print("TEST SUITE COMPLETE")
    print("=" * 70 + "\n")
