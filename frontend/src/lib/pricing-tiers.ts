export interface PricingTier {
  id: string;
  name: string;
  description: string;
  costPerHour: number;
  costPerMinute: number;
  recommended?: boolean;
  underConstruction?: boolean;
  features: string[];
  config: {
    llmProvider: string;
    llmModel: string;
    sttProvider: string;
    sttModel: string;
    ttsProvider: string;
    ttsModel: string;
    telephonyProvider: string;
  };
  performance: {
    latency: string;
    speed: string;
    quality: string;
  };
}

export const PRICING_TIERS: PricingTier[] = [
  {
    id: "grok",
    name: "Grok Voice",
    description: "xAI's Grok with realism enhancements - [whisper], [sigh], [laugh]",
    costPerHour: 3.0,
    costPerMinute: 0.05,
    features: [
      "Grok AI reasoning",
      "Realism cues: [whisper], [sigh], [laugh]",
      "OpenAI Realtime compatible",
      "5 expressive voices",
      "Built-in X search",
    ],
    config: {
      llmProvider: "grok",
      llmModel: "grok-realtime",
      sttProvider: "grok",
      sttModel: "built-in",
      ttsProvider: "grok",
      ttsModel: "built-in",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~300ms",
      speed: "Excellent",
      quality: "Best",
    },
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    description:
      "Grok AI + ElevenLabs TTS (v2.5 low-latency or v3 most expressive) with 100+ voices",
    costPerHour: 2.5,
    costPerMinute: 0.042,
    features: [
      "Grok AI reasoning + tools",
      "ElevenLabs premium TTS",
      "100+ expressive voices",
      "Built-in X/web search",
      "Google Calendar booking support",
    ],
    config: {
      llmProvider: "grok",
      llmModel: "grok-realtime",
      sttProvider: "grok",
      sttModel: "built-in",
      ttsProvider: "elevenlabs",
      ttsModel: "eleven_flash_v2_5",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~400ms",
      speed: "Excellent",
      quality: "Best",
    },
  },
  {
    id: "openai-hume",
    name: "OpenAI + Hume",
    description: "OpenAI GPT-5.4 intelligence with Hume's expressive voices",
    costPerHour: 1.68,
    costPerMinute: 0.028,
    features: [
      "OpenAI GPT-5.4 reasoning",
      "Hume Octave TTS (~100ms)",
      "100+ custom voices",
      "Voice cloning support",
      "Natural expressiveness",
    ],
    config: {
      llmProvider: "openai",
      llmModel: "gpt-5.4-mini",
      sttProvider: "deepgram",
      sttModel: "nova-3",
      ttsProvider: "hume",
      ttsModel: "octave-2",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~320ms",
      speed: "Excellent",
      quality: "Best",
    },
  },
  {
    id: "hume-evi",
    name: "Hume EVI",
    description: "Empathic voice AI with real-time emotion detection",
    costPerHour: 2.16,
    costPerMinute: 0.036,
    features: [
      "Real-time emotion detection",
      "Empathic AI responses",
      "~100ms latency (Octave 2)",
      "11+ languages (EVI 4-mini)",
      "100+ expressive voices",
    ],
    config: {
      llmProvider: "hume-evi",
      llmModel: "evi-3",
      sttProvider: "hume",
      sttModel: "built-in",
      ttsProvider: "hume",
      ttsModel: "octave-2",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~100ms",
      speed: "Excellent",
      quality: "Best",
    },
  },
  {
    id: "premium",
    name: "Premium",
    description: "Best quality with OpenAI's latest gpt-realtime model",
    costPerHour: 1.92,
    costPerMinute: 0.032,
    recommended: true,
    features: [
      "Lowest latency: ~320ms",
      "Most natural & expressive voice",
      "Best instruction following",
      "New voices: marin, cedar",
      "Production-ready (latest snapshot)",
    ],
    config: {
      llmProvider: "openai-realtime",
      llmModel: "gpt-realtime",
      sttProvider: "openai",
      sttModel: "built-in",
      ttsProvider: "openai",
      ttsModel: "built-in",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~320ms",
      speed: "Good",
      quality: "Best",
    },
  },
  {
    id: "premium-mini",
    name: "Premium Mini",
    description: "OpenAI Realtime at a fraction of the cost",
    costPerHour: 0.54,
    costPerMinute: 0.009,
    features: [
      "72% cheaper than Premium",
      "OpenAI Realtime quality",
      "Low latency: ~350ms",
      "Built-in tool connectors",
      "Great for high volume",
    ],
    config: {
      llmProvider: "openai-realtime",
      llmModel: "gpt-realtime-mini",
      sttProvider: "openai",
      sttModel: "built-in",
      ttsProvider: "openai",
      ttsModel: "built-in",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~350ms",
      speed: "Good",
      quality: "Very Good",
    },
  },
  {
    id: "balanced",
    name: "Balanced",
    description: "Best performance-to-cost ratio with multimodal capabilities",
    costPerHour: 1.35,
    costPerMinute: 0.0225,
    underConstruction: true,
    features: [
      "53% cheaper than premium",
      "Fastest: 268 tokens/sec",
      "Multimodal (voice + vision)",
      "All-in-one simplicity",
      "30+ built-in voices",
    ],
    config: {
      llmProvider: "google",
      llmModel: "gemini-2.5-flash",
      sttProvider: "google",
      sttModel: "built-in",
      ttsProvider: "google",
      ttsModel: "built-in",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~400ms",
      speed: "268 tokens/sec",
      quality: "Excellent",
    },
  },
  {
    id: "budget",
    name: "Budget",
    description: "Maximum cost savings - perfect for high-volume operations",
    costPerHour: 0.86,
    costPerMinute: 0.0143,
    underConstruction: true,
    features: [
      "56% cheaper than premium",
      "Ultra-fast: 450 tokens/sec",
      "Enterprise-grade quality",
      "All standard features",
    ],
    config: {
      llmProvider: "cerebras",
      llmModel: "llama-3.3-70b",
      sttProvider: "deepgram",
      sttModel: "nova-3",
      ttsProvider: "elevenlabs",
      ttsModel: "eleven_flash_v2_5",
      telephonyProvider: "telnyx",
    },
    performance: {
      latency: "~530ms",
      speed: "450 tokens/sec",
      quality: "Excellent",
    },
  },
];

export function calculateMonthlyCost(
  tier: PricingTier,
  callsPerMonth: number,
  avgDurationMinutes: number,
  inboundPercentage: number = 50,
): {
  totalMinutes: number;
  aiCost: number;
  telephonyCost: number;
  totalCost: number;
  costPerCall: number;
} {
  const totalMinutes = callsPerMonth * avgDurationMinutes;
  const inboundMinutes = totalMinutes * (inboundPercentage / 100);
  const outboundMinutes = totalMinutes - inboundMinutes;

  // AI costs (same for inbound/outbound)
  const aiCostPerMinute = tier.costPerMinute - (inboundPercentage >= 50 ? 0.0075 : 0.01);
  const aiCost = totalMinutes * aiCostPerMinute;

  // Telephony costs (different for inbound/outbound)
  const telephonyCost = inboundMinutes * 0.0075 + outboundMinutes * 0.01;

  const totalCost = aiCost + telephonyCost;
  const costPerCall = totalCost / callsPerMonth;

  return {
    totalMinutes,
    aiCost,
    telephonyCost,
    totalCost,
    costPerCall,
  };
}
