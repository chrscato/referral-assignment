# RingCentral Fax API (Python) — Strategic Integration Notes

> Goal: programmatically fax PDFs (and other supported file types) from your backend using RingCentral’s REST API, with clean auth, retries, and status tracking.

---

## 0) What you’re building (high-level architecture)

**Core flow**
1. **Authenticate** (JWT for server-to-server, or Auth Code + PKCE for multi-user apps).
2. **Send fax** to `/restapi/v1.0/account/~/extension/~/fax` as a multipart request (JSON “root” + one or more attachments).
3. **Poll message-store** for `messageStatus` until it leaves `Queued` (or use webhooks).
4. **Persist job metadata** (messageId, recipient, file hash, timestamps, final status, any error info).

**Recommended services/modules**
- `rc_auth.py` — token acquisition + refresh handling.
- `rc_fax.py` — send fax + parse response.
- `rc_fax_status.py` — poll message store / webhook handler.
- `storage.py` — store PDFs and job logs (S3/GCS/local).
- `db.py` — persist fax job records.

---

## 1) RingCentral prerequisites

### Accounts / environments
- **Sandbox/dev** uses `https://platform.devtest.ringcentral.com`
- **Production** uses `https://platform.ringcentral.com`

### Create a RingCentral app (Developer Console)
You’ll create a REST API app and enable the permissions/scopes your integration needs. For faxing you’ll typically need:
- **Faxes** (app scope) — “Sending and receiving faxes”  
- **ReadMessages** — included permission for the Faxes scope (needed to read message-store status)  

See the scopes list and the “Faxes” row in RingCentral’s permissions guide. citeturn3view0

---

## 2) Authentication strategy (pick one)

### Option A — JWT (best for backend “service” scripts)
Use JWT for server-to-server / single-tenant style integrations (one RingCentral account). RingCentral provides a JWT quick start and SDK examples for Python. citeturn2search2turn2search5

**Pros**
- No interactive user login
- Simple for batch/daemon jobs

**Cons**
- Usually tied to a single account/extension credential set
- Not ideal for SaaS where many customers connect their own RC accounts

### Option B — Auth Code + PKCE (best for multi-user / SaaS)
If your app has multiple users who each log into RingCentral, RingCentral recommends **Auth Code with PKCE**. citeturn0search14

---

## 3) Fax API fundamentals you must respect

### Multipart payload
Fax is different from many RingCentral APIs: it uses a **root JSON part** plus **one or more document parts** as MIME attachments. The docs explicitly call this out and state the Fax API accepts both `multipart/form-data` and `multipart/mixed`. citeturn6view0

### “From” number behavior
You **cannot** set the `from` number in the request. RingCentral uses the preselected outbound fax number set in the extension’s portal settings. citeturn6view0

### Scheduling
You can schedule a fax using `sendTime` (future datetime). If you need to cancel a scheduled fax, you delete it from the message store using its message id. citeturn6view0

### Attachment limitations (plan for these)
- Combined attachment size ≤ **50MB**
- Avoid special chars in filenames (e.g., `&`, `@#$%^...`)
- Up to **200 pages** total  
All listed in the sending faxes guide. citeturn6view0

### Supported file types
PDF is supported (and many other formats). citeturn6view0

---

## 4) Implementation approach (Python)

### Use the official RingCentral SDK (recommended)
RingCentral publishes official SDKs, including Python. citeturn0search26

**Why SDK?**
- Handles auth token exchange/refresh plumbing
- Provides a **multipart builder** helper used in the official fax samples (less MIME pain)

Install (typical):
```bash
pip install ringcentral
```

---

## 5) Minimal working Python example (JWT + send a PDF + poll status)

This pattern follows RingCentral’s own “Sending Faxes” guide (Python sample) but adjusted to PDF and made more “production-ish.” citeturn6view0

### `.env` (example)
```dotenv
RC_SERVER_URL=https://platform.devtest.ringcentral.com
RC_APP_CLIENT_ID=...
RC_APP_CLIENT_SECRET=...
RC_USER_JWT=...
```

