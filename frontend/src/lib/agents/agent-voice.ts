import {
  REALTIME_VOICES,
  HUME_VOICES,
  GROK_VOICES,
  ELEVENLABS_VOICES,
  type VoiceOption,
} from "@/lib/voice-constants";

/**
 * Single source of truth for agent voice provider / voice resolution shared by
 * the create wizard and the edit screen.
 */

export type VoiceProvider = "openai" | "hume" | "grok" | "elevenlabs";

export const DEFAULT_VOICE_BY_PROVIDER: Record<VoiceProvider, string> = {
  openai: "marin",
  hume: "kora",
  grok: "ara",
  elevenlabs: "ava",
};

/**
 * Map a pricing tier id to the underlying voice provider used by the API.
 * Unknown tiers fall back to OpenAI Realtime.
 */
export function getVoiceProviderForTier(tier: string): VoiceProvider {
  switch (tier) {
    case "grok":
      return "grok";
    case "openai-hume":
      return "hume";
    case "elevenlabs":
      return "elevenlabs";
    default:
      return "openai";
  }
}

/** Return the selectable voices for a given provider. */
export function getVoicesForProvider(provider: string): VoiceOption[] {
  switch (provider) {
    case "grok":
      return GROK_VOICES;
    case "hume":
      return HUME_VOICES;
    case "elevenlabs":
      return ELEVENLABS_VOICES;
    default:
      return REALTIME_VOICES;
  }
}

/** Return the recommended default voice id for a provider. */
export function getDefaultVoiceForProvider(provider: string): string {
  return DEFAULT_VOICE_BY_PROVIDER[provider as VoiceProvider] ?? DEFAULT_VOICE_BY_PROVIDER.openai;
}

/**
 * Resolve a valid voice id for the given provider: keep the current voice when
 * it is valid for the provider, otherwise fall back to the provider default.
 */
export function resolveVoiceForProvider(provider: string, currentVoice: string): string {
  const validIds = getVoicesForProvider(provider).map((v) => v.id);
  return validIds.includes(currentVoice) ? currentVoice : getDefaultVoiceForProvider(provider);
}
