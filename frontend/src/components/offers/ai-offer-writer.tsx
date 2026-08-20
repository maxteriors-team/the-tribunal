"use client";

import { useMutation } from "@tanstack/react-query";
import { Sparkles, Loader2, Check, ChevronRight, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  offersApi,
  GenerateOfferRequest,
  GeneratedOfferContent,
  GeneratedHeadline,
  GeneratedSubheadline,
  GeneratedValueStackItem,
  GeneratedGuarantee,
  GeneratedUrgency,
  GeneratedCTA,
} from "@/lib/api/offers";
import { formatNumber } from "@/lib/utils/number";
import type { ValueStackItem, GuaranteeType, UrgencyType } from "@/types";

interface AIOfferWriterProps {
  workspaceId: string;
  onApply: (data: {
    headline?: string;
    subheadline?: string;
    value_stack_items?: ValueStackItem[];
    guarantee_type?: GuaranteeType;
    guarantee_days?: number;
    guarantee_text?: string;
    urgency_type?: UrgencyType;
    urgency_text?: string;
    scarcity_count?: number;
    cta_text?: string;
    cta_subtext?: string;
  }) => void;
}

type Step =
  | "inputs"
  | "headlines"
  | "subheadlines"
  | "values"
  | "guarantees"
  | "urgency"
  | "ctas"
  | "review";

const STEPS: Step[] = [
  "inputs",
  "headlines",
  "subheadlines",
  "values",
  "guarantees",
  "urgency",
  "ctas",
  "review",
];

