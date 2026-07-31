"use client";

/**
 * The copy fields every good/better/best tier has, whatever the trade.
 *
 * Lifted out of the seasonal editor so the roofing/siding/gutter editor writes
 * the same four inputs instead of a near-copy that drifts. The markup is
 * unchanged from the seasonal original — only the placeholders vary by category,
 * because "e.g. Premier — The Full Display" is nonsense on a roof.
 */
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface PackageCopyValue {
  /** Internal label the operator sorts and recognises the tier by. */
  label: string;
  /** Client-facing name on the card. */
  name: string;
  /** A sentence or two describing what the tier feels like to buy. */
  experience: string;
  /** Selling points, one per line. */
  points: string;
}

interface PackageCopyFieldsProps {
  value: PackageCopyValue;
  onChange: (patch: Partial<PackageCopyValue>) => void;
  disabled?: boolean;
  labelPlaceholder: string;
  namePlaceholder: string;
  experiencePlaceholder: string;
  pointsPlaceholder: string;
}

export function PackageCopyFields({
  value,
  onChange,
  disabled,
  labelPlaceholder,
  namePlaceholder,
  experiencePlaceholder,
  pointsPlaceholder,
}: PackageCopyFieldsProps) {
  return (
    <>
      <div className="flex flex-wrap gap-3">
        <div className="space-y-2 flex-1 min-w-[180px]">
          <Label>Package label</Label>
          <Input
            placeholder={labelPlaceholder}
            value={value.label}
            onChange={(e) => onChange({ label: e.target.value })}
            disabled={disabled}
          />
        </div>
        <div className="space-y-2 flex-1 min-w-[180px]">
          <Label>Display name</Label>
          <Input
            placeholder={namePlaceholder}
            value={value.name}
            onChange={(e) => onChange({ name: e.target.value })}
            disabled={disabled}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label>Experience</Label>
        <Textarea
          rows={2}
          placeholder={experiencePlaceholder}
          value={value.experience}
          onChange={(e) => onChange({ experience: e.target.value })}
          disabled={disabled}
        />
      </div>

      <div className="space-y-2">
        <Label>Selling points</Label>
        <Textarea
          rows={3}
          placeholder={pointsPlaceholder}
          value={value.points}
          onChange={(e) => onChange({ points: e.target.value })}
          disabled={disabled}
        />
        <p className="text-xs text-muted-foreground">One bullet per line.</p>
      </div>
    </>
  );
}
