import type {
  LandscapeAnnotation,
  LandscapeArrow,
  LandscapeHighlightStroke,
  LandscapeMeasurementLine,
  LandscapeProposalZone,
  Point,
} from "@/lib/estimator/types";

export const createLandscapeAnnotation = (
  id: string,
  type: LandscapeAnnotation["type"],
  at: Point,
  options: Omit<Partial<LandscapeAnnotation>, "id" | "type" | "at"> = {},
): LandscapeAnnotation => ({ id, type, at, ...options });

export const createLandscapeMeasurement = (
  id: string,
  a: Point,
  b: Point,
  label?: string,
): LandscapeMeasurementLine => ({ id, a, b, label, visible: true });

export const createLandscapeHighlight = (
  id: string,
  points: Point[],
  color = "#F2C94C",
  widthPx = 18,
): LandscapeHighlightStroke => ({ id, points, color, widthPx });

export const createLandscapeArrow = (
  id: string,
  a: Point,
  b: Point,
  label?: string,
): LandscapeArrow => ({ id, a, b, label });

export function upsertProposalZone(
  zones: readonly LandscapeProposalZone[],
  zone: LandscapeProposalZone,
): LandscapeProposalZone[] {
  const normalized = {
    ...zone,
    name: zone.name.trim().slice(0, 120),
    description: zone.description.trim().slice(0, 2000),
    shotIds: [...new Set(zone.shotIds)],
  };
  if (!normalized.name) return [...zones];
  return zones.some((entry) => entry.id === zone.id)
    ? zones.map((entry) => (entry.id === zone.id ? normalized : entry))
    : [...zones, normalized];
}

export function removeProposalZone(
  zones: readonly LandscapeProposalZone[],
  zoneId: string,
): LandscapeProposalZone[] {
  return zones.filter((zone) => zone.id !== zoneId);
}