export function AIOfferWriter({ workspaceId, onApply }: AIOfferWriterProps) {
  const [open, setOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState<Step>("inputs");

  // Input form state
  const [inputs, setInputs] = useState<GenerateOfferRequest>({
    business_type: "",
    target_audience: "",
    main_offer: "",
    price_point: undefined,
    desired_outcome: "",
    pain_points: [],
    unique_mechanism: "",
  });
  const [painPointInput, setPainPointInput] = useState("");

  // Generated content state
  const [generatedContent, setGeneratedContent] = useState<GeneratedOfferContent | null>(null);

  // Selected options state
  const [selectedHeadline, setSelectedHeadline] = useState<GeneratedHeadline | null>(null);
  const [selectedSubheadline, setSelectedSubheadline] = useState<GeneratedSubheadline | null>(null);
  const [selectedValueItems, setSelectedValueItems] = useState<GeneratedValueStackItem[]>([]);
  const [selectedGuarantee, setSelectedGuarantee] = useState<GeneratedGuarantee | null>(null);
  const [selectedUrgency, setSelectedUrgency] = useState<GeneratedUrgency | null>(null);
  const [selectedCTA, setSelectedCTA] = useState<GeneratedCTA | null>(null);

  const generateMutation = useMutation({
    mutationFn: () => offersApi.generate(workspaceId, inputs),
    onSuccess: (data) => {
      setGeneratedContent(data);
      setCurrentStep("headlines");
    },
  });

  const addPainPoint = () => {
    if (painPointInput.trim()) {
      setInputs((prev) => ({
        ...prev,
        pain_points: [...(prev.pain_points || []), painPointInput.trim()],
      }));
      setPainPointInput("");
    }
  };

  const removePainPoint = (index: number) => {
    setInputs((prev) => ({
      ...prev,
      pain_points: prev.pain_points?.filter((_, i) => i !== index),
    }));
  };

  const handleNext = () => {
    const currentIndex = STEPS.indexOf(currentStep);
    if (currentIndex < STEPS.length - 1) {
      setCurrentStep(STEPS[currentIndex + 1]);
    }
  };

  const handleBack = () => {
    const currentIndex = STEPS.indexOf(currentStep);
    if (currentIndex > 0) {
      setCurrentStep(STEPS[currentIndex - 1]);
    }
  };

  const handleApply = () => {
    const data: Parameters<typeof onApply>[0] = {};

    if (selectedHeadline) {
      data.headline = selectedHeadline.text;
    }

    if (selectedSubheadline) {
      data.subheadline = selectedSubheadline.text;
    }

    if (selectedValueItems.length > 0) {
      data.value_stack_items = selectedValueItems.map((item) => ({
        name: item.name,
        description: item.description,
        value: item.value,
        included: true,
      }));
    }

    if (selectedGuarantee) {
      data.guarantee_type = selectedGuarantee.type as GuaranteeType;
      data.guarantee_days = selectedGuarantee.days;
      data.guarantee_text = selectedGuarantee.text;
    }

    if (selectedUrgency) {
      data.urgency_type = selectedUrgency.type as UrgencyType;
      data.urgency_text = selectedUrgency.text;
      if (selectedUrgency.count) {
        data.scarcity_count = selectedUrgency.count;
      }
    }

    if (selectedCTA) {
      data.cta_text = selectedCTA.text;
      data.cta_subtext = selectedCTA.subtext;
    }

    onApply(data);
    setOpen(false);
    resetState();
  };

  const resetState = () => {
    setCurrentStep("inputs");
    setInputs({
      business_type: "",
      target_audience: "",
      main_offer: "",
      price_point: undefined,
      desired_outcome: "",
      pain_points: [],
      unique_mechanism: "",
    });
    setGeneratedContent(null);
    setSelectedHeadline(null);
    setSelectedSubheadline(null);
    setSelectedValueItems([]);
    setSelectedGuarantee(null);
    setSelectedUrgency(null);
    setSelectedCTA(null);
  };

  const toggleValueItem = (item: GeneratedValueStackItem) => {
    setSelectedValueItems((prev) => {
      const exists = prev.some((i) => i.name === item.name);
      if (exists) {
        return prev.filter((i) => i.name !== item.name);
      }
      return [...prev, item];
    });
  };

  const renderInputsStep = () => (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="business_type">Business Type *</Label>
        <Input
          id="business_type"
          placeholder="e.g., Fitness coaching, SaaS, Marketing agency"
          value={inputs.business_type}
          onChange={(e) => setInputs((prev) => ({ ...prev, business_type: e.target.value }))}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="target_audience">Target Audience *</Label>
        <Input
          id="target_audience"
          placeholder="e.g., Busy professionals aged 30-45"
          value={inputs.target_audience}
          onChange={(e) => setInputs((prev) => ({ ...prev, target_audience: e.target.value }))}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="main_offer">Main Offer/Service *</Label>
        <Textarea
          id="main_offer"
          placeholder="What are you offering? e.g., 12-week transformation program"
          value={inputs.main_offer}
          onChange={(e) => setInputs((prev) => ({ ...prev, main_offer: e.target.value }))}
          rows={2}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="desired_outcome">Dream Outcome</Label>
        <Input
          id="desired_outcome"
          placeholder="What transformation will they achieve?"
          value={inputs.desired_outcome}
          onChange={(e) => setInputs((prev) => ({ ...prev, desired_outcome: e.target.value }))}
        />
        <p className="text-xs text-muted-foreground">
          The Hormozi value equation: Value = Dream Outcome / (Time + Effort)
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="price_point">Price Point (optional)</Label>
        <Input
          id="price_point"
          type="number"
          placeholder="e.g., 997"
          value={inputs.price_point || ""}
          onChange={(e) =>
            setInputs((prev) => ({
              ...prev,
              price_point: e.target.value ? parseFloat(e.target.value) : undefined,
            }))
          }
        />
      </div>

      <div className="space-y-2">
        <Label>Pain Points</Label>
        <div className="flex gap-2">
          <Input
            placeholder="Add a pain point..."
            value={painPointInput}
            onChange={(e) => setPainPointInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addPainPoint())}
          />
          <Button type="button" variant="outline" onClick={addPainPoint}>
            Add
          </Button>
        </div>
        {inputs.pain_points && inputs.pain_points.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {inputs.pain_points.map((point, index) => (
              <Badge key={index} variant="secondary" className="gap-1">
                {point}
                <button
                  type="button"
                  onClick={() => removePainPoint(index)}
                  className="ml-1 hover:text-destructive"
                >
                  <X className="size-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="unique_mechanism">Unique Mechanism</Label>
        <Input
          id="unique_mechanism"
          placeholder="What makes your approach different?"
          value={inputs.unique_mechanism}
          onChange={(e) => setInputs((prev) => ({ ...prev, unique_mechanism: e.target.value }))}
        />
      </div>
    </div>
  );

  const renderSelectionStep = <T extends { text?: string; name?: string }>(
    title: string,
    description: string,
    options: T[],
    selected: T | T[] | null,
    onSelect: (item: T) => void,
    isMulti = false,
  ) => (
    <div className="space-y-4">
      <div className="text-center">
        <h3 className="font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="space-y-3">
        {options.map((option, index) => {
          const text = option.text || option.name || "";
          const isSelected = isMulti
            ? (selected as T[])?.some((s) => (s.text || s.name) === (option.text || option.name))
            : selected &&
              ((selected as T).text || (selected as T).name) === (option.text || option.name);

          return (
            <Card
              key={index}
              className={`cursor-pointer transition-all ${
                isSelected ? "ring-2 ring-primary bg-primary/5" : "hover:bg-accent"
              }`}
              onClick={() => onSelect(option)}
            >
              <CardContent className="p-4 flex items-start gap-3">
                <div
                  className={`size-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 mt-0.5 ${
                    isSelected ? "border-primary bg-primary" : "border-muted-foreground"
                  }`}
                >
                  {isSelected && <Check className="size-3 text-primary-foreground" />}
                </div>
                <div className="flex-1">
                  <p className="font-medium">{text}</p>
                  {"style" in option && (option as { style?: string }).style ? (
                    <Badge variant="outline" className="mt-1">
                      {(option as { style?: string }).style}
                    </Badge>
                  ) : null}
                  {"description" in option && (
                    <p className="text-sm text-muted-foreground mt-1">
                      {(option as unknown as GeneratedValueStackItem).description}
                    </p>
                  )}
                  {"value" in option && (
                    <p className="text-sm font-medium text-success mt-1">
                      ${formatNumber((option as unknown as GeneratedValueStackItem).value)} value
                    </p>
                  )}
                  {"days" in option && (
                    <Badge variant="secondary" className="mt-1">
                      {(option as unknown as GeneratedGuarantee).days} days
                    </Badge>
                  )}
                  {"count" in option && (option as unknown as GeneratedUrgency).count && (
                    <Badge variant="secondary" className="mt-1">
                      {(option as unknown as GeneratedUrgency).count} spots
                    </Badge>
                  )}
                  {"subtext" in option && (option as GeneratedCTA).subtext && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {(option as GeneratedCTA).subtext}
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );

  const renderReviewStep = () => (
    <div className="space-y-4">
      <div className="text-center">
        <h3 className="font-semibold">Review Your Selections</h3>
        <p className="text-sm text-muted-foreground">These will be applied to your offer form</p>
      </div>

      <div className="space-y-3">
        {selectedHeadline && (
          <div className="p-3 bg-muted rounded-lg">
            <Label className="text-xs text-muted-foreground">Headline</Label>
            <p className="font-medium">{selectedHeadline.text}</p>
          </div>
        )}

        {selectedSubheadline && (
          <div className="p-3 bg-muted rounded-lg">
            <Label className="text-xs text-muted-foreground">Subheadline</Label>
            <p>{selectedSubheadline.text}</p>
          </div>
        )}

        {selectedValueItems.length > 0 && (
          <div className="p-3 bg-muted rounded-lg">
            <Label className="text-xs text-muted-foreground">
              Value Stack ({selectedValueItems.length} items)
            </Label>
            <ul className="mt-1 space-y-1">
              {selectedValueItems.map((item, i) => (
                <li key={i} className="text-sm flex justify-between">
                  <span>{item.name}</span>
                  <span className="text-success">${formatNumber(item.value)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {selectedGuarantee && (
          <div className="p-3 bg-muted rounded-lg">
            <Label className="text-xs text-muted-foreground">Guarantee</Label>
            <p className="text-sm">{selectedGuarantee.text}</p>
          </div>
        )}

        {selectedUrgency && (
          <div className="p-3 bg-muted rounded-lg">
            <Label className="text-xs text-muted-foreground">Urgency</Label>
            <p className="text-sm">{selectedUrgency.text}</p>
          </div>
        )}

        {selectedCTA && (
          <div className="p-3 bg-muted rounded-lg">
            <Label className="text-xs text-muted-foreground">Call to Action</Label>
            <p className="font-medium">{selectedCTA.text}</p>
            {selectedCTA.subtext && (
              <p className="text-xs text-muted-foreground">{selectedCTA.subtext}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );

  const renderStepContent = () => {
    switch (currentStep) {
      case "inputs":
        return renderInputsStep();
      case "headlines":
        return (
          generatedContent &&
          renderSelectionStep(
            "Choose a Headline",
            "Select the headline that best captures your offer",
            generatedContent.headlines,
            selectedHeadline,
            setSelectedHeadline,
          )
        );
      case "subheadlines":
        return (
          generatedContent &&
          renderSelectionStep(
            "Choose a Subheadline",
            "Supporting text that reinforces your headline",
            generatedContent.subheadlines,
            selectedSubheadline,
            setSelectedSubheadline,
          )
        );
      case "values":
        return (
          generatedContent &&
          renderSelectionStep(
            "Build Your Value Stack",
            "Select items to include in your offer (select multiple)",
            generatedContent.value_stack_items,
            selectedValueItems,
            toggleValueItem,
            true,
          )
        );
      case "guarantees":
        return (
          generatedContent &&
          renderSelectionStep(
            "Choose a Guarantee",
            "Remove risk with a powerful guarantee",
            generatedContent.guarantees,
            selectedGuarantee,
            setSelectedGuarantee,
          )
        );
      case "urgency":
        return (
          generatedContent &&
          renderSelectionStep(
            "Add Urgency",
            "Create a reason to act now",
            generatedContent.urgency_options,
            selectedUrgency,
            setSelectedUrgency,
          )
        );
      case "ctas":
        return (
          generatedContent &&
          renderSelectionStep(
            "Choose Your CTA",
            "The button text that drives action",
            generatedContent.ctas,
            selectedCTA,
            setSelectedCTA,
          )
        );
      case "review":
        return renderReviewStep();
      default:
        return null;
    }
  };

  const canProceed = () => {
    if (currentStep === "inputs") {
      return inputs.business_type && inputs.target_audience && inputs.main_offer;
    }
    return true;
  };

  const getStepLabel = (step: Step) => {
    const labels: Record<Step, string> = {
      inputs: "1. Inputs",
      headlines: "2. Headlines",
      subheadlines: "3. Subheadlines",
      values: "4. Value Stack",
      guarantees: "5. Guarantees",
      urgency: "6. Urgency",
      ctas: "7. CTAs",
      review: "8. Review",
    };
    return labels[step];
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="w-full gap-2 sm:w-auto">
          <Sparkles className="size-4" />
          Generate with AI
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-5 text-primary" />
            AI Offer Writer
          </DialogTitle>
          <DialogDescription>
            Generate compelling offer content using the Hormozi value framework
          </DialogDescription>
        </DialogHeader>

        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {STEPS.map((step, index) => (
            <span
              key={step}
              className={`${
                step === currentStep
                  ? "text-primary font-medium"
                  : STEPS.indexOf(currentStep) > index
                    ? "text-primary/60"
                    : ""
              }`}
            >
              {getStepLabel(step)}
              {index < STEPS.length - 1 && <ChevronRight className="size-3 inline ml-1" />}
            </span>
          ))}
        </div>

        <ScrollArea className="max-h-[50vh] pr-4">{renderStepContent()}</ScrollArea>

        <div className="mt-4 flex flex-wrap justify-between gap-2 border-t pt-4">
          <Button
            variant="outline"
            onClick={currentStep === "inputs" ? () => setOpen(false) : handleBack}
          >
            {currentStep === "inputs" ? "Cancel" : "Back"}
          </Button>

          {currentStep === "inputs" ? (
            <Button
              onClick={() => generateMutation.mutate()}
              disabled={!canProceed() || generateMutation.isPending}
            >
              {generateMutation.isPending ? (
                <>
                  <Loader2 className="size-4 mr-2 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Sparkles className="size-4 mr-2" />
                  Generate Content
                </>
              )}
            </Button>
          ) : currentStep === "review" ? (
            <Button onClick={handleApply}>
              <Check className="size-4 mr-2" />
              Apply to Form
            </Button>
          ) : (
            <Button onClick={handleNext}>
              Next
              <ChevronRight className="size-4 ml-1" />
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
