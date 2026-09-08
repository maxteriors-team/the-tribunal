"""Responses shared by manual calendar reminder operations."""

from pydantic import BaseModel


class CustomerReminderResponse(BaseModel):
    """Result of attempting to send a stock customer reminder."""

    success: bool
    message: str
    sent_to: str | None = None
    already_sent: bool = False
