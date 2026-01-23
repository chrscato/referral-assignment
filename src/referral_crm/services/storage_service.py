"""
S3 Storage service for emails, attachments, and referral data.
Provides upload, download, and presigned URL generation.
"""

import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional
from io import BytesIO

from referral_crm.config import get_settings

# Lazy import boto3
boto3 = None
botocore = None


def get_boto3():
    """Lazily import boto3."""
    global boto3, botocore
    if boto3 is None:
        import boto3 as _boto3
        import botocore as _botocore
        boto3 = _boto3
        botocore = _botocore
    return boto3


class StorageService:
    """
    S3-based storage service for referral data.

    Storage structure:
    s3://{bucket}/
        referrals/{referral_id}/
            email.html          # Original email HTML
            email.json          # Email metadata
            extraction.json     # LLM extraction results
            attachments/
                {filename}      # Original attachments
                {filename}.txt  # Extracted text (if applicable)
    """

    def __init__(self):
        self.settings = get_settings()
        self._client = None

    @property
    def client(self):
        """Get or create S3 client."""
        if self._client is None:
            boto = get_boto3()

            client_kwargs = {}
            if self.settings.aws_endpoint_url:
                client_kwargs["endpoint_url"] = self.settings.aws_endpoint_url
            if self.settings.aws_access_key_id:
                client_kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
                client_kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
            if self.settings.aws_region:
                client_kwargs["region_name"] = self.settings.aws_region

            self._client = boto.client("s3", **client_kwargs)
        return self._client

    @property
    def bucket(self) -> str:
        """Get the S3 bucket name."""
        return self.settings.s3_bucket

    def is_configured(self) -> bool:
        """Check if S3 storage is configured."""
        return bool(self.settings.s3_bucket)

    def _get_referral_prefix(self, referral_id: int) -> str:
        """Get the S3 key prefix for a referral."""
        return f"referrals/{referral_id}"

    # =========================================================================
    # Email Storage
    # =========================================================================
    def upload_email(
        self,
        referral_id: int,
        email_html: str,
        email_metadata: dict,
    ) -> dict:
        """
        Upload email content and metadata to S3.

        Returns:
            dict with S3 keys for stored objects
        """
        prefix = self._get_referral_prefix(referral_id)
        result = {}

        # Upload HTML content
        html_key = f"{prefix}/email.html"
        self.client.put_object(
            Bucket=self.bucket,
            Key=html_key,
            Body=email_html.encode("utf-8"),
            ContentType="text/html",
        )
        result["email_html_key"] = html_key

        # Upload metadata as JSON
        meta_key = f"{prefix}/email.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=meta_key,
            Body=json.dumps(email_metadata, default=str, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        result["email_meta_key"] = meta_key

        return result

    def get_email_html(self, referral_id: int) -> Optional[str]:
        """Get the stored email HTML for a referral."""
        key = f"{self._get_referral_prefix(referral_id)}/email.html"
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except self.client.exceptions.NoSuchKey:
            return None

    def get_email_html_url(self, referral_id: int, expires_in: int = 3600) -> Optional[str]:
        """Get a presigned URL to view the email HTML."""
        key = f"{self._get_referral_prefix(referral_id)}/email.html"
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception:
            return None

    # =========================================================================
    # Attachment Storage
    # =========================================================================
    def upload_attachment(
        self,
        referral_id: int,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
        extracted_text: Optional[str] = None,
    ) -> dict:
        """
        Upload an attachment to S3.

        Returns:
            dict with S3 keys and URLs
        """
        prefix = self._get_referral_prefix(referral_id)

        # Guess content type if not provided
        if not content_type:
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or "application/octet-stream"

        result = {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        }

        # Upload the attachment
        att_key = f"{prefix}/attachments/{filename}"
        self.client.put_object(
            Bucket=self.bucket,
            Key=att_key,
            Body=content,
            ContentType=content_type,
        )
        result["s3_key"] = att_key

        # Upload extracted text if available
        if extracted_text:
            text_key = f"{prefix}/attachments/{filename}.txt"
            self.client.put_object(
                Bucket=self.bucket,
                Key=text_key,
                Body=extracted_text.encode("utf-8"),
                ContentType="text/plain",
            )
            result["text_s3_key"] = text_key

        return result

    def get_attachment(self, referral_id: int, filename: str) -> Optional[bytes]:
        """Download an attachment from S3."""
        key = f"{self._get_referral_prefix(referral_id)}/attachments/{filename}"
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except Exception:
            return None

    def get_attachment_url(
        self,
        referral_id: int,
        filename: str,
        expires_in: int = 3600,
        inline: bool = False,
    ) -> Optional[str]:
        """
        Get a presigned URL to download/view an attachment.

        Args:
            referral_id: The referral ID
            filename: The attachment filename
            expires_in: URL expiration in seconds
            inline: If True, set content-disposition to inline for viewing
        """
        key = f"{self._get_referral_prefix(referral_id)}/attachments/{filename}"

        params = {"Bucket": self.bucket, "Key": key}
        if inline:
            content_type, _ = mimetypes.guess_type(filename)
            if content_type:
                params["ResponseContentType"] = content_type
            params["ResponseContentDisposition"] = "inline"

        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
        except Exception:
            return None

    def get_attachment_text_url(
        self,
        referral_id: int,
        filename: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        """Get a presigned URL to view extracted text from an attachment."""
        key = f"{self._get_referral_prefix(referral_id)}/attachments/{filename}.txt"
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception:
            return None

    def list_attachments(self, referral_id: int) -> list[dict]:
        """List all attachments for a referral."""
        prefix = f"{self._get_referral_prefix(referral_id)}/attachments/"

        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
            )
        except Exception:
            return []

        attachments = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = key.replace(prefix, "")

            # Skip extracted text files
            if filename.endswith(".txt"):
                continue

            attachments.append({
                "filename": filename,
                "s3_key": key,
                "size_bytes": obj["Size"],
                "last_modified": obj["LastModified"],
            })

        return attachments

    # =========================================================================
    # Extraction Data Storage
    # =========================================================================
    def upload_extraction(
        self,
        referral_id: int,
        extraction_data: dict,
    ) -> str:
        """
        Upload LLM extraction results to S3.

        Returns:
            S3 key for the stored extraction
        """
        key = f"{self._get_referral_prefix(referral_id)}/extraction.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(extraction_data, default=str, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        return key

    def get_extraction(self, referral_id: int) -> Optional[dict]:
        """Get the stored extraction data for a referral."""
        key = f"{self._get_referral_prefix(referral_id)}/extraction.json"
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception:
            return None

    # =========================================================================
    # Bulk Operations
    # =========================================================================
    def upload_referral_data(
        self,
        referral_id: int,
        email_html: Optional[str] = None,
        email_metadata: Optional[dict] = None,
        extraction_data: Optional[dict] = None,
        attachments: Optional[list[tuple[str, bytes, str]]] = None,  # (filename, content, extracted_text)
    ) -> dict:
        """
        Upload all data for a referral to S3 in one call.

        Args:
            referral_id: The referral ID
            email_html: The email HTML content
            email_metadata: Email metadata dict
            extraction_data: LLM extraction results
            attachments: List of (filename, content_bytes, extracted_text) tuples

        Returns:
            dict with all S3 keys
        """
        result = {"referral_id": referral_id}

        if email_html and email_metadata:
            email_result = self.upload_email(referral_id, email_html, email_metadata)
            result.update(email_result)

        if extraction_data:
            result["extraction_key"] = self.upload_extraction(referral_id, extraction_data)

        if attachments:
            result["attachments"] = []
            for filename, content, extracted_text in attachments:
                att_result = self.upload_attachment(
                    referral_id, filename, content, extracted_text=extracted_text
                )
                result["attachments"].append(att_result)

        return result

    def delete_referral_data(self, referral_id: int) -> int:
        """
        Delete all S3 data for a referral.

        Returns:
            Number of objects deleted
        """
        prefix = self._get_referral_prefix(referral_id)

        # List all objects with this prefix
        objects_to_delete = []
        paginator = self.client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                objects_to_delete.append({"Key": obj["Key"]})

        if not objects_to_delete:
            return 0

        # Delete in batches of 1000 (S3 limit)
        deleted = 0
        for i in range(0, len(objects_to_delete), 1000):
            batch = objects_to_delete[i:i + 1000]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": batch},
            )
            deleted += len(batch)

        return deleted


# Convenience functions
_storage_service = None


def get_storage_service() -> StorageService:
    """Get the global storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
