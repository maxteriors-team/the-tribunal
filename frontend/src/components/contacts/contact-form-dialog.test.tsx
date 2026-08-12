import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContactFormDialog } from "@/components/contacts/contact-form-dialog";
import type { LeadSource } from "@/lib/api/lead-sources";
import type { Contact, Tag } from "@/types";

/**
 * The three detours this form used to force on an operator mid-contact:
 * leaving for Settings to add a lead source, guessing a comma-separated tag
 * string, and hand-typing an address into four separate fields. Each one is now
 * inline, and each one has to end up in the create payload — an inline control
 * that doesn't reach the API is worse than no control, because it looks saved.
 */

const {
  manualCreateMock,
  updateMock,
  listLeadSourcesMock,
  createLeadSourceMock,
  captureSettingsMock,
  listTagsMock,
  createTagMock,
  suggestMock,
  resolveMock,
} = vi.hoisted(() => ({
  manualCreateMock: vi.fn(),
  updateMock: vi.fn(),
  listLeadSourcesMock: vi.fn(),
  createLeadSourceMock: vi.fn(),
  captureSettingsMock: vi.fn(),
  listTagsMock: vi.fn(),
  createTagMock: vi.fn(),
  suggestMock: vi.fn(),
  resolveMock: vi.fn(),
}));

vi.mock("@/lib/api/contacts", () => ({
  contactsApi: { manualCreate: manualCreateMock, update: updateMock },
}));

vi.mock("@/lib/api/lead-sources", () => ({
  leadSourcesApi: {
    list: listLeadSourcesMock,
    create: createLeadSourceMock,
    getCaptureSettings: captureSettingsMock,
  },
}));

vi.mock("@/lib/api/tags", () => ({
  tagsApi: { list: listTagsMock, create: createTagMock },
}));

vi.mock("@/lib/api/addresses", () => ({
  addressesApi: { suggest: suggestMock, resolve: resolveMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws-1" }));

vi.mock("@/lib/contact-store", () => ({
  useContactStore: () => ({ setSelectedContact: vi.fn() }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function makeLeadSource(overrides: Partial<LeadSource> = {}): LeadSource {
  return {
    id: "src-1",
    workspace_id: "ws-1",
    name: "FB Christmas light leads",
    public_key: "pk_1",
    allowed_domains: [],
    enabled: true,
    source_type: "facebook_ads",
    action: "collect",
    action_config: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    endpoint_url: "https://example.test/capture",
    ...overrides,
  };
}

function makeTag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: "tag-1",
    workspace_id: "ws-1",
    name: "vip",
    color: "#6366f1",
    contact_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContactFormDialog mode="create" open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: 1,
    user_id: 1,
    first_name: "Dana",
    last_name: "Reyes",
    phone_number: "+15125550142",
    status: "new",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as Contact;
}

function renderEditDialog(contact: Contact = makeContact()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContactFormDialog mode="edit" open contact={contact} onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

/** The two fields the form requires before it will submit anything. */
async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText("John"), "Dana");
  await user.type(screen.getByPlaceholderText("+1 (555) 123-4567"), "5125550142");
}

beforeEach(() => {
  vi.clearAllMocks();
  manualCreateMock.mockResolvedValue({ id: 1 });
  listLeadSourcesMock.mockResolvedValue([makeLeadSource()]);
  captureSettingsMock.mockResolvedValue({ require_lead_source_on_manual_create: false });
  listTagsMock.mockResolvedValue({ items: [makeTag()], total: 1 });
  suggestMock.mockResolvedValue({ provider: "census", suggestions: [] });
});

describe("ContactFormDialog inline creation", () => {
  it("creates a lead source inline and submits the new source with the contact", async () => {
    const user = userEvent.setup();
    createLeadSourceMock.mockResolvedValue(
      makeLeadSource({ id: "src-new", name: "Nextdoor post", source_type: "organic" }),
    );
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /new lead source/i }));
    await user.type(screen.getByLabelText("New lead source name"), "Nextdoor post");
    await user.click(screen.getByRole("button", { name: "Add source" }));

    await waitFor(() =>
      expect(createLeadSourceMock).toHaveBeenCalledWith("ws-1", {
        name: "Nextdoor post",
        allowed_domains: [],
        source_type: "other",
        action: "collect",
      }),
    );

    // The new source has to come back selected, or the operator has to go
    // hunting for it in a list that just changed under them.
    listLeadSourcesMock.mockResolvedValue([
      makeLeadSource(),
      makeLeadSource({ id: "src-new", name: "Nextdoor post" }),
    ]);
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Create Contact" }));

    await waitFor(() => expect(manualCreateMock).toHaveBeenCalled());
    expect(manualCreateMock.mock.calls[0][1]).toMatchObject({ lead_source_id: "src-new" });
  });

  it("keeps Enter in the inline source name from submitting the contact form", async () => {
    const user = userEvent.setup();
    createLeadSourceMock.mockResolvedValue(makeLeadSource({ id: "src-new", name: "Yard sign" }));
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /new lead source/i }));
    await user.type(screen.getByLabelText("New lead source name"), "Yard sign{Enter}");

    await waitFor(() => expect(createLeadSourceMock).toHaveBeenCalled());
    expect(manualCreateMock).not.toHaveBeenCalled();
  });

  it("creates a tag inline and submits it as a contact tag", async () => {
    const user = userEvent.setup();
    createTagMock.mockResolvedValue(makeTag({ id: "tag-new", name: "storm damage" }));
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /add tags/i }));
    await user.type(screen.getByPlaceholderText("Search or create tag..."), "storm damage");
    await user.click(screen.getByRole("button", { name: /create "storm damage"/i }));

    await waitFor(() =>
      expect(createTagMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ name: "storm damage" }),
      ),
    );

    listTagsMock.mockResolvedValue({
      items: [makeTag(), makeTag({ id: "tag-new", name: "storm damage" })],
      total: 2,
    });
    await user.keyboard("{Escape}");
    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Create Contact" }));

    await waitFor(() => expect(manualCreateMock).toHaveBeenCalled());
    expect(manualCreateMock.mock.calls[0][1]).toMatchObject({ tags: ["storm damage"] });
  });

  it("selecting an existing tag adds a removable chip", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /add tags/i }));
    await user.click(await screen.findByRole("button", { name: /^vip$/i }));
    await user.keyboard("{Escape}");

    expect(screen.getAllByText("vip").length).toBeGreaterThan(0);
    // Chips carry their own remove control, so a mis-tag is one click to undo.
    expect(screen.getAllByRole("button", { name: /remove/i }).length).toBeGreaterThan(0);
  });
});

