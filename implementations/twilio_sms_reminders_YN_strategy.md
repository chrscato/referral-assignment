# Twilio SMS Reminders (Y/N Acknowledgment) — Strategic Implementation Plan (Python + Automations)

> Purpose: Send appointment (or task) reminder texts from your internal CRM, and capture a **simple reply of `Y` or `N`** to acknowledge or decline. This plan is Python-first and automation-driven, designed to be reliable, auditable, and easy to scale.

---

## 1) Product Scope

### What v1 does
- Send outbound reminder SMS for CRM events (e.g., upcoming appointment, doc-needed deadline).
- Accept inbound replies of **`Y`** or **`N`** only.
- Update CRM state automatically:
  - `Y` → confirmed/acknowledged
  - `N` → needs reschedule / human follow-up task
- Maintain a complete message audit trail (sent, delivered, replied, failed).

### What v1 does NOT do (yet)
- Free-form conversational texting
- Marketing blasts or campaigns
- Multi-channel orchestration (email/voice/WhatsApp)

---

## 2) Architecture (Python-first)

### Components
1. **CRM (source of truth)**
   - appointments, tasks, contacts
2. **Messaging Service (Python)**
   - a small module/service that sends SMS via Twilio and logs outbound messages
3. **Automations/Workers**
   - scheduled jobs (48h, 24h, 2h reminders) and event-triggered jobs
4. **Webhook Receiver (Python HTTP)**
   - receives inbound `Y/N` replies
   - receives delivery status callbacks
5. **Database**
   - contact + consent
   - thread mapping
   - message log
   - automation runs

### Key flows
**Outbound**
CRM event → automation job → render reminder template → send via Twilio → log message → status callback updates delivery

**Inbound**
Twilio inbound webhook → validate signature → normalize reply → map to latest pending reminder → update CRM + log → optionally enqueue next action

---

## 3) Data Model (Minimal & Durable)

### contacts
- `id`, `name`, `phone_e164`, `timezone`
- flags: `is_blocked`, `is_verified`

### sms_consent
- `contact_id`
- `status`: `opted_in | opted_out | unknown`
- `source`, `timestamp`, `actor`, `evidence`

### sms_threads
- `id`, `contact_id`
- `last_message_at`
- `state`: `open | closed`

### sms_messages
- `id` (UUID)
- `thread_id`, `contact_id`
- `direction`: `inbound | outbound`
- `body`
- `status`: `queued | sent | delivered | undelivered | failed | received`
- `twilio_message_sid`
- `error_code`, `error_message`
- `correlation_id` (idempotency key)
- `metadata_json` (e.g., `appointment_id`, `workflow_id`, `reminder_type`)
- timestamps: `created_at`, `sent_at`, `delivered_at`, `received_at`

### reminder_requests (recommended)
Tracks a reminder awaiting Y/N response.
- `id` (UUID)
- `appointment_id` (or `task_id`)
- `contact_id`
- `status`: `pending | yes | no | expired | resolved`
- `expires_at`
- `last_outbound_message_id`
- `last_inbound_message_id`
- `created_at`, `updated_at`

### automation_runs
- `id`, `workflow_name`, `version`
- `entity_refs` (appointment/task/contact)
- `state_json`, `next_run_at`, `status`

---

## 4) Message Design (Y/N Only)

### Reminder template (example)
- **Body**:  
  `Reminder: you’re scheduled for {appt_date} at {appt_time}. Reply Y to confirm or N if you need to reschedule.`

### Guardrails
- Keep messages short and unambiguous
- Avoid including sensitive details in SMS (use a secure link if needed)
- Always instruct the recipient clearly: **Reply Y or N**

### Optional follow-ups
- If reply is not Y/N:
  - auto-reply once: `Please reply Y to confirm or N to reschedule.`
  - then stop and create a human follow-up task if repeated.

---

## 5) Automation Logic (Scheduling)

### Recommended cadence
- T-48 hours: reminder #1 (if not already confirmed)
- T-24 hours: reminder #2
- T-2 hours: final reminder (optional, depends on workflow)

### Automation triggers
- Appointment created/updated → compute reminder schedule
- Appointment canceled/rescheduled → cancel pending reminders / create new ones
- Reply received (`Y/N`) → stop future reminders for that appointment

### Time zones
- Use `contact.timezone` and schedule sends at appropriate local times
- Avoid sending late-night/early-morning texts (configurable quiet hours)

---

## 6) Webhooks (Inbound + Status)

### Endpoints
- `POST /twilio/inbound`
  - Receives inbound SMS
  - Validates Twilio signature
  - Normalizes body to uppercase + trims
  - Routes:
    - `Y` → mark relevant `reminder_requests` as `yes`
    - `N` → mark as `no` + create reschedule task
    - else → gentle correction once

- `POST /twilio/status`
  - Receives outbound status updates
  - Updates `sms_messages.status`
  - If undelivered/failed → create CRM call task (fallback)

