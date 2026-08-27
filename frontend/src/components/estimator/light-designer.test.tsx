import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  dominantPermanentComplexity,
  LightDesigner,
  type LandscapeProjectPersistenceAdapter,
  PERMANENT_COMPLEXITY_OPTIONS,
} from "@/components/estimator/light-designer";
import { estimatorApi } from "@/lib/api/estimator";
import { quotesApi } from "@/lib/api/quotes";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { designScale, designToEstimateInputs, hasDesign } from "@/lib/estimator/design";
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

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: {
    get: vi.fn(),
    deliver: vi.fn(),
  },
}));

// The workspace price book + pricing config drive the landscape fixture types.
vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    listCatalog: vi.fn(),
    getPricing: vi.fn(),
    preview: vi.fn(),
    inventoryAvailability: vi.fn(),
    save: vi.fn(),
    deliver: vi.fn(),
  },
}));

const quoteEditDialogProps = vi.hoisted(() => vi.fn());

vi.mock("@/components/quotes/quote-edit-dialog", () => ({
  QuoteEditDialog: (props: { open: boolean; quote: { number: string } | null }) => {
    quoteEditDialogProps(props);
    return props.open ? <div role="dialog" aria-label="Quote payment terms" /> : null;
  },
}));

vi.mock("@/lib/estimator/landscape-draft", () => ({
  createLandscapeDraft: vi.fn(
    (shots, activeShotId, updatedAt, proposal, liveState, projectType) => ({
      version: 2,
      projectType: projectType ?? "landscape",
      activeShotId,
      shots,
      updatedAt: updatedAt ?? "2026-08-11T10:00:00.000Z",
      ...liveState,
      ...(proposal ? { proposal: { ...liveState?.proposal, ...proposal } } : {}),
    }),
  ),
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
  proposal_side: "comparison",
  discount_amount: 0,
  permanent: {
    enabled: true,
    total: 3300,
    subtotal: 3300,
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
    subtotal: 900,
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

// Real catalog products resolve to package SKUs exactly as they do in production.
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
  {
    id: "id-transformer",
    workspace_id: "ws_1",
    name: "Luxor Transformer",
    description: null,
    sku: "best-transformer",
    kind: "product",
    unit_price: 900,
    taxable: true,
    is_active: true,
    attributes: { transformer: true },
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
  focus: "all" | "landscape" | "permanent" = "all",
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
    vi.mocked(designScale).mockReturnValue({ ftPerPx: 0.05, pxPerFt: 20, calibrated: false });
    vi.mocked(hasDesign).mockReturnValue(true);
    vi.mocked(salesWizardApi.listCatalog).mockResolvedValue(PRICE_BOOK);
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue(PRICING);
    vi.mocked(salesWizardApi.inventoryAvailability).mockResolvedValue({
      connected: true,
      is_available: false,
      items: [
        {
          sku: "PATH",
          description: "Path light",
          inventory_behavior: "consumable",
          required_quantity: 2,
          item_id: "item-path",
          item_name: "Path light",
          unit_of_measure: "each",
          tracked: true,
          is_counted: true,
          quantity_on_hand: 1,
          quantity_reserved: 0,
          quantity_deployed: 0,
          available_to_promise: 1,
          shortage_quantity: 1,
          is_available: false,
        },
      ],
    });
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
      inventory_availability: {
        has_requirements: true,
        has_shortages: true,
        shortage_items: 1,
        not_counted_items: 0,
        untracked_items: 0,
        items: [
          {
            sku: "PATH",
            inventory_item_name: "Path light",
            required_quantity: 2,
            quantity_on_hand: 1,
            shortfall: 1,
            unit_of_measure: "each",
            status: "shortage",
          },
        ],
      },
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.preview>>);
    vi.mocked(salesWizardApi.deliver).mockResolvedValue({
      ok: true,
      channel: "email",
      to: "pat@example.com",
    });
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
    vi.mocked(estimatorApi.render).mockResolvedValue({
      image: "data:image/jpeg;base64,AI-RENDER",
    });
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
      id: "quote-1",
      number: "QUO-000007",
      deposit_amount: null,
    } as Awaited<ReturnType<typeof estimatorApi.createQuote>>);
    vi.mocked(quotesApi.deliver).mockResolvedValue({
      ok: true,
      channel: "email",
      to: "pat@example.com",
    });
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
    const { container } = renderEstimator("landscape", undefined, {
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
    await userEvent.click(wireTool);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Wire" })).toHaveAttribute("aria-pressed", "true"),
    );

    const uplightTool = await screen.findByRole("button", { name: /^Uplight:/i });
    await userEvent.click(uplightTool);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Uplight:/i })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
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
    renderEstimator("landscape");
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
    enableService(/^Christmas$/);
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

  it("flushes and links a permanent server project before creating its quote", async () => {
    const flushBeforeProposal = vi.fn().mockResolvedValue(undefined);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "permanent",
        activeShotId: "front",
        shots: [
          {
            id: "front",
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
        updatedAt: "2026-08-26T12:00:00.000Z",
      },
      onLandscapeDraftChange: vi.fn(),
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      projectId: "permanent-project",
      projectName: "Pat permanent roofline",
      contactName: "Pat Lee",
      contactId: 42,
      flushBeforeProposal,
      resetKey: 0,
    };
    renderEstimator("permanent", adapter);

    fireEvent.click(await screen.findByRole("button", { name: /Create permanent quote/i }));

    await waitFor(() => expect(flushBeforeProposal).toHaveBeenCalledOnce());
    expect(estimatorApi.createQuote).toHaveBeenCalledWith(
      "ws_1",
      expect.objectContaining({
        side: "permanent",
        lighting_project_id: "permanent-project",
        proposal_preview: {
          shot_id: "front",
          image: "data:image/jpeg;base64,LIT",
        },
      }),
    );
  });

  it("keeps permanent proposal creation disabled until the selected shot has a design", async () => {
    const actualDesign = await vi.importActual<typeof import("@/lib/estimator/design")>(
      "@/lib/estimator/design",
    );
    vi.mocked(hasDesign).mockImplementation(actualDesign.hasDesign);
    const flushBeforeProposal = vi.fn().mockResolvedValue(undefined);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "permanent",
        activeShotId: "front",
        shots: [
          {
            id: "front",
            photo: { dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 },
            design: { runs: [], items: [], calibration: null },
            dusk: 0.4,
          },
        ],
        updatedAt: "2026-08-26T12:00:00.000Z",
      },
      onLandscapeDraftChange: vi.fn(),
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      projectId: "permanent-project",
      projectName: "Pat permanent roofline",
      contactName: "Pat Lee",
      contactId: 42,
      flushBeforeProposal,
      resetKey: 0,
    };
    renderEstimator("permanent", adapter);

    const createButton = await screen.findByRole("button", { name: /Create permanent quote/i });
    await waitFor(() => expect(createButton).toBeDisabled());
    fireEvent.click(createButton);
    expect(flushBeforeProposal).not.toHaveBeenCalled();
    expect(estimatorApi.createQuote).not.toHaveBeenCalled();
  });

  it("offers Aerial Pics as the fixed 1.5× Light Designer run option", () => {
    expect(PERMANENT_COMPLEXITY_OPTIONS).toContainEqual({
      value: "aerial",
      label: "Aerial Pics · 1.5×",
    });
  });

  it("uses the hardest measured run as the scalar complexity fallback", () => {
    expect(dominantPermanentComplexity({ aerial: 100, easy: 0, standard: 0, complex: 0 })).toBe(
      "aerial",
    );
    expect(dominantPermanentComplexity({ aerial: 0, easy: 100, standard: 0, complex: 0 })).toBe(
      "easy",
    );
    expect(dominantPermanentComplexity({ aerial: 0, easy: 0, standard: 0, complex: 100 })).toBe(
      "complex",
    );
    expect(dominantPermanentComplexity({ aerial: 50, easy: 50, standard: 0, complex: 0 })).toBe(
      "easy",
    );
    expect(dominantPermanentComplexity({ aerial: 0, easy: 50, standard: 0, complex: 50 })).toBe(
      "complex",
    );
    expect(dominantPermanentComplexity({ aerial: 0, easy: 0, standard: 0, complex: 0 })).toBe(
      "standard",
    );
  });

  it("hides the previous total while a pricing change is being recomputed", async () => {
    let resolveReprice: ((value: LinearFeetEstimateResult) => void) | undefined;
    vi.mocked(estimatorApi.estimate).mockImplementation(async (_workspaceId, request) => {
      if (request.discount_amount === 500) {
        return new Promise<LinearFeetEstimateResult>((resolve) => {
          resolveReprice = resolve;
        });
      }
      return {
        ...ESTIMATE,
        proposal_side: request.proposal_side,
        discount_amount: request.discount_amount,
      };
    });
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await waitFor(() => expect(container.querySelector(".ep-totals")).not.toBeNull());
    expect(container.querySelector(".ep-totals")).toHaveTextContent("$3,300");

    fireEvent.change(screen.getByLabelText(/Overall proposal discount/i), {
      target: { value: "500" },
    });
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ discount_amount: 500 }),
      ),
    );
    expect(screen.getByText("Pricing…")).toBeInTheDocument();
    expect(container.querySelector(".ep-totals")).toBeNull();

    await act(async () => {
      resolveReprice?.({
        ...ESTIMATE,
        discount_amount: 500,
        permanent: { ...ESTIMATE.permanent, total: 2800 },
      });
    });
    await waitFor(() => expect(container.querySelector(".ep-totals")).not.toBeNull());
    expect(container.querySelector(".ep-totals")).toHaveTextContent("$2,800");
  });

  it("adds a deposit percentage to the permanent quote and shows the payment path", async () => {
    vi.mocked(estimatorApi.createQuote).mockResolvedValueOnce({
      id: "quote-1",
      number: "QUO-000007",
      deposit_amount: 990,
    } as Awaited<ReturnType<typeof estimatorApi.createQuote>>);
    const { container } = renderEstimator();
    await uploadPhoto(container);

    fireEvent.change(await screen.findByRole("spinbutton", { name: /Permanent quote deposit/i }), {
      target: { value: "30" },
    });
    expect(screen.getByText("$990.00 due when the customer approves.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Create permanent quote/i }));

    await waitFor(() =>
      expect(estimatorApi.createQuote).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({
          side: "permanent",
          feet: 100,
          deposit_percentage: 30,
        }),
      ),
    );
    expect(await screen.findByText(/\$990.00 deposit/i)).toBeInTheDocument();
    expect(screen.getByText(/Customer approval opens secure card checkout/i)).toBeInTheDocument();
  });

  it("creates and emails the actionable permanent proposal in one click", async () => {
    vi.mocked(quotesApi.deliver).mockResolvedValue({
      ok: true,
      channel: "email",
      to: "buyer@example.com",
    });

    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Permanent$/);

    const emailBtn = screen.getByRole("button", { name: /Email proposal/i });
    expect(emailBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Customer email/i), {
      target: { value: "buyer@example.com" },
    });
    expect(emailBtn).toBeEnabled();
    expect(screen.getByText(/customer accepts it there/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save & share link only/i })).toHaveTextContent(
      /no approval or payment/i,
    );

    fireEvent.click(emailBtn);

    await waitFor(() =>
      expect(estimatorApi.createQuote).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ side: "permanent", client_email: "buyer@example.com" }),
      ),
    );
    await waitFor(() =>
      expect(quotesApi.deliver).toHaveBeenCalledWith(
        "ws_1",
        "quote-1",
        "email",
        "buyer@example.com",
      ),
    );
    expect(estimatorApi.share).not.toHaveBeenCalled();
    expect(estimatorApi.deliver).not.toHaveBeenCalled();
    expect(await screen.findByText(/Emailed to buyer@example\.com/i)).toBeInTheDocument();
  });

  it("creates and texts the actionable permanent proposal in one click", async () => {
    vi.mocked(quotesApi.deliver).mockResolvedValue({
      ok: true,
      channel: "sms",
      to: "+15551234567",
    });

    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Permanent$/);

    const textBtn = screen.getByRole("button", { name: /Text proposal/i });
    expect(textBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Customer phone/i), {
      target: { value: "+15551234567" },
    });
    expect(textBtn).toBeEnabled();

    fireEvent.click(textBtn);

    await waitFor(() =>
      expect(quotesApi.deliver).toHaveBeenCalledWith(
        "ws_1",
        "quote-1",
        "sms",
        "+15551234567",
      ),
    );
    expect(estimatorApi.share).not.toHaveBeenCalled();
    expect(estimatorApi.deliver).not.toHaveBeenCalled();
    expect(await screen.findByText(/Texted to \+15551234567/i)).toBeInTheDocument();
  });

  it("surfaces quote delivery errors for permanent proposals", async () => {
    // The server's refusals are actionable; preserve them instead of replacing
    // them with a generic retry sentence.
    vi.mocked(quotesApi.deliver).mockRejectedValue(
      Object.assign(new Error("Request failed"), {
        response: {
          status: 422,
          data: {
            detail: "No SMS-enabled phone number in this workspace — add one under Settings.",
          },
        },
      }),
    );

    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Permanent$/);
    fireEvent.change(screen.getByLabelText(/Customer phone/i), {
      target: { value: "+15551234567" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Text proposal/i }));

    expect(await screen.findByText(/add one under Settings/i)).toBeInTheDocument();
  });

  it("retries delivery without creating a duplicate permanent quote", async () => {
    vi.mocked(quotesApi.deliver)
      .mockRejectedValueOnce(new Error("Provider unavailable"))
      .mockResolvedValueOnce({
        ok: true,
        channel: "email",
        to: "buyer@example.com",
      });

    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Permanent$/);
    fireEvent.change(screen.getByLabelText(/Customer email/i), {
      target: { value: "buyer@example.com" },
    });

    const emailButton = screen.getByRole("button", { name: /Email proposal/i });
    fireEvent.click(emailButton);
    expect(await screen.findByText(/Provider unavailable/i)).toBeInTheDocument();

    fireEvent.click(emailButton);
    expect(await screen.findByText(/Emailed to buyer@example\.com/i)).toBeInTheDocument();
    expect(estimatorApi.createQuote).toHaveBeenCalledTimes(1);
    expect(quotesApi.deliver).toHaveBeenCalledTimes(2);
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

  it("shares a discounted permanent proposal without exposing seasonal pricing", async () => {
    vi.mocked(estimatorApi.estimate).mockImplementation(async (_workspaceId, request) => ({
      ...ESTIMATE,
      proposal_side: request.proposal_side,
      discount_amount: request.discount_amount,
      permanent: {
        ...ESTIMATE.permanent,
        total: Math.max(0, ESTIMATE.permanent.subtotal - request.discount_amount),
      },
    }));
    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Permanent$/);

    fireEvent.change(screen.getByLabelText(/Overall proposal discount/i), {
      target: { value: "500" },
    });
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ proposal_side: "permanent", discount_amount: 500 }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /Client preview/i }));
    const preview = await waitFor(() => {
      const element = container.querySelector(".est-client-preview");
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(preview).toHaveTextContent("$2,800");
    expect(preview).not.toHaveTextContent("$900");

    fireEvent.click(screen.getByRole("button", { name: /Rep view/i }));
    fireEvent.change(screen.getByLabelText(/Customer email/i), {
      target: { value: "buyer@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Email proposal/i }));
    await waitFor(() =>
      expect(estimatorApi.createQuote).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ proposal_side: "permanent", discount_amount: 500 }),
      ),
    );
    expect(estimatorApi.share).not.toHaveBeenCalled();
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
    enableService(/^Permanent$/);

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

  it("drops a removed photo from the totals and the strip", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);
    await uploadPhoto(container);

    fireEvent.click(screen.getByRole("button", { name: /remove photo 2/i }));

    expect(shotTabs()).toHaveLength(1);
    await waitFor(() =>
      expect(estimatorApi.estimate).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ feet: 100 }),
      ),
    );
  });

  it("returns to the welcome screen when the last photo is removed", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    fireEvent.click(screen.getByRole("button", { name: /remove photo 1/i }));

    expect(container.querySelector("canvas")).toBeNull();
    expect(screen.getByText(/Design their lights on a photo/i)).toBeInTheDocument();
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
        projectType: "landscape",
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

    renderEstimator("landscape", adapter);
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

  it("restores and saves permanent server projects without browser draft storage", async () => {
    const onLandscapeDraftChange = vi.fn();
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "permanent",
        activeShotId: "permanent-shot",
        shots: [
          {
            id: "permanent-shot",
            photo: {
              dataUrl: "data:image/png;base64,AAAA",
              width: 1200,
              height: 800,
            },
            design: { runs: [], items: [], calibration: null },
            dusk: 0.4,
          },
        ],
        updatedAt: "2026-08-11T09:00:00.000Z",
      },
      onLandscapeDraftChange,
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      projectId: "permanent-project",
      projectName: "Pat permanent roofline",
      contactName: "Pat Lee",
      contactId: 42,
      resetKey: 0,
    };
    const { container } = renderEstimator("permanent", adapter);

    expect(
      await screen.findByLabelText("Property photo lighting design canvas"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Services in this design" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /Permanent LED Roofline/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Uplight/i })).not.toBeInTheDocument();

    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(input!, {
      target: { files: [new File(["second"], "second-house.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(onLandscapeDraftChange).toHaveBeenCalled(), { timeout: 1_500 });
    expect(onLandscapeDraftChange.mock.calls.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        projectType: "permanent",
        shots: expect.arrayContaining([expect.objectContaining({ id: expect.any(String) })]),
      }),
    );
    expect(loadLandscapeDraft).not.toHaveBeenCalled();
    expect(saveLandscapeDraft).not.toHaveBeenCalled();
  });

  it("adds, edits, persists, exports, and removes manual BOM lines without an aerial", async () => {
    const onLandscapeDraftChange = vi.fn();
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "landscape",
        activeShotId: null,
        activeWorkflowTab: "bom",
        shots: [],
        updatedAt: "2026-08-14T12:00:00.000Z",
      },
      onLandscapeDraftChange,
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      resetKey: 0,
    };
    renderEstimator("landscape", adapter);

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
        projectType: "landscape",
        activeShotId: null,
        activeWorkflowTab: "proposal",
        shots: [],
        updatedAt: "2026-08-14T12:00:00.000Z",
      },
      onLandscapeDraftChange,
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      resetKey: 0,
    };
    renderEstimator("landscape", adapter);

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
          sections: [{ title: "Fixtures", item_ids: ["best-zd-up", "best-transformer"] }],
        },
        {
          ["key"]: "better",
          label: "Better",
          tab: "Better",
          sections: [{ title: "Fixtures", item_ids: ["best-zd-up", "best-transformer"] }],
        },
        {
          ["key"]: "best",
          label: "Best",
          tab: "Best",
          sections: [{ title: "Fixtures", item_ids: ["best-zd-up", "best-transformer"] }],
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
      inventory_availability: {
        has_requirements: true,
        has_shortages: true,
        shortage_items: 1,
        not_counted_items: 0,
        untracked_items: 0,
        items: [
          {
            sku: "PATH",
            inventory_item_name: "Path light",
            required_quantity: 2,
            quantity_on_hand: 1,
            shortfall: 1,
            unit_of_measure: "each",
            status: "shortage",
          },
        ],
      },
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.preview>>);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "landscape",
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
                {
                  id: "transformer-1",
                  productId: "fixture-transformer",
                  at: { x: 300, y: 320 },
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

    renderEstimator("landscape", adapter);
    await openProposalPreview();

    expect(await screen.findByRole("heading", { name: "Patio lighting" })).toBeVisible();
    expect(screen.getByText(/presentation-ready view of Pat Lee’s proposed/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Make this look real" }));
    const aiDialog = await screen.findByRole("dialog", { name: "AI aerial render" });
    expect(within(aiDialog).getByRole("textbox", { name: "Describe the finish" })).toHaveValue(
      "Make this look real.",
    );
    fireEvent.click(within(aiDialog).getByRole("button", { name: "Generate client render" }));
    expect(await within(aiDialog).findByAltText("AI aerial night render")).toHaveAttribute(
      "src",
      "data:image/jpeg;base64,AI-RENDER",
    );
    fireEvent.click(within(aiDialog).getAllByRole("button", { name: "Close" })[0]);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "AI aerial render" })).toBeNull(),
    );
    expect(screen.getByAltText("AI-generated lighting concept for Patio lighting")).toHaveAttribute(
      "src",
      "data:image/jpeg;base64,AI-RENDER",
    );

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
            expect.objectContaining({ item_id: "best-transformer", quantity: 1 }),
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
    expect(screen.getByText("Inventory check")).toBeVisible();
    expect(screen.getByText("1 required item is short.")).toBeVisible();
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
          night_preview: {
            image: "data:image/jpeg;base64,AI-RENDER",
            images: ["data:image/jpeg;base64,AI-RENDER"],
            services: ["landscape"],
          },
          quantities: expect.arrayContaining([
            expect.objectContaining({ item_id: "best-zd-up", quantity: 2 }),
          ]),
          selected_tier: "better",
          customer_can_select_package: false,
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
    expect(screen.getByText(/customer link is locked to the highlighted fixture package/i)).toBeVisible();
    expect(screen.getByText("Collect payment in three steps")).toBeVisible();
    expect(screen.getByText(/Set the deposit due when the customer accepts/i)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open quote & preview payment page" })).toHaveAttribute(
      "href",
      "/quotes",
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Set deposit & payment terms" }));

    expect(await screen.findByRole("dialog", { name: "Quote payment terms" })).toBeVisible();
    await waitFor(() =>
      expect(quoteEditDialogProps).toHaveBeenLastCalledWith(
        expect.objectContaining({
          open: true,
          quote: expect.objectContaining({ number: "Q-1042" }),
        }),
      ),
    );
  });

  it("creates and emails a clear Bistro-only estimate from measured runs and pole markers", async () => {
    vi.mocked(designScale).mockReturnValue({ ftPerPx: 1, pxPerFt: 1, calibrated: true });
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 0,
      christmas_items: {},
      fixtures: {},
      bistro_feet: 312.5,
    });
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue({
      ...PRICING,
      bistro: {
        enabled: true,
        minimum: 0,
        temporary: {
          label: "Temporary Bistro Lighting",
          lights_per_ft: 18,
          poles_each: 350,
        },
        permanent: {
          label: "Permanent Bistro Lighting",
          lights_per_ft: 22,
          poles_each: 350,
        },
      },
    } as Awaited<ReturnType<typeof salesWizardApi.getPricing>>);
    vi.mocked(salesWizardApi.preview).mockResolvedValue({
      title: "Permanent Bistro estimate",
      tiers: [
        {
          key: "best",
          label: "Best",
          popular: true,
          lines: [],
          pricing: {
            subtotal_net: 0,
            overhead: 0,
            commission: 0,
            profit: 0,
            tax: 0,
            financed_total: 0,
            cash_total: 0,
            monthly_payment: 0,
          },
        },
      ],
      selection: {
        selected_tier: "best",
        selected_financed_total: 0,
        selected_cash_total: 0,
        deposit_due_now: 0,
      },
      bistro: {
        pricing_mode: "installation",
        feet: 312.5,
        product: "installation",
        tier: "",
        per_ft: 0,
        hardware: 0,
        minimum: 0,
        lights_cost: 7725,
        poles_cost: 787,
        raw_total: 8512,
        total: 8512,
        min_applied: false,
        ordered_ft: 312.5,
        installations: [
          {
            installation: "permanent",
            label: "Permanent Bistro Lighting",
            feet: 312.5,
            pole_count: 2,
            lights_per_ft: 22,
            poles_each: 350,
            lights_cost: 7725,
            poles_cost: 787,
            total: 8512,
          },
        ],
      },
      care_plan: { fixture_count: 0, options: [] },
      categories: ["landscape", "bistro"],
      line_count: 1,
      services: [],
      mockups: [],
      grand_financed_total: 8512,
      grand_cash_total: 7576,
      grand_monthly_payment: 0,
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.preview>>);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "landscape",
        activeShotId: "patio",
        shots: [
          {
            id: "patio",
            photo: { dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 },
            design: {
              calibration: {
                a: { x: 0, y: 0 },
                b: { x: 100, y: 0 },
                feet: 100,
              },
              runs: [
                {
                  id: "bistro-run-1",
                  productId: "bistro-permanent-layout",
                  points: [
                    { x: 0, y: 100 },
                    { x: 312.5, y: 100 },
                  ],
                  colors: ["#f7e7b2"],
                  spacingIn: 15,
                },
              ],
              items: [
                {
                  id: "pole-1",
                  productId: "bistro-support-pole",
                  bistroRunId: "bistro-run-1",
                  at: { x: 75, y: 100 },
                  sizePx: 12,
                },
                {
                  id: "pole-2",
                  productId: "bistro-support-pole",
                  bistroRunId: "bistro-run-1",
                  at: { x: 250, y: 100 },
                  sizePx: 12,
                },
              ],
              planImages: [],
            },
            dusk: 0.4,
          },
        ],
        updatedAt: "2026-08-25T12:00:00.000Z",
      },
      onLandscapeDraftChange: vi.fn(),
      persistenceStatus: { state: "saved", label: "Saved to Tribunal" },
      projectId: "project-bistro",
      projectName: "Permanent Bistro estimate",
      contactName: "Pat Lee",
      contactId: 42,
      installationShotId: "patio",
      onSelectInstallationShot: vi.fn().mockResolvedValue(undefined),
      flushBeforeProposal: vi.fn().mockResolvedValue(undefined),
      resetKey: 0,
    };

    renderEstimator("landscape", adapter);
    await openProposalPreview();
    expect(await screen.findByText("Bistro lighting layout")).toBeVisible();
    expect(screen.getByRole("region", { name: "Bistro lighting run schedule" })).toHaveTextContent(
      "313 ft",
    );

    await waitFor(() =>
      expect(salesWizardApi.preview).toHaveBeenLastCalledWith(
        "ws_1",
        expect.objectContaining({
          quantities: [],
          bistro: expect.objectContaining({
            runs: [{ installation: "permanent", feet: 312.5, pole_count: 2 }],
          }),
        }),
      ),
    );
    expect(screen.getByText("Permanent Bistro Lighting lights")).toBeVisible();
    expect(screen.getByText("2 marked poles")).toBeVisible();
    expect(
      screen.getByText("Bistro estimate total").parentElement?.parentElement,
    ).toHaveTextContent("$8,512.00");

    const createQuote = screen.getByRole("button", { name: "Create draft quote" });
    expect(createQuote).toBeEnabled();
    fireEvent.click(createQuote);
    expect(await screen.findByText(/Draft quote Q-1042 was created/i)).toBeVisible();

    expect(screen.getByText(/customer link is locked to the highlighted fixture package/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Email selected package" }));
    await waitFor(() =>
      expect(salesWizardApi.deliver).toHaveBeenNthCalledWith(1, "ws_1", "quote-1", "email"),
    );
    expect(await screen.findByText("Proposal emailed to pat@example.com.")).toBeVisible();

    vi.mocked(salesWizardApi.deliver).mockResolvedValueOnce({
      ok: true,
      channel: "sms",
      to: "+15551234567",
    });
    fireEvent.click(screen.getByRole("button", { name: "Text selected package" }));
    await waitFor(() =>
      expect(salesWizardApi.deliver).toHaveBeenNthCalledWith(2, "ws_1", "quote-1", "sms"),
    );
    expect(await screen.findByText("Proposal texted to +15551234567.")).toBeVisible();
  });

  it("requires and persists an installation-sheet selection before quoting", async () => {
    vi.mocked(designToEstimateInputs).mockReturnValue({
      feet: 0,
      christmas_items: {},
      fixtures: { uplight: 2 },
      bistro_feet: 0,
    });
    const onSelectInstallationShot = vi.fn().mockResolvedValue(undefined);
    const adapter: LandscapeProjectPersistenceAdapter = {
      initialDraft: {
        version: 2,
        projectType: "landscape",
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

    renderEstimator("landscape", adapter);
    expect(
      await screen.findByRole("button", { name: "Use L-1 as installation sheet" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use L-1 as installation sheet" }));
    await waitFor(() => expect(onSelectInstallationShot).toHaveBeenCalledWith("front"));
    await openProposalPreview();
    await waitFor(() =>
      expect(salesWizardApi.preview).toHaveBeenLastCalledWith(
        "ws_1",
        expect.objectContaining({ lighting_project_id: null }),
      ),
    );
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
    enableService(/^Permanent$/);

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
