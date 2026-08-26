import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LandscapeProjectPersistenceAdapter } from "@/components/estimator/light-designer";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { LightingProjectDetail } from "@/lib/api/lighting-projects";
import type { LandscapeDraft } from "@/lib/estimator/landscape-draft";

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

function projectDraft(
  activeShotId = "shot-1",
  dusk = 0.4,
  includeFixture = false,
  projectType: LandscapeDraft["projectType"] = "landscape",
): LandscapeDraft {
  return {
    version: 2,
    projectType,
    activeShotId,
    shots: [
      {
        id: activeShotId,
        photo: {
          dataUrl: "data:image/png;base64,AAAA",
          width: 1200,
          height: 800,
        },
        design: {
          calibration: null,
          runs: [],
          items: includeFixture
            ? [
                {
                  id: "saved-uplight",
                  productId: "fixture-uplight",
                  at: { x: 160, y: 240 },
                  sizePx: 30,
                },
              ]
            : [],
        },
        dusk,
      },
    ],
    updatedAt: "2026-08-11T10:00:00.000Z",
  };
}

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
    project_type: "landscape",
    status: "active",
    version: 1,
    updated_by_id: 7,
    updater_name: "Morgan Manager",
    created_at: "2026-08-11T09:00:00.000Z",
    updated_at: "2026-08-11T10:00:00.000Z",
    created_by_id: 7,
    document: projectDraft(),
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
    expect(screen.getByRole("button", { name: "Proposal & payment" })).toHaveAttribute(
      "title",
      "Set the deposit, preview the client payment page, and send the proposal",
    );
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

  it("saves, reopens by project ID from persistence, edits, and saves again", async () => {
    let persistedProject = project();
    apiMocks.get.mockImplementation(async () => persistedProject);
    apiMocks.update.mockImplementation(async (_workspaceId, _projectId, update) => {
      persistedProject = {
        ...persistedProject,
        version: persistedProject.version + 1,
        document: update.document ?? persistedProject.document,
      };
      return persistedProject;
    });

    const firstEdit: LandscapeDraft = {
      ...projectDraft("saved-shot", 0.4, true),
      updatedAt: "2026-08-11T10:05:00.000Z",
    };
    const firstRender = renderEditor();
    expect(await screen.findByTestId("light-designer")).toHaveTextContent("shot-1");

    act(() => {
      const persistence = designerProps.mock.lastCall?.[0]
        .landscapeProject as LandscapeProjectPersistenceAdapter;
      persistence.onLandscapeDraftChange(firstEdit, { immediate: true });
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("Saved to Tribunal")).toBeInTheDocument());
    expect(apiMocks.update).toHaveBeenLastCalledWith(WORKSPACE_ID, PROJECT_ID, {
      expected_version: 1,
      document: firstEdit,
    });
    firstRender.unmount();

    renderEditor();
    expect(await screen.findByTestId("light-designer")).toHaveTextContent("saved-shot");
    expect(apiMocks.get).toHaveBeenCalledTimes(2);
    expect(apiMocks.get).toHaveBeenLastCalledWith(WORKSPACE_ID, PROJECT_ID);
    const reopenedPersistence = designerProps.mock.lastCall?.[0]
      .landscapeProject as LandscapeProjectPersistenceAdapter;
    expect(reopenedPersistence.initialDraft.shots[0].design.items).toEqual([
      expect.objectContaining({ id: "saved-uplight", productId: "fixture-uplight" }),
    ]);

    const secondEdit: LandscapeDraft = {
      ...projectDraft("edited-after-reopen", 0.65, true),
      updatedAt: "2026-08-11T10:10:00.000Z",
    };
    act(() => {
      reopenedPersistence.onLandscapeDraftChange(secondEdit, { immediate: true });
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(2));
    expect(apiMocks.update).toHaveBeenLastCalledWith(WORKSPACE_ID, PROJECT_ID, {
      expected_version: 2,
      document: secondEdit,
    });
    expect(persistedProject).toMatchObject({
      id: PROJECT_ID,
      version: 3,
      document: {
        activeShotId: "edited-after-reopen",
        shots: [{ dusk: 0.65 }],
      },
    });
  });

  it("keeps a client-linked permanent design editable after save and reopen", async () => {
    let persistedProject = project({
      name: "Pat permanent roofline",
      project_type: "permanent",
      document: projectDraft("permanent-shot", 0.4, true, "permanent"),
    });
    apiMocks.get.mockImplementation(async () => persistedProject);
    apiMocks.update.mockImplementation(async (_workspaceId, _projectId, update) => {
      persistedProject = {
        ...persistedProject,
        version: persistedProject.version + 1,
        document: update.document ?? persistedProject.document,
      };
      return persistedProject;
    });

    const firstRender = renderEditor();
    expect(await screen.findByTestId("light-designer")).toHaveTextContent("permanent-shot");
    expect(designerProps.mock.lastCall?.[0]).toEqual(
      expect.objectContaining({
        focus: "permanent",
        landscapeProject: expect.objectContaining({ contactId: 42 }),
      }),
    );
    expect(screen.queryByRole("button", { name: "Proposal & payment" })).not.toBeInTheDocument();

    const savedEdit = projectDraft("saved-permanent-shot", 0.5, true, "permanent");
    act(() => {
      const persistence = designerProps.mock.lastCall?.[0]
        .landscapeProject as LandscapeProjectPersistenceAdapter;
      persistence.onLandscapeDraftChange(savedEdit, { immediate: true });
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(1));
    firstRender.unmount();

    renderEditor();
    expect(await screen.findByTestId("light-designer")).toHaveTextContent("saved-permanent-shot");
    const reopenedPersistence = designerProps.mock.lastCall?.[0]
      .landscapeProject as LandscapeProjectPersistenceAdapter;
    expect(reopenedPersistence.initialDraft).toMatchObject({
      projectType: "permanent",
      activeShotId: "saved-permanent-shot",
    });

    const secondEdit = projectDraft("edited-permanent-shot", 0.65, true, "permanent");
    act(() => reopenedPersistence.onLandscapeDraftChange(secondEdit, { immediate: true }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(2));
    expect(apiMocks.update).toHaveBeenLastCalledWith(WORKSPACE_ID, PROJECT_ID, {
      expected_version: 2,
      document: secondEdit,
    });
    expect(persistedProject).toMatchObject({
      contact_id: 42,
      project_type: "permanent",
      version: 3,
      document: { projectType: "permanent", activeShotId: "edited-permanent-shot" },
    });
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
