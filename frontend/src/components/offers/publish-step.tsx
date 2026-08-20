"use client";

import { Globe, Copy, Check, ExternalLink } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import type { Offer } from "@/types";

import type { OfferFormData } from "./offer-builder-wizard";

interface PublishStepProps {
  formData: OfferFormData;
  onFieldChange: (updates: Partial<OfferFormData>) => void;
  existingOffer?: Offer;
}

export function PublishStep({ formData, onFieldChange, existingOffer }: PublishStepProps) {
  const [copied, setCopied] = useState(false);

  const handleCopyLink = () => {
    const url = `${window.location.origin}/p/offers/${formData.public_slug}`;
    void navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Link copied");
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between p-4 border rounded-lg">
        <div className="space-y-0.5">
          <Label htmlFor="offer-public-page" className="text-base">
            Public Landing Page
          </Label>
          <p className="text-sm text-muted-foreground">
            Enable a shareable landing page for this offer
          </p>
        </div>
        <Switch
          id="offer-public-page"
          checked={formData.is_public}
          onCheckedChange={(checked) => onFieldChange({ is_public: checked })}
        />
      </div>

      {formData.is_public && (
        <>
          <div className="space-y-2">
            <Label htmlFor="public_slug">URL Slug</Label>
            <div className="flex gap-2">
              <div className="flex-1 flex items-center gap-2 p-2 bg-muted rounded-md text-sm text-muted-foreground">
                <span>{typeof window !== "undefined" ? window.location.origin : ""}/p/offers/</span>
                <Input
                  id="public_slug"
                  placeholder="my-offer"
                  value={formData.public_slug}
                  onChange={(e) =>
                    onFieldChange({
                      public_slug: e.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9-]/g, "-")
                        .replace(/-+/g, "-"),
                    })
                  }
                  className="flex-1 h-8"
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Only lowercase letters, numbers, and dashes allowed
            </p>
          </div>

          {formData.public_slug && (
            <div className="flex items-center gap-2 p-3 bg-primary/5 rounded-lg border border-primary/20">
              <Globe className="size-4 text-primary" />
              <span className="text-sm flex-1 truncate">
                {typeof window !== "undefined" ? window.location.origin : ""}/p/offers/
                {formData.public_slug}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleCopyLink}
                aria-label={copied ? "Copied" : "Copy public link"}
              >
                {copied ? <Check className="size-4 text-green-500" /> : <Copy className="size-4" />}
              </Button>
              {existingOffer?.is_public && existingOffer?.public_slug && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => window.open(`/p/offers/${existingOffer.public_slug}`, "_blank")}
                >
                  <ExternalLink className="size-4" />
                </Button>
              )}
            </div>
          )}

          <Separator />

          <div className="space-y-4">
            <h4 className="font-medium">Required Fields</h4>
            <p className="text-sm text-muted-foreground">
              Choose what information visitors must provide to access this offer
            </p>

            <div className="space-y-3">
              <div className="flex items-center space-x-3">
                <Checkbox
                  id="require_email"
                  checked={formData.require_email}
                  onCheckedChange={(checked) => onFieldChange({ require_email: checked === true })}
                />
                <Label htmlFor="require_email" className="text-sm font-normal cursor-pointer">
                  Email address (recommended)
                </Label>
              </div>

              <div className="flex items-center space-x-3">
                <Checkbox
                  id="require_phone"
                  checked={formData.require_phone}
                  onCheckedChange={(checked) => onFieldChange({ require_phone: checked === true })}
                />
                <Label htmlFor="require_phone" className="text-sm font-normal cursor-pointer">
                  Phone number
                </Label>
              </div>

              <div className="flex items-center space-x-3">
                <Checkbox
                  id="require_name"
                  checked={formData.require_name}
                  onCheckedChange={(checked) => onFieldChange({ require_name: checked === true })}
                />
                <Label htmlFor="require_name" className="text-sm font-normal cursor-pointer">
                  Full name
                </Label>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
