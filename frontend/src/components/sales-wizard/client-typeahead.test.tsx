/**
 * Client-name typeahead on the Quote Builder's first step.
 *
 * The field stays an editable combobox: typing filters the workspace's saved
 * customers into a shortlist, but a brand-new name typed in full must survive
 * untouched. These tests lock down both halves of that contract, plus the
 * keyboard path a rep actually uses.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/types";

import { ClientTypeahead } from "./client-typeahead";

const list = vi.fn();

vi.mock("@/lib/api/contacts", () => ({
  contactsApi: {
    list: (...args: unknown[]) => list(...args),
  },
}));

function contact(id: number, first: string, last: string): Contact {
  return {
    id,
    user_id: 1,
    first_name: first,
    last_name: last,
    phone_number: `248555000${id}`,
    status: "new",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as Contact;
}

const MAXES = [
  contact(1, "Max", "Sherrod"),
  contact(2, "Max", "Kowalski"),
  contact(3, "Maxine", "Reed"),
];

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Mirrors how the Client step binds the field to wizard state. */
function Harness({ onPick }: { onPick?: (c: Contact) => void }) {
  const [value, setValue] = useState("");
  return (
    <ClientTypeahead
      workspaceId="ws-1"
      label="First Name"
      placeholder="Sarah"
      value={value}
      onValueChange={setValue}
      onPickContact={(picked) => {
        setValue(picked.first_name);
        onPick?.(picked);
      }}
    />
  );
}

function renderField(onPick?: (c: Contact) => void) {
  return render(<Harness onPick={onPick} />, { wrapper });
}

const input = () => screen.getByRole("combobox", { name: "First Name" });

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue({
    items: MAXES,
    total: MAXES.length,
    page: 1,
    page_size: 6,
    pages: 1,
  });
});

describe("ClientTypeahead", () => {
  it("surfaces every saved client matching what was typed", async () => {
    const user = userEvent.setup();
    renderField();

    await user.type(input(), "Max");

    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[0]).toHaveTextContent("Max Sherrod");
    expect(options[2]).toHaveTextContent("Maxine Reed");
    expect(list).toHaveBeenCalledWith("ws-1", {
      page: 1,
      page_size: 6,
      search: "Max",
    });
  });

  it("does not query on a single character", async () => {
    const user = userEvent.setup();
    renderField();

    await user.type(input(), "M");

    await waitFor(() => expect(list).not.toHaveBeenCalled());
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("keeps a typed-in-full new name — Enter never takes a suggestion", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    renderField(onPick);

    await user.type(input(), "Maxwell Fontaine");
    await screen.findByRole("listbox");
    // Nothing is pre-highlighted, so Enter leaves the typed name alone.
    expect(input()).not.toHaveAttribute("aria-activedescendant");
    await user.keyboard("{Enter}");

    expect(onPick).not.toHaveBeenCalled();
    expect(input()).toHaveValue("Maxwell Fontaine");
  });

  it("takes a suggestion on arrow-then-Enter", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    renderField(onPick);

    await user.type(input(), "Max");
    await screen.findByRole("listbox");

    await user.keyboard("{ArrowDown}{ArrowDown}");
    const options = screen.getAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(input()).toHaveAttribute("aria-activedescendant", options[1].id);

    await user.keyboard("{Enter}");
    expect(onPick).toHaveBeenCalledWith(MAXES[1]);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("arrows back past the top to the rep's own typed text", async () => {
    const user = userEvent.setup();
    renderField();

    await user.type(input(), "Max");
    await screen.findByRole("listbox");

    await user.keyboard("{ArrowDown}{ArrowUp}");
    expect(input()).not.toHaveAttribute("aria-activedescendant");
  });

  it("takes a suggestion on click", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    renderField(onPick);

    await user.type(input(), "Max");
    const options = await screen.findAllByRole("option");
    await user.click(options[0]);

    expect(onPick).toHaveBeenCalledWith(MAXES[0]);
    expect(input()).toHaveValue("Max");
  });

  it("closes on Escape without changing the typed name", async () => {
    const user = userEvent.setup();
    renderField();

    await user.type(input(), "Max");
    await screen.findByRole("listbox");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input()).toHaveValue("Max");
  });

  it("says so when nothing matches, instead of blocking the entry", async () => {
    const user = userEvent.setup();
    list.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 6,
      pages: 0,
    });
    renderField();

    await user.type(input(), "Zeb");

    expect(
      await screen.findByText(/no existing client matches .Zeb./i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    // …and the same news reaches a screen reader.
    expect(screen.getByRole("status")).toHaveTextContent(
      "No matching clients. Keep typing to add a new one.",
    );
  });

  it("flags when the shortlist is only part of the matches", async () => {
    const user = userEvent.setup();
    list.mockResolvedValue({
      items: MAXES,
      total: 12,
      page: 1,
      page_size: 6,
      pages: 2,
    });
    renderField();

    await user.type(input(), "Max");

    expect(
      await screen.findByText(/showing 3 of 12 matches/i),
    ).toBeInTheDocument();
  });
});
