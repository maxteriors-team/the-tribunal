import { expect, test, type Page, type Request } from "@playwright/test";

const WORKSPACE_ID = "0ef615a3-4fa5-43e7-bb3b-2dbfa0788a11";
const PROJECT_ID = "6c5e45fd-7984-4216-8ff4-988c03cc2a11";
const PROJECT_URL = `/landscape-lighting/${PROJECT_ID}`;

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const planSvg = `data:image/svg+xml;base64,${Buffer.from(
  `
  <svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900">
    <rect width="1400" height="900" fill="#e7e2d7"/>
    <rect x="150" y="160" width="800" height="470" fill="#fbfaf6" stroke="#8f897c" stroke-width="12"/>
    <path d="M120 720 H1120" stroke="#908a7c" stroke-width="28"/>
    <path d="M300 160 V630 M760 160 V630" stroke="#c7c1b5" stroke-width="8"/>
    <circle cx="1080" cy="260" r="100" fill="#b7c2a1"/>
    <circle cx="1120" cy="560" r="130" fill="#acb995"/>
    <text x="180" y="120" font-family="sans-serif" font-size="42" fill="#3d3a34">Hawthorne Residence Lighting Plan</text>
  </svg>
`,
).toString("base64")}`;

const projectDocument = {
  version: 2,
  activeShotId: "shot-front",
  activeWorkflowTab: "drawing",
  updatedAt: "2026-08-11T20:00:00.000Z",
  settings: {
    paperSize: "tabloid",
    planFit: "contain",
    planOpacity: 1,
    legend: { visible: true, position: { x: 24, y: 24 }, scale: 1 },
    halosVisible: true,
    fixtureNumbersVisible: true,
    measurementsVisible: true,
    sourceVoltage: 13,
  },
  proposal: {
    selectedTierKey: "best",
    selectedCarePlanKey: null,
    designIntent: "Warm arrival lighting with clear walkway edges.",
    showCombinedTotal: true,
    showFixtureDetails: true,
    zones: [],
    paymentMilestones: [
      { id: "deposit", label: "Scheduling deposit", percent: 50 },
      { id: "completion", label: "Due at completion", percent: 50 },
    ],
    electricalResponsibility: "Existing GFCI source verified by electrician.",
    enhancements: [],
    commitments: [],
    signatureName: "",
    signatureDate: null,
  },
  procurement: {},
  precon: { responses: [], leadInstaller: "", notes: "" },
  shots: [
    {
      id: "shot-front",
      photo: { dataUrl: planSvg, width: 1400, height: 900 },
      design: {
        calibration: { a: { x: 160, y: 710 }, b: { x: 1160, y: 710 }, feet: 100 },
        runs: [
          {
            id: "run-front",
            productId: "landscape-wire",
            points: [
              { x: 250, y: 680 },
              { x: 520, y: 680 },
              { x: 840, y: 680 },
            ],
            circuitLabel: "Front elevation",
            wireGauge: 12,
            sourceVoltage: 13,
          },
        ],
        items: [
          {
            id: "fixture-1",
            productId: "fixture-uplight",
            at: { x: 300, y: 560 },
            sizePx: 90,
            circuitId: "run-front",
            catalogItemId: "fixture-up",
            catalogSku: "UP-100",
          },
          {
            id: "fixture-2",
            productId: "fixture-uplight",
            at: { x: 760, y: 560 },
            sizePx: 90,
            circuitId: "run-front",
            catalogItemId: "fixture-up",
            catalogSku: "UP-100",
          },
          {
            id: "fixture-3",
            productId: "fixture-pathlight",
            at: { x: 980, y: 700 },
            sizePx: 70,
            circuitId: "run-front",
            catalogItemId: "fixture-path",
            catalogSku: "PATH-200",
          },
        ],
        planImages: [],
        annotations: [
          { id: "note-1", type: "note", at: { x: 1020, y: 160 }, text: "Existing oak" },
        ],
        measurements: [
          {
            id: "measure-1",
            a: { x: 160, y: 760 },
            b: { x: 960, y: 760 },
            label: "80 ft",
            visible: true,
          },
        ],
        highlights: [],
        arrows: [],
      },
      dusk: 0.35,
      sheet: {
        label: "Front elevation",
        drawingTitle: "Landscape lighting design plan",
        drawingNumber: "L-1",
        revisions: [],
      },
    },
  ],
};

const project = {
  id: PROJECT_ID,
  workspace_id: WORKSPACE_ID,
  contact_id: 42,
  contact_name: "Avery Hawthorne",
  service_location_id: null,
  opportunity_id: null,
  assigned_user_id: 41,
  name: "Hawthorne Residence",
  status: "active",
  version: 4,
  installation_shot_id: null,
  updated_by_id: 41,
  updater_name: "Jordan Lee",
  created_at: "2026-08-11T18:00:00.000Z",
  updated_at: "2026-08-11T20:00:00.000Z",
  created_by_id: 41,
  document: projectDocument,
};

