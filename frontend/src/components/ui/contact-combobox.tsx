"use client";

/**
 * Client-name typeahead shared by every surface in the CRM where a customer is
 * named: appointment/job/invoice/service-plan dialogs, the estimator, and the
 * quote builder.
 *
 * It replaces the "search box that filters a separate <Select>" pattern that
 * used to be copy-pasted around the app. That pattern read as autocomplete but
 * wasn't: the typed text never became the answer, and the roster it filtered
 * was capped at one page, so a rep who typed a name that sat past the cap saw
 * an empty dropdown and no explanation.
 *
 * Two exports, one behaviour:
 *   - `ContactCombobox` — free text wins. Used where the stored value is a
 *     name (estimator "Save to customer"), so a brand-new client can be typed
 *     in full and a suggestion is only ever taken on an explicit arrow-then-
 *     Enter or a click.
 *   - `ContactPicker`  — a saved contact is required. Used where the stored
 *     value is a `contact_id`. Editing the text after picking clears the
 *     selection, so the id on the form can never disagree with the name on
 *     screen.
 *
 * Both follow the ARIA 1.2 combobox pattern: focus stays in the input and the
 * active option is tracked with `aria-activedescendant`, never by moving focus
 * into the list. The panel is portalled through Radix Popover because several
 * host dialogs are `overflow-y-auto`, which would clip an absolutely
 * positioned panel.
 */

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import * as React from "react";

import { useFormField } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Popover, PopoverAnchor } from "@/components/ui/popover";
import { useDebounce } from "@/hooks/useDebounce";
import { contactsApi } from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Contact } from "@/types";

/** A scannable shortlist, not a browsable table. */
const MAX_SUGGESTIONS = 6;
const SEARCH_DEBOUNCE_MS = 250;

/** "Sarah Henderson" — falls back to whichever parts exist. */
export function contactDisplayName(contact: Contact): string {
  return (
    [contact.first_name, contact.last_name].filter(Boolean).join(" ").trim() ||
    contact.email ||
    formatPhoneNumber(contact.phone_number ?? "") ||
    `Contact #${contact.id}`
  );
}

/**
 * Second line: just enough to tell two people with the same name apart, and
 * short enough to stay on one line. Phone is the identity key in this CRM;
 * where they live is what a rep recognises. Anything longer (notes, tags)
 * makes the shortlist harder to scan, not easier.
 */
function contactMeta(contact: Contact): string {
  const place =
    [contact.address_city, contact.address_state].filter(Boolean).join(", ") ||
    contact.company_name ||
    contact.email ||
    "";
  return [
    contact.phone_number ? formatPhoneNumber(contact.phone_number) : "",
    place,
  ]
    .filter(Boolean)
    .join("  ·  ");
}

/**
 * Mark the typed run inside a suggestion so the rep sees why it matched.
 * Weight, not colour, carries the signal — it survives forced-colors mode and
 * the highlighted row's inverted palette.
 */
function highlightMatch(text: string, query: string) {
  const at = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark className="bg-transparent font-bold text-inherit">
        {text.slice(at, at + query.length)}
      </mark>
      {text.slice(at + query.length)}
    </>
  );
}

interface SuggestionState {
  suggestions: Contact[];
  total: number;
  /** Results on screen no longer match what has been typed. */
  isStale: boolean;
  isError: boolean;
}

function useContactSuggestions(
  workspaceId: string | null | undefined,
  rawTerm: string,
  enabled: boolean,
  minQueryLength: number,
): SuggestionState {
  const term = useDebounce(rawTerm.trim(), SEARCH_DEBOUNCE_MS);
  const canSearch =
    enabled && !!workspaceId && term.length >= minQueryLength;

  const { data, isFetching, isError } = useQuery({
    queryKey: queryKeys.contacts.search(workspaceId ?? "", term),
    queryFn: () =>
      contactsApi.list(workspaceId!, {
        page: 1,
        page_size: MAX_SUGGESTIONS,
        // An empty term is the "show me the roster" case the old <Select>
        // covered; sending `search: ""` would filter on an empty string.
        search: term || undefined,
      }),
    enabled: canSearch,
    staleTime: 30_000,
  });

  return {
    suggestions: canSearch ? (data?.items ?? []) : [],
    total: data?.total ?? 0,
    isStale: canSearch && (isFetching || term !== rawTerm.trim()),
    isError,
  };
}

