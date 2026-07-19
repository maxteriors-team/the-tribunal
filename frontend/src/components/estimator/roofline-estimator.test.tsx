import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RooflineEstimator } from "@/components/estimator/roofline-estimator";
import { estimatorApi } from "@/lib/api/estimator";
import type { LinearFeetEstimateResult } from "@/types/estimate";

// Server pricing is always mocked — the component only ever sends feet/counts.
vi.mock("@/lib/api/estimator", () => ({
  estimatorApi: {
    estimate: vi.fn(),
    share: vi.fn(),
    deliver: vi.fn(),
    render: vi.fn(),
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

// The glow engine is exercised in render.test.ts; here it's a no-op so the
// canvas component mounts without a 2D context.
vi.mock("@/lib/estimator/render", () => ({
  drawScene: vi.fn(),
  itemHit: vi.fn(() => false),
  resizeHandlePos: vi.fn(() => ({ x: 0, y: 0 })),
}));

// jsdom can't produce traced geometry (getBoundingClientRect is all zeros), so
// force a measured design: hasDesign true + a fixed mapped payload. The mapping
// math itself is unit-tested in design.test.ts.
const MAPPED = { feet: 100, christmas_items: {} };
vi.mock("@/lib/estimator/design", () => ({
  designToEstimateInputs: vi.fn(() => MAPPED),
  hasDesign: vi.fn(() => true),
  designScale: vi.fn(() => ({ ftPerPx: 0.05, pxPerFt: 20, calibrated: false })),
  formatFeet: (n: number) => `${n} ft`,
}));

const ESTIMATE: LinearFeetEstimateResult = {
  feet: 100,
  permanent: { enabled: true, total: 3300, per_ft: 32 },
  christmas: {
    enabled: true,
    total: 900,
    per_ft: 6,
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

function stubCanvas() {
  // Returning null makes the canvas draw() bail cleanly (no jsdom "not
  // implemented" noise) — rendering is covered by render.test.ts.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
}

function renderEstimator() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RooflineEstimator workspaceId="ws_1" />
    </QueryClientProvider>,
  );
}

async function uploadPhoto(container: HTMLElement) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  const file = new File(["x"], "house.png", { type: "image/png" });
  fireEvent.change(input!, { target: { files: [file] } });
  await waitFor(() => expect(container.querySelector("canvas")).not.toBeNull());
}

describe("RooflineEstimator", () => {
  beforeEach(() => {
    stubCanvas();
    vi.mocked(estimatorApi.estimate).mockResolvedValue(ESTIMATE);
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "",
      token: "",
      contact_id: null,
      saved_to_customer: false,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({ ok: true, to: "" });
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

    // After upload: the tool palette + a drawable roofline product + estimate panel.
    expect(screen.getByRole("heading", { name: /^Tools$/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /C9 Roofline — Warm White/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Select & edit/i }),
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
});
