import { expect, test, type BrowserContext, type Request } from "@playwright/test";

const WORKSPACE_ID = "0ef615a3-4fa5-43e7-bb3b-2dbfa0788f01";
const QUOTE_ID = "0ef615a3-4fa5-43e7-bb3b-2dbfa0788f02";
const PUBLIC_TOKEN = "fresh-workspace-client-link";

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const starterItems = [
  ["starter-essential-transformer", "Essential 150W Transformer", 504],
  ["starter-essential-uplight", "Essential Accent Uplight", 172],
  ["starter-essential-path", "Essential Path Light", 376],
  ["starter-professional-transformer", "Professional 300W Transformer", 1072],
  ["starter-professional-uplight", "Professional Accent Uplight", 386],
  ["starter-professional-path", "Professional Path Light", 376],
  ["starter-estate-transformer", "Estate Smart 300W Transformer", 2266],
  ["starter-estate-uplight", "Estate Color Uplight", 785],
  ["starter-estate-path", "Estate Color Path Light", 1001],
] as const;

const catalog = starterItems.map(([sku, name, unitPrice], index) => ({
  id: `0ef615a3-4fa5-43e7-bb3b-2dbfa0788${String(index).padStart(3, "0")}`,
  workspace_id: WORKSPACE_ID,
  created_by_id: 41,
  sku,
  name,
  description: `Installed ${name.toLowerCase()}.`,
  unit_price: unitPrice,
  taxable: true,
  kind: "service",
  category: "Landscape Lighting",
  unit_label: "each",
  is_active: true,
  is_attachable: false,
  attach_targets: [],
  attributes: {},
  components: [],
  created_at: "2026-08-19T12:00:00Z",
  updated_at: "2026-08-19T12:00:00Z",
}));

const tierConfigs = [
  {
    key: "best",
    label: "BEST",
    name: "Estate",
    popular: false,
    experience: "Smart color-changing fixtures and controls.",
    warranty: "Premium system package",
    sections: [
      {
        title: "Estate fixtures",
        item_ids: ["starter-estate-transformer", "starter-estate-uplight", "starter-estate-path"],
      },
    ],
  },
  {
    key: "better",
    label: "BETTER",
    name: "Professional",
    popular: true,
    experience: "Premium brass fixtures for a durable, polished design.",
    warranty: "Professional system package",
    sections: [
      {
        title: "Professional fixtures",
        item_ids: [
          "starter-professional-transformer",
          "starter-professional-uplight",
          "starter-professional-path",
        ],
      },
    ],
  },
  {
    key: "good",
    label: "GOOD",
    name: "Essential",
    popular: false,
    experience: "A warm, reliable lighting foundation.",
    warranty: "Essential system package",
    sections: [
      {
        title: "Essential fixtures",
        item_ids: [
          "starter-essential-transformer",
          "starter-essential-uplight",
          "starter-essential-path",
        ],
      },
    ],
  },
];

const pricing = {
  tier_order: ["best", "better", "good"],
  tiers: tierConfigs,
  care_plan: { enabled: false, fixture_count_item_ids: [], options: [] },
  cash_discount: {
    enabled: true,
    card_reserve_rate: 0.03,
    label: "Cash / Check Pricing",
  },
  financing: {
    enabled: true,
    provider: "Wisetack",
    max_amount: 25000,
    terms: [6, 12, 24],
    default_term: 24,
    apr: 0,
    fee_buffer: 0.11,
    category_minimums: { landscape: 0 },
    disclaimer: "Payment options are estimates and subject to approval.",
  },
  bistro: {
    enabled: false,
    minimum: 0,
    tiers: [],
    classic: {
      name: "Classic Bistro",
      hardware: 0,
      bulb_spacing_ft: 2,
      min_footage: 0,
      strand_lengths: [],
    },
    color: {
      name: "Color Bistro",
      hardware: 0,
      bulb_spacing_ft: 2,
      min_footage: 0,
      strand_lengths: [],
    },
  },
  tax: { enabled: false, rate: 0, label: "Sales Tax" },
  payment_schedule: { enabled: false, milestones: [] },
  commission: {
    enabled: true,
    rate: 0.12,
    in_price: false,
    label: "Sales Commission",
  },
  seasonal: { enabled: false, products: [], extras: [], removal: { tiers: [] } },
  permanent: { enabled: false, products: [], extras: [] },
};

