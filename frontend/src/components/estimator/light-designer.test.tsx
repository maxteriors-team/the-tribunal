import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LightDesigner,
  type LandscapeProjectPersistenceAdapter,
} from "@/components/estimator/light-designer";
import type { DesignerProposalHost } from "@/components/estimator/proposal-host";
import { estimatorApi } from "@/lib/api/estimator";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { designToEstimateInputs } from "@/lib/estimator/design";
import {
  defaultLandscapePrecon,
  defaultLandscapeProposal,
  defaultLandscapeSettings,
} from "@/lib/estimator/landscape-document";
import { loadLandscapeDraft, saveLandscapeDraft } from "@/lib/estimator/landscape-draft";
import type { LinearFeetEstimateResult } from "@/types/estimate";

// Server pricing is always mocked — the component only ever sends feet/counts.
vi.mock("@/lib/api/estimator", () => ({
  estimatorApi: {
    estimate: vi.fn(),
    share: vi.fn(),
    deliver: vi.fn(),
    render: vi.fn(),
    createQuote: vi.fn(),
  },
}));

// The workspace price book + pricing config drive the landscape fixture types.
vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    listCatalog: vi.fn(),
    getPricing: vi.fn(),
    preview: vi.fn(),
    save: vi.fn(),
  },
}));

vi.mock("@/lib/estimator/landscape-draft", () => ({
  createLandscapeDraft: vi.fn((shots, activeShotId, updatedAt, proposal, liveState) => ({
    version: 2,
    activeShotId,
    shots,
    updatedAt: updatedAt ?? "2026-08-11T10:00:00.000Z",
    ...liveState,
    ...(proposal ? { proposal: { ...liveState?.proposal, ...proposal } } : {}),
  })),
  loadLandscapeDraft: vi.fn(),
  saveLandscapeDraft: vi.fn(),
}));

// jsdom can't decode images or drive a real canvas, so mock the photo loader:
// upload resolves a fixed PhotoInfo and the canvas gets a fake decoded image.
vi.mock("@/lib/estimator/photo", () => ({
  fileToPhoto: vi.fn().mockResolvedValue({
    dataUrl: "data:image/png;base64,AAAA",
    width: 1200,
    height: 800,
  }),
  loadImage: vi.fn(() => new Promise(() => undefined)),
}));

// jsdom can't flatten a canvas, so the composite is a fixed data URL.
vi.mock("@/lib/estimator/export", () => ({
  exportDesignJpeg: vi.fn().mockResolvedValue("data:image/jpeg;base64,LIT"),
}));

// The glow engine is exercised in render.test.ts; here it's a no-op so the
// canvas component mounts without a 2D context.
vi.mock("@/lib/estimator/render", () => ({
  drawScene: vi.fn(),
  itemHit: vi.fn(() => false),
  resizeHandlePos: vi.fn(() => ({ x: 0, y: 0 })),
  beamHandlePos: vi.fn(() => null),
  beamAngleAt: vi.fn(() => 30),
  DEFAULT_DUSK: 0.52,
  MAX_DUSK: 0.92,
}));

// jsdom can't produce traced geometry (getBoundingClientRect is all zeros), so
// force a measured design: hasDesign true + a fixed mapped payload. The mapping
// math itself is unit-tested in design.test.ts.
const MAPPED = {
  feet: 100,
  christmas_items: {},
  fixtures: {},
  bistro_feet: 0,
};
// Partial mock: only the photo-dependent readings are faked. `sumEstimateInputs`
// stays real, so the multi-photo totals under test are the production math.
vi.mock("@/lib/estimator/design", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/estimator/design")>()),
  designToEstimateInputs: vi.fn(() => MAPPED),
  hasDesign: vi.fn(() => true),
  designScale: vi.fn(() => ({ ftPerPx: 0.05, pxPerFt: 20, calibrated: false })),
}));

const ESTIMATE: LinearFeetEstimateResult = {
  feet: 100,
  permanent: {
    enabled: true,
    total: 3300,
    per_ft: 0,
    package_feet: 100,
    package_cogs: 1249,
    markup: 3.5,
    roofline_cost: 4371.5,
    custom_total: 0,
  },
  christmas: {
    enabled: true,
    total: 900,
    per_ft: 6,
    roofline_cost: 600,
    custom_total: 0,
    items: [{ key: "wreaths", label: "Wreaths", unit: "each", cost: 96 }],
  },
  difference: 2400,
  years: 5,
  temporary_multi_year: 4500,
  permanent_one_time: 3300,
  multi_year_savings: 1200,
  permanent_perks: [],
  christmas_perks: [],
  christmas_catalog: [
    {
      key: "wreaths",
      label: "Wreaths",
      unit: "each",
      options: [{ key: "standard", name: "Wreath (up to 36 in)", price: 85 }],
    },
  ],
};

// Priced Good/Better/Best seasonal packages (workspace with `packages_enabled`).
// Totals ascend so the resolver's "most inclusive last" default is observable,
// and each package carries the full ChristmasPricing breakdown the server sends.
function pkgPricing(total: number) {
  return {
    min_applied: false,
    minimum: 0,
    raw_total: total,
    roofline_cost: 0,
    roofline_feet: 100,
    storage_cost: 0,
    takedown_cost: 0,
    total,
    items: [],
    lines: [],
  };
}

const WITH_PACKAGES: LinearFeetEstimateResult = {
  ...ESTIMATE,
  christmas_packages: [
    {
      key: "essential",
      label: "Essential",
      name: "Essential",
      includes_roofline: false,
      popular: false,
      pricing: pkgPricing(700),
    },
    {
      key: "middle",
      label: "Middle",
      name: "Middle",
      includes_roofline: true,
      popular: true,
      pricing: pkgPricing(1100),
    },
    {
      key: "premier",
      label: "Premier",
      name: "Premier",
      includes_roofline: true,
      popular: false,
      pricing: pkgPricing(1400),
    },
  ],
};

