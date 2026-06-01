# The Tribunal — Frontend

Next.js 16 dashboard for The Tribunal AI CRM. Provides the operator UI for managing leads, AI voice agents, SMS campaigns, calendars, and human-in-the-loop approval gates. Talks to the FastAPI backend over REST and websockets.

## Tech

- **Next.js 16** (App Router) + **React 19** + **TypeScript 5** (strict)
- **TailwindCSS 4** + **shadcn/ui** (Radix primitives)
- **React Query 5** for server state, **Zustand 5** for client state
- **Zod 4** for validation, **react-hook-form** for forms
- **Vitest** + Testing Library for unit tests

## Prerequisites

- **Node.js 20.18.0** — pinned in [`.nvmrc`](./.nvmrc). With `nvm`:
  ```bash
  nvm use
  ```
- **npm** (ships with Node)
- A running backend at `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`)

## Setup

```bash
cd frontend
nvm use
npm ci
cp .env.example .env.local   # if present; otherwise create .env.local (see below)
npm run dev
```

The dev server runs on http://localhost:3000.

## Available Scripts

| Script                  | What it does                                                       |
| ----------------------- | ------------------------------------------------------------------ |
| `npm run dev`           | Start the Next.js dev server on :3000                              |
| `npm run build`         | Production build                                                   |
| `npm run start`         | Serve the production build                                         |
| `npm run lint`          | Run ESLint (`eslint-config-next`)                                  |
| `npm run test`          | Run the Vitest suite once                                          |
| `npm run test:watch`    | Vitest in watch mode                                               |
| `npm run test:coverage` | Vitest with coverage report                                        |
| `npm run codegen`       | Regenerate `src/lib/api/_generated.ts` from `backend/openapi.json` |
| `npx tsc --noEmit`      | Type-check without emitting (no dedicated script)                  |

> Type checking and formatting are not separate scripts today — `npm run build` enforces types, and ESLint covers stylistic rules.

## OpenAPI-Typed API Client

The frontend talks to the backend through a thin axios wrapper that derives request and response types directly from the backend's OpenAPI schema. This means a backend route rename, query-param change, or schema tweak surfaces as a frontend type error at build time — no more drift between hand-rolled interfaces and the real wire contract.

### Files

- **`backend/openapi.json`** — source of truth. Exported by `make codegen`. CI runs `make codegen/check` and fails if it drifts from the live FastAPI routers.
- **`src/lib/api/_generated.ts`** — generated TypeScript types (`paths`, `components`, `operations`). Produced by `openapi-typescript`. **Do not edit by hand.** It's git-tracked so reviewers see API surface changes in the diff, and ESLint ignores it.
- **`src/lib/api/_client.ts`** — the typed axios wrapper. Re-exports `Paths`, `Components`, `Schemas`, and helper types (`ResponseOf`, `PathParamsOf`, `QueryParamsOf`, `RequestBodyOf`). Exposes `apiClient.get/post/put/patch/del` whose URL argument is constrained to spec paths that actually expose that verb.
- **`src/lib/api/contacts.ts`** — proof-of-concept resource client using `apiClient`. Other resource modules under `src/lib/api/` will migrate incrementally.

### Regenerating types after a backend change

```bash
make codegen          # refresh openapi.json and regenerate _generated.ts
make codegen/check    # rerun generation and fail if committed artifacts drift
cd frontend && npm run typecheck  # catch any consumer breakage
```

Commit both `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together with the backend change.

### Using `apiClient` in a resource module

```ts
import { apiClient, type Schemas } from "@/lib/api/_client";

export type ContactListResponse = Schemas["ContactListResponse"];

export async function listContacts(workspaceId: string, page = 1) {
  // URL, path params, query params, and the return type are all checked
  // against the spec. A typo in the URL or a removed query param fails to compile.
  return apiClient.get("/api/v1/workspaces/{workspace_id}/contacts", {
    path: { workspace_id: workspaceId },
    query: { page, page_size: 50 },
  });
}
```

For `multipart/form-data` endpoints (which the JSON-typed `body` slot can't express), pass the `FormData` through `config.data`:

```ts
apiClient.post("/api/v1/workspaces/{workspace_id}/contacts/import", {
  path: { workspace_id: workspaceId },
  config: { data: formData, headers: { "Content-Type": "multipart/form-data" } },
});
```

## Environment Variables

Create `frontend/.env.local`. Only `NEXT_PUBLIC_*` vars are exposed to the browser.

| Variable                 | Required   | Default                 | Purpose                                                                  |
| ------------------------ | ---------- | ----------------------- | ------------------------------------------------------------------------ |
| `NEXT_PUBLIC_API_URL`    | yes (prod) | `http://localhost:8000` | Base URL for the FastAPI backend; also used to derive the websocket host |
| `NEXT_PUBLIC_PLAN_PRICE` | no         | `$297/month`            | Plan price shown on billing/onboarding surfaces                          |

Example `.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_PLAN_PRICE=$297/month
```

## Project Structure

```
src/
  app/            # Next.js App Router pages (route groups per feature: agents,
                  # campaigns, contacts, calls, dashboard, settings, offers, etc.)
  components/     # React components, one per file, grouped by feature.
                  # `components/ui/` holds shadcn primitives.
  lib/            # Framework-agnostic code:
                  #   api/         — one client module per backend resource
                  #   api.ts       — axios wrapper
                  #   query-keys.ts, query-options.ts — React Query helpers
                  #   utils/       — small utilities
                  #   contact-store.ts — Zustand store
  hooks/          # Custom React hooks (useContacts, useWizard, etc.)
  providers/      # App-level providers (auth, workspace, React Query)
  types/          # Shared TypeScript types
  widget/         # Embeddable chat widget bundle
  test/           # Vitest setup and shared test helpers
```

See the root [`CLAUDE.md`](../CLAUDE.md) for organization rules and shared primitives (`PageLoadingState`, query-key factory, etc.). In dev, visit <http://localhost:3000/dev/components> for a living style guide that renders every `@/components/ui/*` primitive — including `PageLoadingState`, `PageErrorState`, and `PageEmptyState` — side-by-side with canonical usage. Reach for these before rolling a new spinner, error screen, or empty state by hand. The route is gated to `NODE_ENV !== "production"` and is unreachable on deployed builds.

## Deployment

Deployed on **Vercel**.

- **Root Directory:** `frontend`
- **Install Command:** `npm ci`
- **Build Command:** `npm run build`
- **Output:** managed by Vercel's Next.js integration (no override needed)
- **Node version:** 20.x (matches `.nvmrc` / `engines.node`)
- **Environment variables:** set `NEXT_PUBLIC_API_URL` (and optionally `NEXT_PUBLIC_PLAN_PRICE`) per environment (Production / Preview / Development) in the Vercel dashboard.

Preview deployments are created automatically for pull requests.

## Contributing

See the repository-level [CONTRIBUTING.md](../CONTRIBUTING.md) for branch conventions, commit style, and the required `npm run lint && npm run build` gate before opening a PR.
