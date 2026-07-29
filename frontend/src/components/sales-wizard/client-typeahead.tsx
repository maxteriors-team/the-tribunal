"use client";

/**
 * Editable client-name combobox for the Quote Builder's Client step.
 *
 * Typing filters the workspace's existing contacts and offers a short
 * suggestion list; picking one fills the whole client block and links the
 * quote to that customer record so saving can't mint a duplicate.
 *
 * Nothing is ever forced. No option is pre-highlighted, so Enter and Tab
 * always keep exactly what the rep typed — which is how a brand-new client
 * gets entered. A suggestion is only taken on an explicit arrow-then-Enter or
 * a click, following the ARIA combobox pattern (focus stays in the input and
 * the active option is tracked with `aria-activedescendant`).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { useDebounce } from "@/hooks/useDebounce";
import { contactsApi } from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Contact } from "@/types";

/** A scannable shortlist, not a browsable table. */
const MAX_SUGGESTIONS = 6;
/** Below this a query returns most of the roster instead of filtering it. */
const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 250;

interface ClientTypeaheadProps {
  workspaceId: string;
  label: string;
  placeholder: string;
  value: string;
  onValueChange: (value: string) => void;
  /** Called when the rep explicitly takes a suggestion. */
  onPickContact: (contact: Contact) => void;
}

/** "Sarah Henderson" — falls back to the parts that exist. */
function contactName(contact: Contact): string {
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
 * where they live is what a rep recognises. Anything longer (email, notes)
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

/** Mark the typed run inside a suggestion so the rep sees why it matched. */
function highlight(text: string, query: string) {
  const at = text.toLowerCase().indexOf(query.toLowerCase());
  if (query.length === 0 || at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark>{text.slice(at, at + query.length)}</mark>
      {text.slice(at + query.length)}
    </>
  );
}

export function ClientTypeahead({
  workspaceId,
  label,
  placeholder,
  value,
  onValueChange,
  onPickContact,
}: ClientTypeaheadProps) {
  const inputId = useId();
  const listboxId = useId();
  const optionId = (index: number) => `${listboxId}-opt-${index}`;

  const [isOpen, setIsOpen] = useState(false);
  // -1 means "no suggestion taken" — the resting state, so a typed-in-full
  // name is never swapped out from under the rep.
  const [activeIndex, setActiveIndex] = useState(-1);
  const listRef = useRef<HTMLUListElement>(null);

  const term = useDebounce(value.trim(), SEARCH_DEBOUNCE_MS);
  const canSearch = isOpen && term.length >= MIN_QUERY_LENGTH;

  const { data, isFetching } = useQuery({
    queryKey: queryKeys.contacts.search(workspaceId, term),
    queryFn: () =>
      contactsApi.list(workspaceId, {
        page: 1,
        page_size: MAX_SUGGESTIONS,
        search: term,
      }),
    enabled: canSearch,
    staleTime: 30_000,
  });

  const suggestions = canSearch ? (data?.items ?? []) : [];
  const total = data?.total ?? 0;
  const hasMore = suggestions.length > 0 && total > suggestions.length;
  // Results for the previous term are stale while a new one is in flight.
  const isStale = canSearch && (isFetching || term !== value.trim());
  const showPanel = canSearch && (suggestions.length > 0 || !isStale);

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

  const pick = (contact: Contact) => {
    onPickContact(contact);
    close();
  };

  const move = (step: number) => {
    const count = suggestions.length;
    if (count === 0) return;
    setActiveIndex((prev) => {
      const next = prev + step;
      // Wrapping through -1 returns the rep to their own typed text.
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
        // With nothing highlighted, Enter is left alone so the typed name stands.
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

  const status = !canSearch
    ? ""
    : isStale
      ? ""
      : suggestions.length === 0
        ? "No matching clients. Keep typing to add a new one."
        : `${total} matching client${total === 1 ? "" : "s"}. Use the arrow keys to review them.`;

  return (
    <div className="field-wrap">
      <label className="field-label" htmlFor={inputId}>
        {label}
      </label>
      <div className="sw-typeahead">
        <input
          id={inputId}
          className="field-input"
          type="text"
          placeholder={placeholder}
          autoComplete="off"
          role="combobox"
          aria-expanded={showPanel}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            activeIndex >= 0 ? optionId(activeIndex) : undefined
          }
          value={value}
          onChange={(event) => {
            setIsOpen(true);
            setActiveIndex(-1);
            onValueChange(event.target.value);
          }}
          onKeyDown={handleKeyDown}
          onBlur={close}
        />

        {showPanel ? (
          <div className="sw-typeahead-panel">
            <ul
              ref={listRef}
              className="sw-typeahead-list"
              id={listboxId}
              role="listbox"
              aria-label={`Existing clients matching ${term}`}
            >
              {suggestions.map((contact, index) => {
                const meta = contactMeta(contact);
                return (
                  // Keyboard control of the listbox lives on the combobox input
                  // via `aria-activedescendant`, per the ARIA combobox pattern —
                  // options are deliberately not focusable and carry no key
                  // handler of their own.
                  // eslint-disable-next-line jsx-a11y/click-events-have-key-events
                  <li
                    key={contact.id}
                    id={optionId(index)}
                    data-index={index}
                    className="sw-typeahead-option"
                    role="option"
                    aria-selected={index === activeIndex}
                    onMouseEnter={() => setActiveIndex(index)}
                    // Keep focus in the input so the click isn't lost to blur.
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => pick(contact)}
                  >
                    <span className="sw-typeahead-name">
                      {highlight(contactName(contact), term)}
                    </span>
                    {meta ? (
                      <span className="sw-typeahead-meta">{meta}</span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            {suggestions.length === 0 ? (
              <p className="sw-typeahead-foot">
                {`No existing client matches “${term}” — keep typing to add a new one.`}
              </p>
            ) : (
              <p className="sw-typeahead-foot">
                {hasMore
                  ? `Showing ${suggestions.length} of ${total} matches — keep typing to narrow.`
                  : "Pick a client to fill their details, or keep typing a new name."}
              </p>
            )}
          </div>
        ) : null}
      </div>
      <span className="sw-vis-hidden" role="status">
        {status}
      </span>
    </div>
  );
}