// A price book + a single package that sells an uplight and a path light, so a
// drawn "Uplight" resolves to a real SKU exactly as it does in production.
const PRICE_BOOK = [
  {
    id: "id-up",
    workspace_id: "ws_1",
    name: "ZD Uplight",
    description: null,
    sku: "best-zd-up",
    kind: "product",
    unit_price: 411,
    taxable: true,
    is_active: true,
    attributes: null,
    components: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
] as unknown as Awaited<ReturnType<typeof salesWizardApi.listCatalog>>;

const PRICING = {
  tier_order: ["best"],
  tiers: [
    {
      key: "best",
      label: "Best — The Premier",
      tab: "Best",
      points: ["Color change from your phone"],
      sections: [{ title: "Fixtures", item_ids: ["best-zd-up"] }],
    },
  ],
  landscape: { perks: ["Lit walkways every night"] },
  permanent: { perks: ["Never hang lights again"] },
  christmas: { perks: ["Takedown and storage included"] },
  roofline_comparison_enabled: false,
} as unknown as Awaited<ReturnType<typeof salesWizardApi.getPricing>>;

function stubCanvas() {
  // Returning null makes the canvas draw() bail cleanly (no jsdom "not
  // implemented" noise) — rendering is covered by render.test.ts.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
}

function renderEstimator(
  proposal?: DesignerProposalHost,
  focus: "all" | "landscape" = "all",
  landscapeProject?: LandscapeProjectPersistenceAdapter,
  workspace: { id: string; name?: string; logoUrl?: string | null } = { id: "ws_1" },
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LightDesigner
        workspaceId={workspace.id}
        workspaceName={workspace.name}
        workspaceLogoUrl={workspace.logoUrl}
        proposal={proposal}
        focus={focus}
        landscapeProject={landscapeProject}
      />
    </QueryClientProvider>,
  );
}

async function uploadPhoto(container: HTMLElement) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  const file = new File(["x"], "house.png", { type: "image/png" });
  fireEvent.change(input!, { target: { files: [file] } });
  await waitFor(() => expect(container.querySelector("canvas")).not.toBeNull());
}

/** The photo thumbnails in the shot strip, in the order the rep added them. */
function shotTabs() {
  return screen.queryAllByRole("button", { name: /^Photo \d+/ });
}

/** The photo the canvas is currently showing, 1-based. */
function activeShotIndex() {
  return shotTabs().findIndex((tab) => tab.getAttribute("aria-current") === "true");
}

/**
 * Turn a service on. The palette only carries the selected services, so a test
 * that expects Christmas decor has to opt into Christmas first — same as a rep.
 */
function enableService(name: RegExp) {
  fireEvent.click(screen.getByRole("button", { name }));
}

async function openProposalPreview() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Present" }));
  await user.click(await screen.findByRole("menuitem", { name: "Open proposal preview" }));
}