describe("ContactFormDialog address autocomplete", () => {
  it("fills city, state and ZIP from a picked suggestion", async () => {
    const user = userEvent.setup();
    suggestMock.mockResolvedValue({
      provider: "census",
      suggestions: [
        {
          id: "census:0",
          label: "1600 Pennsylvania Ave NW",
          description: "Washington, DC 20500",
          parts: {
            address_line1: "1600 Pennsylvania Ave NW",
            address_line2: "",
            address_city: "Washington",
            address_state: "DC",
            address_zip: "20500",
          },
        },
      ],
    });
    renderDialog();

    await user.type(screen.getByPlaceholderText("123 Main St"), "1600 pennsylvania");

    const option = await screen.findByRole("option", { name: /1600 Pennsylvania Ave NW/ });
    await user.click(option);

    await waitFor(() =>
      expect(screen.getByPlaceholderText("New York")).toHaveValue("Washington"),
    );
    expect(screen.getByPlaceholderText("NY")).toHaveValue("DC");
    expect(screen.getByPlaceholderText("10001")).toHaveValue("20500");
    // A census suggestion arrives already structured, so picking it must not
    // cost a second (billed, on the Google path) round trip.
    expect(resolveMock).not.toHaveBeenCalled();
  });

  it("resolves a suggestion that arrives without parts", async () => {
    const user = userEvent.setup();
    suggestMock.mockResolvedValue({
      provider: "google_places",
      suggestions: [
        {
          id: "google:ChIJ123",
          label: "1600 Amphitheatre Pkwy",
          description: "Mountain View, CA, USA",
          parts: null,
        },
      ],
    });
    resolveMock.mockResolvedValue({
      address_line1: "1600 Amphitheatre Parkway",
      address_line2: "",
      address_city: "Mountain View",
      address_state: "CA",
      address_zip: "94043",
    });
    renderDialog();

    await user.type(screen.getByPlaceholderText("123 Main St"), "1600 amphi");
    await user.click(await screen.findByRole("option", { name: /1600 Amphitheatre Pkwy/ }));

    await waitFor(() =>
      expect(screen.getByPlaceholderText("New York")).toHaveValue("Mountain View"),
    );
    expect(resolveMock).toHaveBeenCalledWith("ws-1", "google:ChIJ123", expect.any(String));
  });

  it("leaves the typed address alone when the provider is unavailable", async () => {
    const user = userEvent.setup();
    suggestMock.mockRejectedValue(new Error("provider down"));
    renderDialog();

    const line1 = screen.getByPlaceholderText("123 Main St");
    await user.type(line1, "42 Rural Route 3");

    await waitFor(() => expect(suggestMock).toHaveBeenCalled());
    expect(line1).toHaveValue("42 Rural Route 3");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("submits the picked address with the contact", async () => {
    const user = userEvent.setup();
    suggestMock.mockResolvedValue({
      provider: "census",
      suggestions: [
        {
          id: "census:0",
          label: "4412 Ridgeview Dr",
          description: "Austin, TX 78731",
          parts: {
            address_line1: "4412 Ridgeview Dr",
            address_line2: "",
            address_city: "Austin",
            address_state: "TX",
            address_zip: "78731",
          },
        },
      ],
    });
    renderDialog();

    await user.type(screen.getByPlaceholderText("123 Main St"), "4412 ridgeview");
    await user.click(await screen.findByRole("option", { name: /4412 Ridgeview Dr/ }));
    await waitFor(() => expect(screen.getByPlaceholderText("New York")).toHaveValue("Austin"));

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Create Contact" }));

    await waitFor(() => expect(manualCreateMock).toHaveBeenCalled());
    expect(manualCreateMock.mock.calls[0][1]).toMatchObject({
      address_line1: "4412 Ridgeview Dr",
      address_city: "Austin",
      address_state: "TX",
      address_zip: "78731",
    });
  });
});

describe("ContactFormDialog layout", () => {
  it("scrolls the fields instead of pushing the title or submit off-screen", async () => {
    renderDialog();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Add New Contact" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Create Contact" })).toBeVisible();

    // The fields are the only scrolling region, so the header and footer stay
    // anchored no matter how many fields the form grows.
    const scroller = dialog.querySelector(".overflow-y-auto");
    expect(scroller).not.toBeNull();
    expect(scroller).toContainElement(screen.getByPlaceholderText("John"));
    expect(scroller).not.toContainElement(
      within(dialog).getByRole("button", { name: "Create Contact" }),
    );
  });
});

