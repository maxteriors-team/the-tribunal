import type {
  LandscapePreconResponse,
  LandscapePreconResponseValue,
  LandscapePreconState,
} from "@/lib/estimator/types";

export interface LandscapePreconItem {
  id: string;
  group: string;
  label: string;
}

export const LANDSCAPE_PRECON_ITEMS: readonly LandscapePreconItem[] = [
  { id: "contract-scope", group: "Contract", label: "Signed scope matches the approved design" },
  { id: "contract-payment", group: "Contract", label: "Deposit and payment milestones are confirmed" },
  { id: "contract-change-orders", group: "Contract", label: "Open change orders are documented" },
  { id: "client-contact", group: "Client and site", label: "Day-of-install contact is confirmed" },
  { id: "site-access", group: "Client and site", label: "Crew and vehicle access is confirmed" },
  { id: "site-gates", group: "Client and site", label: "Gate codes and lock access are available" },
  { id: "site-pets", group: "Client and site", label: "Pet containment plan is confirmed" },
  { id: "site-utilities", group: "Client and site", label: "Private and public utilities are marked" },
  { id: "site-irrigation", group: "Client and site", label: "Irrigation heads and lines are identified" },
  { id: "site-landscape", group: "Client and site", label: "Sensitive plantings and surfaces are identified" },
  { id: "design-current", group: "Design", label: "Crew has the current drawing revision" },
  { id: "design-scale", group: "Design", label: "Plan scale and key measurements are confirmed" },
  { id: "design-fixtures", group: "Design", label: "Fixture count and aiming intent are reviewed" },
  { id: "design-zones", group: "Design", label: "Transformer zones and named runs are reviewed" },
  { id: "materials-fixtures", group: "Materials", label: "Fixtures are received and inspected" },
  { id: "materials-lamps", group: "Materials", label: "Lamps and accessories are received" },
  { id: "materials-transformers", group: "Materials", label: "Transformers and controls are received" },
  { id: "materials-wire", group: "Materials", label: "Required wire gauges and quantities are loaded" },
  { id: "materials-mounting", group: "Materials", label: "Mounting hardware and consumables are loaded" },
  { id: "electrical-source", group: "Electrical", label: "Source power location is confirmed" },
  { id: "electrical-voltage", group: "Electrical", label: "Source voltage and minimum voltage plan are reviewed" },
  { id: "electrical-capacity", group: "Electrical", label: "Transformer capacity and design checks are reviewed" },
  { id: "crew-lead", group: "Crew and logistics", label: "Lead installer is assigned" },
  { id: "crew-schedule", group: "Crew and logistics", label: "Install date and estimated duration are confirmed" },
  { id: "crew-equipment", group: "Crew and logistics", label: "Specialty tools and access equipment are loaded" },
  { id: "closeout-plan", group: "Crew and logistics", label: "Testing, cleanup, training, and closeout plan is reviewed" },
] as const;

export interface LandscapePreconProgress {
  completed: number;
  total: number;
  percent: number;
  ready: number;
  blocked: number;
  notApplicable: number;
}

export function preconResponseMap(
  state: LandscapePreconState | undefined,
): Map<string, LandscapePreconResponse> {
  return new Map((state?.responses ?? []).map((response) => [response.itemId, response]));
}

export function setPreconResponse(
  state: LandscapePreconState,
  itemId: string,
  value: LandscapePreconResponseValue,
  comment?: string,
): LandscapePreconState {
  if (!LANDSCAPE_PRECON_ITEMS.some((item) => item.id === itemId)) return state;
  const current = preconResponseMap(state).get(itemId);
  const response: LandscapePreconResponse = {
    itemId,
    value,
    comment: comment ?? current?.comment ?? "",
  };
  return {
    ...state,
    responses: [
      ...state.responses.filter((entry) => entry.itemId !== itemId),
      response,
    ],
  };
}

export function calculatePreconProgress(
  state: LandscapePreconState | undefined,
): LandscapePreconProgress {
  const responses = preconResponseMap(state);
  const values = LANDSCAPE_PRECON_ITEMS.map((item) => responses.get(item.id)?.value ?? null);
  const completed = values.filter(Boolean).length;
  return {
    completed,
    total: LANDSCAPE_PRECON_ITEMS.length,
    percent: Math.round((completed / LANDSCAPE_PRECON_ITEMS.length) * 100),
    ready: values.filter((value) => value === "yes").length,
    blocked: values.filter((value) => value === "no").length,
    notApplicable: values.filter((value) => value === "na").length,
  };
}

export const groupPreconItems = (): Array<{ group: string; items: LandscapePreconItem[] }> => {
  const groups = new Map<string, LandscapePreconItem[]>();
  for (const item of LANDSCAPE_PRECON_ITEMS) {
    groups.set(item.group, [...(groups.get(item.group) ?? []), item]);
  }
  return [...groups].map(([group, items]) => ({ group, items }));
};
