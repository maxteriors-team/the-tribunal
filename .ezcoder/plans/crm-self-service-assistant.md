# CRM Self-Service Assistant

Implement directly by grounding the existing assistant in the CRM’s actual routes, labels, and supported workflows, then verify representative how-to questions end to end.

## Steps
1. Inspect the existing assistant, CRM navigation, API contracts, and tests.
2. Add a maintainable CRM help knowledge source covering every user-facing workflow and screen.
3. Ground assistant responses in that source and require clear, route-accurate step-by-step instructions.
4. Add fallback and source-maintenance behavior so unsupported questions are handled honestly.
5. Add and run focused tests for invoicing and representative CRM usage questions.
