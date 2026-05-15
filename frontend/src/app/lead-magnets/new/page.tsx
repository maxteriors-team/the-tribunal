"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  Video,
  CheckSquare,
  FileSpreadsheet,
  HelpCircle,
  Calculator,
  BookOpen,
  GraduationCap,
  ChevronLeft,
  ChevronRight,
  Check,
  Loader2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { PageEmptyState } from "@/components/ui/page-state";

import { QuizBuilder } from "@/components/lead-magnets/quiz-builder";
import { CalculatorBuilder } from "@/components/lead-magnets/calculator-builder";
import { RichTextEditor } from "@/components/lead-magnets/rich-text-editor";

import { useWorkspace } from "@/providers/workspace-provider";
import { leadMagnetsApi, CreateLeadMagnetRequest } from "@/lib/api/lead-magnets";
import { formatNumber } from "@/lib/utils/number";
import type {
  LeadMagnetType,
  DeliveryMethod,
  QuizContent,
  CalculatorContent,
  RichTextContent,
} from "@/types";

interface TypeOption {
  type: LeadMagnetType;
  label: string;
  description: string;
  icon: React.ReactNode;
  category: "static" | "interactive";
}

const TYPE_OPTIONS: TypeOption[] = [
  // Static types
  {
    type: "pdf",
    label: "PDF Download",
    description: "Ebook, guide, or report",
    icon: <FileText className="size-6" />,
    category: "static",
  },
  {
    type: "video",
    label: "Video",
    description: "Training or tutorial video",
    icon: <Video className="size-6" />,
    category: "static",
  },
  {
    type: "checklist",
    label: "Checklist",
    description: "Actionable checklist",
    icon: <CheckSquare className="size-6" />,
    category: "static",
  },
  {
    type: "template",
    label: "Template",
    description: "Ready-to-use template",
    icon: <FileSpreadsheet className="size-6" />,
    category: "static",
  },
  // Interactive types
  {
    type: "quiz",
    label: "Quiz",
    description: "Assessment with scoring",
    icon: <HelpCircle className="size-6" />,
    category: "interactive",
  },
  {
    type: "calculator",
    label: "Calculator",
    description: "ROI or value calculator",
    icon: <Calculator className="size-6" />,
    category: "interactive",
  },
  {
    type: "rich_text",
    label: "Rich Content",
    description: "Interactive article",
    icon: <BookOpen className="size-6" />,
    category: "interactive",
  },
  {
    type: "video_course",
    label: "Mini Course",
    description: "Multi-video course",
    icon: <GraduationCap className="size-6" />,
    category: "interactive",
  },
];

const DELIVERY_OPTIONS: { value: DeliveryMethod; label: string }[] = [
  { value: "email", label: "Email" },
  { value: "download", label: "Direct Download" },
  { value: "redirect", label: "Redirect to URL" },
  { value: "sms", label: "SMS" },
];

type Step = "type" | "content" | "delivery" | "review";

const STEPS: Step[] = ["type", "content", "delivery", "review"];

const emptyQuizContent: QuizContent = {
  title: "",
  description: "",
  questions: [],
  results: [],
};

const emptyCalculatorContent: CalculatorContent = {
  title: "",
  description: "",
  inputs: [],
  calculations: [],
  outputs: [],
  cta: undefined,
};

const emptyRichTextContent: RichTextContent = {
  title: "",
  description: "",
  content: { type: "doc", content: [{ type: "paragraph" }] },
};

