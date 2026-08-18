# RE Voice — Voice-First, WhatsApp-Centric Real Estate CRM

A channel + intelligence layer for the Kreatao RE platform. Requires `re_core` and
`re_crm`; every command resolves to an operation on a DocType those apps already own.
Disable it and the platform still works from the desk — voice is an accelerator, never
the only path.

## Architecture

```
inbound webhook (signature-verified, ACK <5s, deduped)
      └─ background worker
            ├─ sender is an active, voice-enabled RE Agent ──► AGENT PIPELINE
            │     audio → ASR → transcript/translation
            │     → Tier-1 keyword matcher (free, ~ms)
            │     → Tier-2 LLM function-calling (fallback)
            │     → entity extraction (locale-aware)
            │     → confirmation tap for destructive intents
            │     → execute as frappe.set_user(agent.user)
            └─ anyone else ──────────────────────────────────► CUSTOMER PIPELINE
                  auto-reply with matching listings + visit prompt
                  post-visit feedback list → Site Visit outcome + Deal stage
```

The two pipelines never cross. A number that does not match an agent cannot reach a
command handler — that separation is the app's main security property.

## What's included

- **15 DocTypes**: Voice Command registry (+ Command Entity), Voice Intent, Voice
  Message, Conversation Session, Customer Thread (+ Thread Message), WhatsApp Webhook
  Log, WhatsApp Template, Lead Score Model/Log, Sentiment Reading, Voice Locale Profile,
  AI Settings, Voice Usage Log
- **24 seeded voice commands** across lead lifecycle, scheduling, content, and queries
- **Two-tier intent engine** — deterministic matcher plus LLM fallback, both reading the
  same registry, so adding a command is a data change not a deploy
- **Locale-aware entity extraction** — lakh/crore vs thousand, BHK vs BR, spoken
  date/times, money in words ("forty five lakhs" → 4,500,000)
- **ASR + translation** preserving all four layers: original audio → native transcript →
  English translation → CRM note
- **Transparent lead scoring** — five weighted signals, every score persisting its
  components and a plain-language reason
- **Sentiment, conversation summaries, explainable property matching**
- **Voice Command Analytics** report + Voice CRM workspace

## Install

```bash
bench get-app /path/to/re_voice
bench --site yoursite.local install-app re_voice
bench --site yoursite.local migrate
```

Add to `site_config.json` (required — the webhook fails closed without the secret):

```json
{
  "whatsapp_app_secret": "<Meta app secret>",
  "whatsapp_verify_token": "<any long random string>"
}
```

Register the callback URL with Meta:

```
https://yoursite/api/method/re_voice.api.webhook.receive
```

Then: **AI Settings** (enable voice, pick ASR/LLM providers, set the monthly budget and
audio retention), **Voice Locale Profile** (two are seeded — GCC and India), and on each
**RE Agent** set the WhatsApp number and tick *Voice Commands Enabled*.

## Operating notes

- **The 24-hour window is enforced, not assumed.** Free-form outbound is refused outside
  Meta's customer service window; `send_template()` is the only path after it closes.
  Register post-visit and follow-up templates in **WhatsApp Template** and get them
  approved before relying on those flows.
- **Interactive limits are real**: 3 buttons max, 10 list rows, 24-char list titles. The
  post-visit feedback prompt has four options, so it ships as a list message.
- **Destructive commands require a Confirm tap** (Mark Lost/Won, Close, Assign,
  Transfer, Cancel Visit, Generate Quotation/Booking Form). ASR mishears names and
  numbers; this is the guard that keeps the pipeline clean.
- **Graceful degradation**: over budget, LLM disabled, or provider down → Tier-1
  commands keep working. Every AI call returns None rather than raising.
- **Privacy**: customers get a one-time consent notice and STOP support; audio is purged
  on a retention timer while transcripts are kept.

## Regenerating DocType JSONs

```bash
python3 scripts/generate_doctypes.py
```

## Tests

```bash
python3 scripts/test_logic.py
```
Covers the frappe-free layers: money/range/unit-type/datetime/phone/name extraction and
the Tier-1 matcher, including ambiguity and locale behaviour.
