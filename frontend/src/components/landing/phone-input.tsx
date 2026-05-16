"use client";

import { type ChangeEvent, type ComponentProps } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface PhoneInputProps
  extends Omit<ComponentProps<"input">, "onChange" | "value"> {
  value: string;
  onChange: (value: string) => void;
}

/**
 * Extract the 10-digit phone number, stripping leading country code if present
 */
function extractDigits(input: string): string {
  const digits = input.replace(/\D/g, "");
  // If 11 digits starting with 1, strip the country code
  if (digits.length === 11 && digits.startsWith("1")) {
    return digits.slice(1);
  }
  // Otherwise just take first 10 digits
  return digits.slice(0, 10);
}

/**
 * Format phone number for display: (555) 123-4567
 */
function formatPhoneDisplay(digits: string): string {
  if (digits.length === 0) return "";
  if (digits.length <= 3) return `(${digits}`;
  if (digits.length <= 6) return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6, 10)}`;
}

/**
 * Normalize phone number to E.164 format: +12485551234
 */
export function normalizeToE164(value: string): string {
  const digits = extractDigits(value);
  if (digits.length === 10) {
    return `+1${digits}`;
  }
  return value;
}

export function PhoneInput({
  value,
  onChange,
  className,
  ...props
}: PhoneInputProps) {
  // Extract the 10-digit number for display
  const digits = extractDigits(value);
  const displayValue = formatPhoneDisplay(digits);

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const input = e.target.value;
    const newDigits = extractDigits(input);
    // Pass back the normalized E.164 format
    onChange(normalizeToE164(newDigits));
  };

  return (
    <Input
      type="tel"
      inputMode="numeric"
      autoComplete="tel"
      placeholder="(555) 123-4567"
      value={displayValue}
      onChange={handleChange}
      className={cn("font-mono", className)}
      aria-label={props["aria-label"] || (!props.id ? "Phone number" : undefined)}
      {...props}
    />
  );
}
