"""Google Calendar integration package.

Modules:
- ``oauth`` — per-workspace OAuth2 connect/callback + token refresh.
- ``client`` — Google Calendar API calls (events + free/busy).
- ``availability`` — local slot engine (weekly hours + free/busy -> slots).
- ``provider`` — ``GoogleCalendarProvider`` implementing ``CalendarProvider``.
"""