interface ComboboxCoreProps {
  workspaceId: string | null | undefined;
  /** Text in the field. */
  query: string;
  onQueryChange: (value: string) => void;
  onPick: (contact: Contact) => void;
  /** 0 shows the roster as soon as the field is focused. */
  minQueryLength: number;
  /** Rendered under the list when at least one contact matched. */
  hint: string;
  /** Rendered under the list when nothing matched. */
  emptyHint: string;
  /** Trailing control, e.g. the picker's clear button. */
  trailing?: React.ReactNode;
  /**
   * Render a bare `<input>` carrying only the caller's className, for surfaces
   * with their own field CSS (the estimator). Mixing those rules with the
   * shadcn `Input` utilities would leave the field visibly different from the
   * email and phone inputs sitting right under it.
   */
  unstyled?: boolean;
  inputProps: React.ComponentProps<"input">;
}

function ComboboxCore({
  workspaceId,
  query,
  onQueryChange,
  onPick,
  minQueryLength,
  hint,
  emptyHint,
  trailing,
  unstyled,
  inputProps,
}: ComboboxCoreProps) {
  const listboxId = React.useId();
  const optionId = (index: number) => `${listboxId}-opt-${index}`;

  const [isOpen, setIsOpen] = React.useState(false);
  // -1 means "nothing taken" — the resting state, so a name typed in full is
  // never swapped out from under the user.
  const [activeIndex, setActiveIndex] = React.useState(-1);
  const listRef = React.useRef<HTMLUListElement>(null);

  const { suggestions, total, isStale, isError } = useContactSuggestions(
    workspaceId,
    query,
    isOpen,
    minQueryLength,
  );

  const meetsMinLength = query.trim().length >= minQueryLength;
  const showPanel =
    isOpen && meetsMinLength && (suggestions.length > 0 || !isStale);
  const hasMore = suggestions.length > 0 && total > suggestions.length;

  // Keep the highlighted row in view while arrowing through a scrolled list.
  React.useEffect(() => {
    if (activeIndex < 0) return;
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const close = React.useCallback(() => {
    setIsOpen(false);
    setActiveIndex(-1);
  }, []);

  const pick = (contact: Contact) => {
    onPick(contact);
    close();
  };

  const move = (step: number) => {
    const count = suggestions.length;
    if (count === 0) return;
    setActiveIndex((prev) => {
      const next = prev + step;
      // Wrapping through -1 returns the user to their own typed text.
      if (next < -1) return count - 1;
      if (next >= count) return -1;
      return next;
    });
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        if (!showPanel) {
          setIsOpen(true);
          return;
        }
        move(event.key === "ArrowDown" ? 1 : -1);
        return;
      }
      case "Enter": {
        const active = activeIndex >= 0 ? suggestions[activeIndex] : undefined;
        // With nothing highlighted, Enter is left alone so the typed text
        // stands and the host form can submit.
        if (!active) return;
        event.preventDefault();
        pick(active);
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

  // Mirrors the panel's footer for screen readers, which cannot see it. Kept
  // silent while results are in flight so arrowing through the list isn't
  // interrupted by chatter.
  const status = !showPanel
    ? ""
    : isError
      ? "Couldn't reach the customer list. Keep typing, or try again."
      : isStale
        ? ""
        : suggestions.length === 0
          ? emptyHint
          : `${total} matching client${total === 1 ? "" : "s"}. Use the arrow keys to review them.`;

  return (
    <>
      <Popover open={showPanel} onOpenChange={(next) => !next && close()}>
        <PopoverAnchor asChild>
          <div className="relative">
            {React.createElement(unstyled ? "input" : Input, {
              ...inputProps,
              type: "text",
              autoComplete: "off",
              role: "combobox",
              "aria-expanded": showPanel,
              // Only advertise the listbox while one is actually rendered —
              // a zero-match panel is just a message.
              "aria-controls":
                showPanel && suggestions.length > 0 ? listboxId : undefined,
              "aria-autocomplete": "list",
              "aria-activedescendant":
                activeIndex >= 0 ? optionId(activeIndex) : undefined,
              className: cn(
                trailing && !unstyled ? "pe-9" : undefined,
                inputProps.className,
              ),
              value: query,
              onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
                setIsOpen(true);
                setActiveIndex(-1);
                onQueryChange(event.target.value);
                inputProps.onChange?.(event);
              },
              onFocus: (event: React.FocusEvent<HTMLInputElement>) => {
                setIsOpen(true);
                inputProps.onFocus?.(event);
              },
              // A dialog that autofocuses this field leaves it focused before
              // the user ever touches it, so no focus event fires on the first
              // click and focus alone would never open the list.
              onClick: (event: React.MouseEvent<HTMLInputElement>) => {
                setIsOpen(true);
                inputProps.onClick?.(event);
              },
              onKeyDown: handleKeyDown,
              onBlur: (event: React.FocusEvent<HTMLInputElement>) => {
                close();
                inputProps.onBlur?.(event);
              },
            })}
            {trailing ? (
              <div className="absolute inset-y-0 end-1.5 flex items-center">
                {trailing}
              </div>
            ) : null}
          </div>
        </PopoverAnchor>

        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            // A listbox, not a nested dialog — the role Radix defaults to
            // would announce this as one and swallow the combobox semantics.
            role="presentation"
            align="start"
            sideOffset={4}
            // Focus never leaves the input, per the ARIA combobox pattern.
            onOpenAutoFocus={(event) => event.preventDefault()}
            onCloseAutoFocus={(event) => event.preventDefault()}
            // A column so the footer stays pinned while only the list
            // scrolls — the "showing 6 of 24" count is the cue that there is
            // more to find, and it is worthless below the fold.
            className="bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 z-50 flex max-h-72 w-(--radix-popover-trigger-width) flex-col overflow-hidden rounded-md border p-0 shadow-md outline-hidden"
          >
            {suggestions.length > 0 ? (
              <ul
                ref={listRef}
                id={listboxId}
                role="listbox"
                aria-label="Matching clients"
                className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1"
              >
                {suggestions.map((contact, index) => {
                  const meta = contactMeta(contact);
                  return (
                    // Keyboard control of the listbox lives on the combobox
                    // input via `aria-activedescendant`, per the ARIA combobox
                    // pattern — options are deliberately not focusable and
                    // carry no key handler of their own.
                    // eslint-disable-next-line jsx-a11y/click-events-have-key-events
                    <li
                      key={contact.id}
                      id={optionId(index)}
                      data-index={index}
                      role="option"
                      aria-selected={index === activeIndex}
                      className={cn(
                        "cursor-pointer px-3 py-2 transition-colors",
                        index === activeIndex
                          ? "bg-accent text-accent-foreground"
                          : "hover:bg-muted/60",
                      )}
                      onMouseEnter={() => setActiveIndex(index)}
                      // Keep focus in the input so the click isn't lost to blur.
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => pick(contact)}
                    >
                      <span className="block truncate text-sm font-medium">
                        {highlightMatch(contactDisplayName(contact), query.trim())}
                      </span>
                      {meta ? (
                        <span
                          className={cn(
                            "block truncate text-xs",
                            index === activeIndex
                              ? "text-accent-foreground/80"
                              : "text-muted-foreground",
                          )}
                        >
                          {meta}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}

            {/* The status line below carries this same wording to screen
                readers, so this copy is visual only — otherwise it is
                announced twice. */}
            <p
              aria-hidden="true"
              className="shrink-0 border-t px-3 py-2 text-xs text-muted-foreground first:border-t-0"
            >
              {isError
                ? "Couldn't reach the customer list. Keep typing, or try again."
                : suggestions.length === 0
                  ? emptyHint
                  : hasMore
                    ? `Showing ${suggestions.length} of ${total} matches — keep typing to narrow.`
                    : hint}
            </p>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </Popover>

      <span className="sr-only" role="status">
        {status}
      </span>
    </>
  );
}

type SharedFieldProps = Omit<
  React.ComponentProps<"input">,
  "value" | "onChange" | "type" | "role" | "children"
>;

export interface ContactComboboxProps extends SharedFieldProps {
  workspaceId: string | null | undefined;
  /** The name in the field. Free text — this is the stored value. */
  value: string;
  onValueChange: (value: string) => void;
  /** Fired only when a saved contact is explicitly taken. */
  onSelectContact?: (contact: Contact) => void;
  /** Suggestions stay hidden until this many characters are typed. */
  minQueryLength?: number;
  /** Render a bare input for surfaces that bring their own field CSS. */
  unstyled?: boolean;
}

/**
 * Editable client-name field: what the user types is the value, and a
 * suggestion only replaces it on an explicit pick.
 */
export function ContactCombobox({
  workspaceId,
  value,
  onValueChange,
  onSelectContact,
  minQueryLength = 2,
  unstyled,
  ...inputProps
}: ContactComboboxProps) {
  return (
    <ComboboxCore
      workspaceId={workspaceId}
      query={value}
      onQueryChange={onValueChange}
      unstyled={unstyled}
      onPick={(contact) => {
        onValueChange(contactDisplayName(contact));
        onSelectContact?.(contact);
      }}
      minQueryLength={minQueryLength}
      hint="Pick a client to fill their details, or keep typing a new name."
      emptyHint="No existing client matches. Keep typing to add a new one."
      inputProps={inputProps}
    />
  );
}

export interface ContactPickerProps extends SharedFieldProps {
  workspaceId: string | null | undefined;
  /** Id of the chosen contact, `""` when nothing is chosen. */
  value: string;
  /** `contact` is null when the choice is cleared or typed over. */
  onChange: (contactId: string, contact: Contact | null) => void;
  /** Pre-selected contact, for forms that open on an existing record. */
  initialContact?: Contact | null;
}

/**
 * Client field that must resolve to a saved contact. The typed text is only a
 * query: it is never submitted, and editing it after a pick clears the id so
 * the form can't carry an id that disagrees with the name on screen.
 */
export function ContactPicker({
  workspaceId,
  value,
  onChange,
  initialContact = null,
  placeholder = "Search clients by name, phone, or email…",
  disabled,
  ...inputProps
}: ContactPickerProps) {
  const [selected, setSelected] = React.useState<Contact | null>(initialContact);
  const [query, setQuery] = React.useState(
    initialContact ? contactDisplayName(initialContact) : "",
  );

  // A host form reset (dialog closed and reopened) empties `value`; the field
  // has to follow or it would still show the previous customer's name. Done
  // during render rather than in an effect, per React's documented pattern for
  // adjusting state when a prop changes, so the stale name never paints.
  const [lastValue, setLastValue] = React.useState(value);
  if (value !== lastValue) {
    setLastValue(value);
    if (value === "" && selected !== null) {
      setSelected(null);
      setQuery("");
    }
  }

  const clear = () => {
    setSelected(null);
    setQuery("");
    onChange("", null);
  };

  return (
    <ComboboxCore
      workspaceId={workspaceId}
      query={query}
      onQueryChange={(next) => {
        setQuery(next);
        // Typing over a pick invalidates it — the id must never outlive the
        // name it was chosen for.
        if (selected) {
          setSelected(null);
          onChange("", null);
        }
      }}
      onPick={(contact) => {
        setSelected(contact);
        setQuery(contactDisplayName(contact));
        onChange(String(contact.id), contact);
      }}
      // 0 keeps the browse-the-roster affordance the old <Select> had: focus
      // the field and the first page of clients is already there.
      minQueryLength={0}
      hint="Pick a client to attach them to this record."
      emptyHint="No matching client. Add them from Contacts first."
      trailing={
        selected && !disabled ? (
          <button
            type="button"
            onClick={clear}
            // Fires before blur closes the panel.
            onMouseDown={(event) => event.preventDefault()}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-sm p-1 transition-colors focus-visible:ring-[3px] focus-visible:outline-none"
            aria-label={`Clear selected client ${contactDisplayName(selected)}`}
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        ) : undefined
      }
      inputProps={{ ...inputProps, placeholder, disabled }}
    />
  );
}

/**
 * `ContactPicker` wired to the surrounding `<FormField>`.
 *
 * The picker renders an input plus a portalled panel, so it can't be handed to
 * `<FormControl>` (a Slot, which needs a single DOM child). This pulls the same
 * id and description wiring off the field context by hand, so the `<FormLabel>`
 * still points at the real input and `<FormMessage>` is still announced.
 */
export function FormContactPicker(props: ContactPickerProps) {
  const { error, formItemId, formDescriptionId, formMessageId } = useFormField();

  return (
    <ContactPicker
      id={formItemId}
      aria-invalid={!!error}
      aria-describedby={
        error ? `${formDescriptionId} ${formMessageId}` : formDescriptionId
      }
      {...props}
    />
  );
}
