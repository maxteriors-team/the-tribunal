import type { TimelineItem } from "@/types";

const QUO_HOSTNAME = "my.quo.com";

type QuoLinkSource = Pick<TimelineItem, "source_provider" | "external_url">;

export function getValidatedQuoLink(item: QuoLinkSource): string | null {
  if (item.source_provider !== "quo" || !item.external_url) return null;
  if (item.external_url.trim() !== item.external_url) return null;

  try {
    const url = new URL(item.external_url);
    if (
      url.protocol !== "https:" ||
      url.hostname !== QUO_HOSTNAME ||
      url.port ||
      url.username ||
      url.password
    ) {
      return null;
    }
  } catch {
    return null;
  }

  return item.external_url;
}

export function getLatestQuoLink(timeline: readonly TimelineItem[]): string | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const link = getValidatedQuoLink(timeline[index]);
    if (link) return link;
  }

  return null;
}
