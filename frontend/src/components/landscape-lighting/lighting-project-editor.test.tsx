import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LandscapeProjectPersistenceAdapter } from "@/components/estimator/light-designer";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { LightingProjectDetail } from "@/lib/api/lighting-projects";

import { LightingProjectEditor } from "./lighting-project-editor";

const apiMocks = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
}));
const draftMocks = vi.hoisted(() => ({
  deletePending: vi.fn(),
  loadPending: vi.fn(),
  savePending: vi.fn(),
}));
const designerProps = vi.hoisted(() => vi.fn());
const routerPush = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({
    currentWorkspaceId: "9029c83b-7a2a-44ce-b6b9-5567ac75cc3f",
    currentWorkspace: {
      workspace: {
        name: "Northstar Workspace",
        settings: {
          proposal_template: {
            business_name: "Northstar Outdoor Lighting",
            logo_url: "https://northstar.example/logo.svg",
          },
        },
      },
    },
    isPending: false,
  }),
}));

vi.mock("@/components/estimator/light-designer", () => ({
  LightDesigner: (props: { landscapeProject: LandscapeProjectPersistenceAdapter }) => {
    designerProps(props);
    return (
      <div data-testid="light-designer">
        {props.landscapeProject.initialDraft.activeShotId ?? "empty"}
      </div>
    );
  },
}));

vi.mock("@/lib/api/lighting-projects", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/lighting-projects")>();
  return {
    ...original,
    lightingProjectsApi: apiMocks,
  };
});

vi.mock("@/lib/estimator/landscape-draft", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/estimator/landscape-draft")>();
  return {
    ...original,
    deletePendingLandscapeDraft: draftMocks.deletePending,
    loadPendingLandscapeDraft: draftMocks.loadPending,
    savePendingLandscapeDraft: draftMocks.savePending,
  };
});

const WORKSPACE_ID = "9029c83b-7a2a-44ce-b6b9-5567ac75cc3f";
const PROJECT_ID = "62774d85-6fb8-49ce-a348-e390972fa9d4";

function project(overrides: Partial<LightingProjectDetail> = {}): LightingProjectDetail {
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
    version: 1,
    updated_by_id: 7,
    updater_name: "Morgan Manager",
    created_at: "2026-08-11T09:00:00.000Z",
    updated_at: "2026-08-11T10:00:00.000Z",
    created_by_id: 7,
    document: {
      version: 2,
      activeShotId: "shot-1",
      shots: [
        {
          id: "shot-1",
          photo: {
            dataUrl: "data:image/png;base64,AAAA",
            width: 1200,
            height: 800,
          },
          design: { calibration: null, runs: [], items: [] },
          dusk: 0.4,
        },
      ],
      updatedAt: "2026-08-11T10:00:00.000Z",
    },
    ...overrides,
  };
}

function renderEditor() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client },
      createElement(SidebarProvider, { defaultOpen: false }, children),
    );
  return render(<LightingProjectEditor projectId={PROJECT_ID} />, { wrapper });
}

beforeEach(() => {
  apiMocks.get.mockReset();
  apiMocks.update.mockReset();
  apiMocks.create.mockReset();
  draftMocks.loadPending.mockReset();
  draftMocks.savePending.mockReset();
  draftMocks.deletePending.mockReset();
  designerProps.mockReset();
  routerPush.mockReset();
  draftMocks.loadPending.mockResolvedValue(null);
  draftMocks.savePending.mockResolvedValue(undefined);
  draftMocks.deletePending.mockResolvedValue(undefined);
});

describe("LightingProjectEditor", () => {
  it("loads the server project before mounting LightDesigner with its authoritative draft", async () => {
    apiMocks.get.mockResolvedValue(project());
    renderEditor();

    expect(screen.getByText("Loading the lighting project...")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Patio lighting")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.queryByText(/Pat Lee/)).not.toBeInTheDocument();
    expect(await screen.findByTestId("light-designer")).toHaveTextContent("shot-1");
    expect(designerProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        workspaceId: WORKSPACE_ID,
        workspaceName: "Northstar Outdoor Lighting",
        workspaceLogoUrl: "https://northstar.example/logo.svg",
        focus: "landscape",
        landscapeProject: expect.objectContaining({
          initialDraft: expect.objectContaining({ activeShotId: "shot-1" }),
          persistenceStatus: expect.objectContaining({
            label: "Saved to Tribunal",
          }),
        }),
      }),
    );
  });

  it("shows not-found and retry states without mounting the drawing editor", async () => {
    apiMocks.get.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404 },
    });
    renderEditor();

    expect(
      await screen.findByText("This lighting project was not found in the selected workspace."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("light-designer")).not.toBeInTheDocument();
  });

  it("opens an accessible conflict dialog for a stale device draft and loads Tribunal safely", async () => {
    const current = project({ version: 2 });
    apiMocks.get.mockResolvedValue(current);
    draftMocks.loadPending.mockResolvedValue({
      projectId: PROJECT_ID,
      baseServerVersion: 1,
      draft: {
        version: 2,
        activeShotId: null,
        shots: [],
        updatedAt: "2026-08-11T10:05:00.000Z",
      },
      dirty: true,
      localUpdatedAt: "2026-08-11T10:05:00.000Z",
    });
    renderEditor();

    expect(
      await screen.findByRole("dialog", { name: "Choose which lighting plan to keep" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load Tribunal version" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save my work as a copy" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load Tribunal version" }));
    await waitFor(() => expect(draftMocks.deletePending).toHaveBeenCalledWith(PROJECT_ID));
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Choose which lighting plan to keep" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps an archived project read only", async () => {
    apiMocks.get.mockResolvedValue(project({ status: "archived" }));
    renderEditor();

    expect(
      await screen.findByRole("heading", { name: "Archived project is read only" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("light-designer")).not.toBeInTheDocument();
    await waitFor(() => expect(apiMocks.get).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID));
  });
});