describe("LightDesigner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubCanvas();
    // Reset the design mapping each test; landscape cases override it.
    vi.mocked(designToEstimateInputs).mockReturnValue(MAPPED);
    vi.mocked(salesWizardApi.listCatalog).mockResolvedValue(PRICE_BOOK);
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue(PRICING);
    vi.mocked(salesWizardApi.preview).mockResolvedValue({
      title: "Landscape lighting proposal",
      tiers: [
        {
          ["key"]: "best",
          label: "Best",
          name: "Premier",
          popular: true,
          lines: [
            {
              item_id: "best-zdc-up",
              name: "ZDC Color Uplight",
              quantity: 2,
              unit_price: 785,
              line_total: 1570,
              transformer: false,
            },
          ],
          pricing: {
            subtotal_net: 1570,
            overhead: 0,
            commission: 0,
            profit: 0,
            tax: 0,
            financed_total: 1570,
            cash_total: 1500,
            monthly_payment: 131,
          },
        },
      ],
      selection: {
        selected_tier: "best",
        selected_financed_total: 1570,
        selected_cash_total: 1500,
        deposit_due_now: 0,
      },
      care_plan: { fixture_count: 2, options: [] },
      categories: ["landscape"],
      line_count: 1,
      services: [],
      mockups: [],
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.preview>>);
    vi.mocked(salesWizardApi.save).mockResolvedValue({
      id: "quote-1",
      workspace_id: "workspace-1",
      number: "Q-1042",
      title: "Landscape lighting proposal",
      status: "draft",
      subtotal: 1500,
      tax_amount: 0,
      total: 1500,
      currency: "USD",
      attach_count: 0,
      attach_value: 0,
      view_count: 0,
      created_at: "2026-08-11T00:00:00Z",
      updated_at: "2026-08-11T00:00:00Z",
    } as Awaited<ReturnType<typeof salesWizardApi.save>>);
    vi.mocked(estimatorApi.estimate).mockResolvedValue(ESTIMATE);
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "",
      token: "",
      contact_id: null,
      saved_to_customer: false,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({
      ok: true,
      channel: "email",
      to: "",
    });
    vi.mocked(estimatorApi.createQuote).mockResolvedValue({
      number: "QUO-000007",
    } as Awaited<ReturnType<typeof estimatorApi.createQuote>>);
    vi.mocked(loadLandscapeDraft).mockResolvedValue(null);
    vi.mocked(saveLandscapeDraft).mockImplementation(async (workspaceId, shots) => ({
      workspaceId,
      shots,
      savedAt: "2026-08-10T20:57:00.000Z",
      schemaVersion: 1,
    }));
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the welcome prompt before a photo, then the three-pane editor after upload", async () => {
    const { container } = renderEstimator();

    // Before upload: welcome copy, no canvas, no palette.
    expect(container.querySelector("canvas")).toBeNull();
    expect(screen.getByText(/Design their lights on a photo/i)).toBeInTheDocument();

    await uploadPhoto(container);

    // After upload: the tool palette + the landscape fixture types + estimate.
    expect(screen.getByRole("heading", { name: /^Tools$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select & edit/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /^Uplight/i })).toBeInTheDocument();

    // Christmas is a separate service: its products appear once it's toggled on.
    expect(screen.queryByRole("button", { name: /C9 Roofline — Warm White/i })).toBeNull();
    enableService(/^Christmas$/);
    expect(
      await screen.findByRole("button", { name: /C9 Roofline — Warm White/i }),
    ).toBeInTheDocument();

    // The design is priced server-side (feet is the only measured input sent).
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ feet: 100 }),
      ),
    );
  });

  it("keeps a second workspace brand on internal and customer-facing estimator surfaces", async () => {
    const { container } = renderEstimator(undefined, "landscape", undefined, {
      id: "ws_2",
      name: "Northstar Outdoor Lighting",
      logoUrl: "https://northstar.example/logo.svg",
    });

    expect(
      await screen.findByRole("heading", {
        name: /Start with a top-down aerial plan/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fixture legend")).toBeInTheDocument();
    expect(screen.getAllByText("Untitled lighting project")).not.toHaveLength(0);
    expect(screen.getAllByText("Northstar Outdoor Lighting")).not.toHaveLength(0);
    expect(screen.queryByText(/maxteriors/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Drawing sheet tools")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("tabloid");
    expect(screen.getByRole("button", { name: /Add sheet/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open proposal pricing" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Build quote/i })).not.toBeInTheDocument();
    expect(
      screen.getByRole("navigation", {
        name: /Landscape lighting project sections/i,
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByText(/Street-level and elevation photos do not produce an accurate/i),
    ).toBeInTheDocument();

    await uploadPhoto(container);

    expect(screen.getByLabelText(/top-down aerial lighting plan canvas/i)).toBeInTheDocument();
    expect(screen.getByText("Aerial landscape lighting plan")).toBeInTheDocument();

    const wireTool = await screen.findByRole("button", { name: "Wire" });
    fireEvent.click(wireTool);
    expect(wireTool).toHaveAttribute("aria-pressed", "true");

    const uplightTool = await screen.findByRole("button", { name: /^Uplight:/i });
    fireEvent.click(uplightTool);
    expect(uplightTool).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: "Northstar Outdoor Lighting" })).toHaveAttribute(
      "src",
      "https://northstar.example/logo.svg",
    );
    expect(screen.queryByText(/maxteriors/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(
      screen.getByRole("complementary", { name: "Fixture and drawing tools" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Services in this design")).toBeNull();
    expect(screen.queryByText("Include seasonal takedown")).toBeNull();
    expect(screen.queryByText("Save to customer")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Fixture Schedule" }));
    expect(screen.getByRole("heading", { name: "Fixture Schedule" })).toBeInTheDocument();
    expect(screen.getByText(/Place fixtures on the Drawing Sheet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "BOM" }));
    expect(screen.getByRole("heading", { name: "Bill of Materials" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Supplier CSV" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Electrical" }));
    expect(screen.getByRole("heading", { name: "Electrical Plan" })).toBeInTheDocument();
    expect(screen.getByText("Connected load")).toBeInTheDocument();
    expect(screen.getByText(/Place fixture icons on the drawing/i)).toBeInTheDocument();
    expect(screen.getByText(/Draw a wire circuit on the Drawing Sheet/i)).toBeInTheDocument();

    await waitFor(() => expect(saveLandscapeDraft).toHaveBeenCalled());
    expect(screen.getByTitle("Drafts are saved automatically in this browser")).toHaveTextContent(
      /Saved locally/i,
    );
  });

  it("accepts a downloaded aerial dragged onto an empty drawing sheet", async () => {
    renderEstimator(undefined, "landscape");
    const dropZone = await screen.findByRole("region", {
      name: "Aerial plan file drop zone",
    });
    const image = new File(["aerial"], "downloaded-aerial.png", { type: "image/png" });
    const dataTransfer = { types: ["Files"], files: [image], dropEffect: "none" };

    fireEvent.dragEnter(dropZone, { dataTransfer });
    expect(screen.getByText("Release to place this aerial on Sheet L-1")).toBeInTheDocument();
    fireEvent.drop(dropZone, { dataTransfer });

    expect(
      await screen.findByLabelText(/top-down aerial lighting plan canvas/i),
    ).toBeInTheDocument();
  });

  it("derives the decor palette from the workspace christmas catalog", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Christmas$/);

    // The `each` wreath category becomes a placeable decor product.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Wreath \(up to 36 in\)/i })).toBeInTheDocument(),
    );
    expect(screen.getByText(/Place decor/i)).toBeInTheDocument();
  });

  it("exposes the Save-to-customer fields and an always-present email button once a photo is loaded", async () => {
    const { container } = renderEstimator();
    expect(screen.queryByLabelText(/Customer name/i)).toBeNull();

    await uploadPhoto(container);

    expect(screen.getByLabelText(/Customer name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Customer email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Customer phone/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save & share link only/i })).toBeInTheDocument();

    // The email button is present on every estimate (no need to save first),
    // but disabled until a customer email is entered.
    const emailBtn = screen.getByRole("button", { name: /Email estimate/i });
    expect(emailBtn).toBeInTheDocument();
    expect(emailBtn).toBeDisabled();
  });

  it("renders seasonal package cards and mirrors the picked package's total", async () => {
    vi.mocked(estimatorApi.estimate).mockResolvedValue(WITH_PACKAGES);
    const { container } = renderEstimator();
    await uploadPhoto(container);

    // All three Good/Better/Best cards render by their client-facing name.
    expect(await screen.findByRole("button", { name: /Essential/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Middle/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Premier/i })).toBeInTheDocument();

    // No explicit pick yet → the most-inclusive package (Premier) is the default,
    // so the seasonal headline shows its total, not the à la carte christmas total.
    const grandRow = () => container.querySelector(".ep-total-grand") as HTMLElement;
    expect(grandRow()).toHaveTextContent("$1,400");
    expect(grandRow()).not.toHaveTextContent("$900");

    // Picking a lower tier updates the seasonal headline to that package's total…
    fireEvent.click(screen.getByRole("button", { name: /Essential/i }));
    await waitFor(() => expect(grandRow()).toHaveTextContent("$700"));

    // …and re-prices server-side with the chosen package key.
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ selected_package: "essential" }),
      ),
    );
  });

  it("shares the resolved seasonal package key with the persisted estimate", async () => {
    vi.mocked(estimatorApi.estimate).mockResolvedValue(WITH_PACKAGES);
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await screen.findByRole("button", { name: /Premier/i });

    // Save & share without an explicit pick persists the resolved default
    // (most-inclusive package), so the public page folds that package's total.
    fireEvent.click(screen.getByRole("button", { name: /Save & share link only/i }));
    await waitFor(() =>
      expect(estimatorApi.share).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ selected_package: "premier" }),
      ),
    );
  });

  it("mirrors the seasonal package ladder into the client preview with the pick recommended", async () => {
    vi.mocked(estimatorApi.estimate).mockResolvedValue(WITH_PACKAGES);
    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Christmas$/);
    // Rep panel priced the packages (the picker buttons are present).
    await screen.findByRole("button", { name: /Premier/i });

    // Switch to the client-facing preview; the estimator feeds the same
    // Good/Better/Best ladder (feet-free totals only) into the ComparisonCard.
    fireEvent.click(screen.getByRole("button", { name: /Client preview/i }));
    const preview = await waitFor(() => {
      const el = container.querySelector(".est-client-preview");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });

    // This design sells Christmas, so the preview carries the festive theme —
    // mirroring what the homeowner sees on /p/compare.
    expect(preview).toHaveClass("cmp-festive");

    // All three tiers surface to the client…
    expect(preview.querySelectorAll(".cmp-pkg-grid .cmp-pkg")).toHaveLength(3);
    // …and only the resolved default (most-inclusive Premier, no explicit pick)
    // is flagged Recommended — not the merely `popular` Middle tier — matching
    // what the server folds into the shared page.
    const recommended = preview.querySelectorAll(".cmp-pkg.recommended");
    expect(recommended).toHaveLength(1);
    expect(recommended[0].textContent).toContain("Premier");
  });

  it("converts the measured design into a seasonal draft quote and confirms the number", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    // Both priced sides are enabled, so the rep can convert either side.
    const seasonalBtn = await screen.findByRole("button", {
      name: /Create seasonal quote/i,
    });
    expect(screen.getByRole("button", { name: /Create permanent quote/i })).toBeInTheDocument();

    fireEvent.click(seasonalBtn);

    // Conversion sends only the measured inputs plus the chosen side; every
    // line is recomputed server-side.
    await waitFor(() =>
      expect(estimatorApi.createQuote).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ side: "seasonal", feet: 100 }),
      ),
    );

    // The created quote's number is confirmed inline with a link into Quotes.
    expect(await screen.findByText(/Quote QUO-000007 created/i)).toBeInTheDocument();
  });

  it("converts the permanent side when the permanent quote button is used", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    fireEvent.click(await screen.findByRole("button", { name: /Create permanent quote/i }));

    await waitFor(() =>
      expect(estimatorApi.createQuote).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ side: "permanent", feet: 100 }),
      ),
    );
  });

  it("emails the estimate in one click, minting a share link first", async () => {
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "https://app.test/p/compare/tok_123",
      token: "tok_123",
      contact_id: 42,
      saved_to_customer: true,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({
      ok: true,
      channel: "email",
      to: "buyer@example.com",
    });

    const { container } = renderEstimator();
    await uploadPhoto(container);

    // The email button is there immediately, disabled until an email is typed —
    // the rep never has to press "Save & share" first.
    const emailBtn = screen.getByRole("button", { name: /Email estimate/i });
    expect(emailBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Customer email/i), {
      target: { value: "buyer@example.com" },
    });
    expect(emailBtn).toBeEnabled();

    // One click mints the share link (share) and then delivers it (deliver).
    fireEvent.click(emailBtn);

    await waitFor(() =>
      expect(estimatorApi.share).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ client_email: "buyer@example.com" }),
      ),
    );
    await waitFor(() =>
      expect(estimatorApi.deliver).toHaveBeenCalledWith(
        "ws_1",
        "tok_123",
        "buyer@example.com",
        "email",
      ),
    );
    expect(await screen.findByText(/Emailed to buyer@example\.com/i)).toBeInTheDocument();
  });

  it("texts the estimate to the customer's phone, minting a share link first", async () => {
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "https://app.test/p/compare/tok_123",
      token: "tok_123",
      contact_id: 42,
      saved_to_customer: true,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({
      ok: true,
      channel: "sms",
      to: "+15551234567",
    });

    const { container } = renderEstimator();
    await uploadPhoto(container);

    // Same deal as email: present from the start, disabled until there's a
    // number to send to.
    const textBtn = screen.getByRole("button", { name: /Text estimate/i });
    expect(textBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Customer phone/i), {
      target: { value: "+15551234567" },
    });
    expect(textBtn).toBeEnabled();

    fireEvent.click(textBtn);

    await waitFor(() =>
      expect(estimatorApi.deliver).toHaveBeenCalledWith("ws_1", "tok_123", "+15551234567", "sms"),
    );
    // Names the rail, so a bare phone number never leaves the rep guessing
    // whether this went out as a text or an email.
    expect(await screen.findByText(/Texted to \+15551234567/i)).toBeInTheDocument();
  });

  it("tells the rep what to fix when a text can't be sent", async () => {
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "https://app.test/p/compare/tok_123",
      token: "tok_123",
      contact_id: 42,
      saved_to_customer: true,
    });
    // The server's refusals are actionable; a generic "couldn't send" would
    // throw away the only sentence that tells the rep what to do next.
    vi.mocked(estimatorApi.deliver).mockRejectedValue(
      Object.assign(new Error("Request failed"), {
        response: {
          status: 422,
          data: {
            detail: "No SMS-enabled phone number in this workspace \u2014 add one under Settings.",
          },
        },
      }),
    );

    const { container } = renderEstimator();
    await uploadPhoto(container);
    fireEvent.change(screen.getByLabelText(/Customer phone/i), {
      target: { value: "+15551234567" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Text estimate/i }));

    expect(await screen.findByText(/add one under Settings/i)).toBeInTheDocument();
  });

  // ── Quote Builder host: the one photo tool, embedded in the wizard ────────

  it("swaps the standalone share flow for save-to-proposal when the Quote Builder hosts it", async () => {
    const proposal: DesignerProposalHost = {
      onSave: vi.fn(),
      onShotsChange: vi.fn(),
      onClose: vi.fn(),
    };
    const { container } = renderEstimator(proposal);
    await uploadPhoto(container);

    expect(proposal.onShotsChange).toHaveBeenCalledWith([
      expect.objectContaining({
        photo: expect.objectContaining({ width: 1200 }),
      }),
    ]);
    expect(screen.getByRole("button", { name: /save to proposal/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /back to quote/i })).toBeInTheDocument();
    // The wizard owns the customer and the quote, so the standalone share and
    // convert flows stay out of the way.
    expect(screen.queryByText("Save to customer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /client preview/i })).not.toBeInTheDocument();
  });

  it("hands the host the composite plus the measured fixtures on save", async () => {
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 100,
      christmas_items: {},
      fixtures: { uplight: 4 },
      bistro_feet: 32,
    });

    const onSave = vi.fn();
    const proposal: DesignerProposalHost = {
      onSave,
      onShotsChange: vi.fn(),
      onClose: vi.fn(),
    };
    const { container } = renderEstimator(proposal);
    await uploadPhoto(container);

    fireEvent.click(screen.getByRole("button", { name: /save to proposal/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    // Counts leave the designer keyed by fixture *type*; the host resolves each
    // type to the product its chosen package sells.
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        shots: [expect.objectContaining({ image: "data:image/jpeg;base64,LIT" })],
        fixtures: { uplight: 4 },
        services: ["landscape"],
        rooflineFeet: 100,
        bistroFeet: 32,
      }),
    );
    expect(await screen.findByText(/Saved 1 design to the proposal at/i)).toBeInTheDocument();
  });

  it("tallies drawn fixture types against the product the package sells", async () => {
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 0,
      christmas_items: {},
      fixtures: { uplight: 4 },
      bistro_feet: 0,
    });
    const { container } = renderEstimator();
    await uploadPhoto(container);

    expect(await screen.findByText("Landscape fixtures")).toBeInTheDocument();
    expect(screen.getByText("×4")).toBeInTheDocument();
    // The rep drew a *type*; the package resolves it to the real product and
    // the SKU the crew pulls.
    await waitFor(() =>
      expect(container.querySelector(".ep-line-sku")?.textContent).toBe("ZD Uplight · best-zd-up"),
    );
  });

  it("says so when the package doesn't sell a fixture type the rep drew", async () => {
    // The seeded package sells an uplight only, so a drawn downlight resolves
    // to nothing — surfaced, never silently swapped for another package's part.
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 0,
      christmas_items: {},
      fixtures: { downlight: 2 },
      bistro_feet: 0,
    });
    const { container } = renderEstimator();
    await uploadPhoto(container);

    expect(await screen.findByText(/doesn’t include downlight/i)).toBeInTheDocument();
    expect(container.querySelector(".ep-line-sku.missing")).not.toBeNull();
  });

  it("keeps the Christmas theme off a landscape client preview", async () => {
    // A homeowner buying year-round brass landscape lighting should never be
    // handed a holiday page — the theme follows what's actually being sold.
    vi.mocked(estimatorApi.estimate).mockResolvedValue(WITH_PACKAGES);
    const { container } = renderEstimator();
    await uploadPhoto(container);
    fireEvent.click(screen.getByRole("button", { name: /client preview/i }));

    const preview = await waitFor(() => {
      const el = container.querySelector(".est-client-preview");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(preview).not.toHaveClass("cmp-festive");

    // Adding Christmas to the quote brings the holiday palette back.
    enableService(/^Christmas$/);
    await waitFor(() =>
      expect(container.querySelector(".est-client-preview")).toHaveClass("cmp-festive"),
    );
  });

  it("gives each selected service its own client-facing value propositions", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Christmas$/);
    fireEvent.click(screen.getByRole("button", { name: /client preview/i }));

    // Landscape leads with the chosen package's own point; Christmas argues its
    // own case rather than sharing one blended list.
    expect(await screen.findByText("Architectural Landscape Lighting")).toBeInTheDocument();
    expect(screen.getByText("Seasonal Christmas Lighting")).toBeInTheDocument();
    expect(screen.getByText("Color change from your phone")).toBeInTheDocument();
    expect(screen.getByText("Takedown and storage included")).toBeInTheDocument();
    // Permanent isn't being sold here, so its pitch stays off the page.
    expect(screen.queryByText("Never hang lights again")).toBeNull();
  });
  // ---- Standalone line items (independent of packages) -------------------

  /** Fill the newest line-item row with a label and a price. */
  async function fillLineItem(label: string, price: string) {
    // The editor appears once the workspace's priced sides are known.
    fireEvent.click(await screen.findByRole("button", { name: /Add line item/i }));
    const labels = screen.getAllByLabelText(/Line item description/i);
    const prices = screen.getAllByLabelText(/^Line item price$/i);
    const row = labels.length - 1;
    fireEvent.change(labels[row], { target: { value: label } });
    fireEvent.change(prices[row], { target: { value: price } });
  }

  it("sends a standalone line item to the server for pricing", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    await fillLineItem("Bucket truck day", "150");

    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          custom_lines: [
            {
              label: "Bucket truck day",
              quantity: 1,
              unit_price: 150,
              side: "seasonal",
            },
          ],
        }),
      ),
    );
  });

  it("keeps a half-typed line out of the priced request", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    // A row with a name but no price yet must not price as $0 mid-keystroke.
    fireEvent.click(await screen.findByRole("button", { name: /Add line item/i }));
    fireEvent.change(screen.getByLabelText(/Line item description/i), {
      target: { value: "Still typing" },
    });

    await waitFor(() => expect(estimatorApi.estimate).toHaveBeenCalled());
    expect(estimatorApi.estimate).not.toHaveBeenCalledWith(
      "ws_1",
      expect.objectContaining({
        custom_lines: expect.arrayContaining([expect.objectContaining({ label: "Still typing" })]),
      }),
    );
  });

  it("bills a line item one-time or per season", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    await fillLineItem("Remove old clips", "90");
    fireEvent.change(screen.getByLabelText(/Line item applies to/i), {
      target: { value: "permanent" },
    });

    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          custom_lines: [expect.objectContaining({ side: "permanent", unit_price: 90 })],
        }),
      ),
    );
  });

  it("removes a line item from the estimate", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    await fillLineItem("Bucket truck day", "150");
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ custom_lines: [expect.anything()] }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /Remove Bucket truck day/i }));
    // The row is gone, so the next request (and the share) carries no add-on.
    expect(screen.queryByDisplayValue("Bucket truck day")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Save & share link only/i }));
    await waitFor(() =>
      expect(estimatorApi.share).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ custom_lines: [] }),
      ),
    );
  });

  it("adds line items on top of the selected package, not into it", async () => {
    // The server prices packages without the add-ons and reports the add-on
    // subtotal separately; the headline is the pick plus that subtotal, exactly
    // as the client's page computes it.
    vi.mocked(estimatorApi.estimate).mockResolvedValue({
      ...WITH_PACKAGES,
      christmas: { ...WITH_PACKAGES.christmas, custom_total: 200 },
    });
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await screen.findByRole("button", { name: /Premier/i });

    const grandRow = () => container.querySelector(".ep-total-grand") as HTMLElement;
    // Premier is $1,400 on its card…
    expect(screen.getByRole("button", { name: /Premier/i })).toHaveTextContent("$1,400");
    // …and the seasonal headline carries the $200 of add-ons on top of it.
    await waitFor(() => expect(grandRow()).toHaveTextContent("$1,600"));
  });

  it("scopes a line item to one package when the rep pins it there", async () => {
    // The bucket-truck day Premier needs and Essential doesn't: pinning it sends
    // the tier, and the server prices it inside that card only.
    vi.mocked(estimatorApi.estimate).mockResolvedValue(WITH_PACKAGES);
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await screen.findByRole("button", { name: /Premier/i });

    await fillLineItem("Bucket truck day", "200");
    fireEvent.change(screen.getByLabelText(/Line item package/i), {
      target: { value: "premier" },
    });

    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          custom_lines: [
            expect.objectContaining({
              label: "Bucket truck day",
              package_key: "premier",
            }),
          ],
        }),
      ),
    );
  });

  it("defaults a line item to every package", async () => {
    // Today's behavior is the default: no tier is sent, so the line rides on
    // top of whichever package the client picks.
    vi.mocked(estimatorApi.estimate).mockResolvedValue(WITH_PACKAGES);
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await screen.findByRole("button", { name: /Premier/i });

    await fillLineItem("Trip charge", "75");

    expect(screen.getByLabelText(/Line item package/i)).toHaveValue("");
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          custom_lines: [
            {
              label: "Trip charge",
              quantity: 1,
              unit_price: 75,
              side: "seasonal",
            },
          ],
        }),
      ),
    );
  });

  it("offers no package picker when the workspace sells no packages", async () => {
    // À la carte seasonal has no tier for a line to live inside.
    const { container } = renderEstimator();
    await uploadPhoto(container);

    await fillLineItem("Bucket truck day", "200");

    expect(screen.queryByLabelText(/Line item package/i)).toBeNull();
  });

  it("hides the line-item editor when the Quote Builder hosts the designer", async () => {
    // That flow prices from the wizard's own document, so a line typed here
    // would never reach the quote. Absent beats silently dropped.
    const { container } = renderEstimator({
      onSave: vi.fn(),
      onShotsChange: vi.fn(),
      onClose: vi.fn(),
      tierKey: "best",
    });
    await uploadPhoto(container);
    await screen.findByRole("heading", { name: /^Tools$/i });

    expect(screen.queryByRole("button", { name: /Add line item/i })).toBeNull();
  });

  // ── Several photos in one design ────────────────────────────────────

  it("adds a photo instead of replacing the one already designed", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);
    expect(shotTabs()).toHaveLength(1);

    // The rep photographs the back of the house next. The front must survive:
    // trading it away for the new angle is the bug this guards.
    await uploadPhoto(container);

    expect(shotTabs()).toHaveLength(2);
    // The new photo opens for drawing, and the first is still there to go back to.
    expect(activeShotIndex()).toBe(1);

    fireEvent.click(shotTabs()[0]);
    expect(activeShotIndex()).toBe(0);
  });

  it("totals the measurements across every photo", async () => {
    // Each photo maps to 100 ft, so two shots is a 200 ft job — the quote has to
    // cover the whole house, not whichever photo was on screen.
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ feet: 100 }),
      ),
    );

    await uploadPhoto(container);

    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ feet: 200 }),
      ),
    );
  });

  it("sends every drawn photo to the proposal in one save", async () => {
    const onSave = vi.fn();
    const { container } = renderEstimator({
      onSave,
      onShotsChange: vi.fn(),
      onClose: vi.fn(),
    });
    await uploadPhoto(container);
    await uploadPhoto(container);

    fireEvent.click(screen.getByRole("button", { name: /save 2 designs to proposal/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].shots).toHaveLength(2);
    expect(await screen.findByText(/Saved 2 designs to the proposal at/i)).toBeInTheDocument();
  });

  it("drops a removed photo from the totals and the strip", async () => {
    const onSave = vi.fn();
    const onShotsChange = vi.fn();
    const { container } = renderEstimator({
      onSave,
      onShotsChange,
      onClose: vi.fn(),
    });
    await uploadPhoto(container);
    await uploadPhoto(container);

    fireEvent.click(screen.getByRole("button", { name: /remove photo 2/i }));

    expect(shotTabs()).toHaveLength(1);
    expect(onShotsChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ photo: expect.anything() }),
    ]);
    // What the quote is measured from, not just what's on screen: the deleted
    // photo's 100 ft must leave with it.
    fireEvent.click(screen.getByRole("button", { name: /save to proposal/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({
      rooflineFeet: 100,
      shots: [expect.anything()],
    });
  });

  it("returns to the welcome screen when the last photo is removed", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    fireEvent.click(screen.getByRole("button", { name: /remove photo 1/i }));

    expect(container.querySelector("canvas")).toBeNull();
    expect(screen.getByText(/Design their lights on a photo/i)).toBeInTheDocument();
  });

  it("hands the photos to the host on the way back to the quote", async () => {
    // The editor unmounts when the rep steps back to the quote, so the host is
    // the only thing that can hold the work — saved or not.
    const onShotsChange = vi.fn();
    const { container } = renderEstimator({
      onSave: vi.fn(),
      onShotsChange,
      onClose: vi.fn(),
    });
    await uploadPhoto(container);
    await uploadPhoto(container);
    onShotsChange.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /back to quote/i }));

    expect(onShotsChange).toHaveBeenCalledWith([
      expect.objectContaining({ photo: expect.anything() }),
      expect.objectContaining({ photo: expect.anything() }),
    ]);
  });

  it("resumes every photo the host held from the last visit", async () => {
    // Leaving the designer for the quote and coming back must restore the whole
    // set, not just the shot that happened to be saved.
    const photo = {
      dataUrl: "data:image/png;base64,AAAA",
      width: 1200,
      height: 800,
    };
    renderEstimator({
      onSave: vi.fn(),
      onShotsChange: vi.fn(),
      onClose: vi.fn(),
      initial: {
        shots: [
          {
            id: "s1",
            photo,
            design: { runs: [], items: [], calibration: null },
            dusk: 0.52,
          },
          {
            id: "s2",
            photo,
            design: { runs: [], items: [], calibration: null },
            dusk: 0.52,
          },
        ],
      },
    });

    expect(shotTabs()).toHaveLength(2);
    expect(activeShotIndex()).toBe(0);
  });

  it("uses the server-project adapter without restoring or saving the workspace browser draft", async () => {
    const onLandscapeDraftChange = vi.fn();
    const photo = {
      dataUrl: "data:image/png;base64,AAAA",
      width: 1200,
      height: 800,
    };
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        activeShotId: "server-shot",
        shots: [
          {
            id: "server-shot",
            photo,
            design: { runs: [], items: [], calibration: null },
            dusk: 0.4,
          },
        ],
        updatedAt: "2026-08-11T09:00:00.000Z",
        activeWorkflowTab: "drawing",
        settings: {
          ...defaultLandscapeSettings(),
          paperSize: "arch-c",
          planFit: "cover",
          planOpacity: 0.5,
          legend: { visible: false, position: { x: 72, y: 48 }, scale: 1.2 },
          halosVisible: false,
          fixtureNumbersVisible: false,
          measurementsVisible: false,
          sourceVoltage: 15,
        },
        proposal: {
          ...defaultLandscapeProposal(),
          designIntent: "Warm entry sequence",
          showFixtureDetails: false,
        },
        procurement: {
          "fixture-1": {
            orderedQuantity: 4,
            receivedQuantity: 2,
            supplierNote: "ETA Friday",
          },
        },
        precon: {
          ...defaultLandscapePrecon(),
          leadInstaller: "Jordan",
          notes: "Protect copper roof",
        },
      },
      onLandscapeDraftChange,
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      resetKey: 0,
    };

    renderEstimator(undefined, "landscape", adapter);
    expect(await screen.findByLabelText("Top-down aerial lighting plan canvas")).toHaveAttribute(
      "data-viewport-policy",
      "locked",
    );
    expect(screen.getByRole("button", { name: "Replace aerial" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /sheet/i })).toHaveValue("arch-c");
    expect(screen.getByRole("button", { name: "Fixture #: Off" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Present" })).toBeInTheDocument();
    expect(screen.queryByText("Lighting plan")).not.toBeInTheDocument();
    expect(loadLandscapeDraft).not.toHaveBeenCalled();
    expect(saveLandscapeDraft).not.toHaveBeenCalled();
    expect(onLandscapeDraftChange).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Present" }));
    await user.click(await screen.findByRole("menuitem", { name: "Show original aerial" }));
    await waitFor(
      () =>
        expect(onLandscapeDraftChange).toHaveBeenCalledWith(
          expect.objectContaining({
            version: 2,
            activeShotId: "server-shot",
            shots: [expect.objectContaining({ id: "server-shot", dusk: 0 })],
            activeWorkflowTab: "drawing",
            settings: expect.objectContaining({
              paperSize: "arch-c",
              planFit: "cover",
              planOpacity: 0.5,
              halosVisible: false,
              fixtureNumbersVisible: false,
              measurementsVisible: false,
              sourceVoltage: 15,
              legend: { visible: false, position: { x: 72, y: 48 }, scale: 1.2 },
            }),
            proposal: expect.objectContaining({
              designIntent: "Warm entry sequence",
              showFixtureDetails: false,
            }),
            procurement: expect.objectContaining({
              "fixture-1": expect.objectContaining({ orderedQuantity: 4, receivedQuantity: 2 }),
            }),
            precon: expect.objectContaining({
              leadInstaller: "Jordan",
              notes: "Protect copper roof",
            }),
          }),
        ),
      { timeout: 1_500 },
    );
    expect(saveLandscapeDraft).not.toHaveBeenCalled();
  });

  it("adds, edits, persists, exports, and removes manual BOM lines without an aerial", async () => {
    const onLandscapeDraftChange = vi.fn();
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        activeShotId: null,
        activeWorkflowTab: "bom",
        shots: [],
        updatedAt: "2026-08-14T12:00:00.000Z",
      },
      onLandscapeDraftChange,
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      resetKey: 0,
    };
    renderEstimator(undefined, "landscape", adapter);

    const user = userEvent.setup();
    expect(screen.getByText(/No additional materials yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Supplier CSV" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Add line item" }));
    await user.type(screen.getByLabelText("BOM line item 1 description"), "Copper ground stake");
    await user.type(screen.getByLabelText("BOM line item 1 SKU"), "STAKE-CU");
    await user.clear(screen.getByLabelText("BOM line item 1 quantity"));
    await user.type(screen.getByLabelText("BOM line item 1 quantity"), "4");
    await user.selectOptions(screen.getByLabelText("BOM line item 1 unit"), "each");

    expect(screen.getByRole("button", { name: "Supplier CSV" })).toBeEnabled();
    await waitFor(() => {
      const latestDraft = onLandscapeDraftChange.mock.calls.at(-1)?.[0];
      expect(latestDraft?.bomLineItems).toEqual([
        expect.objectContaining({
          description: "Copper ground stake",
          sku: "STAKE-CU",
          quantity: 4,
          unit: "each",
        }),
      ]);
    });

    await user.click(
      screen.getByRole("button", { name: "Remove BOM line item 1: Copper ground stake" }),
    );
    expect(screen.queryByLabelText("BOM line item 1 description")).not.toBeInTheDocument();
    await waitFor(() => {
      const latestDraft = onLandscapeDraftChange.mock.calls.at(-1)?.[0];
      expect(latestDraft?.bomLineItems).toEqual([]);
    });
  });

  it("keeps an empty proposal focusable and guides the operator to add an aerial", async () => {
    const onLandscapeDraftChange = vi.fn();
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        activeShotId: null,
        activeWorkflowTab: "proposal",
        shots: [],
        updatedAt: "2026-08-14T12:00:00.000Z",
      },
      onLandscapeDraftChange,
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      resetKey: 0,
    };
    renderEstimator(undefined, "landscape", adapter);

    await waitFor(() => expect(onLandscapeDraftChange).toHaveBeenCalled(), { timeout: 1_500 });
    const quoteBuilder = screen.getByRole("region", {
      name: "Landscape Lighting Quote Builder",
    });
    expect(quoteBuilder).toHaveAttribute("id", "landscape-quote-builder");
    expect(quoteBuilder).toHaveAttribute("tabindex", "-1");
    expect(
      screen.getByRole("heading", { name: "Landscape Lighting Quote Builder" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload aerial plan" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Create draft quote" })).not.toBeInTheDocument();
  });

  it("prices Good, Better, and Best fixtures with a care plan and creates the quote here", async () => {
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 0,
      christmas_items: {},
      fixtures: { uplight: 2 },
      bistro_feet: 0,
    });
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue({
      ...PRICING,
      tier_order: ["good", "better", "best"],
      tiers: [
        {
          ["key"]: "good",
          label: "Good",
          tab: "Good",
          sections: [{ title: "Fixtures", item_ids: ["best-zd-up"] }],
        },
        {
          ["key"]: "better",
          label: "Better",
          tab: "Better",
          sections: [{ title: "Fixtures", item_ids: ["best-zd-up"] }],
        },
        {
          ["key"]: "best",
          label: "Best",
          tab: "Best",
          sections: [{ title: "Fixtures", item_ids: ["best-zd-up"] }],
        },
      ],
    } as Awaited<ReturnType<typeof salesWizardApi.getPricing>>);
    vi.mocked(salesWizardApi.preview).mockResolvedValue({
      title: "Patio lighting",
      tiers: [
        {
          ["key"]: "good",
          label: "Good",
          popular: false,
          lines: [
            {
              item_id: "best-zd-up",
              name: "ZD Uplight",
              quantity: 2,
              unit_price: 500,
              line_total: 1000,
              transformer: false,
            },
          ],
          pricing: {
            subtotal_net: 1000,
            overhead: 0,
            commission: 0,
            profit: 0,
            tax: 0,
            financed_total: 1000,
            cash_total: 950,
            monthly_payment: 84,
          },
        },
        {
          ["key"]: "better",
          label: "Better",
          popular: true,
          lines: [
            {
              item_id: "best-zd-up",
              name: "ZD Uplight",
              quantity: 2,
              unit_price: 700,
              line_total: 1400,
              transformer: false,
            },
          ],
          pricing: {
            subtotal_net: 1400,
            overhead: 0,
            commission: 0,
            profit: 0,
            tax: 0,
            financed_total: 1400,
            cash_total: 1330,
            monthly_payment: 117,
          },
        },
        {
          ["key"]: "best",
          label: "Best",
          popular: false,
          lines: [
            {
              item_id: "best-zd-up",
              name: "ZD Uplight",
              quantity: 2,
              unit_price: 900,
              line_total: 1800,
              transformer: false,
            },
          ],
          pricing: {
            subtotal_net: 1800,
            overhead: 0,
            commission: 0,
            profit: 0,
            tax: 0,
            financed_total: 1800,
            cash_total: 1710,
            monthly_payment: 150,
          },
        },
      ],
      selection: {
        selected_tier: "good",
        selected_financed_total: 1000,
        selected_cash_total: 950,
        deposit_due_now: 0,
      },
      care_plan: {
        fixture_count: 2,
        options: [
          {
            ["key"]: "essential",
            name: "Essential Care",
            price: 249,
            savings: 0,
            visits: 1,
            repair_discount: 10,
            popular: true,
            blurb: "Annual aiming and inspection",
          },
        ],
      },
      categories: ["landscape"],
      line_count: 1,
      services: [],
      mockups: [],
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.preview>>);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        activeShotId: "server-shot",
        shots: [
          {
            id: "server-shot",
            photo: { dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 },
            design: {
              runs: [],
              items: [
                {
                  id: "fixture-1",
                  productId: "fixture-uplight",
                  at: { x: 200, y: 220 },
                  sizePx: 30,
                },
              ],
              calibration: null,
            },
            dusk: 0.4,
          },
        ],
        updatedAt: "2026-08-11T09:00:00.000Z",
      },
      onLandscapeDraftChange: vi.fn(),
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      projectId: "project-1",
      projectName: "Patio lighting",
      contactName: "Pat Lee",
      contactId: 42,
      opportunityId: "opportunity-1",
      serviceLocationId: "service-location-1",
      installationShotId: "server-shot",
      onSelectInstallationShot: vi.fn().mockResolvedValue(undefined),
      flushBeforeProposal: vi.fn().mockResolvedValue(undefined),
      resetKey: 0,
    };

    renderEstimator(undefined, "landscape", adapter);
    await openProposalPreview();

    expect(await screen.findByRole("button", { name: /Good.*\$950\.00/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Better.*\$1,330\.00/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Best.*\$1,710\.00/i })).toBeInTheDocument();
    expect(screen.getAllByText("CRM price book")).toHaveLength(3);
    expect(screen.queryByText(/financed/i)).not.toBeInTheDocument();
    expect(screen.getByText("$500.00")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add line item" }));
    fireEvent.change(screen.getByPlaceholderText("Description"), {
      target: { value: "Core drill through masonry" },
    });
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "275.50" } });

    await waitFor(() =>
      expect(salesWizardApi.preview).toHaveBeenLastCalledWith(
        "ws_1",
        expect.objectContaining({
          contact_id: 42,
          opportunity_id: "opportunity-1",
          service_location_id: "service-location-1",
          lighting_project_id: "project-1",
          title: "Patio lighting",
          quantities: expect.arrayContaining([
            expect.objectContaining({ item_id: "best-zd-up", quantity: 2 }),
          ]),
          selected_tier: "good",
          care_plan_tier: null,
          care_count_manual: 2,
          additional_charges: [
            expect.objectContaining({
              description: "Core drill through masonry",
              net_amount: 275.5,
            }),
          ],
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /Better.*\$1,330\.00/i }));
    fireEvent.click(screen.getByRole("button", { name: /Essential Care.*\$249\.00\/year/i }));
    const createQuote = screen.getByRole("button", { name: "Create draft quote" });
    await waitFor(() => expect(createQuote).toBeEnabled());
    fireEvent.click(createQuote);

    await waitFor(() =>
      expect(salesWizardApi.save).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          pricing_source: "price_book",
          contact_id: 42,
          opportunity_id: "opportunity-1",
          service_location_id: "service-location-1",
          lighting_project_id: "project-1",
          title: "Patio lighting",
          quantities: expect.arrayContaining([
            expect.objectContaining({ item_id: "best-zd-up", quantity: 2 }),
          ]),
          selected_tier: "better",
          care_plan_tier: "essential",
          care_count_manual: 2,
          additional_charges: [
            expect.objectContaining({
              description: "Core drill through masonry",
              net_amount: 275.5,
            }),
          ],
        }),
      ),
    );
    expect(adapter.flushBeforeProposal).toHaveBeenCalled();
    expect(await screen.findByText(/Draft quote Q-1042 was created/i)).toBeInTheDocument();
  });

  it("requires and persists an installation-sheet selection before quoting", async () => {
    const onSelectInstallationShot = vi.fn().mockResolvedValue(undefined);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        activeShotId: "front",
        shots: [
          {
            id: "front",
            photo: { dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 },
            design: { runs: [], items: [], calibration: null },
            dusk: 0.4,
          },
        ],
        updatedAt: "2026-08-11T09:00:00.000Z",
      },
      onLandscapeDraftChange: vi.fn(),
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      projectId: "project-1",
      projectName: "Patio lighting",
      contactId: 42,
      installationShotId: null,
      onSelectInstallationShot,
      flushBeforeProposal: vi.fn().mockResolvedValue(undefined),
      resetKey: 0,
    };

    renderEstimator(undefined, "landscape", adapter);
    expect(
      await screen.findByRole("button", { name: "Use L-1 as installation sheet" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use L-1 as installation sheet" }));
    await waitFor(() => expect(onSelectInstallationShot).toHaveBeenCalledWith("front"));
    await openProposalPreview();
    expect(await screen.findByText(/Select and save an installation sheet/)).toBeInTheDocument();
  });

  it("can share and quote a line item with nothing drawn on the photo", async () => {
    // The standalone case: no roofline, no decor — just the rep's own line.
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 0,
      christmas_items: {},
      fixtures: {},
      bistro_feet: 0,
    });
    const { container } = renderEstimator();
    await uploadPhoto(container);

    const share = () => screen.getByRole("button", { name: /Save & share link only/i });
    expect(share()).toBeDisabled();

    await fillLineItem("Consultation", "75");

    await waitFor(() => expect(share()).toBeEnabled());
    fireEvent.click(share());
    await waitFor(() =>
      expect(estimatorApi.share).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          custom_lines: [expect.objectContaining({ label: "Consultation" })],
        }),
      ),
    );
  });
});