### Mapping inbound replies to the right appointment
**Preferred approach (v1):**
- Only treat `Y/N` as valid if there is exactly one **pending** `reminder_request` for that contact within a time window (e.g., last 14 days), otherwise:
  - reply with clarification link or
  - create staff follow-up task

**Stronger approach (v2):**
- include a short token in the message:
  - `Reply Y123 or N123`
- still looks like Y/N, but removes ambiguity when multiple appointments exist

---

## 7) Reliability & Safety

### Idempotency (must-have)
- Correlation ID per outbound reminder:
  - `f"{appointment_id}:{reminder_type}:{scheduled_at_iso}"`
- Before sending, check if a message with same correlation already exists; if yes, do not resend.

### Retries
- Retry transient failures (network/5xx) with exponential backoff
- Do not retry permanent failures (invalid number, opted out)
- Record failures and escalate to human workflow

### Consent gating
- Do not send reminders unless `sms_consent.status == opted_in`
- Respect STOP keywords:
  - Inbound `STOP` → set `opted_out` and cease all future sends

### Quiet hours
- Configurable “do not text” window (e.g., 9pm–8am local)
- Delay sends that fall in quiet hours

---

## 8) Implementation Plan (Phased)

### Phase 0 — Foundations (Fast)
- Twilio Messaging Service configured (sender number)
- Webhook endpoints deployed
- DB tables for messages + reminder requests
- Manual “Send reminder” action in CRM for testing

**Exit criteria**
- Can send a reminder and see inbound reply recorded

### Phase 1 — Y/N Workflow v1
- Create `reminder_requests` on appointment creation
- Scheduled jobs fire reminders at T-48/T-24/T-2
- Inbound parsing:
  - `Y` → mark confirmed + stop future reminders
  - `N` → create reschedule task + stop future reminders
  - invalid → one correction message + then escalate

**Exit criteria**
- End-to-end Y/N processing is automatic and auditable

### Phase 2 — Hardening & Scale
- Better disambiguation (tokened Y/N if needed)
- Metrics + alerts (undelivered spikes, opt-out spikes)
- Staff inbox view: “pending confirmations”, “needs reschedule”, “failed delivery”

---

## 9) Minimal Python Pseudocode (Illustrative)

### Outbound send
```python
def enqueue_reminder(appointment_id: str, reminder_type: str, scheduled_at):
    correlation_id = f"{appointment_id}:{reminder_type}:{scheduled_at.isoformat()}"
    # if exists in sms_messages by correlation_id: return
    # else push job to queue: send_reminder_job(...)
```

### Send job
```python
def send_reminder_job(appointment_id: str, reminder_type: str, correlation_id: str):
    appt = load_appointment(appointment_id)
    contact = load_contact(appt.contact_id)

    assert contact.consent == "opted_in"

    body = render_template(reminder_type, appt, contact)

    msg_id = create_sms_message_row(
        contact_id=contact.id,
        direction="outbound",
        status="queued",
        body=body,
        correlation_id=correlation_id,
        metadata={"appointment_id": appointment_id, "reminder_type": reminder_type},
    )

    twilio_sid = twilio_send_sms(
        to=contact.phone_e164,
        body=body,
        status_callback_url="/twilio/status",
    )

    mark_sms_message_sent(msg_id, twilio_sid)
    link_reminder_request_last_outbound(appointment_id, msg_id)
```

### Inbound webhook
```python
def inbound_webhook(request):
    verify_twilio_signature(request)

    from_phone = request.form["From"]
    body = request.form.get("Body", "").strip().upper()

    contact = find_or_create_contact_by_phone(from_phone)

    if body == "STOP":
        set_consent(contact.id, "opted_out", source="inbound_keyword")
        return "OK", 200

    if body not in ("Y", "N"):
        handle_invalid_reply(contact.id)
        return "OK", 200

    pending = find_pending_reminder_requests(contact.id)
    target = choose_target_request(pending)

    if not target:
        # no pending reminders; create staff task rather than guessing
        create_crm_task(contact.id, "Inbound Y/N but no pending reminder request.")
        return "OK", 200

    if body == "Y":
        mark_reminder_yes(target.id)
        mark_appointment_confirmed(target.appointment_id)
    else:
        mark_reminder_no(target.id)
        create_reschedule_task(target.appointment_id)

    return "OK", 200
```

---

## 10) Operational Dashboards (What You’ll Want Day 1)
- Pending confirmations (count, aging)
- Replies received (Y vs N)
- Undelivered/failed messages
- Opt-outs and STOP rate
- Average time-to-confirmation

---

## 11) Acceptance Criteria (v1)
- ✅ Reminders send on schedule with idempotency protections
- ✅ Replies `Y/N` correctly update appointment/task state
- ✅ Invalid replies handled safely (one correction + escalation)
- ✅ Full audit trail (who, what, when, delivery status, reply status)
- ✅ Opt-out respected and logged

---

## 12) Recommended Defaults (You Can Change Later)
- Reminders: 48h + 24h (+ optional 2h)
- Pending window: 14 days
- Invalid reply: 1 correction attempt, then human task
- Quiet hours: 9pm–8am contact local time
