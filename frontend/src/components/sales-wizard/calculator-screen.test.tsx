/**
 * The Quote Builder's flow, in the order a quote is actually sold.
 *
 * Two things are pinned here because both were previously unprotected and both
 * fail silently:
 *
 * 1. **Step order and count.** The builder previously grew and shrank steps
 *    depending on which product lines were ticked, and each section decided its
 *    own visibility by comparing a hardcoded string to the current step. A typo
 *    in one of those comparisons hid a whole step's UI while the progress bar
 *    still claimed it existed, and no test caught it.
 *
 * 2. **The Light Designer is reachable on a Christmas quote.** Its launch button
 *    used to sit inside the landscape-only Design step, so a seasonal rep could
 *    never open it, even though saving a design already feeds measured roofline
 *    feet back into a Christmas quote. That branch was unreachable UI.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { salesWizardApi } from "@/lib/api/sales-wizard";

import { CalculatorScreen } from "./calculator-screen";
import { useSalesWizard, type ServiceKey } from "./use-sales-wizard";

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    getPricing: vi.fn(),
    listCatalog: vi.fn().mockResolvedValue([]),
    preview: vi.fn().mockResolvedValue({}),
    save: vi.fn(),
    send: vi.fn(),
    deliver: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Renders the builder against the real hook, on a given service branch. */
function Harness({
  service,
  onOpenNight = vi.fn(),
}: {
  service: ServiceKey;
  onOpenNight?: () => void;
}) {
  const wizard = useSalesWizard("ws-1", service);
  return (
    <CalculatorScreen
      wizard={wizard}
      brandName="Maxteriors Lighting"
      onOpenNight={onOpenNight}
    />
  );
}

async function renderBuilder(
  service: ServiceKey = "landscape",
  onOpenNight = vi.fn(),
) {
  render(<Harness service={service} onOpenNight={onOpenNight} />, { wrapper });
  // The builder renders a loading card until the pricing config resolves.
  await waitFor(() =>
    expect(screen.getByLabelText(/quote builder progress/i)).toBeInTheDocument(),
  );
  return { onOpenNight };
}

const stepButtons = () =>
  within(screen.getByLabelText(/quote builder progress/i))
    .getAllByRole("button")
    .map((b) => b.textContent?.replace(/^\d+/, "").trim());

/** The single visible step section. */
const activeStep = () => document.querySelector(".wizard-step.active");

describe("CalculatorScreen — builder flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue({
      tiers: [],
      tier_order: [],
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.getPricing>>);
    vi.mocked(salesWizardApi.listCatalog).mockResolvedValue([]);
    vi.mocked(salesWizardApi.preview).mockResolvedValue(
      {} as Awaited<ReturnType<typeof salesWizardApi.preview>>,
    );
  });

  it("walks Customer, Mockup, Line Items, Preview, Send", async () => {
    await renderBuilder();

    expect(stepButtons()).toEqual([
      "Customer",
      "Mockup",
      "Line Items",
      "Preview",
      "Send",
    ]);
  });

  it("keeps the same five steps on a Christmas quote", async () => {
    // Steps used to appear and disappear with the ticked product lines, which
    // renumbered the step the rep was standing on mid-quote.
    await renderBuilder("christmas");

    expect(stepButtons()).toEqual([
      "Customer",
      "Mockup",
      "Line Items",
      "Preview",
      "Send",
    ]);
  });

  it("starts on Customer and advances one step at a time", async () => {
    const user = userEvent.setup();
    await renderBuilder();

    expect(activeStep()).toHaveTextContent(/Step 1 of 5/);
    expect(activeStep()).toHaveTextContent(/Customer Details/);

    await user.click(screen.getByRole("button", { name: /next: mockup/i }));
    expect(activeStep()).toHaveTextContent(/Step 2 of 5/);
    expect(activeStep()).toHaveTextContent(/Visual Mockup/);

    await user.click(screen.getByRole("button", { name: /next: line items/i }));
    expect(activeStep()).toHaveTextContent(/Step 3 of 5/);
  });

  it("opens the Light Designer from a Christmas quote", async () => {
    const user = userEvent.setup();
    const onOpenNight = vi.fn();
    await renderBuilder("christmas", onOpenNight);

    await user.click(screen.getByRole("button", { name: /next: mockup/i }));
    await user.click(
      screen.getByRole("button", { name: /open the light designer/i }),
    );

    expect(onOpenNight).toHaveBeenCalledTimes(1);
  });

  it("puts the mockup uploader in the Mockup step, not in add-ons", async () => {
    const user = userEvent.setup();
    await renderBuilder();

    await user.click(screen.getByRole("button", { name: /next: mockup/i }));
    const mockupStep = activeStep();
    expect(mockupStep).toHaveTextContent(/design mockups/i);
    expect(
      within(mockupStep as HTMLElement).getByRole("button", {
        name: /open the light designer/i,
      }),
    ).toBeInTheDocument();
  });

  it("offers texting and emailing from the Send step", async () => {
    const user = userEvent.setup();
    await renderBuilder();

    await user.click(
      within(screen.getByLabelText(/quote builder progress/i)).getByRole(
        "button",
        { name: /send/i },
      ),
    );

    const send = activeStep();
    expect(send).toHaveTextContent(/Step 5 of 5/);
    expect(send).toHaveTextContent(/Send to the Customer/);
    expect(
      within(send as HTMLElement).getByRole("button", {
        name: /save & get client link/i,
      }),
    ).toBeInTheDocument();
  });
});