type WizardPayload = {
  client?: Record<string, unknown>;
  selected_tier?: string | null;
  quantities?: Array<{ item_id: string; quantity: number }>;
  additional_charges?: Array<{ description: string | null; net_amount: number }>;
};

function parseRequestBody(request: Request): WizardPayload {
  try {
    return request.postDataJSON() as WizardPayload;
  } catch {
    return {};
  }
}

function proposalDocument(payload: WizardPayload) {
  const quantities = new Map(
    (payload.quantities ?? []).map(({ item_id, quantity }) => [item_id, quantity]),
  );
  const itemBySku = new Map<string, (typeof catalog)[number]>(
    catalog.map((item) => [item.sku, item]),
  );
  const tiers = tierConfigs.map((tier) => {
    const lines = tier.sections.flatMap((section) =>
      section.item_ids.map((itemId) => {
        const item = itemBySku.get(itemId);
        if (!item) throw new Error(`Missing E2E catalog item ${itemId}`);
        const qty = quantities.get(itemId) ?? 0;
        const unitPrice = Math.round(item.unit_price / (1 - pricing.financing.fee_buffer));
        return {
          item_id: itemId,
          name: item.name,
          description: item.description,
          qty,
          unit_price: unitPrice,
          line_total: qty * unitPrice,
        };
      }),
    );
    const base = lines.reduce((total, line) => total + line.line_total, 0);
    const cashDiscountRate =
      1 - (1 + pricing.cash_discount.card_reserve_rate) * (1 - pricing.financing.fee_buffer);
    const cashTotal = Math.round(base * (1 - cashDiscountRate));
    return {
      key: tier.key,
      label: tier.label,
      name: tier.name,
      popular: tier.popular,
      experience: tier.experience,
      warranty: tier.warranty,
      points: lines.filter((line) => line.qty > 0).map((line) => line.name),
      lines,
      charges: [],
      care_plan: null,
      subtotal: base,
      pricing: {
        base,
        discount: base - cashTotal,
        cash_total: cashTotal,
        financed_total: base,
        monthly_payment: base / pricing.financing.default_term,
        monthly_by_term: Object.fromEntries(
          pricing.financing.terms.map((term) => [term, base / term]),
        ),
        tax: 0,
        tax_rate: 0,
        tax_label: "Sales Tax",
        pre_tax_total: base,
      },
    };
  });
  const selectedTier =
    tiers.find((tier) => tier.key === (payload.selected_tier ?? "best")) ?? tiers[0];

  return {
    version: 1,
    generated_at: "2026-08-19T12:00:00Z",
    workspace_id: WORKSPACE_ID,
    client: {
      first_name: "Avery",
      last_name: "Stone",
      email: "avery@example.com",
      phone: "",
      street: "",
      city: "",
      state: "",
      zip: "",
      rep_name: "Jordan Lee",
      ...(payload.client ?? {}),
    },
    tiers,
    additional_charges: (payload.additional_charges ?? []).map((charge) => ({
      description: charge.description ?? "Additional charge",
      amount: charge.net_amount,
    })),
    care_plan: null,
    bistro: null,
    financing: {
      enabled: true,
      provider: pricing.financing.provider,
      plans: pricing.financing.terms.map((term) => ({
        term_months: term,
        apr: 0,
      })),
      default_term_months: pricing.financing.default_term,
      min_finance: 0,
      disclaimer: pricing.financing.disclaimer,
    },
    tax: { enabled: false, rate: 0, label: "Sales Tax" },
    tier_order: ["best", "better", "good"],
    selected_tier_key: selectedTier.key,
    grand_cash_total: selectedTier.pricing.cash_total,
    grand_financed_total: selectedTier.pricing.financed_total,
    grand_monthly_payment: 0,
  };
}

