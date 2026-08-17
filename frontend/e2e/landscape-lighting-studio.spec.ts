import { readFile } from "node:fs/promises";

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
  <svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" viewBox="0 0 1400 900">
    <rect width="1400" height="900" fill="#66885f"/>
    <path d="M70 60 H1330 V840 H70 Z" fill="#7da06f" stroke="#f4f0dc" stroke-width="6" stroke-dasharray="22 14"/>
    <path d="M870 510 H1120 V840 H760 V700 H870 Z" fill="#b7afa0" stroke="#ddd7ca" stroke-width="8"/>
    <path d="M305 200 H965 V565 H305 Z" fill="#c6b9a6" stroke="#443f39" stroke-width="10"/>
    <path d="M325 220 L635 90 L945 220 L945 545 H325 Z" fill="#76685b" stroke="#443f39" stroke-width="8"/>
    <path d="M635 90 V545 M325 220 H945" stroke="#9d8d7b" stroke-width="8"/>
    <rect x="775" y="430" width="170" height="115" fill="#918171" stroke="#443f39" stroke-width="6"/>
    <path d="M520 545 V690 H760" fill="none" stroke="#d4cbb9" stroke-width="54"/>
    <path d="M170 160 C230 120 285 145 300 210 C265 270 205 275 155 230 Z" fill="#305b38"/>
    <path d="M1030 135 C1110 95 1190 130 1205 215 C1150 285 1060 270 1015 210 Z" fill="#315f3a"/>
    <path d="M150 610 C230 555 315 600 320 690 C265 760 170 750 130 675 Z" fill="#2e5936"/>
    <path d="M1040 620 C1140 555 1245 610 1250 720 C1180 790 1070 775 1020 690 Z" fill="#2d5734"/>
    <g fill="#bdd080" stroke="#557047" stroke-width="5">
      <circle cx="390" cy="625" r="34"/><circle cx="455" cy="640" r="30"/>
      <circle cx="930" cy="620" r="38"/><circle cx="995" cy="590" r="30"/>
    </g>
    <path d="M1220 150 V85 M1220 85 L1200 120 M1220 85 L1240 120" stroke="#f7f2df" stroke-width="8" fill="none"/>
    <text x="1198" y="70" font-family="Arial" font-size="30" font-weight="700" fill="#f7f2df">N</text>
    <text x="105" y="115" font-family="Arial" font-size="36" font-weight="700" fill="#f7f2df">TOP-DOWN AERIAL PLAN</text>
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
            circuitLabel: "Front yard circuit",
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
        label: "Aerial plan",
        drawingTitle: "Aerial landscape lighting plan",
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
    id: "lamp-2700k",
    workspace_id: WORKSPACE_ID,
    name: "MR16 2700K LED Lamp",
    description: "Five-watt warm white lamp",
    sku: "MR16-2700-5W",
    kind: "product",
    unit_price: 18.5,
    taxable: true,
    is_active: true,
    is_attachable: true,
    attach_targets: ["landscape_fixture"],
    attributes: { manufacturer: "Tribunal Lighting", supplier: "SiteOne" },
    components: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "ground-stake",
    workspace_id: WORKSPACE_ID,
    name: "Brass Ground Stake",
    description: "Replacement fixture stake",
    sku: "STAKE-BRASS",
    kind: "product",
    unit_price: 12,
    taxable: true,
    is_active: true,
    is_attachable: true,
    attach_targets: ["landscape_fixture"],
    attributes: { manufacturer: "Tribunal Lighting", supplier: "SiteOne" },
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
  test.describe.configure({ mode: "serial" });

  test("uses every workflow, autosaves, exports, and delivers through captured providers", async ({
    page,
  }) => {
    const { updates, deliveries } = await installStudioApi(page);
    await page.goto(PROJECT_URL);
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Drawing Sheet" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("region", { name: "Drawing toolbar" })).toBeVisible();

    const baselineUpdateCount = updates.length;
    await page.getByRole("button", { name: "Highlight" }).click();
    const canvas = page.getByLabel("Top-down aerial lighting plan canvas");
    const canvasBox = await canvas.boundingBox();
    if (!canvasBox) throw new Error("Top-down aerial lighting plan canvas did not render");
    await page.mouse.move(canvasBox.x + 260, canvasBox.y + 260);
    await page.mouse.down();
    await page.mouse.move(canvasBox.x + 430, canvasBox.y + 310, { steps: 8 });
    await page.mouse.up();
    await expect.poll(() => updates.length).toBeGreaterThan(baselineUpdateCount);
    const latestDraft = updates.at(-1) as {
      document?: { shots?: Array<{ design?: { highlights?: unknown[] } }> };
    };
    expect(latestDraft.document?.shots?.[0]?.design?.highlights).toHaveLength(1);

    await page.locator('label[title="Blue"]').click();
    await expect(page.getByRole("radio", { name: "Blue" })).toBeChecked();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await page.getByRole("menuitem", { name: "Uplight" }).click();
    await canvas.click({ position: { x: canvasBox.width / 2, y: canvasBox.height / 2 } });
    await expect
      .poll(() =>
        updates.some((entry) => {
          const document = entry as {
            document?: { shots?: Array<{ design: { items: Array<{ markerColor?: string }> } }> };
          };
          return document.document?.shots?.some((shot) =>
            shot.design.items.some((item) => item.markerColor === "#2f80ed"),
          );
        }),
      )
      .toBe(true);

    await page.getByRole("button", { name: "Wiring: Off" }).click();
    await canvas.click({ position: { x: canvasBox.width * 0.35, y: canvasBox.height * 0.62 } });
    await canvas.click({ position: { x: canvasBox.width * 0.55, y: canvasBox.height * 0.68 } });
    await canvas.press("Enter");
    await expect
      .poll(() =>
        updates.some((entry) => {
          const document = entry as {
            document?: { shots?: Array<{ design: { runs: unknown[] } }> };
          };
          return (document.document?.shots?.[0]?.design.runs.length ?? 0) >= 2;
        }),
      )
      .toBe(true);

    await page.getByRole("button", { name: "File", exact: true }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("menuitem", { name: "Save editable project" }).click();
    await expect((await download).suggestedFilename()).toContain("tribunal.json");

    for (const tab of ["Fixture Schedule", "BOM", "Electrical", "Proposal", "Pre-Con"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("button", { name: "Fit document" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Print", exact: true })).toBeVisible();
      if (tab !== "Fixture Schedule") {
        await expect(
          page.getByRole("button", { name: "Save active sheet as PDF using the print dialog" }),
        ).toBeVisible();
      }
      if (tab === "BOM") {
        await expect(page.getByRole("button", { name: "Recount" })).toBeVisible();
        await expect(page.getByRole("button", { name: "CSV" })).toBeEnabled();
        await page.getByRole("button", { name: "Add line item" }).click();
        await page.getByLabel("BOM line item 1 description").fill("Copper ground stake");
        await page.getByLabel("BOM line item 1 SKU").fill("STAKE-CU");
        await page.getByLabel("BOM line item 1 quantity").fill("4");
        await expect
          .poll(() =>
            updates.some((entry) => {
              const update = entry as {
                document?: {
                  bomLineItems?: Array<{ description?: string; quantity?: number }>;
                };
              };
              return update.document?.bomLineItems?.some(
                (line) => line.description === "Copper ground stake" && line.quantity === 4,
              );
            }),
          )
          .toBe(true);
      }
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
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: /Create draft quote/i }).click();
    await expect(page.getByText(/Draft quote Q-1042/i)).toBeVisible();
    await page.getByRole("button", { name: "Email proposal" }).click();
    await expect.poll(() => deliveries.length).toBe(1);
    expect(deliveries[0]).toMatchObject({ channel: "email" });
  });

  test("edits fixture assignments and purchase-ready bill of materials", async ({ page }) => {
    const { updates } = await installStudioApi(page);
    await page.goto(PROJECT_URL);

    await page.getByRole("tab", { name: "Fixture Schedule" }).click();
    await expect(
      page.getByRole("table", { name: /Fixture schedule with editable lamp and accessory/i }),
    ).toBeVisible();
    await page.getByLabel("Lamp for fixture 1").selectOption("lamp-2700k");
    await page.getByLabel("Add accessory to fixture 1").selectOption("ground-stake");
    await expect(page.getByLabel("Lamp for fixture 1")).toHaveValue("lamp-2700k");
    await expect(
      page.getByRole("button", { name: "Remove Brass Ground Stake from fixture 1" }),
    ).toBeVisible();

    await expect
      .poll(() => {
        const update = updates.at(-1) as
          | {
              document?: {
                shots?: Array<{
                  design?: {
                    items?: Array<{
                      id?: string;
                      lampCatalogItemId?: string;
                      accessoryCatalogItemIds?: string[];
                    }>;
                  };
                }>;
              };
            }
          | undefined;
        return update?.document?.shots?.[0]?.design?.items?.find((item) => item.id === "fixture-1");
      })
      .toMatchObject({
        lampCatalogItemId: "lamp-2700k",
        accessoryCatalogItemIds: ["ground-stake"],
      });

    await page.getByRole("tab", { name: "BOM" }).click();
    const description = page.getByLabel("Material description for CORA Brass Uplight");
    await description.fill("Patina brass uplight");
    await description.press("Tab");
    const sku = page.getByLabel("SKU for Patina brass uplight");
    await sku.fill("UP-CUSTOM");
    await sku.press("Tab");
    const manufacturer = page.getByLabel("Manufacturer for Patina brass uplight");
    await manufacturer.fill("Tribunal Lighting");
    await manufacturer.press("Tab");
    const needed = page.getByLabel("Quantity needed for Patina brass uplight");
    await needed.fill("9");
    await needed.press("Tab");
    const ordered = page.getByLabel("Quantity ordered for Patina brass uplight");
    await ordered.fill("4");
    await ordered.press("Tab");
    const received = page.getByLabel("Quantity received for Patina brass uplight");
    await received.fill("1");
    await received.press("Tab");
    const unitCost = page.getByLabel("Unit cost for Patina brass uplight");
    await unitCost.fill("82.5");
    await unitCost.press("Tab");
    const supplier = page.getByLabel("Supplier for Patina brass uplight");
    await supplier.fill("Regional Supply");
    await supplier.press("Tab");
    const notes = page.getByLabel("Notes for Patina brass uplight");
    await notes.fill("PO-1042");
    await notes.press("Tab");

    await expect
      .poll(() => {
        const update = [...updates].reverse().find((entry) => {
          const candidate = entry as {
            document?: { procurement?: Record<string, Record<string, unknown>> };
          };
          return Object.values(candidate.document?.procurement ?? {}).some(
            (line) => line.description === "Patina brass uplight",
          );
        }) as { document?: { procurement?: Record<string, Record<string, unknown>> } } | undefined;
        return Object.values(update?.document?.procurement ?? {}).find(
          (line) => line.description === "Patina brass uplight",
        );
      })
      .toMatchObject({
        catalogSku: "UP-CUSTOM",
        description: "Patina brass uplight",
        manufacturer: "Tribunal Lighting",
        supplier: "Regional Supply",
        neededQuantity: 9,
        orderedQuantity: 4,
        receivedQuantity: 1,
        unitCost: 82.5,
        supplierNote: "PO-1042",
      });

    const downloadStarted = page.waitForEvent("download");
    await page.getByRole("button", { name: "Supplier CSV" }).click();
    const download = await downloadStarted;
    const downloadPath = await download.path();
    if (!downloadPath) throw new Error("Supplier CSV download did not produce a local file");
    const csv = await readFile(downloadPath, "utf8");
    expect(csv).toContain("Patina brass uplight");
    expect(csv).toContain("UP-CUSTOM");
    expect(csv).toContain("Regional Supply");
    expect(csv).toContain("PO-1042");

    await page.getByRole("button", { name: "Recount plan" }).click();
    await expect(needed).toHaveValue("2");
    await expect(ordered).toHaveValue("4");
    await expect(unitCost).toHaveValue("82.5");
  });

  test("keeps complete geometry at desktop, laptop, mobile, reduced motion, and forced colors", async ({
    page,
  }) => {
    await installStudioApi(page);
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await page.goto(PROJECT_URL);

    const canvas = page.getByLabel("Top-down aerial lighting plan canvas");
    await page.setViewportSize({ width: 1440, height: 1000 });
    const desktopScale = Number(await canvas.getAttribute("data-view-scale"));
    const desktopView = await canvas.evaluate((element) => ({
      scale: element.getAttribute("data-view-scale"),
      x: element.getAttribute("data-view-origin-x"),
      y: element.getAttribute("data-view-origin-y"),
    }));
    await canvas.dispatchEvent("wheel", { deltaX: 80, deltaY: 120 });
    expect(
      await canvas.evaluate((element) => ({
        scale: element.getAttribute("data-view-scale"),
        x: element.getAttribute("data-view-origin-x"),
        y: element.getAttribute("data-view-origin-y"),
      })),
    ).toEqual(desktopView);

    for (const viewport of [
      { width: 1280, height: 800 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
      { width: 320, height: 568 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(page.getByRole("tab", { name: "Pre-Con" })).toBeAttached();
      await expect(page.getByRole("region", { name: "Drawing toolbar" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Fit document" })).toBeVisible();
    }

    const mobileScale = Number(await canvas.getAttribute("data-view-scale"));
    expect(mobileScale).toBeLessThan(desktopScale);
    const toolbar = page.getByRole("region", { name: "Drawing toolbar" });
    expect(
      await toolbar.evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
    ).toBe(true);
    const fitted = await page.locator(".ll-document-viewport").evaluate((viewport) => {
      const stage = viewport.querySelector<HTMLElement>(".ll-document-stage");
      const frame = viewport.querySelector<HTMLElement>(".ll-document-scale-frame");
      if (!stage || !frame) return false;
      const stageRect = stage.getBoundingClientRect();
      const frameRect = frame.getBoundingClientRect();
      return frameRect.width <= stageRect.width + 1 && frameRect.height <= stageRect.height + 1;
    });
    expect(fitted).toBe(true);
    const drawing = page.getByRole("tab", { name: "Drawing Sheet" });
    await drawing.focus();
    await page.keyboard.press("ArrowRight");
    const fixtureScheduleTab = page.getByRole("tab", { name: "Fixture Schedule" });
    await expect(fixtureScheduleTab).toHaveAttribute("aria-selected", "true");
    await fixtureScheduleTab.focus();
    await page.keyboard.press("ArrowRight");
    const bomTab = page.getByRole("tab", { name: "BOM" });
    await expect(bomTab).toHaveAttribute("aria-selected", "true");
    await expect(bomTab).toBeInViewport({ ratio: 1 });

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await expect(page.getByRole("heading", { name: "Bill of Materials" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Recount plan" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Bill of materials table" })).toBeVisible();
    const pageHasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(pageHasHorizontalOverflow).toBe(false);
  });

  test("captures every document at desktop, tablet, and mobile", async ({ page }) => {
    test.setTimeout(60_000);
    await installStudioApi(page);
    const viewports = [
      { name: "desktop", width: 1440, height: 960 },
      { name: "tablet", width: 768, height: 1024 },
      { name: "mobile", width: 390, height: 844 },
    ] as const;
    const documents = [
      { tab: "Drawing Sheet", slug: "drawing" },
      { tab: "Fixture Schedule", slug: "schedule" },
      { tab: "BOM", slug: "bom" },
      { tab: "Electrical", slug: "electrical" },
      { tab: "Proposal", slug: "proposal" },
      { tab: "Pre-Con", slug: "precon" },
    ] as const;

    await page.goto(PROJECT_URL);
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      for (const document of documents) {
        await page.getByRole("tab", { name: document.tab }).click();
        await expect(page.getByRole("tab", { name: document.tab })).toHaveAttribute(
          "aria-selected",
          "true",
        );
        await expect(page.locator(".ll-document-viewport")).toHaveAttribute(
          "data-document-zoom",
          /\d+/,
        );
        await page.screenshot({
          path: `../.ezcoder/screenshots/niteliteos-final/${viewport.name}/${document.slug}.png`,
          animations: "disabled",
        });
        if (document.slug === "drawing" && viewport.name !== "tablet") {
          await page.screenshot({
            path: `../.ezcoder/screenshots/maxteriors-studio-${viewport.name}.png`,
            animations: "disabled",
          });
        }
      }
    }
  });
});
