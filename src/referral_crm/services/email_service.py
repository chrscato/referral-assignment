"""
Email service for Microsoft Graph API integration.
Handles email fetching, replies, and forwarding.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from referral_crm.config import get_settings

# Lazy import for MSAL
msal = None


def get_msal():
    """Lazily import MSAL."""
    global msal
    if msal is None:
        import msal as _msal

        msal = _msal
    return msal


@dataclass
class EmailMessage:
    """Represents an email message from Graph API."""

    id: str
    subject: str
    body_content: str
    body_content_type: str
    body_preview: str
    from_name: str
    from_email: str
    received_datetime: datetime
    web_link: str
    internet_message_id: str
    conversation_id: str
    has_attachments: bool

    @classmethod
    def from_graph_response(cls, data: dict) -> "EmailMessage":
        """Create from a Graph API message response."""
        return cls(
            id=data.get("id", ""),
            subject=data.get("subject", ""),
            body_content=data.get("body", {}).get("content", ""),
            body_content_type=data.get("body", {}).get("contentType", "text"),
            body_preview=data.get("bodyPreview", ""),
            from_name=data.get("from", {}).get("emailAddress", {}).get("name", ""),
            from_email=data.get("from", {}).get("emailAddress", {}).get("address", ""),
            received_datetime=datetime.fromisoformat(
                data.get("receivedDateTime", "").replace("Z", "+00:00")
            ),
            web_link=data.get("webLink", ""),
            internet_message_id=data.get("internetMessageId", ""),
            conversation_id=data.get("conversationId", ""),
            has_attachments=data.get("hasAttachments", False),
        )


@dataclass
class EmailAttachment:
    """Represents an email attachment from Graph API."""

    id: str
    name: str
    content_type: str
    size: int
    content_bytes: Optional[bytes] = None

    @classmethod
    def from_graph_response(cls, data: dict) -> "EmailAttachment":
        """Create from a Graph API attachment response."""
        content_bytes = None
        if "contentBytes" in data:
            content_bytes = base64.b64decode(data["contentBytes"])

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            content_type=data.get("contentType", "application/octet-stream"),
            size=data.get("size", 0),
            content_bytes=content_bytes,
        )


class EmailService:
    """Service for interacting with Microsoft Graph API for email operations."""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.settings = get_settings()
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    def is_configured(self) -> bool:
        """Check if Microsoft Graph API is configured."""
        return bool(
            self.settings.graph_client_id
            and self.settings.graph_client_secret
            and self.settings.graph_tenant_id
        )

    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if not self.is_configured():
            raise ValueError("Microsoft Graph API not configured")

        # Check if we have a valid token
        if self._access_token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at:
                return self._access_token

        # Get new token using client credentials flow
        msal_lib = get_msal()
        app = msal_lib.ConfidentialClientApplication(
            self.settings.graph_client_id,
            authority=f"https://login.microsoftonline.com/{self.settings.graph_tenant_id}",
            client_credential=self.settings.graph_client_secret,
        )

        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )

        if "access_token" not in result:
            raise ValueError(f"Failed to acquire token: {result.get('error_description')}")

        self._access_token = result["access_token"]
        # Token typically valid for 1 hour, set expiry a bit earlier to be safe
        self._token_expires_at = datetime.utcnow().replace(minute=55)

        return self._access_token

    def _get_headers(self) -> dict:
        """Get headers for Graph API requests."""
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json",
        }

    def list_messages(
        self,
        folder: str = "Inbox",
        top: int = 50,
        skip: int = 0,
        filter_query: Optional[str] = None,
        order_by: str = "receivedDateTime desc",
    ) -> list[EmailMessage]:
        """
        List messages from a mail folder.

        Args:
            folder: Mail folder name (default: Inbox)
            top: Number of messages to return
            skip: Number of messages to skip
            filter_query: OData filter query
            order_by: OData orderby clause

        Returns:
            List of EmailMessage objects
        """
        url = f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder}/messages"
        params = {
            "$top": top,
            "$skip": skip,
            "$orderby": order_by,
            "$select": "id,subject,body,bodyPreview,from,receivedDateTime,webLink,internetMessageId,conversationId,hasAttachments",
        }
        if filter_query:
            params["$filter"] = filter_query

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()

        messages = []
        for msg_data in data.get("value", []):
            messages.append(EmailMessage.from_graph_response(msg_data))

        return messages

    def get_message(self, message_id: str) -> EmailMessage:
        """Get a specific message by ID."""
        url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}"
        params = {
            "$select": "id,subject,body,bodyPreview,from,receivedDateTime,webLink,internetMessageId,conversationId,hasAttachments"
        }

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()

        return EmailMessage.from_graph_response(data)

    def get_attachments(self, message_id: str) -> list[EmailAttachment]:
        """Get attachments for a message."""
        url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}/attachments"

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

        attachments = []
        for att_data in data.get("value", []):
            # Only include file attachments, not item attachments
            if att_data.get("@odata.type") == "#microsoft.graph.fileAttachment":
                attachments.append(EmailAttachment.from_graph_response(att_data))

        return attachments

    def save_attachment(self, attachment: EmailAttachment, directory: Path) -> Path:
        """Save an attachment to disk."""
        directory.mkdir(parents=True, exist_ok=True)
        filepath = directory / attachment.name

        if attachment.content_bytes:
            filepath.write_bytes(attachment.content_bytes)
        else:
            raise ValueError("Attachment has no content")

        return filepath

    def send_reply(
        self,
        message_id: str,
        reply_body: str,
        reply_all: bool = False,
    ) -> None:
        """
        Send a reply to a message.

        Args:
            message_id: ID of the message to reply to
            reply_body: HTML body of the reply
            reply_all: Whether to reply to all recipients
        """
        endpoint = "replyAll" if reply_all else "reply"
        url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}/{endpoint}"

        payload = {"comment": reply_body}

        with httpx.Client() as client:
            response = client.post(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()

    def forward_message(
        self,
        message_id: str,
        to_recipients: list[str],
        comment: Optional[str] = None,
    ) -> None:
        """
        Forward a message to other recipients.

        Args:
            message_id: ID of the message to forward
            to_recipients: List of email addresses to forward to
            comment: Optional comment to include
        """
        url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}/forward"

        payload = {
            "toRecipients": [
                {"emailAddress": {"address": email}} for email in to_recipients
            ]
        }
        if comment:
            payload["comment"] = comment

        with httpx.Client() as client:
            response = client.post(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()

    def mark_as_read(self, message_id: str, is_read: bool = True) -> None:
        """Mark a message as read or unread."""
        url = f"{self.GRAPH_BASE_URL}/me/messages/{message_id}"
        payload = {"isRead": is_read}

        with httpx.Client() as client:
            response = client.patch(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()

    def get_unread_count(self, folder: str = "Inbox") -> int:
        """Get count of unread messages in a folder."""
        url = f"{self.GRAPH_BASE_URL}/me/mailFolders/{folder}"

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

        return data.get("unreadItemCount", 0)

    def _get_user_endpoint(self, mailbox: Optional[str] = None) -> str:
        """Get the user endpoint - either /me or /users/{mailbox}."""
        if mailbox:
            return f"{self.GRAPH_BASE_URL}/users/{mailbox}"
        return f"{self.GRAPH_BASE_URL}/me"

    def get_folder_id(
        self,
        folder_path: str,
        mailbox: Optional[str] = None,
    ) -> str:
        """
        Get the folder ID for a nested folder path like 'Inbox/Assigned'.

        Args:
            folder_path: Folder path with '/' separator (e.g., 'Inbox/Assigned')
            mailbox: Optional shared mailbox email address

        Returns:
            The folder ID
        """
        base_url = self._get_user_endpoint(mailbox)
        parts = folder_path.split("/")

        # Start with the root folder
        current_folder_id = parts[0]

        with httpx.Client() as client:
            # If there are subfolders, navigate to them
            for subfolder_name in parts[1:]:
                # Get child folders of current folder
                url = f"{base_url}/mailFolders/{current_folder_id}/childFolders"
                response = client.get(url, headers=self._get_headers())
                response.raise_for_status()
                data = response.json()

                # Find the subfolder by name
                found = False
                for folder in data.get("value", []):
                    if folder.get("displayName", "").lower() == subfolder_name.lower():
                        current_folder_id = folder["id"]
                        found = True
                        break

                if not found:
                    raise ValueError(f"Folder not found: {subfolder_name} in {folder_path}")

        return current_folder_id

    def list_messages_from_shared_mailbox(
        self,
        mailbox: str,
        folder_path: str = "Inbox",
        top: int = 50,
        skip: int = 0,
        filter_query: Optional[str] = None,
        order_by: str = "receivedDateTime desc",
    ) -> list[EmailMessage]:
        """
        List messages from a shared mailbox folder.

        Args:
            mailbox: Shared mailbox email address
            folder_path: Mail folder path (e.g., 'Inbox' or 'Inbox/Assigned')
            top: Number of messages to return
            skip: Number of messages to skip
            filter_query: OData filter query
            order_by: OData orderby clause

        Returns:
            List of EmailMessage objects
        """
        base_url = self._get_user_endpoint(mailbox)
        folder_id = self.get_folder_id(folder_path, mailbox)

        url = f"{base_url}/mailFolders/{folder_id}/messages"
        params = {
            "$top": top,
            "$skip": skip,
            "$orderby": order_by,
            "$select": "id,subject,body,bodyPreview,from,receivedDateTime,webLink,internetMessageId,conversationId,hasAttachments",
        }
        if filter_query:
            params["$filter"] = filter_query

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()

        messages = []
        for msg_data in data.get("value", []):
            messages.append(EmailMessage.from_graph_response(msg_data))

        return messages

    def get_conversation_messages(
        self,
        conversation_id: str,
        mailbox: Optional[str] = None,
        folder_path: str = "Inbox",
    ) -> list[EmailMessage]:
        """
        Get all messages in a conversation thread.

        Args:
            conversation_id: The conversation ID to fetch
            mailbox: Optional shared mailbox email address
            folder_path: Mail folder path to search in

        Returns:
            List of EmailMessage objects in the conversation, ordered by date (oldest first)
        """
        base_url = self._get_user_endpoint(mailbox)
        folder_id = self.get_folder_id(folder_path, mailbox)

        url = f"{base_url}/mailFolders/{folder_id}/messages"
        params = {
            "$filter": f"conversationId eq '{conversation_id}'",
            "$orderby": "receivedDateTime asc",
            "$select": "id,subject,body,bodyPreview,from,receivedDateTime,webLink,internetMessageId,conversationId,hasAttachments",
        }

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()

        messages = []
        for msg_data in data.get("value", []):
            messages.append(EmailMessage.from_graph_response(msg_data))

        return messages

    def get_first_message_in_chain(
        self,
        message: EmailMessage,
        mailbox: Optional[str] = None,
        folder_path: str = "Inbox",
    ) -> EmailMessage:
        """
        Get the first (oldest) message in an email chain.

        Args:
            message: Any message in the conversation
            mailbox: Optional shared mailbox email address
            folder_path: Mail folder path to search in

        Returns:
            The first EmailMessage in the conversation thread
        """
        messages = self.get_conversation_messages(
            message.conversation_id,
            mailbox=mailbox,
            folder_path=folder_path,
        )

        if not messages:
            return message

        # Return the oldest message (first in the list since ordered by date asc)
        return messages[0]

    def get_message_from_shared_mailbox(
        self,
        message_id: str,
        mailbox: str,
    ) -> EmailMessage:
        """Get a specific message by ID from a shared mailbox."""
        base_url = self._get_user_endpoint(mailbox)
        url = f"{base_url}/messages/{message_id}"
        params = {
            "$select": "id,subject,body,bodyPreview,from,receivedDateTime,webLink,internetMessageId,conversationId,hasAttachments"
        }

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()

        return EmailMessage.from_graph_response(data)

    def get_attachments_from_shared_mailbox(
        self,
        message_id: str,
        mailbox: str,
    ) -> list[EmailAttachment]:
        """Get attachments for a message from a shared mailbox."""
        base_url = self._get_user_endpoint(mailbox)
        url = f"{base_url}/messages/{message_id}/attachments"

        with httpx.Client() as client:
            response = client.get(url, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

        attachments = []
        for att_data in data.get("value", []):
            if att_data.get("@odata.type") == "#microsoft.graph.fileAttachment":
                attachments.append(EmailAttachment.from_graph_response(att_data))

        return attachments


class EmailTemplateService:
    """Service for managing email reply templates."""

    DEFAULT_TEMPLATES = {
        "missing_auth": {
            "label": "Missing Authorization",
            "subject": "RE: {original_subject}",
            "body": """Hi {adjuster_name},