export default function NewLeadMagnetPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.workspace.id;

  const [currentStep, setCurrentStep] = useState<Step>("type");
  const [selectedType, setSelectedType] = useState<LeadMagnetType | null>(null);

  // Form data
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [contentUrl, setContentUrl] = useState("");
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [estimatedValue, setEstimatedValue] = useState<number | undefined>();
  const [deliveryMethod, setDeliveryMethod] = useState<DeliveryMethod>("email");

  // Rich content
  const [quizContent, setQuizContent] = useState<QuizContent>(emptyQuizContent);
  const [calculatorContent, setCalculatorContent] = useState<CalculatorContent>(emptyCalculatorContent);
  const [richTextContent, setRichTextContent] = useState<RichTextContent>(emptyRichTextContent);

  const createMutation = useMutation({
    mutationFn: async (data: CreateLeadMagnetRequest) => {
      if (!workspaceId) throw new Error("No workspace selected");
      return leadMagnetsApi.create(workspaceId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lead-magnets", workspaceId] });
      router.push("/lead-magnets");
    },
  });

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

  const handleSubmit = () => {
    if (!selectedType) return;

    let contentData: QuizContent | CalculatorContent | RichTextContent | undefined;
    if (selectedType === "quiz") {
      contentData = quizContent;
    } else if (selectedType === "calculator") {
      contentData = calculatorContent;
    } else if (selectedType === "rich_text") {
      contentData = richTextContent;
    }

    const data: CreateLeadMagnetRequest = {
      name,
      description: description || undefined,
      magnet_type: selectedType,
      delivery_method: deliveryMethod,
      content_url: contentUrl || undefined,
      thumbnail_url: thumbnailUrl || undefined,
      estimated_value: estimatedValue,
      content_data: contentData,
      is_active: true,
    };

    createMutation.mutate(data);
  };

  const canProceed = () => {
    switch (currentStep) {
      case "type":
        return selectedType !== null;
      case "content":
        if (!name) return false;
        if (selectedType === "quiz") {
          return quizContent.questions.length > 0 && quizContent.results.length > 0;
        }
        if (selectedType === "calculator") {
          return calculatorContent.inputs.length > 0 && calculatorContent.outputs.length > 0;
        }
        if (selectedType === "rich_text") {
          return richTextContent.title !== "";
        }
        return contentUrl !== "";
      case "delivery":
        return true;
      case "review":
        return true;
      default:
        return false;
    }
  };

  const renderTypeStep = () => (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Choose Lead Magnet Type</h2>
        <p className="text-sm text-muted-foreground">
          Select the type of content you want to create
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-3">Static Content</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {TYPE_OPTIONS.filter((t) => t.category === "static").map((option) => (
              <Card
                key={option.type}
                className={`cursor-pointer transition-all hover:border-primary ${
                  selectedType === option.type ? "ring-2 ring-primary border-primary" : ""
                }`}
                onClick={() => setSelectedType(option.type)}
              >
                <CardContent className="p-4 text-center">
                  <div className="flex justify-center mb-2 text-muted-foreground">
                    {option.icon}
                  </div>
                  <p className="font-medium text-sm">{option.label}</p>
                  <p className="text-xs text-muted-foreground mt-1">{option.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-3">Interactive Content</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {TYPE_OPTIONS.filter((t) => t.category === "interactive").map((option) => (
              <Card
                key={option.type}
                className={`cursor-pointer transition-all hover:border-primary ${
                  selectedType === option.type ? "ring-2 ring-primary border-primary" : ""
                }`}
                onClick={() => setSelectedType(option.type)}
              >
                <CardContent className="p-4 text-center">
                  <div className="flex justify-center mb-2 text-muted-foreground">
                    {option.icon}
                  </div>
                  <p className="font-medium text-sm">{option.label}</p>
                  <p className="text-xs text-muted-foreground mt-1">{option.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  const renderContentStep = () => (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="name">Name *</Label>
          <Input
            id="name"
            placeholder="e.g., Marketing Readiness Quiz"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="estimated_value">Estimated Value ($)</Label>
          <Input
            id="estimated_value"
            type="number"
            placeholder="e.g., 497"
            value={estimatedValue || ""}
            onChange={(e) => setEstimatedValue(parseFloat(e.target.value) || undefined)}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          placeholder="Brief description of this lead magnet..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
        />
      </div>

      <Separator />

      {selectedType === "quiz" && workspaceId && (
        <QuizBuilder
          workspaceId={workspaceId}
          value={quizContent}
          onChange={setQuizContent}
        />
      )}

      {selectedType === "calculator" && workspaceId && (
        <CalculatorBuilder
          workspaceId={workspaceId}
          value={calculatorContent}
          onChange={setCalculatorContent}
        />
      )}

      {selectedType === "rich_text" && (
        <RichTextEditor
          value={richTextContent}
          onChange={setRichTextContent}
        />
      )}

      {selectedType && !["quiz", "calculator", "rich_text"].includes(selectedType) && (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="content_url">Content URL *</Label>
            <Input
              id="content_url"
              placeholder="https://example.com/your-content.pdf"
              value={contentUrl}
              onChange={(e) => setContentUrl(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              URL where the content is hosted
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="thumbnail_url">Thumbnail URL</Label>
            <Input
              id="thumbnail_url"
              placeholder="https://example.com/thumbnail.png"
              value={thumbnailUrl}
              onChange={(e) => setThumbnailUrl(e.target.value)}
            />
          </div>
        </div>
      )}
    </div>
  );

  const renderDeliveryStep = () => (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Delivery Settings</h2>
        <p className="text-sm text-muted-foreground">
          Configure how leads receive this content
        </p>
      </div>

      <div className="space-y-2">
        <Label>Delivery Method</Label>
        <Select value={deliveryMethod} onValueChange={(v) => setDeliveryMethod(v as DeliveryMethod)}>
          <SelectTrigger className="w-full sm:w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DELIVERY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          How the lead magnet will be delivered after opt-in
        </p>
      </div>

      {!["quiz", "calculator", "rich_text"].includes(selectedType || "") && !contentUrl && (
        <div className="space-y-2">
          <Label htmlFor="content_url_delivery">Content URL</Label>
          <Input
            id="content_url_delivery"
            placeholder="https://example.com/your-content.pdf"
            value={contentUrl}
            onChange={(e) => setContentUrl(e.target.value)}
          />
        </div>
      )}
    </div>
  );

  const renderReviewStep = () => {
    const typeOption = TYPE_OPTIONS.find((t) => t.type === selectedType);

    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold mb-1">Review & Create</h2>
          <p className="text-sm text-muted-foreground">
            Review your lead magnet before publishing
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {typeOption?.icon}
              {name || "Untitled Lead Magnet"}
            </CardTitle>
            <CardDescription>{description || "No description"}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Type:</span>
                <span className="ml-2 font-medium">{typeOption?.label}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Delivery:</span>
                <span className="ml-2 font-medium capitalize">{deliveryMethod}</span>
              </div>
              {estimatedValue && (
                <div>
                  <span className="text-muted-foreground">Estimated Value:</span>
                  <span className="ml-2 font-medium">${formatNumber(estimatedValue)}</span>
                </div>
              )}
            </div>

            {selectedType === "quiz" && (
              <div className="text-sm">
                <span className="text-muted-foreground">Questions:</span>
                <span className="ml-2 font-medium">{quizContent.questions.length}</span>
                <span className="text-muted-foreground ml-4">Results:</span>
                <span className="ml-2 font-medium">{quizContent.results.length}</span>
              </div>
            )}

            {selectedType === "calculator" && (
              <div className="text-sm">
                <span className="text-muted-foreground">Inputs:</span>
                <span className="ml-2 font-medium">{calculatorContent.inputs.length}</span>
                <span className="text-muted-foreground ml-4">Outputs:</span>
                <span className="ml-2 font-medium">{calculatorContent.outputs.length}</span>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  };

  const renderStepContent = () => {
    switch (currentStep) {
      case "type":
        return renderTypeStep();
      case "content":
        return renderContentStep();
      case "delivery":
        return renderDeliveryStep();
      case "review":
        return renderReviewStep();
      default:
        return null;
    }
  };

  const getStepLabel = (step: Step) => {
    const labels: Record<Step, string> = {
      type: "1. Type",
      content: "2. Content",
      delivery: "3. Delivery",
      review: "4. Review",
    };
    return labels[step];
  };

  if (!workspaceId) {
    return (
      <PageEmptyState
        className="h-full"
        title="Please select a workspace"
      />
    );
  }

  return (
    <div className="container max-w-4xl py-8">
      <div className="mb-8">
        <Button variant="ghost" onClick={() => router.push("/lead-magnets")} className="mb-4">
          <ChevronLeft className="size-4 mr-1" />
          Back to Lead Magnets
        </Button>
        <h1 className="text-2xl font-bold">Create Lead Magnet</h1>
        <p className="text-muted-foreground">
          Build an interactive lead magnet to capture and qualify leads
        </p>
      </div>

      {/* Step Indicator */}
      <div className="flex items-center gap-2 mb-8 text-sm">
        {STEPS.map((step, index) => (
          <span
            key={step}
            className={`${
              step === currentStep
                ? "text-primary font-medium"
                : STEPS.indexOf(currentStep) > index
                ? "text-primary/60"
                : "text-muted-foreground"
            }`}
          >
            {getStepLabel(step)}
            {index < STEPS.length - 1 && <ChevronRight className="size-4 inline ml-2" />}
          </span>
        ))}
      </div>

      {/* Step Content */}
      <Card>
        <CardContent className="pt-6">{renderStepContent()}</CardContent>
      </Card>

      {/* Navigation */}
      <div className="flex items-center justify-between mt-6">
        <Button variant="outline" onClick={handleBack} disabled={currentStep === "type"}>
          <ChevronLeft className="size-4 mr-1" />
          Back
        </Button>

        {currentStep === "review" ? (
          <Button onClick={handleSubmit} disabled={!canProceed() || createMutation.isPending}>
            {createMutation.isPending ? (
              <>
                <Loader2 className="size-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Check className="size-4 mr-2" />
                Create Lead Magnet
              </>
            )}
          </Button>
        ) : (
          <Button onClick={handleNext} disabled={!canProceed()}>
            Next
            <ChevronRight className="size-4 ml-1" />
          </Button>
        )}
      </div>
    </div>
  );
}