const catalog = [
  {
    id: "fixture-up",
    workspace_id: WORKSPACE_ID,
    name: "CORA Brass Uplight",
    description: "Warm white directional accent fixture",
    sku: "UP-100",
    kind: "product",
    unit_price: 411,
    taxable: true,
    is_active: true,
    is_attachable: true,
    attributes: {
      fixture_type: "uplight",
      fixture_watts: 5,
      manufacturer: "FX Luminaire",
      supplier: "SiteOne",
    },
    components: [{ sku: "MR16-5W", qty: 1, description: "MR16 5W lamp" }],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "fixture-path",
    workspace_id: WORKSPACE_ID,
    name: "TM Path Light",
    description: "Warm white path fixture",
    sku: "PATH-200",
    kind: "product",
    unit_price: 376,
    taxable: true,
    is_active: true,
    is_attachable: true,
    attributes: {
      fixture_type: "pathlight",
      fixture_watts: 3,
      manufacturer: "FX Luminaire",
      supplier: "SiteOne",
    },
    components: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "transformer",
    workspace_id: WORKSPACE_ID,
    name: "DX 300W Transformer",
    description: "Low-voltage transformer",
    sku: "TX-300",
    kind: "product",
    unit_price: 1072,
    taxable: true,
    is_active: true,
    is_attachable: false,
    attributes: {
      transformer: true,
      transformer_capacity_watts: 300,
      manufacturer: "FX Luminaire",
      supplier: "SiteOne",
    },
    components: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

const pricing = {
  comparison_years: 5,
  quote_validity_days: 30,
  roofline_comparison_enabled: false,
  tier_order: ["best"],
  tiers: [
    {
      key: "best",
      label: "Premier lighting",
      tab: "Best",
      points: ["Premium brass fixtures", "Transformer zoning"],
      sections: [{ title: "Fixtures", item_ids: ["UP-100", "PATH-200", "TX-300"] }],
    },
  ],
  landscape: { perks: ["Professional aiming and commissioning"] },
};

const estimate = {
  feet: 0,
  permanent: { enabled: false, total: 0, per_ft: 0, roofline_cost: 0, custom_total: 0 },
  christmas: { enabled: false, total: 0, per_ft: 0, roofline_cost: 0, custom_total: 0, items: [] },
  difference: 0,
  years: 5,
  temporary_multi_year: 0,
  permanent_one_time: 0,
  multi_year_savings: 0,
  permanent_perks: [],
  christmas_perks: [],
  christmas_catalog: [],
};

function parseRequestBody(request: Request): Record<string, unknown> {
  try {
    return request.postDataJSON() as Record<string, unknown>;
  } catch {
    return {};
  }
}

async function installStudioApi(page: Page) {
  let serverVersion = 4;
  let serverDocument = structuredClone(projectDocument);
  let installationShotId: string | null = null;
  const updates: unknown[] = [];
  const deliveries: unknown[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();

    if (method === "GET" && pathname === "/api/v1/auth/me") {
      await route.fulfill(
        json({
          id: 41,
          email: "owner@maxteriors.example",
          full_name: "Jordan Lee",
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
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
              name: "Maxteriors",
              slug: "maxteriors",
              description: null,
              settings: {},
              is_active: true,
              onboarding_completed_at: "2026-01-01T00:00:00Z",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
            role: "owner",
            is_default: true,
          },
        ]),
      );
      return;
    }
    if (
      method === "GET" &&
      pathname === `/api/v1/workspaces/${WORKSPACE_ID}/lighting-projects/${PROJECT_ID}`
    ) {
      await route.fulfill(
        json({
          ...project,
          version: serverVersion,
          document: serverDocument,
          installation_shot_id: installationShotId,
        }),
      );
      return;
    }
    if (
      method === "PATCH" &&
      pathname === `/api/v1/workspaces/${WORKSPACE_ID}/lighting-projects/${PROJECT_ID}`
    ) {
      const body = parseRequestBody(request);
      updates.push(body);
      serverVersion += 1;
      if (body.document) serverDocument = body.document as typeof serverDocument;
      if (typeof body.installation_shot_id === "string")
        installationShotId = body.installation_shot_id;
      await route.fulfill(
        json({
          ...project,
          version: serverVersion,
          document: serverDocument,
          installation_shot_id: installationShotId,
        }),
      );
      return;
    }
    if (method === "POST" && pathname.endsWith("/quotes/estimate")) {
      await route.fulfill(json(estimate));
      return;
    }
    if (method === "GET" && pathname.endsWith("/catalog-items")) {
      await route.fulfill(
        json({ items: catalog, total: catalog.length, page: 1, page_size: 500, pages: 1 }),
      );
      return;
    }
    if (
      method === "GET" &&
      pathname.includes("/settings/workspaces/") &&
      pathname.endsWith("/pricing")
    ) {
      await route.fulfill(json(pricing));
      return;
    }
    if (method === "POST" && pathname.endsWith("/quotes/wizard/preview")) {
      await route.fulfill(
        json({
          tiers: [],
          selected_tier_key: "best",
          selected_care_plan_key: null,
          total: 2199,
          fixture_total: 2199,
          care_plan_total: 0,
        }),
      );
      return;
    }
    if (method === "POST" && pathname.endsWith("/quotes/wizard")) {
      await route.fulfill(json({ id: "quote-1", number: "Q-1042", status: "draft", total: 2199 }));
      return;
    }
    if (method === "POST" && pathname.endsWith("/quotes/quote-1/deliver")) {
      const body = parseRequestBody(request);
      deliveries.push(body);
      await route.fulfill(
        json({
          ok: true,
          channel: body.channel,
          to: body.channel === "sms" ? "+15125550142" : "avery@example.com",
        }),
      );
      return;
    }
    if (
      method === "GET" &&
      (pathname.endsWith("/nudges/stats") || pathname.endsWith("/pending-actions/stats"))
    ) {
      await route.fulfill(json({}));
      return;
    }
    await route.fulfill(json({ detail: `Unexpected ${method} ${pathname}` }, 404));
  });

  return { updates, deliveries };
}

