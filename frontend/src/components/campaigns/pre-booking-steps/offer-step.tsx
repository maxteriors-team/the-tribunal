"use client";

import { Tag } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { previewOffer } from "@/lib/pre-booking";
import { formatCurrency } from "@/lib/utils/number";
import type { PreBookingAmountType } from "@/types";

import type { WizardErrors, WizardStep } from "../wizard-types";

export interface OfferStepFields {
  incentive_type: PreBookingAmountType;
  incentive_value: number;
  deposit_type: PreBookingAmountType;
  deposit_value: number;
  slot_cap: number;
  hold_hours: number;
  /** Wizard-only: the job price the worked example is priced against. */
  example_job_amount: number;
}

export const MAX_SLOT_CAP = 1000;
export const MAX_HOLD_HOURS = 720;

export function validateOffer(data: OfferStepFields): WizardErrors {
  const errors: WizardErrors = {};
  if (!(data.incentive_value > 0)) {
    errors.incentive_value = "The discount is what buys the early commitment";
  }
  if (data.incentive_type === "percentage" && data.incentive_value > 100) {
    errors.incentive_value = "A percentage discount cannot exceed 100%";
  }
  if (!(data.deposit_value > 0)) {
    errors.deposit_value = "A deposit is required — it is what makes it a booking";
  }
  if (data.deposit_type === "percentage" && data.deposit_value > 100) {
    errors.deposit_value = "A percentage deposit cannot exceed 100%";
  }
  if (!Number.isInteger(data.slot_cap) || data.slot_cap < 1) {
    errors.slot_cap = "Set how many slots this season can absorb";
  } else if (data.slot_cap > MAX_SLOT_CAP) {
    errors.slot_cap = `Slot cap cannot exceed ${MAX_SLOT_CAP}`;
  }
  if (!Number.isInteger(data.hold_hours) || data.hold_hours < 1) {
    errors.hold_hours = "Holds must last at least an hour";
  } else if (data.hold_hours > MAX_HOLD_HOURS) {
    errors.hold_hours = `Holds cannot exceed ${MAX_HOLD_HOURS} hours (30 days)`;
  }
  return errors;
}

/**
 * "Offer" step: the discount, the deposit, and the cap.
 *
 * The deposit is not optional and the cap is not decoration — together they are
 * what separates a pre-booking campaign from a coupon. The deposit turns a
 * "yeah, sounds good" into revenue in the dead months; the cap is the only
 * thing stopping the crew calendar from being sold past what it can deliver.
 */
export function makeOfferStep<
  TStepId extends string,
  TFormData extends OfferStepFields,
