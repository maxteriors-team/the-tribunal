import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  LightingProjectDetail,
  PaginatedLightingProjects,
} from "@/lib/api/lighting-projects";
import type { LandscapeDraft } from "@/lib/estimator/landscape-draft";

import { LightingProjectsPage } from "./lighting-projects-page";

const apiMocks = vi.hoisted(() => ({
  archive: vi.fn(),
  contactsList: vi.fn(),
  create: vi.fn(),
  list: vi.fn(),
}));
const draftMocks = vi.hoisted(() => ({
  deleteDraft: vi.fn(),
  loadDraft: vi.fn(),
}));
const routerPush = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/contacts", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/contacts")>();
  return {
    ...original,
    contactsApi: { ...original.contactsApi, list: apiMocks.contactsList },
  };
});

vi.mock("@/lib/api/lighting-projects", async (importOriginal) => {
  const original = await importOriginal<
    typeof import("@/lib/api/lighting-projects")
  >();
  return {
    ...original,
    lightingProjectsApi: {
      ...original.lightingProjectsApi,
      create: apiMocks.create,
      list: apiMocks.list,
      update: apiMocks.archive,
    },
  };
});

vi.mock("@/lib/estimator/landscape-draft", async (importOriginal) => {
  const original = await importOriginal<
    typeof import("@/lib/estimator/landscape-draft")
  >();
  return {
    ...original,
    deleteLandscapeDraft: draftMocks.deleteDraft,
    loadLandscapeDraft: draftMocks.loadDraft,
  };
});

const WORKSPACE_ID = "9029c83b-7a2a-44ce-b6b9-5567ac75cc3f";
const PROJECT_ID = "62774d85-6fb8-49ce-a348-e390972fa9d4";

const browserDraft: LandscapeDraft = {
  version: 2,
  activeShotId: "shot-1",
  shots: [
    {
      id: "shot-1",
      photo: {
        dataUrl: "data:image/png;base64,AAAA",
        width: 1000,
        height: 700,
      },
      design: { calibration: null, runs: [], items: [] },
      dusk: 0.35,
    },
  ],
  updatedAt: "2026-08-11T10:00:00.000Z",
};

function project(
  overrides: Partial<LightingProjectDetail> = {},
): LightingProjectDetail {
  return {
    id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    contact_id: 42,
    contact_name: "Pat Lee",
    service_location_id: null,
    opportunity_id: null,
    assigned_user_id: null,
    name: "Patio lighting",
    status: "active",
    version: 2,
    updated_by_id: 7,
    updater_name: "Morgan Manager",
    created_at: "2026-08-11T09:00:00.000Z",
    updated_at: "2026-08-11T10:00:00.000Z",
    created_by_id: 7,
    document: browserDraft,
    ...overrides,
  };
}

function page(items: LightingProjectDetail[] = []): PaginatedLightingProjects {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 100,
    pages: items.length ? 1 : 0,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return {
    ...render(<LightingProjectsPage workspaceId={WORKSPACE_ID} />, { wrapper }),
    queryClient,
  };
}

beforeEach(() => {
  apiMocks.list.mockReset();
  apiMocks.create.mockReset();
  apiMocks.archive.mockReset();
  apiMocks.contactsList.mockReset();
  draftMocks.loadDraft.mockReset();
  draftMocks.deleteDraft.mockReset();
  routerPush.mockReset();

  apiMocks.list.mockResolvedValue(page());
  apiMocks.contactsList.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, pages: 0 });
  draftMocks.loadDraft.mockResolvedValue(null);
  draftMocks.deleteDraft.mockResolvedValue(undefined);
});

/**
 * The customer field is a typeahead: focusing it opens the suggestion listbox,
 * and the customer is taken by clicking an option.
 */
async function pickCustomer(name: RegExp | string) {
  await userEvent.click(screen.getByLabelText("Customer"));
  await userEvent.click(await screen.findByRole("option", { name }));
}

