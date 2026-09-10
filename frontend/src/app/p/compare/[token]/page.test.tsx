import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { publicComparisonsApi } from "@/lib/api/public-comparisons";
import type { PublicComparison } from "@/types/estimate";

import PublicComparisonPage from "./page";

vi.mock("@/lib/api/public-comparisons", () => ({
  publicComparisonsApi: { get: vi.fn() },
}));

const COMPARISON: PublicComparison = {
  client_name: "Pat Lee",
  years: 5,
  currency: "USD",
  business_name: "Maxteriors",
  logo_url: "https://api.example.com/static/brand/maxteriors-logo.png",
  brand_color: "#304854",
  accent_color: "#fcb400",
  proposal_side: "permanent",
  discount_amount: 0,
  permanent: { enabled: true, subtotal: 9000, total: 9000 },
  christmas: { enabled: false, subtotal: 0, total: 0 },
  christmas_packages: [],
  difference: 9000,
  temporary_multi_year: 0,
  permanent_one_time: 9000,
  multi_year_savings: 0,
  permanent_perks: [],
  christmas_perks: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("legacy public comparison", () => {
  it("keeps the estimate preview branded without implying approval or payment", async () => {
    vi.mocked(publicComparisonsApi.get).mockResolvedValue(COMPARISON);

    let container!: HTMLElement;
    await act(async () => {
      container = render(
        <Suspense fallback={null}>
          <PublicComparisonPage params={Promise.resolve({ token: "fake-comparison-token" })} />
        </Suspense>,
        { wrapper },
      ).container;
    });

    expect(await screen.findByRole("heading", { name: "Estimate preview" })).toBeVisible();
    expect(screen.getByText(/not an approval or payment request/i)).toBeVisible();
    expect(screen.getByRole("img", { name: "Maxteriors" })).toHaveAttribute(
      "src",
      COMPARISON.logo_url,
    );
    expect(container.querySelector(".cmp-view")).toHaveStyle({
      "--brand-primary": "#304854",
      "--brand-accent": "#fcb400",
      "--gold": "#fcb400",
    });
    expect(screen.queryByRole("button", { name: /approve|accept|pay/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: /payment/i })).not.toBeInTheDocument();
  });
});
