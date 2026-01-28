#!/usr/bin/env python3
"""
Load reference data (ICD-10 codes, procedure codes) into the database.

Usage:
    python scripts/load_reference_data.py --icd10 data/icd10_codes.csv
    python scripts/load_reference_data.py --procedures data/procedure_codes.csv
    python scripts/load_reference_data.py --all  # Load sample data
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from referral_crm.models import init_db, session_scope, ICD10Code, ProcedureCode
from referral_crm.services.reference_data import ReferenceDataService


# Sample ICD-10 codes for workers' compensation (common diagnoses)
SAMPLE_ICD10_CODES = [
    # Back/Spine
    ("M54.5", "Low back pain", "Musculoskeletal", "Back"),
    ("M54.2", "Cervicalgia", "Musculoskeletal", "Neck"),
    ("M54.16", "Radiculopathy, lumbar region", "Musculoskeletal", "Back"),
    ("M54.17", "Radiculopathy, lumbosacral region", "Musculoskeletal", "Back"),
    ("M51.16", "Intervertebral disc disorders with radiculopathy, lumbar region", "Musculoskeletal", "Back"),
    ("M51.26", "Other intervertebral disc degeneration, lumbar region", "Musculoskeletal", "Back"),
    ("M47.816", "Spondylosis without myelopathy, lumbar region", "Musculoskeletal", "Back"),

    # Shoulder
    ("M75.100", "Unspecified rotator cuff tear of unspecified shoulder", "Musculoskeletal", "Shoulder"),
    ("M75.101", "Unspecified rotator cuff tear of right shoulder", "Musculoskeletal", "Shoulder"),
    ("M75.102", "Unspecified rotator cuff tear of left shoulder", "Musculoskeletal", "Shoulder"),
    ("M25.511", "Pain in right shoulder", "Musculoskeletal", "Shoulder"),
    ("M25.512", "Pain in left shoulder", "Musculoskeletal", "Shoulder"),
    ("S43.001A", "Unspecified subluxation of right shoulder joint, initial encounter", "Injury", "Shoulder"),
    ("S43.002A", "Unspecified subluxation of left shoulder joint, initial encounter", "Injury", "Shoulder"),

    # Knee
    ("M17.11", "Primary osteoarthritis, right knee", "Musculoskeletal", "Knee"),
    ("M17.12", "Primary osteoarthritis, left knee", "Musculoskeletal", "Knee"),
    ("M23.201", "Derangement of unspecified meniscus, right knee", "Musculoskeletal", "Knee"),
    ("M23.202", "Derangement of unspecified meniscus, left knee", "Musculoskeletal", "Knee"),
    ("M25.561", "Pain in right knee", "Musculoskeletal", "Knee"),
    ("M25.562", "Pain in left knee", "Musculoskeletal", "Knee"),
    ("S83.101A", "Unspecified subluxation of right knee, initial encounter", "Injury", "Knee"),

    # Wrist/Hand
    ("S62.001A", "Unspecified fracture of navicular bone of right wrist, initial encounter", "Injury", "Wrist"),
    ("S62.002A", "Unspecified fracture of navicular bone of left wrist, initial encounter", "Injury", "Wrist"),
    ("G56.00", "Carpal tunnel syndrome, unspecified upper limb", "Nervous System", "Wrist"),
    ("G56.01", "Carpal tunnel syndrome, right upper limb", "Nervous System", "Wrist"),
    ("G56.02", "Carpal tunnel syndrome, left upper limb", "Nervous System", "Wrist"),

    # Hip
    ("M16.11", "Primary osteoarthritis, right hip", "Musculoskeletal", "Hip"),
    ("M16.12", "Primary osteoarthritis, left hip", "Musculoskeletal", "Hip"),
    ("M25.551", "Pain in right hip", "Musculoskeletal", "Hip"),
    ("M25.552", "Pain in left hip", "Musculoskeletal", "Hip"),

    # Ankle/Foot
    ("S93.401A", "Sprain of calcaneofibular ligament of right ankle, initial encounter", "Injury", "Ankle"),
    ("S93.402A", "Sprain of calcaneofibular ligament of left ankle, initial encounter", "Injury", "Ankle"),
    ("M25.571", "Pain in right ankle and joints of right foot", "Musculoskeletal", "Ankle"),
    ("M25.572", "Pain in left ankle and joints of left foot", "Musculoskeletal", "Ankle"),
]

# Sample procedure/CPT codes for workers' compensation services
SAMPLE_PROCEDURE_CODES = [
    # Physical Therapy - Evaluation
    ("97161", "PT evaluation low complexity", "PT Evaluation", "Physical Therapy", "General"),
    ("97162", "PT evaluation moderate complexity", "PT Evaluation", "Physical Therapy", "General"),
    ("97163", "PT evaluation high complexity", "PT Evaluation", "Physical Therapy", "General"),

    # Physical Therapy - Treatment
    ("97110", "Therapeutic exercises", "PT Treatment", "Physical Therapy", "General"),
    ("97112", "Neuromuscular re-education", "PT Treatment", "Physical Therapy", "General"),
    ("97116", "Gait training", "PT Treatment", "Physical Therapy", "General"),
    ("97140", "Manual therapy techniques", "PT Treatment", "Physical Therapy", "General"),
    ("97530", "Therapeutic activities", "PT Treatment", "Physical Therapy", "General"),
    ("97535", "Self-care/home management training", "PT Treatment", "Physical Therapy", "General"),

    # MRI - Spine
    ("72141", "MRI cervical spine without contrast", "MRI", "Imaging", "Spine"),
    ("72146", "MRI thoracic spine without contrast", "MRI", "Imaging", "Spine"),
    ("72148", "MRI lumbar spine without contrast", "MRI", "Imaging", "Spine"),
    ("72156", "MRI cervical spine with and without contrast", "MRI", "Imaging", "Spine"),
    ("72157", "MRI thoracic spine with and without contrast", "MRI", "Imaging", "Spine"),
    ("72158", "MRI lumbar spine with and without contrast", "MRI", "Imaging", "Spine"),

    # MRI - Extremity
    ("73221", "MRI any joint of upper extremity", "MRI", "Imaging", "Upper Extremity"),
    ("73721", "MRI any joint of lower extremity", "MRI", "Imaging", "Lower Extremity"),
    ("73218", "MRI upper extremity non-joint without contrast", "MRI", "Imaging", "Upper Extremity"),
    ("73718", "MRI lower extremity non-joint without contrast", "MRI", "Imaging", "Lower Extremity"),

    # CT Scan
    ("72125", "CT cervical spine without contrast", "CT Scan", "Imaging", "Spine"),
    ("72128", "CT thoracic spine without contrast", "CT Scan", "Imaging", "Spine"),
    ("72131", "CT lumbar spine without contrast", "CT Scan", "Imaging", "Spine"),
    ("73200", "CT upper extremity without contrast", "CT Scan", "Imaging", "Upper Extremity"),
    ("73700", "CT lower extremity without contrast", "CT Scan", "Imaging", "Lower Extremity"),

    # X-Ray
    ("72020", "X-ray spine single view", "X-Ray", "Imaging", "Spine"),
    ("72052", "X-ray cervical spine complete", "X-Ray", "Imaging", "Spine"),
    ("72100", "X-ray lumbosacral spine 2-3 views", "X-Ray", "Imaging", "Spine"),
    ("73030", "X-ray shoulder complete", "X-Ray", "Imaging", "Shoulder"),
    ("73060", "X-ray humerus", "X-Ray", "Imaging", "Upper Extremity"),
    ("73110", "X-ray wrist complete", "X-Ray", "Imaging", "Wrist"),
    ("73560", "X-ray knee 1-2 views", "X-Ray", "Imaging", "Knee"),
    ("73610", "X-ray ankle complete", "X-Ray", "Imaging", "Ankle"),

    # Ultrasound
    ("76881", "Ultrasound extremity non-vascular complete", "Ultrasound", "Imaging", "Extremity"),
    ("76882", "Ultrasound extremity non-vascular limited", "Ultrasound", "Imaging", "Extremity"),

    # IME / Evaluation
    ("99456", "Work-related disability examination", "IME", "Medical Evaluation", "General"),

    # FCE
    ("97750", "Physical performance test or measurement", "FCE", "Functional Assessment", "General"),
]


def load_sample_icd10(session):
    """Load sample ICD-10 codes into database."""
    count = 0
    for code, description, category, body_region in SAMPLE_ICD10_CODES:
        existing = session.query(ICD10Code).filter(ICD10Code.code == code).first()
        if existing:
            existing.description = description
            existing.category = category
            existing.body_region = body_region
            existing.is_active = True
        else:
            icd10 = ICD10Code(
                code=code,
                description=description,
                category=category,
                body_region=body_region,
            )
            session.add(icd10)
        count += 1
    session.commit()
    return count


def load_sample_procedures(session):
    """Load sample procedure codes into database."""
    count = 0
    for code, description, service_type, modality, body_region in SAMPLE_PROCEDURE_CODES:
        existing = session.query(ProcedureCode).filter(ProcedureCode.code == code).first()
        if existing:
            existing.description = description
            existing.service_type = service_type
            existing.modality = modality
            existing.body_region = body_region
            existing.is_active = True
        else:
            proc = ProcedureCode(
                code=code,
                description=description,
                service_type=service_type,
                modality=modality,
                body_region=body_region,
            )
            session.add(proc)
        count += 1
    session.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description="Load reference data into database")
    parser.add_argument("--icd10", type=Path, help="Path to ICD-10 CSV file")
    parser.add_argument("--procedures", type=Path, help="Path to procedures CSV file")
    parser.add_argument("--all", action="store_true", help="Load all sample data")
    args = parser.parse_args()

    # Initialize database
    init_db()
    print("Database initialized.")

    with session_scope() as session:
        ref_service = ReferenceDataService(session)

        if args.icd10:
            if not args.icd10.exists():
                print(f"Error: File not found: {args.icd10}")
                sys.exit(1)
            count = ref_service.load_icd10_from_csv(args.icd10)
            print(f"Loaded {count} ICD-10 codes from {args.icd10}")

        if args.procedures:
            if not args.procedures.exists():
                print(f"Error: File not found: {args.procedures}")
                sys.exit(1)
            count = ref_service.load_procedures_from_csv(args.procedures)
            print(f"Loaded {count} procedure codes from {args.procedures}")

        if args.all or (not args.icd10 and not args.procedures):
            # Load sample data
            print("Loading sample ICD-10 codes...")
            count = load_sample_icd10(session)
            print(f"  Loaded {count} ICD-10 codes")

            print("Loading sample procedure codes...")
            count = load_sample_procedures(session)
            print(f"  Loaded {count} procedure codes")

        # Print summary
        icd10_count = session.query(ICD10Code).filter(ICD10Code.is_active == True).count()
        proc_count = session.query(ProcedureCode).filter(ProcedureCode.is_active == True).count()
        print(f"\nDatabase now contains:")
        print(f"  - {icd10_count} active ICD-10 codes")
        print(f"  - {proc_count} active procedure codes")


if __name__ == "__main__":
    main()