describe("LightingProjectsPage", () => {
  it("renders loading, empty, error, and retry states", async () => {
    let resolveList: ((value: PaginatedLightingProjects) => void) | undefined;
    apiMocks.list.mockImplementationOnce(
      () =>
        new Promise<PaginatedLightingProjects>((resolve) => {
          resolveList = resolve;
        }),
    );
    const first = renderPage();
    expect(screen.getByText("Loading lighting projects...")).toBeInTheDocument();
    resolveList?.(page());
    await screen.findByRole("heading", { name: "No active lighting projects" });
    first.unmount();

    apiMocks.list.mockRejectedValueOnce(new Error("offline"));
    renderPage();
    expect(
      await screen.findByText("Lighting projects could not be loaded."),
    ).toBeInTheDocument();
    apiMocks.list.mockResolvedValueOnce(page());
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("heading", { name: "No active lighting projects" }),
    ).toBeInTheDocument();
  });

  it("lists customer identity and switches between active and archived filters", async () => {
    apiMocks.list.mockImplementation(
      (_workspaceId: string, params: { status?: string }) =>
        Promise.resolve(
          params.status === "archived"
            ? page([project({ status: "archived", name: "Pool terrace" })])
            : page([project()]),
        ),
    );
    renderPage();

    expect(await screen.findAllByText("Patio lighting")).not.toHaveLength(0);
    expect(screen.getAllByText("Pat Lee")).not.toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Archived" }));
    expect(await screen.findAllByText("Pool terrace")).not.toHaveLength(0);
    expect(apiMocks.list).toHaveBeenLastCalledWith(
      WORKSPACE_ID,
      expect.objectContaining({ status: "archived" }),
    );
  });

  it("creates a named project with a required searched customer", async () => {
    apiMocks.contactsList.mockResolvedValue({
      items: [
        {
          id: 42,
          first_name: "Pat",
          last_name: "Lee",
          email: "pat@example.com",
          company_name: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    });
    apiMocks.create.mockResolvedValue(project({ name: "Front walk" }));
    renderPage();

    await userEvent.click(
      screen.getAllByRole("button", { name: "New lighting project" })[0],
    );
    await userEvent.type(screen.getByLabelText("Project name"), "Front walk");
    await pickCustomer(/Pat Lee/);
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() =>
      expect(apiMocks.create).toHaveBeenCalledWith(WORKSPACE_ID, {
        contact_id: 42,
        name: "Front walk",
      }),
    );
    expect(routerPush).toHaveBeenCalledWith(
      `/landscape-lighting/${PROJECT_ID}`,
    );
  });

  it("recovers the browser draft and deletes it only after server creation succeeds", async () => {
    draftMocks.loadDraft.mockResolvedValue(browserDraft);
    apiMocks.contactsList.mockResolvedValue({
      items: [{ id: 42, first_name: "Pat", last_name: "Lee", email: null }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    });
    apiMocks.create.mockImplementation(async () => {
      expect(draftMocks.deleteDraft).not.toHaveBeenCalled();
      return project({ name: "Recovered landscape lighting plan" });
    });
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Recover browser draft" }),
    );
    await pickCustomer(/Pat Lee/);
    await userEvent.click(screen.getByRole("button", { name: "Recover project" }));

    await waitFor(() => expect(draftMocks.deleteDraft).toHaveBeenCalledWith(WORKSPACE_ID));
    expect(apiMocks.create).toHaveBeenCalledWith(
      WORKSPACE_ID,
      expect.objectContaining({
        contact_id: 42,
        document: browserDraft,
      }),
    );
  });

  it("never deletes a recovery draft when project creation fails and can archive a row", async () => {
    draftMocks.loadDraft.mockResolvedValue(browserDraft);
    apiMocks.contactsList.mockResolvedValue({
      items: [{ id: 42, first_name: "Pat", last_name: "Lee", email: null }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    });
    apiMocks.list.mockResolvedValue(page([project()]));
    apiMocks.create.mockRejectedValue(new Error("server unavailable"));
    apiMocks.archive.mockResolvedValue(project({ status: "archived", version: 2 }));
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Recover browser draft" }),
    );
    await pickCustomer(/Pat Lee/);
    await userEvent.click(screen.getByRole("button", { name: "Recover project" }));
    await screen.findByRole("alert");
    expect(draftMocks.deleteDraft).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await userEvent.click(screen.getAllByRole("button", { name: "Archive" })[0]);
    await waitFor(() =>
      expect(apiMocks.archive).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID, {
        expected_version: 2,
        status: "archived",
      }),
    );
  });
});
