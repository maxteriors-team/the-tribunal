"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  DollarSign,
  Layers,
  Gift,
  Shield,
  Clock,
  Eye,
  ChevronLeft,
  ChevronRight,
  Check,
  Loader2,
  Globe,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { BasicsStep } from "./basics-step";
import { PricingStep } from "./pricing-step";
import { ValueStackStep } from "./value-stack-step";
import { LeadMagnetsStep } from "./lead-magnets-step";
import { GuaranteeStep } from "./guarantee-step";
import { UrgencyStep } from "./urgency-step";
import { PublishStep } from "./publish-step";
import { ReviewStep } from "./review-step";

import { offersApi, CreateOfferRequest } from "@/lib/api/offers";
import { queryKeys } from "@/lib/query-keys";
import { leadMagnetsApi } from "@/lib/api/lead-magnets";
import type {
  Offer,
  DiscountType,
  GuaranteeType,
  UrgencyType,
  ValueStackItem,
  LeadMagnet,
} from "@/types";

interface OfferBuilderWizardProps {
  workspaceId: string;
  existingOffer?: Offer;
  onSuccess?: (offer: Offer) => void;
}

interface Step {
  id: string;
  label: string;
  icon: React.ReactNode;
}

const STEPS: Step[] = [
  { id: "basics", label: "Basics", icon: <FileText className="size-4" /> },
  { id: "pricing", label: "Pricing", icon: <DollarSign className="size-4" /> },
  { id: "value-stack", label: "Value Stack", icon: <Layers className="size-4" /> },
  { id: "lead-magnets", label: "Lead Magnets", icon: <Gift className="size-4" /> },
  { id: "guarantee", label: "Guarantee", icon: <Shield className="size-4" /> },
  { id: "urgency", label: "Urgency", icon: <Clock className="size-4" /> },
  { id: "publish", label: "Publish", icon: <Globe className="size-4" /> },
  { id: "review", label: "Review", icon: <Eye className="size-4" /> },
];

interface FormData {
  name: string;
  description: string;
  headline: string;
  subheadline: string;
  discount_type: DiscountType;
  discount_value: number;
  regular_price: number;
  offer_price: number;
  savings_amount: number;
  value_stack_items: ValueStackItem[];
  lead_magnet_ids: string[];
  guarantee_type: GuaranteeType | "";
  guarantee_days: number;
  guarantee_text: string;
  urgency_type: UrgencyType | "";
  urgency_text: string;
  scarcity_count: number;
  cta_text: string;
  cta_subtext: string;
  terms: string;
  is_active: boolean;
  // Public landing page fields
  is_public: boolean;
  public_slug: string;
  require_email: boolean;
  require_phone: boolean;
  require_name: boolean;
}

export type OfferFormData = FormData;

const initialFormData: FormData = {
  name: "",
  description: "",
  headline: "",
  subheadline: "",
  discount_type: "percentage",
  discount_value: 0,
  regular_price: 0,
  offer_price: 0,
  savings_amount: 0,
  value_stack_items: [],
  lead_magnet_ids: [],
  guarantee_type: "",
  guarantee_days: 30,
  guarantee_text: "",
  urgency_type: "",
  urgency_text: "",
  scarcity_count: 0,
  cta_text: "Get Started Now",
  cta_subtext: "",
  terms: "",
  is_active: true,
  // Public landing page defaults
  is_public: false,
  public_slug: "",
  require_email: true,
  require_phone: false,
  require_name: false,
};

