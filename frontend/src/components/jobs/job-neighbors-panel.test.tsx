import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobNeighborsPanel } from "@/components/jobs/job-neighbors-panel";
import type { NeighborBatch, NeighborEntry } from "@/lib/api/jobs";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import { selectOption } from "@/test/select-option";

/**
 * The "Neighbors" tab on a completed job.
 *
 * The rules that matter here are legal, not cosmetic: a neighbour who is not a
 * consented contact must never be shown a messaging affordance, and the panel
 * must treat "no list generated yet" (a 404) as an empty state rather than an
 * error. The export is built in the browser because the rows are customer PII.
 */

const { neighborsMock, generateMock, updateEntryMock, exportMock, capabilitiesMock } = vi.hoisted(
  () => ({
    neighborsMock: vi.fn(),
    generateMock: vi.fn(),
    updateEntryMock: vi.fn(),
    exportMock: vi.fn(),
    capabilitiesMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/jobs", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/jobs")>("@/lib/api/jobs");
  return {
    ...actual,
    jobsApi: {
      ...actual.jobsApi,
      neighbors: neighborsMock,
      generateNeighbors: generateMock,
      updateNeighborEntry: updateEntryMock,
      neighborsExport: exportMock,
    },
  };
});

// Capabilities need a workspace provider; drive them from a role string through
// the real permission matrix instead, so the matrix and this gate stay in sync.
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

function notFound() {
  return Object.assign(new Error("Not found"), { response: { status: 404 } });
}

function entry(overrides: Partial<NeighborEntry> = {}): NeighborEntry {
  return {
    id: "entry-1",
    service_location_id: "loc-1",
    contact_id: 42,
    distance_meters: 59.9,
    status: "pending",
    channel: "print",
    messaging_blocked_reason: "missing_sms_consent",
    contacted_at: null,
    status_changed_at: null,
    notes: null,
    created_at: "2026-07-20T18:00:00.000Z",
    label: "102 Oak",
    customer_name: "Dana Ruiz",
    messageable: false,
    ...overrides,
  };
}

function batch(entries: NeighborEntry[]): NeighborBatch {
  return {
    id: "batch-1",
    job_id: "job-1",
    origin_location_id: "loc-origin",
    origin_latitude: 44.9778,
    origin_longitude: -93.265,
    radius_meters: 150,
    generated_at: "2026-07-20T18:00:00.000Z",
    created_at: "2026-07-20T18:00:00.000Z",
    entries,
    total: entries.length,
    pending_count: entries.filter((item) => item.status === "pending").length,
    messageable_count: entries.filter((item) => item.messageable).length,
  };
}

function renderPanel(props: { readOnly?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobNeighborsPanel workspaceId="ws-1" jobId="job-1" {...props} />
    </QueryClientProvider>,
  );
}

describe("JobNeighborsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signedInAs("dispatcher");
  });

  it("treats a 404 as 'not generated yet', not a failure", async () => {
    neighborsMock.mockRejectedValue(notFound());
    renderPanel();

    expect(await screen.findByText("No neighbor list yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Find neighbors/i })).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load/i)).not.toBeInTheDocument();
  });

  it("surfaces a real failure as an error, not an empty state", async () => {
    neighborsMock.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );
    renderPanel();

    // A non-404 gets one retry with backoff before it settles into the error
    // state, so this needs longer than the 1s default.
    expect(
      await screen.findByText(/Failed to load neighbors/i, undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Find neighbors/i })).not.toBeInTheDocument();
  });

  it("lists neighbours with their distance and how far the search reached", async () => {
    neighborsMock.mockResolvedValue(
      batch([
        entry(),
        entry({
          id: "entry-2",
          label: "106 Oak",
          customer_name: "Sam Okonkwo",
          distance_meters: 119.9,
        }),
      ]),
    );
    renderPanel();

    expect(await screen.findByText("Dana Ruiz")).toBeInTheDocument();
    expect(screen.getByText("Sam Okonkwo")).toBeInTheDocument();
    expect(screen.getByText("60 m")).toBeInTheDocument();
    expect(screen.getByText("120 m")).toBeInTheDocument();
    expect(screen.getByText(/2 within 150 m/)).toBeInTheDocument();
  });

  it("explains why an unconsented neighbour is print-only", async () => {
    neighborsMock.mockResolvedValue(batch([entry()]));
    renderPanel();

    expect(await screen.findByText("No messaging consent — print only")).toBeInTheDocument();
    expect(screen.queryByText(/Can be messaged/)).not.toBeInTheDocument();
  });

  it("says opted-out neighbours are print-only rather than hiding the reason", async () => {
    neighborsMock.mockResolvedValue(batch([entry({ messaging_blocked_reason: "global_opt_out" })]));
    renderPanel();

    expect(await screen.findByText("Opted out — print only")).toBeInTheDocument();
  });

  it("only marks a neighbour messageable when the server says so", async () => {
    neighborsMock.mockResolvedValue(
      batch([entry({ messageable: true, channel: "sms", messaging_blocked_reason: null })]),
    );
    renderPanel();

    expect(await screen.findByText(/Can be messaged/)).toBeInTheDocument();
  });

  it("advances an entry's status", async () => {
    neighborsMock.mockResolvedValue(batch([entry()]));
    updateEntryMock.mockResolvedValue(entry({ status: "contacted" }));
    renderPanel();

    await selectOption(await screen.findByLabelText("Status for Dana Ruiz"), "Contacted");

    await waitFor(() =>
      expect(updateEntryMock).toHaveBeenCalledWith("ws-1", "job-1", "entry-1", {
        status: "contacted",
      }),
    );
  });

  it("hides generate and export from a read-only viewer", async () => {
    neighborsMock.mockResolvedValue(batch([entry()]));
    renderPanel({ readOnly: true });

    expect(await screen.findByText("Dana Ruiz")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Export list/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Refresh/i })).not.toBeInTheDocument();
  });

  it("never offers the address export to a technician", async () => {
    signedInAs("technician");
    neighborsMock.mockResolvedValue(batch([entry()]));
    renderPanel();

    expect(await screen.findByText("Dana Ruiz")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Export list/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Status for Dana Ruiz")).toBeDisabled();
  });

  it("builds the print export in the browser rather than fetching a server file", async () => {
    const user = userEvent.setup();
    neighborsMock.mockResolvedValue(batch([entry()]));
    exportMock.mockResolvedValue({
      job_id: "job-1",
      batch_id: "batch-1",
      radius_meters: 150,
      generated_at: "2026-07-20T18:00:00.000Z",
      total: 1,
      rows: [
        {
          entry_id: "entry-1",
          service_location_id: "loc-1",
          label: "102 Oak",
          customer_name: "Dana Ruiz",
          address_line1: "102 Oak St",
          address_line2: null,
          city: "Minneapolis",
          state: "MN",
          postal_code: "55401",
          country: "US",
          latitude: 44.9783,
          longitude: -93.265,
          distance_meters: 59.9,
          status: "pending",
          channel: "print",
        },
      ],
    });

    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:neighbors");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderPanel();
    await user.click(await screen.findByRole("button", { name: /Export list/i }));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    const blob = createObjectURL.mock.calls[0][0];
    expect(blob.type).toContain("text/csv");
    await expect(blob.text()).resolves.toContain("102 Oak St");
    anchorClick.mockRestore();
    vi.unstubAllGlobals();
  });
});
