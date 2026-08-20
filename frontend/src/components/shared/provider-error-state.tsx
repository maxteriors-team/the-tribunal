"use client";

import { Settings2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { PageEmptyState, PageErrorState } from "@/components/ui/page-state";
import { useCapabilities } from "@/hooks/useCapabilities";
import {
  getApiErrorCode,
  getApiErrorDetails,
  isProviderConfigurationError,
} from "@/lib/utils/errors";

export type ProviderSetupKind = "telnyx" | "openai" | "ad-library" | "scraping" | "people-search";

interface ProviderStateCopy {
  setupTitle: string;
  setupDescription: string;
  setupAction: string;
}

const INTEGRATIONS_SETTINGS_HREF = "/settings?tab=integrations";

export const PROVIDER_STATE_COPY: Record<ProviderSetupKind, ProviderStateCopy> = {
  telnyx: {
    setupTitle: "Connect Telnyx to manage phone numbers",
    setupDescription: "Phone-number search, purchase, release, and sync need a Telnyx connection.",
    setupAction: "Set up Telnyx",
  },
  openai: {
    setupTitle: "Connect OpenAI to use AI lead discovery",
    setupDescription: "AI lead enrichment needs an active OpenAI connection.",
    setupAction: "Set up OpenAI",
  },
  "ad-library": {
    setupTitle: "Connect an ad-library provider to search ads",
    setupDescription: "Ad Library search needs active Meta or Google ad-library credentials.",
    setupAction: "Set up ad-library access",
  },
  scraping: {
    setupTitle: "Connect a scraping provider to find leads",
    setupDescription:
      "Business lead search needs an active Google Places or scraping-provider connection.",
    setupAction: "Set up lead search",
  },
  "people-search": {
    setupTitle: "Configure people search to find decision-makers",
    setupDescription: "People discovery needs an active search or web-crawling provider.",
    setupAction: "Set up people search",
  },
};

function configuredProviderName(error: unknown): string {
  const details = getApiErrorDetails(error);
  if (typeof details !== "object" || details === null || !("provider" in details)) {
    return "";
  }

  const provider = (details as { provider?: unknown }).provider;
  return typeof provider === "string" ? provider.toLowerCase() : "";
}

/** Resolve a provider-specific response from a shared backend setup error. */
export function resolveProviderSetupKind(
  error: unknown,
  fallback: ProviderSetupKind,
): ProviderSetupKind {
  const signature = `${getApiErrorCode(error) ?? ""} ${configuredProviderName(error)}`;

  if (signature.includes("telnyx")) return "telnyx";
  if (signature.includes("openai")) return "openai";
  if (
    signature.includes("ad_library") ||
    signature.includes("ad-library") ||
    signature.includes("google_ads") ||
    signature.includes("meta")
  ) {
    return "ad-library";
  }
  if (signature.includes("people") || signature.includes("web_people")) {
    return "people-search";
  }
  if (signature.includes("scrap") || signature.includes("google_places")) {
    // A free-text people search also uses Google Places to locate company sites.
    return fallback === "people-search" ? "people-search" : "scraping";
  }

  return fallback;
}

interface ProviderPageErrorStateProps {
  error: unknown;
  provider: ProviderSetupKind;
  transientTitle: string;
  transientMessage: string;
  onRetry: () => void;
}

/** Full-page recovery state for provider-backed features. */
export function ProviderPageErrorState({
  error,
  provider,
  transientTitle,
  transientMessage,
  onRetry,
}: ProviderPageErrorStateProps) {
  const { can } = useCapabilities();
  const canConfigureIntegrations = can("workspace:manage");

  if (!isProviderConfigurationError(error)) {
    return <PageErrorState title={transientTitle} message={transientMessage} onRetry={onRetry} />;
  }

  const copy = PROVIDER_STATE_COPY[resolveProviderSetupKind(error, provider)];
  const description = canConfigureIntegrations
    ? copy.setupDescription
    : `${copy.setupDescription} Ask a workspace owner or admin to configure it.`;

  return (
    <PageEmptyState
      icon={<Settings2 className="size-8" />}
      title={copy.setupTitle}
      description={description}
      action={
        canConfigureIntegrations ? (
          <Button asChild>
            <Link href={INTEGRATIONS_SETTINGS_HREF}>{copy.setupAction}</Link>
          </Button>
        ) : undefined
      }
    />
  );
}