test.describe("landscape lighting studio", () => {
  test("uses every workflow, autosaves, exports, and delivers through captured providers", async ({
    page,
  }) => {
    const { updates, deliveries } = await installStudioApi(page);
    await page.goto(PROJECT_URL);
    await expect(page.getByRole("button", { name: "Save now" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Drawing Sheet" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("region", { name: "Drawing toolbar" })).toBeVisible();

    const baselineUpdateCount = updates.length;
    await page.getByRole("button", { name: "Highlight" }).click();
    await page.getByRole("button", { name: "Save now" }).click();
    await expect.poll(() => updates.length).toBeGreaterThan(baselineUpdateCount);

    await page.getByRole("button", { name: "File", exact: true }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("menuitem", { name: "Save editable project" }).click();
    await expect((await download).suggestedFilename()).toContain("tribunal.json");

    for (const tab of ["Fixture Schedule", "BOM", "Electrical", "Proposal", "Pre-Con"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
    }

    await page.getByRole("tab", { name: "Pre-Con" }).click();
    await page.getByRole("button", { name: "Yes" }).first().click();
    await page.getByRole("textbox", { name: "Lead installer", exact: true }).fill("Morgan Lee");
    await expect(page.getByText("1/26 complete")).toBeVisible();

    await page.getByRole("tab", { name: "Drawing Sheet" }).click();
    await page.getByRole("button", { name: "Use L-1 as installation sheet" }).click();
    await expect
      .poll(() =>
        updates.some(
          (entry) =>
            typeof entry === "object" &&
            entry !== null &&
            "installation_shot_id" in entry &&
            entry.installation_shot_id === "shot-front",
        ),
      )
      .toBe(true);
    await page.getByRole("tab", { name: "Proposal" }).click();
    await page.getByRole("button", { name: /Create draft quote/i }).click();
    await expect(page.getByText(/Draft quote Q-1042/i)).toBeVisible();
    await page.getByRole("button", { name: "Email proposal" }).click();
    await expect.poll(() => deliveries.length).toBe(1);
    expect(deliveries[0]).toMatchObject({ channel: "email" });
  });

  test("keeps complete geometry at desktop, laptop, mobile, reduced motion, and forced colors", async ({
    page,
  }) => {
    await installStudioApi(page);
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await page.goto(PROJECT_URL);

    for (const viewport of [
      { width: 1440, height: 1000 },
      { width: 1280, height: 800 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(page.getByRole("tab", { name: "Pre-Con" })).toBeAttached();
      await expect(page.getByRole("region", { name: "Drawing toolbar" })).toBeVisible();
    }

    const toolbar = page.getByRole("region", { name: "Drawing toolbar" });
    await expect(toolbar).toHaveCSS("overflow-x", "auto");
    const drawing = page.getByRole("tab", { name: "Drawing Sheet" });
    await drawing.focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Fixture Schedule" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("captures representative desktop and mobile drawing states", async ({ page }) => {
    await installStudioApi(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(PROJECT_URL);
    await expect(page.getByRole("region", { name: "Drawing toolbar" })).toBeVisible();
    await page.screenshot({
      path: "../.ezcoder/screenshots/maxteriors-studio-desktop.png",
      fullPage: true,
      animations: "disabled",
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: "../.ezcoder/screenshots/maxteriors-studio-mobile.png",
      fullPage: true,
      animations: "disabled",
    });
  });
});
