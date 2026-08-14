import type { DesignerShot } from "@/components/estimator/proposal-host";

export const MAX_LANDSCAPE_SHEETS = 6;

const uniqueId = (prefix: string): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? `${prefix}-${crypto.randomUUID()}`
    : `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;

export function relabelLandscapeSheets(shots: readonly DesignerShot[]): DesignerShot[] {
  return shots.map((shot, index) => ({
    ...shot,
    sheet: {
      ...shot.sheet,
      label: shot.sheet?.label?.trim() || `Aerial plan ${index + 1}`,
      drawingTitle: shot.sheet?.drawingTitle?.trim() || "Aerial landscape lighting plan",
      drawingNumber: `L-${index + 1}`,
      revisions: shot.sheet?.revisions ?? [],
    },
  }));
}

export function addLandscapeSheet(
  shots: readonly DesignerShot[],
  shot: DesignerShot,
): DesignerShot[] {
  if (shots.length >= MAX_LANDSCAPE_SHEETS) return [...shots];
  return relabelLandscapeSheets([...shots, shot]);
}

export function duplicateLandscapeSheet(
  shots: readonly DesignerShot[],
  shotId: string,
): DesignerShot[] {
  if (shots.length >= MAX_LANDSCAPE_SHEETS) return [...shots];
  const index = shots.findIndex((shot) => shot.id === shotId);
  if (index < 0) return [...shots];
  const source = shots[index];
  const copy: DesignerShot = structuredClone(source);
  copy.id = uniqueId("shot");
  copy.design.runs = copy.design.runs.map((run) => ({ ...run, id: uniqueId("run") }));
  const runIds = new Map(
    source.design.runs.map((run, runIndex) => [run.id, copy.design.runs[runIndex]?.id]),
  );
  copy.design.items = copy.design.items.map((item) => ({
    ...item,
    id: uniqueId("item"),
    circuitId: item.circuitId ? runIds.get(item.circuitId) : undefined,
  }));
  copy.design.planImages = copy.design.planImages?.map((image) => ({
    ...image,
    id: uniqueId("plan-image"),
  }));
  copy.sheet = {
    ...copy.sheet,
    label: `${source.sheet?.label || `Aerial plan ${index + 1}`} copy`,
  };
  return relabelLandscapeSheets([
    ...shots.slice(0, index + 1),
    copy,
    ...shots.slice(index + 1),
  ]);
}

export function deleteLandscapeSheet(
  shots: readonly DesignerShot[],
  shotId: string,
): DesignerShot[] {
  if (shots.length <= 1) return [...shots];
  return relabelLandscapeSheets(shots.filter((shot) => shot.id !== shotId));
}

export function renameLandscapeSheet(
  shots: readonly DesignerShot[],
  shotId: string,
  label: string,
): DesignerShot[] {
  const normalized = label.trim().slice(0, 120);
  return shots.map((shot) =>
    shot.id === shotId
      ? { ...shot, sheet: { ...shot.sheet, label: normalized || shot.sheet?.label } }
      : shot,
  );
}

export interface NumberedLandscapeFixture {
  number: number;
  shotId: string;
  itemId: string;
  productId: string;
}

export function recountLandscapeFixtures(
  shots: readonly DesignerShot[],
  isFixture: (productId: string) => boolean,
): NumberedLandscapeFixture[] {
  const rows: NumberedLandscapeFixture[] = [];
  for (const shot of shots) {
    for (const item of shot.design.items) {
      if (!isFixture(item.productId)) continue;
      rows.push({ number: rows.length + 1, shotId: shot.id, itemId: item.id, productId: item.productId });
    }
  }
  return rows;
}
