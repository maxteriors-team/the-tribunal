import { Wand2 } from "lucide-react";
import type { UseFormReturn } from "react-hook-form";

import type { EditAgentFormValues } from "@/components/agents/agent-edit-schema";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils/number";
import { BEST_PRACTICES_PROMPT } from "@/lib/voice-constants";

interface PromptTabProps {
  form: UseFormReturn<EditAgentFormValues>;
}

export function PromptTab({ form }: PromptTabProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">AI Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-lg border border-dashed bg-muted/50 p-3">
          <div>
            <p className="text-sm font-medium">Need help writing a prompt?</p>
            <p className="text-xs text-muted-foreground">Start with our best practices template</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => form.setValue("systemPrompt", BEST_PRACTICES_PROMPT)}
            className="shrink-0"
          >
            <Wand2 className="mr-1.5 h-3.5 w-3.5" />
            Use Best Practices
          </Button>
        </div>

        <FormField
          control={form.control}
          name="systemPrompt"
          render={({ field }) => {
            const charCount = field.value?.length ?? 0;
            const isOptimal = charCount >= 100 && charCount <= 2000;
            const isTooShort = charCount > 0 && charCount < 100;
            const isTooLong = charCount > 2000;
            return (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>System Prompt</FormLabel>
                  <span
                    className={cn(
                      "text-xs",
                      isOptimal && "text-green-600",
                      isTooShort && "text-yellow-600",
                      isTooLong && "text-destructive",
                    )}
                  >
                    {formatNumber(charCount)} characters
                    {isTooShort && " (recommended: 100+)"}
                    {isTooLong && " (recommended: under 2,000)"}
                  </span>
                </div>
                <FormControl>
                  <Textarea
                    placeholder="You are a helpful customer support agent..."
                    className="min-h-[200px] font-mono text-sm"
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  Instructions that define your agent&apos;s personality and behavior
                </FormDescription>
                <FormMessage />
              </FormItem>
            );
          }}
        />

        <div className="space-y-4 rounded-lg border p-4">
          <FormField
            control={form.control}
            name="websiteLeadQualificationEnabled"
            render={({ field }) => (
              <FormItem className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <FormLabel>Qualify website leads before booking</FormLabel>
                  <FormDescription>
                    Ask the checklist one question at a time. Booking stays unavailable until the
                    lead qualifies.
                  </FormDescription>
                </div>
                <FormControl>
                  <Switch
                    aria-label="Qualify website leads before booking"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                </FormControl>
              </FormItem>
            )}
          />

          {form.watch("websiteLeadQualificationEnabled") && (
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="qualificationQuestions"
                render={({ field }) => (
                  <FormItem className="md:col-span-2">
                    <FormLabel>Qualification checklist</FormLabel>
                    <FormControl>
                      <Textarea
                        aria-label="Qualification checklist"
                        placeholder={"What service do you need?\nWhat is your project timeline?"}
                        className="min-h-28"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      One question per line, up to 10. Form answers are reused instead of re-asked.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="qualificationMinScore"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Minimum qualification score</FormLabel>
                    <FormControl>
                      <Input
                        aria-label="Minimum qualification score"
                        type="number"
                        min={0}
                        max={100}
                        value={field.value}
                        onChange={(event) => field.onChange(event.target.valueAsNumber)}
                      />
                    </FormControl>
                    <FormDescription>0-100; 60 is the recommended default.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="qualificationBookingLabel"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Booking transition label</FormLabel>
                    <FormControl>
                      <Input aria-label="Booking transition label" {...field} />
                    </FormControl>
                    <FormDescription>
                      Shown to the AI, for example Zoom consultation.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          )}
        </div>

        <FormField
          control={form.control}
          name="temperature"
          render={({ field }) => {
            const getTemperatureLabel = (value: number) => {
              if (value <= 0.3) return "Focused";
              if (value <= 0.7) return "Balanced";
              if (value <= 1.2) return "Creative";
              return "Very Creative";
            };
            return (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>Temperature</FormLabel>
                  <span className="text-sm font-medium">
                    {field.value?.toFixed(1) ?? "0.7"} ({getTemperatureLabel(field.value ?? 0.7)})
                  </span>
                </div>
                <FormControl>
                  <div className="space-y-2">
                    <Slider
                      min={0}
                      max={2}
                      step={0.1}
                      value={[field.value ?? 0.7]}
                      onValueChange={(value) => field.onChange(value[0])}
                      className="w-full"
                    />
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>Focused</span>
                      <span>Creative</span>
                    </div>
                  </div>
                </FormControl>
                <FormDescription>
                  Lower values produce more focused and deterministic responses
                </FormDescription>
                <FormMessage />
              </FormItem>
            );
          }}
        />
      </CardContent>
    </Card>
  );
}
