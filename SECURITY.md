# Security Policy

We take the security of The Tribunal (AI CRM) seriously. This document describes how to report vulnerabilities and what to expect from our response process.

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

Please report suspected vulnerabilities through one of the following channels:

- **GitHub Security Advisory** (preferred): [Report a vulnerability](https://github.com/Gahroot/aicrm/security/advisories/new)
- **Email**: security@thetribunal.ai

When reporting, please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept code, request payloads, screenshots)
- Affected version, commit SHA, or deployment URL
- Any suggested remediation, if known

Please give us reasonable time to investigate and remediate before public disclosure. We support coordinated disclosure and will credit reporters who wish to be acknowledged.

## Response SLA

We aim to meet the following response times for valid reports:

| Stage                         | Target                  |
| ----------------------------- | ----------------------- |
| Initial acknowledgement       | Within **2 business days** |
| Triage and severity assessment | Within **5 business days** |
| Status update cadence         | At least **weekly** until resolved |
| Fix for **Critical** issues   | Within **7 days** of triage |
| Fix for **High** issues       | Within **30 days** of triage |
| Fix for **Medium/Low** issues | Within **90 days** of triage |

Severity follows [CVSS v3.1](https://www.first.org/cvss/v3-1/) scoring.

## Supported Versions

The Tribunal is deployed as a continuously delivered SaaS product from the `main` branch. We provide security fixes for the following:

| Version            | Supported          |
| ------------------ | ------------------ |
| `main` (production) | ✅ Yes             |
| Tagged releases within the last 90 days | ✅ Yes |
| Older tagged releases | ❌ No — upgrade required |
| Forks and self-hosted modifications | ❌ Not covered |

Customers running self-hosted deployments should track `main` and apply migrations promptly.

## Scope

In scope:

- The backend API (`backend/`) and its services, workers, and webhooks
- The frontend application (`frontend/`) and the embeddable widget
- Authentication, authorization, multi-tenant isolation, and data handling
- Third-party integrations as configured in this repository (Telnyx, Cal.com, OpenAI, ElevenLabs, SendGrid)

Out of scope:

- Denial-of-service via volumetric traffic
- Social engineering of staff or customers
- Vulnerabilities in third-party services themselves (report to the vendor)
- Findings from automated scanners without a working proof-of-concept

## Safe Harbor

We will not pursue legal action against researchers who:

- Make a good-faith effort to comply with this policy
- Avoid privacy violations, data destruction, and service degradation
- Do not exfiltrate data beyond the minimum required to demonstrate the issue
- Give us reasonable time to remediate before public disclosure
