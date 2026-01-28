"""
FILEMAKER INTAKE EXTRACTION PROMPT
===================================

LLM prompt template optimized for extracting referral data into FileMaker intake form fields.
Copy this into your extraction_service.py to replace the generic extraction prompt.
"""

FILEMAKER_EXTRACTION_PROMPT = """You are a workers' compensation intake specialist. Your job is to extract structured data from a referral email for FileMaker intake form submission.

DOCUMENT TO EXTRACT FROM:
{document_text}

IMPORTANT: Return ONLY valid JSON with no additional text, markdown, or explanations.

EXTRACT EXACTLY THESE FIELDS FOR FILEMAKER:

CRITICAL FIELDS (Must extract):
==================
1. claimant_first_name: First name of patient/claimant
   - If only full name given: "John Smith" → first_name: "John"
   - Must be present

2. claimant_last_name: Last name of patient/claimant
   - If only full name given: "John Smith" → last_name: "Smith"
   - Must be present

3. claim_number: Workers' compensation claim number
   - Look for patterns: WC-2025-001234, 2025-001234, WC2025001234
   - Often in email header, early in document, or in bold
   - Must be present

4. carrier: Insurance company/carrier name (Intake Client Company in FileMaker)
   - Examples: "ACE Insurance", "Travelers", "Liberty Mutual"
   - Often in adjuster's email domain or signature
   - Must be present

5. service_requested: Type of service requested (Intake Instructions in FileMaker)
   - PT Evaluation, PT Treatment, IME, MRI, CT Scan, X-Ray, Ultrasound, NMR
   - May also include frequency or special instructions
   - Must be present


HIGH PRIORITY FIELDS (Strongly try to extract):
================================================
6. claimant_dob: Date of birth (format as YYYY-MM-DD)
   - May appear as: 1/15/1985, 01-15-1985, January 15, 1985, 15 Jan 1985
   - Convert to YYYY-MM-DD format

7. date_of_injury: Date injury occurred (format as YYYY-MM-DD)
   - Look for "DOI", "date of injury", "injury date", "date injured"
   - May be in claim description
   - Convert to YYYY-MM-DD format

8. body_parts: Injured body parts (Injury Description in FileMaker)
   - Use medical terminology: "left shoulder", "lower back", "right knee"
   - NOT abbreviations: use "shoulder" not "L shoulder"
   - If multiple parts: "left shoulder and right wrist"
   - Must be specific

9. claimant_phone: Phone number (Intake Client Phone in FileMaker)
   - Normalize to format: (XXX) XXX-XXXX
   - May be adjuster's phone or claimant's phone - context matters
   - Look for claimant phone specifically


MEDIUM PRIORITY FIELDS (Try to extract):
=========================================
10. claimant_email: Email address (Intake Client Email in FileMaker)
    - Should be valid email format with @ and domain
    - If multiple emails, use claimant email not adjuster email

11. claimant_address_1: Street address (Patient Address 1 in FileMaker)
    - First line of address
    - Example: "123 Main Street" or "123 Main St, Apt 4B"

12. claimant_address_2: Address line 2 (Patient Address 2 in FileMaker)
    - Apartment, suite, etc if applicable
    - Leave blank if not applicable

13. claimant_city: City (Patient Address City in FileMaker)
    - Just the city name
    - Example: "Springfield"

14. claimant_state: State (Patient Address State in FileMaker)
    - Use 2-letter code: CA, IL, NY, TX, etc
    - NOT full name: use "IL" not "Illinois"
    - Examples: CA, CO, CT, DE, FL, GA, HI, ID, IL, IN, IA, KS, KY, LA, ME, MD, MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ, NM, NY, NC, ND, OH, OK, OR, PA, RI, SC, SD, TN, TX, UT, VT, VA, WA, WV, WI, WY

15. claimant_zip: ZIP code (Patient Address ZIP in FileMaker)
    - 5 or 9 digits only
    - Example: "62701" or "62701-1234"
    - Numbers only, no formatting


LOW PRIORITY FIELDS (Nice to have):
===================================
16. employer_name: Employer company name (Patient Employer in FileMaker)
    - Only if explicitly mentioned

17. employer_address: Full employer address
    - Parse into: address_1, city, state, zip components

18. authorization_number: Authorization number if provided
    - Look for "auth", "authorization", "auth #", "auth number"


ADDITIONAL METADATA:
====================
19. adjuster_name: Name of the person sending the referral
    - From email signature or sender info
    - For audit trail only

20. adjuster_email: Email of the person sending referral
    - From email "From" field
    - For audit trail only


CONFIDENCE SCORING:
===================
For EVERY field you extract, provide a confidence score (0-100):

95-100%: Field is explicitly and clearly stated
- Example: "Patient: John Smith", "Claim #: WC-2025-001234"
- Direct statement with no ambiguity

85-94%: Field is clearly stated or obvious from context
- Example: Service type mentioned in email
- One reasonable interpretation

70-84%: Field is fairly clear but some ambiguity
- Example: Address inferred from context
- Could be interpreted a couple ways

50-69%: Field has significant uncertainty
- Example: DOB partially visible or format unclear
- Multiple possible interpretations

<50%: Field is guessed or inferred with low certainty
- Not explicitly stated, heavily inferred
- DO NOT include if <50% confidence (return null instead)


EXTRACTION RULES:
=================

NAMES:
- Always split into first and last name
- "John Q Smith" → first: "John Q", last: "Smith"  (or first: "John", last: "Q Smith")
- "John Smith Jr" → first: "John", last: "Smith Jr"
- "Dr. John Smith" → first: "John", last: "Smith" (remove titles)

DATES:
- Always convert to YYYY-MM-DD format
- "1/15/2025" → "2025-01-15"
- "January 15, 2025" → "2025-01-15"
- "01-15-2025" → "2025-01-15"

PHONE:
- Always normalize to (XXX) XXX-XXXX format
- "555-123-4567" → "(555) 123-4567"
- "555.123.4567" → "(555) 123-4567"
- "5551234567" → "(555) 123-4567"
- If has country code: "(1) (555) 123-4567" → "(555) 123-4567"

STATE:
- Always use 2-letter codes
- "California" → "CA"
- "IL" → "IL" (already correct)
- "new york" → "NY"

ZIP:
- Numbers only, 5 or 9 digits
- "62701" → "62701"
- "62701-1234" → "62701-1234" (both formats acceptable)
- "IL 62701" → "62701" (extract just ZIP)

BODY PARTS:
- Use proper anatomical terminology
- "L shoulder" → "left shoulder"
- "low back pain" → "lower back"
- "ankle sprain" → "ankle"
- "multiple: shoulder, knee, ankle" → "left shoulder, left knee, left ankle" (be specific about sides)

SERVICE TYPES:
- Physical Therapy: "PT Evaluation", "PT Treatment", "Physical Therapy"
- Imaging: "MRI", "CT Scan", "X-Ray", "Ultrasound"
- Medical: "IME", "Independent Medical Exam", "Medical evaluation"
- Other: "Occupational Therapy", "Speech Therapy", "Chiropractic"

CLAIM NUMBERS:
- Common patterns:
  * WC-YYYY-XXXXXX (most common)
  * YYYY-XXXXXX
  * XXXXXX (6-8 digits)
  * Carrier-specific formats
- Look in: headers, subject lines, email body, early in document
- Often bolded or highlighted

IF FIELD NOT FOUND:
- Return null for the value
- Set confidence to 0
- Provide reasoning why you couldn't find it
- Consider adding to warnings array


RESPONSE FORMAT (MUST BE VALID JSON):
=====================================

{{
  "extraction": {{
    "claimant_first_name": {{
      "value": "John",
      "confidence": 95,
      "source": "Email body paragraph 1",
      "reasoning": "Patient name 'John Smith' clearly stated in referral"
    }},
    "claimant_last_name": {{
      "value": "Smith",
      "confidence": 95,
      "source": "Email body paragraph 1",
      "reasoning": "Patient last name clearly stated with first name"
    }},
    "claim_number": {{
      "value": "WC-2025-001234",
      "confidence": 98,
      "source": "Email header/subject",
      "reasoning": "Standard WC claim number format found in email header"
    }},
    "carrier": {{
      "value": "ACE Insurance",
      "confidence": 92,
      "source": "Adjuster email signature and domain",
      "reasoning": "Company name in adjuster email and footer"
    }},
    "service_requested": {{
      "value": "PT Evaluation",
      "confidence": 88,
      "source": "Email body paragraph 2",
      "reasoning": "Service explicitly mentioned: 'Please schedule PT evaluation'"
    }},
    "claimant_dob": {{
      "value": "1985-03-15",
      "confidence": 82,
      "source": "Email body",
      "reasoning": "Date of birth listed as '3/15/85' - converted to YYYY-MM-DD"
    }},
    "date_of_injury": {{
      "value": "2025-01-10",
      "confidence": 90,
      "source": "Email claim description",
      "reasoning": "Injury date explicitly stated as 'January 10, 2025'"
    }},
    "body_parts": {{
      "value": "right shoulder",
      "confidence": 85,
      "source": "Email body paragraph 2",
      "reasoning": "Injury description mentions 'right shoulder injury'"
    }},
    "claimant_phone": {{
      "value": "(555) 123-4567",
      "confidence": 75,
      "source": "Email body",
      "reasoning": "Phone number found but format was unclear - normalized to standard format"
    }},
    "claimant_email": {{
      "value": "john.smith@example.com",
      "confidence": 80,
      "source": "Email body contact info",
      "reasoning": "Claimant email listed in referral contact information"
    }},
    "claimant_address_1": {{
      "value": "123 Main Street",
      "confidence": 70,
      "source": "Email body address section",
      "reasoning": "Address provided but somewhat unclear - extracted best interpretation"
    }},
    "claimant_address_2": {{
      "value": "",
      "confidence": 0,
      "source": "Not found",
      "reasoning": "No apartment or suite number mentioned"
    }},
    "claimant_city": {{
      "value": "Springfield",
      "confidence": 75,
      "source": "Email body address",
      "reasoning": "City extracted from address line"
    }},
    "claimant_state": {{
      "value": "IL",
      "confidence": 80,
      "source": "Email body address",
      "reasoning": "State extracted from address, converted to 2-letter code"
    }},
    "claimant_zip": {{
      "value": "62701",
      "confidence": 78,
      "source": "Email body address",
      "reasoning": "ZIP code extracted from address"
    }},
    "employer_name": {{
      "value": "Acme Corp",
      "confidence": 65,
      "source": "Email body",
      "reasoning": "Employer mentioned in injury description"
    }},
    "authorization_number": {{
      "value": "",
      "confidence": 0,
      "source": "Not found",
      "reasoning": "No authorization number mentioned in document"
    }},
    "adjuster_name": {{
      "value": "Jane Adjuster",
      "confidence": 95,
      "source": "Email signature",
      "reasoning": "Adjuster name in email footer"
    }},
    "adjuster_email": {{
      "value": "jane.adjuster@aceinsurance.com",
      "confidence": 100,
      "source": "Email from field",
      "reasoning": "Email address from message sender"
    }}
  }},
  "warnings": [
    "Address is incomplete - no apartment number found",
    "DOB confidence is moderate - date format was ambiguous in source"
  ],
  "overall_confidence": 82,
  "extraction_strategy": "comprehensive"
}}


RETURN ONLY THE JSON ABOVE. NO OTHER TEXT.
"""


# ============================================================================
# Usage in extraction_service.py
# ============================================================================

"""
Replace the existing extraction prompt in ExtractionService with:

def extract_from_email_for_filemaker(
    self,
    from_email: str,
    subject: str,
    body: str,
    attachment_texts: Optional[list[str]] = None,
) -> ExtractionResult:
    '''Extract data optimized for FileMaker intake form.'''
    
    # Clean HTML from body
    clean_body = self._strip_html(body)
    
    # Build attachment section
    attachment_section = ""
    if attachment_texts:
        attachment_section = "\\nATTACHMENT CONTENTS:\\n"
        for i, text in enumerate(attachment_texts, 1):
            attachment_section += f"\\n--- Attachment {i} ---\\n{text[:3000]}\\n"
    
    # Build the FileMaker-optimized prompt
    prompt = FILEMAKER_EXTRACTION_PROMPT.format(
        document_text=f"{subject}\\n\\n{clean_body}{attachment_section}"[:10000]
    )
    
    # Call Claude
    try:
        client = get_anthropic_client()
        response = client.messages.create(
            model=self.settings.claude_model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        
        response_text = response.content[0].text
        return self._parse_extraction_response(response_text)
    
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return ExtractionResult()
"""