>(opts: { id: TStepId }): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Offer",
    icon: Tag,
    validate: (data) => validateOffer(data),
    render: ({ formData, errors, updateField }) => {
      const setField = <K extends keyof OfferStepFields>(
        key: K,
        value: OfferStepFields[K],
      ) =>
        updateField(
          key as unknown as keyof TFormData,
          value as unknown as TFormData[keyof TFormData],
        );

      const example = previewOffer({
        baseAmount: formData.example_job_amount,
        incentiveType: formData.incentive_type,
        incentiveValue: formData.incentive_value,
        depositType: formData.deposit_type,
        depositValue: formData.deposit_value,
      });

      return (
        <div className="space-y-6">
          <div className="space-y-4">
            <div>
              <h4 className="font-medium">Booking Incentive</h4>
              <p className="text-sm text-muted-foreground">
                What the customer gets for committing months early.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="incentive-type">Discount Type</Label>
                <Select
                  value={formData.incentive_type}
                  onValueChange={(v) =>
                    setField("incentive_type", v as PreBookingAmountType)
                  }
                >
                  <SelectTrigger id="incentive-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="percentage">Percentage off</SelectItem>
                    <SelectItem value="fixed">Fixed amount off</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="incentive-value">
                  {formData.incentive_type === "percentage"
                    ? "Percent Off *"
                    : "Dollars Off *"}
                </Label>
                <Input
                  id="incentive-value"
                  type="number"
                  min={0}
                  step={formData.incentive_type === "percentage" ? 1 : 5}
                  value={formData.incentive_value}
                  onChange={(e) =>
                    setField("incentive_value", Number(e.target.value))
                  }
                  className={errors.incentive_value ? "border-destructive" : ""}
                />
                {errors.incentive_value && (
                  <p className="text-sm text-destructive">
                    {errors.incentive_value}
                  </p>
                )}
              </div>
            </div>
          </div>

          <Separator />

          <div className="space-y-4">
            <div>
              <h4 className="font-medium">Deposit (Required)</h4>
              <p className="text-sm text-muted-foreground">
                A deposit is what turns interest into a booking — and it is the
                cash that carries the business through the dead months. Every
                reservation issues a quote the customer pays this against.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="deposit-type">Deposit Type</Label>
                <Select
                  value={formData.deposit_type}
                  onValueChange={(v) =>
                    setField("deposit_type", v as PreBookingAmountType)
                  }
                >
                  <SelectTrigger id="deposit-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="percentage">
                      Percentage of the job
                    </SelectItem>
                    <SelectItem value="fixed">Flat amount</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="deposit-value">
                  {formData.deposit_type === "percentage"
                    ? "Percent Due Today *"
                    : "Dollars Due Today *"}
                </Label>
                <Input
                  id="deposit-value"
                  type="number"
                  min={0}
                  step={formData.deposit_type === "percentage" ? 1 : 5}
                  value={formData.deposit_value}
                  onChange={(e) =>
                    setField("deposit_value", Number(e.target.value))
                  }
                  className={errors.deposit_value ? "border-destructive" : ""}
                />
                {errors.deposit_value && (
                  <p className="text-sm text-destructive">
                    {errors.deposit_value}
                  </p>
                )}
              </div>
            </div>
          </div>

          <Separator />

          <div className="space-y-4">
            <div>
              <h4 className="font-medium">Capacity</h4>
              <p className="text-sm text-muted-foreground">
                The slot cap is what stops the crew calendar being oversold: once
                the season is full, no further slot can be held. Holds expire so
                an unpaid &quot;yes&quot; cannot sit on a slot forever.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="slot-cap">Slots for This Season *</Label>
                <Input
                  id="slot-cap"
                  type="number"
                  min={1}
                  max={MAX_SLOT_CAP}
                  value={formData.slot_cap}
                  onChange={(e) => setField("slot_cap", Number(e.target.value))}
                  className={errors.slot_cap ? "border-destructive" : ""}
                />
                {errors.slot_cap ? (
                  <p className="text-sm text-destructive">{errors.slot_cap}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    How many of these jobs the crew can actually deliver.
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="hold-hours">Hold a Slot For (hours)</Label>
                <Input
                  id="hold-hours"
                  type="number"
                  min={1}
                  max={MAX_HOLD_HOURS}
                  value={formData.hold_hours}
                  onChange={(e) =>
                    setField("hold_hours", Number(e.target.value))
                  }
                  className={errors.hold_hours ? "border-destructive" : ""}
                />
                {errors.hold_hours ? (
                  <p className="text-sm text-destructive">{errors.hold_hours}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    After this, an unpaid hold is released back to the pool.
                  </p>
                )}
              </div>
            </div>
          </div>

          <Separator />

          <div className="space-y-3 rounded-lg border bg-muted/50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="font-medium">Worked example</h4>
              <span className="text-sm text-muted-foreground">on a</span>
              <Input
                id="example-job-amount"
                aria-label="Example job price"
                type="number"
                min={0}
                step={25}
                value={formData.example_job_amount}
                onChange={(e) =>
                  setField("example_job_amount", Number(e.target.value))
                }
                className="h-8 w-28"
              />
              <span className="text-sm text-muted-foreground">job</span>
            </div>
            <p className="text-sm">
              A {formatCurrency(formData.example_job_amount)} job becomes{" "}
              <span className="font-medium">
                {formatCurrency(example.discountedTotal)}
              </span>
              . The customer pays{" "}
              <span className="font-medium">
                {formatCurrency(example.depositDueToday)}
              </span>{" "}
              today to hold the slot, {formatCurrency(example.balanceAtService)}{" "}
              when the crew shows up, and saves{" "}
              <span className="font-medium">
                {formatCurrency(example.savings)}
              </span>
              .
            </p>
            <p className="text-xs text-muted-foreground">
              {formatCurrency(example.depositDueToday)} × {formData.slot_cap}{" "}
              slots ={" "}
              {formatCurrency(example.depositDueToday * formData.slot_cap)} of
              deposits banked before the season starts.
            </p>
          </div>
        </div>
      );
    },
  };
}