Thank you for the referral for {claimant_name}.

To proceed with scheduling, we'll need a copy of the authorization letter. Please reply with this document attached.

Best regards,
{signature}""",
        },
        "clarify_service": {
            "label": "Clarify Service Type",
            "subject": "RE: {original_subject}",
            "body": """Hi {adjuster_name},

Thank you for the referral for {claimant_name}.

Could you please clarify the specific service being requested? We want to ensure we match the claimant with the appropriate provider.

Best regards,
{signature}""",
        },
        "need_dob": {
            "label": "Missing Date of Birth",
            "subject": "RE: {original_subject}",
            "body": """Hi {adjuster_name},

We're processing the referral for {claimant_name}.

We need the claimant's date of birth to proceed. Could you please provide this?

Best regards,
{signature}""",
        },
        "confirmation": {
            "label": "Referral Received",
            "subject": "RE: {original_subject}",
            "body": """Hi {adjuster_name},

This confirms receipt of your referral for {claimant_name} (Claim #{claim_number}).

We're processing this and will have scheduling information shortly.

Best regards,
{signature}""",
        },
        "scheduled": {
            "label": "Appointment Scheduled",
            "subject": "RE: {original_subject}",
            "body": """Hi {adjuster_name},

The appointment for {claimant_name} (Claim #{claim_number}) has been scheduled:

Provider: {provider_name}
Date/Time: {appointment_datetime}
Address: {provider_address}

The claimant has been notified. Please let us know if you need anything else.

Best regards,
{signature}""",
        },
    }

    def get_template(self, template_name: str) -> Optional[dict]:
        """Get a template by name."""
        return self.DEFAULT_TEMPLATES.get(template_name)

    def list_templates(self) -> list[dict]:
        """List all available templates."""
        return [
            {"name": name, **template}
            for name, template in self.DEFAULT_TEMPLATES.items()
        ]

    def render_template(self, template_name: str, **context) -> dict:
        """
        Render a template with the given context.

        Returns dict with 'subject' and 'body' keys.
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")

        # Provide defaults for missing context
        context.setdefault("adjuster_name", "")
        context.setdefault("claimant_name", "")
        context.setdefault("claim_number", "")
        context.setdefault("original_subject", "")
        context.setdefault("signature", "")

        return {
            "subject": template["subject"].format(**context),
            "body": template["body"].format(**context),
        }