function quoteDetail(payload: WizardPayload) {
  const document = proposalDocument(payload);
  return {
    id: QUOTE_ID,
    workspace_id: WORKSPACE_ID,
    contact_id: null,
    number: "Q-1001",
    title: "Landscape Lighting Proposal",
    status: "draft",
    currency: "USD",
    subtotal: document.grand_financed_total,
    tax_amount: 0,
    discount_amount: 0,
    total: document.grand_financed_total,
    valid_until: null,
    notes: null,
    terms: null,
    public_token: PUBLIC_TOKEN,
    proposal_document: document,
    wizard_payload: payload,
    line_items: [],
    created_at: "2026-08-19T12:00:00Z",
    updated_at: "2026-08-19T12:00:00Z",
  };
}

async function installFreshWorkspaceApi(
  context: BrowserContext,
  { configured = true }: { configured?: boolean } = {},
) {
  const previews: WizardPayload[] = [];
  const saves: WizardPayload[] = [];
  let savedPayload: WizardPayload | null = null;

  await context.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;
    const method = request.method();

    if (method === "GET" && pathname === "/api/v1/auth/me") {
      await route.fulfill(
        json({
          id: 41,
          email: "owner@fresh.example",
          full_name: "Jordan Lee",
          is_active: true,
          created_at: "2026-08-19T12:00:00Z",
          default_workspace_id: WORKSPACE_ID,
        }),
      );
      return;
    }
    if (method === "GET" && pathname === "/api/v1/workspaces") {
      await route.fulfill(
        json([
          {
            workspace: {
              id: WORKSPACE_ID,
              name: "Fresh Lighting Co.",
              slug: "fresh-lighting",
              description: null,
              settings: {},
              is_active: true,
              onboarding_completed_at: "2026-08-19T11:59:00Z",
              created_at: "2026-08-19T11:00:00Z",
              updated_at: "2026-08-19T11:59:00Z",
            },
            role: "owner",
            is_default: true,
          },
        ]),
      );
      return;
    }
    if (method === "GET" && pathname === `/api/v1/settings/workspaces/${WORKSPACE_ID}/pricing`) {
      await route.fulfill(json(configured ? pricing : { ...pricing, tier_order: [], tiers: [] }));
      return;
    }
    if (method === "GET" && pathname === `/api/v1/workspaces/${WORKSPACE_ID}/catalog-items`) {
      const items = configured ? catalog : [];
      await route.fulfill(json({ items, total: items.length, page: 1, page_size: 500, pages: 1 }));
      return;
    }
    if (method === "GET" && pathname === `/api/v1/workspaces/${WORKSPACE_ID}/contacts`) {
      await route.fulfill(json({ items: [], total: 0, page: 1, page_size: 6, pages: 0 }));
      return;
    }
    if (method === "POST" && pathname.endsWith("/quotes/wizard/preview")) {
      const payload = parseRequestBody(request);
      previews.push(payload);
      await route.fulfill(json(proposalDocument(payload)));
      return;
    }
    if (method === "POST" && pathname.endsWith("/quotes/wizard")) {
      const payload = parseRequestBody(request);
      saves.push(payload);
      savedPayload = payload;
      await route.fulfill(json(quoteDetail(payload)));
      return;
    }
    if (method === "POST" && pathname.endsWith(`/quotes/${QUOTE_ID}/send`)) {
      await route.fulfill(json({ ...quoteDetail(savedPayload ?? {}), status: "sent" }));
      return;
    }
    if (method === "GET" && pathname === `/api/v1/p/quotes/${PUBLIC_TOKEN}`) {
      const payload = savedPayload ?? {};
      const document = proposalDocument(payload);
      const selectedTier = document.tiers.find((tier) => tier.key === document.selected_tier_key);
      const selectedLines = selectedTier?.lines.filter((line) => line.qty > 0) ?? [];
      await route.fulfill(
        json({
          token: PUBLIC_TOKEN,
          number: "Q-1001",
          title: "Landscape Lighting Proposal",
          status: "sent",
          proposal_version: 1,
          currency: "USD",
          subtotal: document.grand_financed_total,
          tax_amount: 0,
          discount_amount: 0,
          total: document.grand_financed_total,
          financing: null,
          issue_date: "2026-08-19",
          expiry_date: null,
          is_expired: false,
          is_decided: false,
          intro: null,
          notes: null,
          terms: null,
          client_name: "Avery Stone",
          deposit_percentage: null,
          deposit_amount: null,
          deposit_paid: false,
          deposit_required: false,
          packages: [],
          line_items: selectedLines.map((line) => ({
            name: line.name,
            description: line.description,
            quantity: line.qty,
            unit_price: line.unit_price,
            discount: 0,
            total: line.line_total,
          })),
          branding: {
            business_name: "Fresh Lighting Co.",
            logo_url: null,
            brand_color: "#111111",
            accent_color: "#d4af5a",
            business_address: null,
            business_phone: null,
            business_email: "owner@fresh.example",
            footer: null,
          },
          proposal_document: document,
        }),
      );
      return;
    }
    if (method === "POST" && pathname === `/api/v1/p/quotes/${PUBLIC_TOKEN}/view`) {
      await route.fulfill({ status: 204, body: "" });
      return;
    }

    await route.fulfill(json({ detail: `Unhandled E2E route: ${method} ${pathname}` }, 404));
  });

  return { previews, saves };
}