/**
 * Attribution is usually learned *after* the contact exists — the operator asks
 * "how did you find us?" on the first call, by which point the record is
 * already saved. The source field used to render only in create mode, so the
 * answer had nowhere to go and the ROI reporting built on it stayed wrong.
 */
describe("ContactFormDialog source editing", () => {
  it("offers the source field when editing an existing contact", async () => {
    renderEditDialog();

    expect(await screen.findByLabelText("How did you hear about us?")).toBeVisible();
  });

  it("preselects the source already recorded on the contact", async () => {
    renderEditDialog(makeContact({ first_touch_lead_source_id: "src-1" }));

    const trigger = await screen.findByLabelText("How did you hear about us?");
    await waitFor(() => expect(trigger).toHaveTextContent("FB Christmas light leads"));
  });

  it("submits a newly picked source on save", async () => {
    const user = userEvent.setup();
    updateMock.mockResolvedValue({ id: 1 });
    renderEditDialog();

    await user.click(await screen.findByLabelText("How did you hear about us?"));
    await user.click(await screen.findByRole("option", { name: /FB Christmas light leads/i }));
    await user.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    expect(updateMock.mock.calls[0][2]).toMatchObject({
      first_touch_lead_source_id: "src-1",
    });
  });

  it("clears a source that was recorded by mistake", async () => {
    const user = userEvent.setup();
    updateMock.mockResolvedValue({ id: 1 });
    renderEditDialog(makeContact({ first_touch_lead_source_id: "src-1" }));

    await user.click(await screen.findByLabelText("How did you hear about us?"));
    await user.click(await screen.findByRole("option", { name: "No lead source" }));
    await user.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    // null, not undefined: an omitted key would leave the wrong source in place.
    expect(updateMock.mock.calls[0][2].first_touch_lead_source_id).toBeNull();
  });

  it("does not enforce the create-time source requirement when editing", async () => {
    const user = userEvent.setup();
    captureSettingsMock.mockResolvedValue({ require_lead_source_on_manual_create: true });
    updateMock.mockResolvedValue({ id: 1 });
    renderEditDialog();

    await user.click(await screen.findByRole("button", { name: "Save Changes" }));

    // An old contact with no source must still be saveable, or the operator is
    // locked out of the very record they opened the form to fix.
    await waitFor(() => expect(updateMock).toHaveBeenCalled());
  });
});
