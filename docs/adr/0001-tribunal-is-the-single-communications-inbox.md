# ADR 0001: Tribunal is the single communications inbox

## Context

Quo currently supplies selected-line SMS history and transport, while Tribunal supports Telnyx-based calling. Moving staff workflow and phone transport simultaneously would increase delivery, attribution, and number-porting risk.

## Decision

Move staff workflow first: every customer text and call is handled inside Tribunal. Keep Quo as a manual, text-only migration bridge while Tribunal calling uses a voice-enabled Telnyx number. Port the customer-facing Quo number only after separate text and call pilots complete 14 consecutive days without missing or duplicate messages, with complete new-message attribution and reliable call handling.

## Rejected alternative

An immediate Quo shutdown and number port was rejected because it combines workflow, transport, and phone-number cutovers without evidence that Tribunal handles production communication reliably.
