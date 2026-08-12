# Maintaining CRM product help

`docs/help/*.md` is the deployed source of truth for CRM Assistant product questions. `search_help` reads and ranks those files directly, so an article change becomes live with the backend deployment; no database seed or embedding job is required.

When a user-facing screen or workflow changes:

1. Update the matching article in `docs/help/` in the same pull request.
2. Preserve the exact UI label and route shown by the frontend.
3. Explain only supported actions and call out role, status, or integration limits.
4. Add or update a representative retrieval assertion in `tests/services/knowledge/test_product_help.py`.
5. Run `uv run pytest tests/services/knowledge/test_product_help.py tests/test_crm_assistant_help_tool.py -q`.

`screen-reference.md` is the compact route inventory. Coverage tests compare the corpus with every production `frontend/src/app/**/page.tsx` route, plus the exact labels and routes in `frontend/src/components/layout/app-nav.ts` and every addressable Settings tab. Adding or renaming a user-facing screen without help coverage fails CI.

`scripts/seeds/seed_product_help.py` is optional compatibility tooling for consumers of the hybrid knowledge index. CRM Assistant answers do not depend on those seeded rows.
