export const PRODUCT_BRAND = {
  name: "The Tribunal",
  shortName: "Tribunal",
  description: "AI-powered CRM for lead capture, follow-up, booking, and customer communications.",
} as const;

export const DEFAULT_WORKSPACE_BRAND_NAME = "Your business";

interface WorkspaceBrandSource {
  name?: string | null;
  settings?: Record<string, unknown> | null;
}

export interface WorkspaceBrand {
  businessName: string;
  logoUrl: string | null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Keep tenant branding separate from the product brand used by shared app chrome. */
export function resolveWorkspaceBrand(workspace?: WorkspaceBrandSource | null): WorkspaceBrand {
  const proposalTemplate = recordValue(workspace?.settings?.proposal_template);

  return {
    businessName:
      nonEmptyString(proposalTemplate?.business_name) ??
      nonEmptyString(workspace?.name) ??
      DEFAULT_WORKSPACE_BRAND_NAME,
    logoUrl: nonEmptyString(proposalTemplate?.logo_url),
  };
}
