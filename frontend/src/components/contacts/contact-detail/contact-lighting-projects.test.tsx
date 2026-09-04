import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContactLightingProjects } from "./contact-lighting-projects";

const { createMock, listMock, pushMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  listMock: vi.fn(),
  pushMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/api/lighting-projects", () => ({
  lightingProjectsApi: {
    create: createMock,
    list: listMock,
  },
}));

function renderProjects() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContactLightingProjects workspaceId="ws_1" contactId={42} contactName="Pat Lee" canCreate />
    </QueryClientProvider>,
  );
}

describe("ContactLightingProjects", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMock.mockResolvedValue({
      items: [{ id: "project-1", name: "Pat roofline", status: "active" }],
      total: 1,
      page: 1,
      page_size: 10,
      pages: 1,
    });
    createMock.mockResolvedValue({ id: "project-2" });
  });

  it("lists this customer's designs and creates a linked permanent project", async () => {
    renderProjects();

    expect(await screen.findByRole("link", { name: /Pat roofline/ })).toHaveAttribute(
      "href",
      "/permanent-lighting/project-1",
    );
    expect(listMock).toHaveBeenCalledWith("ws_1", {
      contact_id: 42,
      project_type: "permanent",
      page_size: 10,
    });

    fireEvent.click(screen.getByRole("button", { name: "New design" }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith("ws_1", {
        contact_id: 42,
        name: "Pat Lee permanent lighting",
        project_type: "permanent",
      }),
    );
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/permanent-lighting/project-2"));
  });
});