test("freshly onboarded workspace prices, previews, saves, and opens its client link", async ({
  page,
  context,
}) => {
  const api = await installFreshWorkspaceApi(context);

  await page.goto("/sales-wizard?service=landscape");
  await expect(page.getByText("Customer Details")).toBeVisible();

  await page.getByLabel("First Name").fill("Avery");
  await page.getByLabel("Last Name").fill("Stone");
  await page.getByLabel("Client Email").fill("avery@example.com");
  await page.getByLabel("Your Name").fill("Jordan Lee");
  await page.getByRole("button", { name: "Next: Mockup" }).click();
  await page.getByRole("button", { name: "Next: Line Items" }).click();

  const estateUplight = page.locator(".fix-row", { hasText: "Estate Color Uplight" });
  await expect(estateUplight).toBeVisible();
  await estateUplight.getByRole("button", { name: "+" }).click();
  await estateUplight.getByRole("button", { name: "+" }).click();

  await expect
    .poll(
      () =>
        api.previews.at(-1)?.quantities?.find((row) => row.item_id === "starter-estate-uplight")
          ?.quantity,
    )
    .toBe(2);
  await expect(estateUplight).toContainText(/\$1,764(?:\.00)?/);

  await page.getByRole("button", { name: "Next: Preview" }).click();
  await expect(page.getByText("Preview the Proposal")).toBeVisible();
  await expect(page.locator(".pkg-card.best .pkg-price")).toHaveText(/\$1,764(?:\.00)?/);

  await page.getByRole("button", { name: "Next: Send" }).click();
  await page.getByRole("button", { name: "Save & Get Client Link" }).click();

  await expect.poll(() => api.saves.length).toBe(1);
  await expect(page.getByLabel("Client proposal link")).toHaveValue(
    new RegExp(`/p/quotes/${PUBLIC_TOKEN}$`),
  );

  const [clientPage] = await Promise.all([
    page.waitForEvent("popup"),
    page.getByRole("link", { name: "Open" }).click(),
  ]);
  await expect(clientPage).toHaveURL(new RegExp(`/p/quotes/${PUBLIC_TOKEN}$`));
  await expect(clientPage.getByText("The Stone Residence")).toBeVisible();
  await expect(clientPage.getByText(/\$1,764(?:\.00)?/).first()).toBeVisible();
});

test("unconfigured workspaces are blocked with a direct Price Book setup action", async ({
  page,
  context,
}) => {
  await installFreshWorkspaceApi(context, { configured: false });

  await page.goto("/sales-wizard");

  await expect(
    page.getByRole("heading", { name: "Set up your Price Book before building a quote" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Set up Price Book" })).toHaveAttribute(
    "href",
    "/catalog",
  );
  await expect(page.getByText("Customer Details")).toHaveCount(0);
});
