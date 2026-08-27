"""Provider-neutral inbound text persistence contracts."""

from dataclasses import dataclass

from app.models.conversation import Message


@dataclass(slots=True, frozen=True)
class InboundMessageIngestResult:
    """Persisted message plus whether this delivery created it."""

    message: Message
    created: bool
