import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LightDesigner } from "@/components/estimator/light-designer";
import type { DesignerProposalHost } from "@/components/estimator/proposal-host";
import { estimatorApi } from "@/lib/api/estimator";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { designToEstimateInputs } from "@/lib/estimator/design";
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
  },
}));

// jsdom can't decode images or drive a real canvas, so mock the photo loader:
// upload resolves a fixed PhotoInfo and the canvas gets a fake decoded image.
vi.mock("@/lib/estimator/photo", () => ({
  fileToPhoto: vi
    .fn()
    .mockResolvedValue({ dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 }),
  loadImage: vi.fn().mockResolvedValue({ naturalWidth: 1200, naturalHeight: 800 }),
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
vi.mock("@/lib/estimator/design", () => ({
  designToEstimateInputs: vi.fn(() => MAPPED),
  hasDesign: vi.fn(() => true),
  designScale: vi.fn(() => ({ ftPerPx: 0.05, pxPerFt: 20, calibrated: false })),
  formatFeet: (n: number) => `${n} ft`,
}));

const ESTIMATE: LinearFeetEstimateResult = {
  feet: 100,
  permanent: { enabled: true, total: 3300, per_ft: 32, roofline_cost: 3200 },
  christmas: {
    enabled: true,
    total: 900,
    per_ft: 6,
    roofline_cost: 600,
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

function renderEstimator(proposal?: DesignerProposalHost) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LightDesigner workspaceId="ws_1" proposal={proposal} />
    </QueryClientProvider>,
  );
}

async function uploadPhoto(container: HTMLElement) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  const file = new File(["x"], "house.png", { type: "image/png" });
  fireEvent.change(input!, { target: { files: [file] } });
  await waitFor(() => expect(container.querySelector("canvas")).not.toBeNull());
}

/**
 * Turn a service on. The palette only carries the selected services, so a test
 * that expects Christmas decor has to opt into Christmas first — same as a rep.
 */
function enableService(name: RegExp) {
  fireEvent.click(screen.getByRole("button", { name }));
}

describe("LightDesigner", () => {
  beforeEach(() => {
    stubCanvas();
    // Reset the design mapping each test; landscape cases override it.
    vi.mocked(designToEstimateInputs).mockReturnValue(MAPPED);
    vi.mocked(salesWizardApi.listCatalog).mockResolvedValue(PRICE_BOOK);
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue(PRICING);
    vi.mocked(estimatorApi.estimate).mockResolvedValue(ESTIMATE);
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "",
      token: "",
      contact_id: null,
      saved_to_customer: false,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({ ok: true, to: "" });
    vi.mocked(estimatorApi.createQuote).mockResolvedValue({
      number: "QUO-000007",
    } as Awaited<ReturnType<typeof estimatorApi.createQuote>>);
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
    expect(
      screen.getByRole("button", { name: /Select & edit/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /^Uplight/i }),
    ).toBeInTheDocument();

    // Christmas is a separate service: its products appear once it's toggled on.
    expect(
      screen.queryByRole("button", { name: /C9 Roofline — Warm White/i }),
    ).toBeNull();
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

  it("derives the decor palette from the workspace christmas catalog", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Christmas$/);

    // The `each` wreath category becomes a placeable decor product.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Wreath \(up to 36 in\)/i }),
      ).toBeInTheDocument(),
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
    expect(
      screen.getByRole("button", { name: /Save & share link only/i }),
    ).toBeInTheDocument();

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
    expect(
      await screen.findByRole("button", { name: /Essential/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Middle/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Premier/i })).toBeInTheDocument();

    // No explicit pick yet → the most-inclusive package (Premier) is the default,
    // so the seasonal headline shows its total, not the à la carte christmas total.
    const grandRow = () =>
      container.querySelector(".ep-total-grand") as HTMLElement;
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
    fireEvent.click(
      screen.getByRole("button", { name: /Save & share link only/i }),
    );
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
    expect(
      screen.getByRole("button", { name: /Create permanent quote/i }),
    ).toBeInTheDocument();

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
    expect(
      await screen.findByText(/Quote QUO-000007 created/i),
    ).toBeInTheDocument();
  });

  it("converts the permanent side when the permanent quote button is used", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);

    fireEvent.click(
      await screen.findByRole("button", { name: /Create permanent quote/i }),
    );

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
      ),
    );
    expect(
      await screen.findByText(/Sent to buyer@example\.com/i),
    ).toBeInTheDocument();
  });

  // ── Quote Builder host: the one photo tool, embedded in the wizard ────────

  it("swaps the standalone share flow for save-to-proposal when the Quote Builder hosts it", async () => {
    const proposal: DesignerProposalHost = {
      onSave: vi.fn(),
      onPhotoChange: vi.fn(),
      onClose: vi.fn(),
    };
    const { container } = renderEstimator(proposal);
    await uploadPhoto(container);

    expect(proposal.onPhotoChange).toHaveBeenCalledWith(
      expect.objectContaining({ width: 1200 }),
    );
    expect(
      screen.getByRole("button", { name: /save to proposal/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /back to quote/i }),
    ).toBeInTheDocument();
    // The wizard owns the customer and the quote, so the standalone share and
    // convert flows stay out of the way.
    expect(screen.queryByText("Save to customer")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /client preview/i }),
    ).not.toBeInTheDocument();
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
      onPhotoChange: vi.fn(),
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
        image: "data:image/jpeg;base64,LIT",
        fixtures: { uplight: 4 },
        services: ["landscape"],
        rooflineFeet: 100,
        bistroFeet: 32,
      }),
    );
    expect(
      await screen.findByText(/Saved to the proposal at/i),
    ).toBeInTheDocument();
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
      expect(container.querySelector(".ep-line-sku")?.textContent).toBe(
        "ZD Uplight · best-zd-up",
      ),
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

    expect(
      await screen.findByText(/doesn’t include downlight/i),
    ).toBeInTheDocument();
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
      expect(container.querySelector(".est-client-preview")).toHaveClass(
        "cmp-festive",
      ),
    );
  });

  it("gives each selected service its own client-facing value propositions", async () => {
    const { container } = renderEstimator();
    await uploadPhoto(container);
    enableService(/^Christmas$/);
    fireEvent.click(screen.getByRole("button", { name: /client preview/i }));

    // Landscape leads with the chosen package's own point; Christmas argues its
    // own case rather than sharing one blended list.
    expect(
      await screen.findByText("Architectural Landscape Lighting"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Seasonal Christmas Lighting"),
    ).toBeInTheDocument();
    expect(screen.getByText("Color change from your phone")).toBeInTheDocument();
    expect(
      screen.getByText("Takedown and storage included"),
    ).toBeInTheDocument();
    // Permanent isn't being sold here, so its pitch stays off the page.
    expect(screen.queryByText("Never hang lights again")).toBeNull();
  });
});
