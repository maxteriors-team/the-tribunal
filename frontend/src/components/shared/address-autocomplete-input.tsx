"use client";

/**
 * Address line 1 with provider-backed suggestions.
 *
 * It stays a plain text field first: every keystroke is kept exactly as typed,
 * nothing is auto-selected, and a dead or unconfigured provider simply means no
 * panel appears. A rural address the provider has never heard of must still be
 * enterable, so suggestions are strictly additive.
 *
 * Picking a row fills city, state and ZIP too, which is the whole point — those
 * four fields are where hand-typed addresses drift apart and stop matching.
 *
 * Follows the ARIA combobox pattern: focus never leaves the input, the active
 * row is tracked with `aria-activedescendant`, and the panel is portalled by
 * Popover so it is not clipped by the dialog's scroll container.
 */

import { useQuery } from "@tanstack/react-query";
import { Loader2, MapPin } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { useDebounce } from "@/hooks/useDebounce";
import { addressesApi, type AddressParts, type AddressSuggestion } from "@/lib/api/addresses";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

/** Matches the backend's floor: shorter queries can't narrow anything. */
const MIN_QUERY_LENGTH = 3;
/** Long enough that a typed word costs one lookup, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 350;

interface AddressAutocompleteInputProps {
  workspaceId: string;
  value: string;
  onValueChange: (value: string) => void;
  /** Called with the full address when a suggestion is taken. */
  onAddressPicked: (parts: AddressParts) => void;
  id?: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}

