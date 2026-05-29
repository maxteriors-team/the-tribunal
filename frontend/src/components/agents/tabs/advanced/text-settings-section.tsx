import type { Control } from "react-hook-form";

import type { EditAgentFormValues } from "@/components/agents/agent-edit-schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Slider } from "@/components/ui/slider";
import {
  TEXT_RESPONSE_DELAY_STEP_MS,
  TEXT_RESPONSE_DEFAULT_DELAY_MS,
  TEXT_RESPONSE_MAX_DELAY_MS,
  TEXT_RESPONSE_MIN_DELAY_MS,
  clampTextResponseDelayMs,
  formatTextResponseDelay,
} from "@/lib/text-response-timing";

interface TextSettingsSectionProps {
  control: Control<EditAgentFormValues>;
}

export function TextSettingsSection({ control }: TextSettingsSectionProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Text Agent Settings</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <FormField
          control={control}
          name="textResponseDelayMs"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-center justify-between">
                <FormLabel>Minimum Response Delay</FormLabel>
                <span className="text-sm font-medium">
                  {formatTextResponseDelay(clampTextResponseDelayMs(field.value))}
                </span>
              </div>
              <FormControl>
                <div className="space-y-2">
                  <Slider
                    min={TEXT_RESPONSE_MIN_DELAY_MS}
                    max={TEXT_RESPONSE_MAX_DELAY_MS}
                    step={TEXT_RESPONSE_DELAY_STEP_MS}
                    value={[clampTextResponseDelayMs(field.value)]}
                    onValueChange={(value) => field.onChange(value[0])}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{formatTextResponseDelay(TEXT_RESPONSE_MIN_DELAY_MS)}</span>
                    <span>{formatTextResponseDelay(TEXT_RESPONSE_DEFAULT_DELAY_MS)}</span>
                    <span>{formatTextResponseDelay(TEXT_RESPONSE_MAX_DELAY_MS)}</span>
                  </div>
                </div>
              </FormControl>
              <FormDescription>
                The fastest an AI text will send. Longer replies automatically wait longer, up to 3 minutes.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={control}
          name="textMaxContextMessages"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-center justify-between">
                <FormLabel>Max Context Messages</FormLabel>
                <span className="text-sm font-medium">{field.value}</span>
              </div>
              <FormControl>
                <Slider
                  min={1}
                  max={50}
                  step={1}
                  value={[field.value]}
                  onValueChange={(value) => field.onChange(value[0])}
                  className="w-full"
                />
              </FormControl>
              <FormDescription>
                Number of previous messages to include for context
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      </CardContent>
    </Card>
  );
}
