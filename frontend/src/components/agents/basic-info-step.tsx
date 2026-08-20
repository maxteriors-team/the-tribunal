"use client";

import type { UseFormReturn } from "react-hook-form";

import { Card, CardContent } from "@/components/ui/card";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  REALTIME_VOICES,
  HUME_VOICES,
  GROK_VOICES,
  ELEVENLABS_VOICES,
} from "@/lib/voice-constants";

import type { AgentFormValues } from "./create-agent-form";

interface BasicInfoStepProps {
  form: UseFormReturn<AgentFormValues>;
  pricingTier: string;
  availableLanguages: Array<{ code: string; name: string }>;
}

export function BasicInfoStep({ form, pricingTier, availableLanguages }: BasicInfoStepProps) {
  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="mb-2">
          <h2 className="text-lg font-medium">Basic Information</h2>
          <p className="text-sm text-muted-foreground">Give your agent a name and identity</p>
        </div>

        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Agent Name *</FormLabel>
              <FormControl>
                <Input placeholder="e.g., Sarah" {...field} />
              </FormControl>
              <FormDescription>A friendly name to identify your agent</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="description"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Description</FormLabel>
              <FormControl>
                <Textarea
                  placeholder="Handles customer inquiries and support requests..."
                  className="min-h-[80px]"
                  {...field}
                />
              </FormControl>
              <FormDescription>Optional description for your reference</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={form.control}
            name="language"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Language ({availableLanguages.length} available)</FormLabel>
                <Select onValueChange={field.onChange} value={field.value}>
                  <FormControl>
                    <SelectTrigger aria-label="Agent language">
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent className="max-h-[300px]">
                    {availableLanguages.map((lang) => (
                      <SelectItem key={lang.code} value={lang.code}>
                        {lang.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="channelMode"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Channel Mode</FormLabel>
                <Select onValueChange={field.onChange} value={field.value}>
                  <FormControl>
                    <SelectTrigger aria-label="Agent channel mode">
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="voice">Voice Only</SelectItem>
                    <SelectItem value="text">Text Only</SelectItem>
                    <SelectItem value="both">Voice & Text</SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        {(pricingTier === "premium" ||
          pricingTier === "premium-mini" ||
          pricingTier === "openai-hume" ||
          pricingTier === "grok" ||
          pricingTier === "elevenlabs") && (
          <FormField
            control={form.control}
            name="voice"
            render={({ field }) => {
              const voices =
                pricingTier === "grok"
                  ? GROK_VOICES
                  : pricingTier === "openai-hume"
                    ? HUME_VOICES
                    : pricingTier === "elevenlabs"
                      ? ELEVENLABS_VOICES
                      : REALTIME_VOICES;
              return (
                <FormItem>
                  <FormLabel>Voice</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger aria-label="Agent voice">
                        <SelectValue placeholder="Select voice" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent className="max-h-[300px]">
                      {voices.map((voice) => (
                        <SelectItem key={voice.id} value={voice.id}>
                          {voice.name} - {voice.description}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              );
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}