function newSessionToken(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AddressAutocompleteInput({
  workspaceId,
  value,
  onValueChange,
  onAddressPicked,
  id,
  placeholder = "123 Main St",
  disabled,
  className,
  "aria-describedby": describedBy,
  "aria-invalid": ariaInvalid,
}: AddressAutocompleteInputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const listboxId = `${generatedId}-listbox`;
  const optionId = (index: number) => `${listboxId}-opt-${index}`;

  const [isOpen, setIsOpen] = useState(false);
  // -1 is the resting state: nothing highlighted, so Enter and Tab always keep
  // exactly what the operator typed.
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isResolving, setIsResolving] = useState(false);
  // One token spans the keystrokes of a single address entry so the provider
  // bills one autocomplete session rather than one lookup per character.
  const sessionTokenRef = useRef<string>(newSessionToken());
  const listRef = useRef<HTMLUListElement>(null);

  const term = useDebounce(value.trim(), SEARCH_DEBOUNCE_MS);
  const canSearch = isOpen && !disabled && !!workspaceId && term.length >= MIN_QUERY_LENGTH;

  const { data, isFetching, isError } = useQuery({
    queryKey: queryKeys.addresses.suggest(workspaceId, term),
    queryFn: () => addressesApi.suggest(workspaceId, term, sessionTokenRef.current),
    enabled: canSearch,
    // Suggestions for a given string don't change minute to minute, and every
    // repeat is a paid call on the Google-backed path.
    staleTime: 5 * 60_000,
    retry: false,
  });

  const suggestions = canSearch ? (data?.suggestions ?? []) : [];
  const providerUnavailable = data?.provider === "none";
  // Results for the previous term are stale while a new one is in flight.
  const isStale = canSearch && (isFetching || term !== value.trim());
  const showPanel =
    canSearch && !providerUnavailable && (suggestions.length > 0 || (!isStale && !isError));

  // Keep the highlighted row in view while arrowing through a scrolled list.
  useEffect(() => {
    if (activeIndex < 0) return;
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const close = () => {
    setIsOpen(false);
    setActiveIndex(-1);
  };

  const pick = async (suggestion: AddressSuggestion) => {
    close();
    // Show the picked line immediately; the remaining fields follow once the
    // provider expands it.
    onValueChange(suggestion.label);

    if (suggestion.parts) {
      onAddressPicked(suggestion.parts);
      sessionTokenRef.current = newSessionToken();
      return;
    }

    setIsResolving(true);
    try {
      const parts = await addressesApi.resolve(
        workspaceId,
        suggestion.id,
        sessionTokenRef.current,
      );
      // A provider that can't expand its own suggestion returns blank parts;
      // keeping the typed line beats wiping the field the operator just filled.
      if (parts.address_line1 || parts.address_city || parts.address_zip) {
        onAddressPicked(parts);
      }
    } catch {
      // Silent by design: the label is already in the field, so the operator
      // can finish the remaining fields by hand.
    } finally {
      setIsResolving(false);
      sessionTokenRef.current = newSessionToken();
    }
  };

  const move = (step: number) => {
    const count = suggestions.length;
    if (count === 0) return;
    setActiveIndex((previous) => {
      const next = previous + step;
      // Wrapping through -1 returns the operator to their own typed text.
      if (next < -1) return count - 1;
      if (next >= count) return -1;
      return next;
    });
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        if (!showPanel) return;
        event.preventDefault();
        move(event.key === "ArrowDown" ? 1 : -1);
        return;
      }
      case "Enter": {
        const active = activeIndex >= 0 ? suggestions[activeIndex] : undefined;
        if (!active) {
          // Nothing highlighted: leave Enter to the form it lives in.
          close();
          return;
        }
        // Taking a suggestion must never also submit the surrounding form.
        event.preventDefault();
        void pick(active);
        return;
      }
      case "Escape": {
        if (!isOpen) return;
        event.preventDefault();
        close();
        return;
      }
      case "Tab": {
        close();
      }
    }
  };

  const status = !canSearch
    ? ""
    : isStale
      ? ""
      : suggestions.length === 0
        ? "No matching addresses. Keep typing to enter it manually."
        : `${suggestions.length} address suggestion${suggestions.length === 1 ? "" : "s"}. Use the arrow keys to review them.`;

  return (
    <Popover open={showPanel} onOpenChange={(open) => !open && close()}>
      <PopoverAnchor asChild>
        <div className="relative">
          <Input
            id={inputId}
            type="text"
            placeholder={placeholder}
            disabled={disabled}
            autoComplete="off"
            role="combobox"
            aria-expanded={showPanel}
            aria-controls={showPanel ? listboxId : undefined}
            aria-autocomplete="list"
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
            aria-describedby={describedBy}
            aria-invalid={ariaInvalid}
            className={cn(isResolving && "pr-9", className)}
            value={value}
            onChange={(event) => {
              setIsOpen(true);
              setActiveIndex(-1);
              onValueChange(event.target.value);
            }}
            onKeyDown={handleKeyDown}
            onBlur={close}
          />
          {isResolving && (
            <Loader2
              aria-hidden="true"
              className="text-muted-foreground pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 animate-spin"
            />
          )}
        </div>
      </PopoverAnchor>

      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-1"
        // Focus stays in the input: this is a combobox panel, not a menu.
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        {suggestions.length === 0 ? (
          <p className="text-muted-foreground px-2 py-3 text-sm">
            No matching addresses. Keep typing to enter it manually.
          </p>
        ) : (
          <ul ref={listRef} id={listboxId} role="listbox" aria-label="Address suggestions">
            {suggestions.map((suggestion, index) => (
              // Keyboard control lives on the combobox input via
              // `aria-activedescendant`, per the ARIA pattern — options are
              // deliberately not focusable and carry no key handler.
              // eslint-disable-next-line jsx-a11y/click-events-have-key-events
              <li
                key={suggestion.id}
                id={optionId(index)}
                data-index={index}
                role="option"
                aria-selected={index === activeIndex}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-sm px-2 py-1.5 text-sm transition-colors",
                  index === activeIndex && "bg-accent text-accent-foreground",
                )}
                onMouseEnter={() => setActiveIndex(index)}
                // Keep focus in the input so the click isn't lost to blur.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => void pick(suggestion)}
              >
                <MapPin aria-hidden="true" className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block truncate">{suggestion.label}</span>
                  {suggestion.description && (
                    <span className="text-muted-foreground block truncate text-xs">
                      {suggestion.description}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>

      <span className="sr-only" role="status">
        {status}
      </span>
    </Popover>
  );
}