export function OfferBuilderWizard({
  workspaceId,
  existingOffer,
  onSuccess,
}: OfferBuilderWizardProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState<FormData>(() => {
    if (existingOffer) {
      return {
        ...initialFormData,
        name: existingOffer.name,
        description: existingOffer.description || "",
        headline: existingOffer.headline || "",
        subheadline: existingOffer.subheadline || "",
        discount_type: existingOffer.discount_type,
        discount_value: existingOffer.discount_value,
        regular_price: existingOffer.regular_price || 0,
        offer_price: existingOffer.offer_price || 0,
        savings_amount: existingOffer.savings_amount || 0,
        value_stack_items: existingOffer.value_stack_items || [],
        lead_magnet_ids: existingOffer.lead_magnets?.map((lm) => lm.id) || [],
        guarantee_type: existingOffer.guarantee_type || "",
        guarantee_days: existingOffer.guarantee_days || 30,
        guarantee_text: existingOffer.guarantee_text || "",
        urgency_type: existingOffer.urgency_type || "",
        urgency_text: existingOffer.urgency_text || "",
        scarcity_count: existingOffer.scarcity_count || 0,
        cta_text: existingOffer.cta_text || "Get Started Now",
        cta_subtext: existingOffer.cta_subtext || "",
        terms: existingOffer.terms || "",
        is_active: existingOffer.is_active,
        // Public landing page fields
        is_public: existingOffer.is_public || false,
        public_slug: existingOffer.public_slug || "",
        require_email: existingOffer.require_email ?? true,
        require_phone: existingOffer.require_phone || false,
        require_name: existingOffer.require_name || false,
      };
    }
    return initialFormData;
  });

  // Fetch lead magnets
  const { data: leadMagnetsData } = useQuery({
    queryKey: queryKeys.leadMagnets.bare(workspaceId ?? ""),
    queryFn: () => leadMagnetsApi.list(workspaceId, { active_only: true }),
  });

  const leadMagnets = leadMagnetsData?.items || [];
  const selectedLeadMagnets = leadMagnets.filter((lm) =>
    formData.lead_magnet_ids.includes(lm.id)
  );

  // Create/update mutation
  const createMutation = useMutation({
    mutationFn: async (data: CreateOfferRequest) => {
      const offer = existingOffer
        ? await offersApi.update(workspaceId, existingOffer.id, data)
        : await offersApi.create(workspaceId, data);

      // Attach lead magnets if any
      if (formData.lead_magnet_ids.length > 0) {
        await offersApi.attachLeadMagnets(
          workspaceId,
          offer.id,
          formData.lead_magnet_ids
        );
      }

      return offer;
    },
    onSuccess: (offer) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.offers.bare(workspaceId ?? "") });
      if (onSuccess) {
        onSuccess(offer);
      } else {
        router.push(`/offers`);
      }
    },
  });

  // Create lead magnet mutation
  const createLeadMagnetMutation = useMutation({
    mutationFn: (data: Partial<LeadMagnet>) =>
      leadMagnetsApi.create(workspaceId, {
        name: data.name || "",
        magnet_type: data.magnet_type || "pdf",
        delivery_method: data.delivery_method || "email",
        content_url: data.content_url || "",
        description: data.description,
        estimated_value: data.estimated_value,
        is_active: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.leadMagnets.bare(workspaceId ?? "") });
    },
  });

  const updateFormData = useCallback(
    (updates: Partial<FormData>) => {
      setFormData((prev) => ({ ...prev, ...updates }));
    },
    []
  );

  const goNext = () => {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep(currentStep + 1);
    }
  };

  const goPrev = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleSubmit = () => {
    const offerData: CreateOfferRequest = {
      name: formData.name,
      description: formData.description || undefined,
      discount_type: formData.discount_type,
      discount_value: formData.discount_value,
      terms: formData.terms || undefined,
      is_active: formData.is_active,
      headline: formData.headline || undefined,
      subheadline: formData.subheadline || undefined,
      regular_price: formData.regular_price || undefined,
      offer_price: formData.offer_price || undefined,
      savings_amount: formData.savings_amount || undefined,
      guarantee_type: formData.guarantee_type || undefined,
      guarantee_days: formData.guarantee_days || undefined,
      guarantee_text: formData.guarantee_text || undefined,
      urgency_type: formData.urgency_type || undefined,
      urgency_text: formData.urgency_text || undefined,
      scarcity_count: formData.scarcity_count || undefined,
      value_stack_items: formData.value_stack_items.length > 0
        ? formData.value_stack_items
        : undefined,
      cta_text: formData.cta_text || undefined,
      cta_subtext: formData.cta_subtext || undefined,
      // Public landing page fields
      is_public: formData.is_public,
      public_slug: formData.public_slug || undefined,
      require_email: formData.require_email,
      require_phone: formData.require_phone,
      require_name: formData.require_name,
    };

    createMutation.mutate(offerData);
  };

  const renderStepContent = () => {
    switch (STEPS[currentStep].id) {
      case "basics":
        return <BasicsStep formData={formData} onFieldChange={updateFormData} workspaceId={workspaceId} />;
      case "pricing":
        return <PricingStep formData={formData} onFieldChange={updateFormData} />;
      case "value-stack":
        return <ValueStackStep items={formData.value_stack_items} onChange={(items) => updateFormData({ value_stack_items: items })} />;
      case "lead-magnets":
        return <LeadMagnetsStep leadMagnets={leadMagnets} selectedIds={formData.lead_magnet_ids} onSelect={(ids) => updateFormData({ lead_magnet_ids: ids })} onCreateLeadMagnet={async (lm) => { await createLeadMagnetMutation.mutateAsync(lm); }} />;
      case "guarantee":
        return <GuaranteeStep formData={formData} onFieldChange={updateFormData} />;
      case "urgency":
        return <UrgencyStep formData={formData} onFieldChange={updateFormData} />;
      case "publish":
        return <PublishStep formData={formData} onFieldChange={updateFormData} existingOffer={existingOffer} />;
      case "review":
        return <ReviewStep formData={formData} selectedLeadMagnets={selectedLeadMagnets} />;
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Step Indicator */}
      <div className="flex items-center justify-between mb-8">
        {STEPS.map((step, index) => (
          <div
            key={step.id}
            className={`flex items-center ${
              index < STEPS.length - 1 ? "flex-1" : ""
            }`}
          >
            <button
              type="button"
              onClick={() => setCurrentStep(index)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${
                index === currentStep
                  ? "bg-primary text-primary-foreground"
                  : index < currentStep
                  ? "bg-primary/20 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {index < currentStep ? (
                <Check className="size-4" />
              ) : (
                step.icon
              )}
              <span className="hidden sm:inline text-sm font-medium">
                {step.label}
              </span>
            </button>
            {index < STEPS.length - 1 && (
              <div
                className={`flex-1 h-0.5 mx-2 ${
                  index < currentStep ? "bg-primary" : "bg-muted"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step Content */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {STEPS[currentStep].icon}
            {STEPS[currentStep].label}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <AnimatePresence mode="wait">
            <motion.div
              key={currentStep}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              {renderStepContent()}
            </motion.div>
          </AnimatePresence>
        </CardContent>
      </Card>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          onClick={goPrev}
          disabled={currentStep === 0}
        >
          <ChevronLeft className="size-4 mr-1" />
          Previous
        </Button>

        {currentStep < STEPS.length - 1 ? (
          <Button onClick={goNext} disabled={!formData.name}>
            Next
            <ChevronRight className="size-4 ml-1" />
          </Button>
        ) : (
          <Button
            onClick={handleSubmit}
            disabled={!formData.name || createMutation.isPending}
          >
            {createMutation.isPending ? (
              <>
                <Loader2 className="size-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Check className="size-4 mr-2" />
                {existingOffer ? "Update Offer" : "Create Offer"}
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