### `send_fax_pdf.py`
```python
import os
import time
from ringcentral import SDK

RC_SERVER_URL = os.getenv("RC_SERVER_URL", "https://platform.devtest.ringcentral.com")
RC_APP_CLIENT_ID = os.environ["RC_APP_CLIENT_ID"]
RC_APP_CLIENT_SECRET = os.environ["RC_APP_CLIENT_SECRET"]
RC_USER_JWT = os.environ["RC_USER_JWT"]

RECIPIENT_FAX = os.environ["RECIPIENT_FAX"]  # e.g. "+17135551212"
PDF_PATH = os.environ.get("PDF_PATH", "test.pdf")

def login_platform() -> tuple[SDK, any]:
    rcsdk = SDK(RC_APP_CLIENT_ID, RC_APP_CLIENT_SECRET, RC_SERVER_URL)
    platform = rcsdk.platform()
    platform.login(jwt=RC_USER_JWT)
    return rcsdk, platform

def send_fax_pdf(rcsdk: SDK, platform, recipient_fax: str, pdf_path: str) -> str:
    builder = rcsdk.create_multipart_builder()
    builder.set_body({
        "to": [{"phoneNumber": recipient_fax}],
        "faxResolution": "High",
        "coverPageText": "Automated fax via RingCentral API (Python)"
        # Optional: "sendTime": "2026-01-27T20:30:00.000Z"  (ISO-8601 in UTC)
    })

    with open(pdf_path, "rb") as f:
        content = f.read()

    # The SDK will set appropriate multipart structure; you provide filename + bytes.
    # Keep filenames simple (avoid special chars) to respect attachment constraints.
    builder.add((os.path.basename(pdf_path), content))

    request = builder.request("/restapi/v1.0/account/~/extension/~/fax")
    resp = platform.send_request(request)
    data = resp.json()
    message_id = str(data.id)
    return message_id

def poll_fax_status(platform, message_id: str, timeout_s: int = 300, poll_s: int = 10) -> dict:
    deadline = time.time() + timeout_s
    endpoint = f"/restapi/v1.0/account/~/extension/~/message-store/{message_id}"

    last = None
    while time.time() < deadline:
        resp = platform.get(endpoint)
        msg = resp.json()
        last = msg
        status = getattr(msg, "messageStatus", None) or msg.get("messageStatus")

        # Typical flow: Queued -> Sent/Delivered (or Failed)
        if status and status != "Queued":
            return {"message_id": message_id, "status": status, "raw": msg}

        time.sleep(poll_s)

    return {"message_id": message_id, "status": "Timeout", "raw": last}

if __name__ == "__main__":
    rcsdk, platform = login_platform()
    message_id = send_fax_pdf(rcsdk, platform, RECIPIENT_FAX, PDF_PATH)
    print(f"Fax queued. messageId={message_id}")
    result = poll_fax_status(platform, message_id)
    print(f"Final status: {result['status']}")
```

**Notes**
- This uses the SDK’s multipart builder pattern shown in the official guide. citeturn6view0
- You’ll get a `messageId` back immediately; delivery is asynchronous.

---

## 6) Webhooks (recommended for scale)

Polling works for low volume; for production you’ll likely want webhooks so you can:
- Record state transitions (Queued → Sent/Delivered/Failed)
- Reduce API calls
- Trigger downstream actions (e.g., upload confirmation, update case status)

Start by subscribing to the **Fax Message Event** and storing `messageId` updates. (The permissions guide also lists the `SubscriptionWebhook` scope if you need it.) citeturn3view0

**Implementation tip**
- Build a webhook endpoint in your app (`POST /webhooks/ringcentral`)
- Validate signatures / tokens per RC guidance
- Map webhook payload → your `fax_jobs` table

---

## 7) Operational “gotchas” you’ll want to design around

### 7.1 File size + page count guardrails
Reject or split jobs that exceed:
- 50MB combined attachment size
- 200 pages combined  
citeturn6view0

### 7.2 Idempotency / retries
- Compute a file hash + recipient + timestamp bucket and store it.
- If a job fails, re-send with a backoff policy.
- Keep `messageId` per attempt.

### 7.3 Phone number normalization
Normalize to E.164 where possible: `+1XXXXXXXXXX`.

### 7.4 Multi-tenant design
If Atlas/BPH ever needs to fax “on behalf of customers,” plan for:
- OAuth Auth Code + PKCE
- Per-customer token storage and refresh
- Per-customer outbound fax settings (“from” number is controlled in their portal) citeturn6view0

---

## 8) What to read next (official docs)

- Programmable Fax API overview citeturn2search6  
- Sending faxes + code samples (JS/Python/PHP/etc.) citeturn6view0  
- Application permissions/scopes (Faxes + ReadMessages, etc.) citeturn3view0  
- Authentication guidance (PKCE recommended for multi-user apps) citeturn0search14  
- SDKs overview citeturn0search26  

---

## 9) Suggested next step for your codebase

If you tell me:
- whether this is **single-tenant** (your own RC account) vs **multi-tenant** (customers connect their RC),
- and whether you want **webhooks** now or later,

…I’ll map this into a clean module layout (files, functions, config) that plugs into your existing PDF pipeline and queues fax jobs reliably.
