/**
 * Shared client-name typeahead used by every surface that names a customer.
 *
 * These lock the two contracts the component exists to guarantee:
 *
 *  - `ContactCombobox` stores free text, so a brand-new client typed in full
 *    must survive untouched — the old pattern quietly discarded it.
 *  - `ContactPicker` stores an id, so the id must never outlive the name shown
 *    next to it. Typing over a pick clears it rather than leaving the form
 *    pointing at a customer the operator can no longer see.
 *
 * Plus the keyboard path a rep actually uses, since the previous
 * search-box-filters-a-Select pattern had no keyboard route from the text to
 * the matching row at all.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/types";

import { ContactCombobox, ContactPicker } from "./contact-combobox";

const list = vi.fn();

vi.mock("@/lib/api/contacts", () => ({
  contactsApi: {
    list: (...args: unknown[]) => list(...args),
  },
}));

const WORKSPACE_ID = "ws-1";

function contact(id: number, first: string, last: string): Contact {
  return {
    id,
    user_id: 1,
    first_name: first,
    last_name: last,
    phone_number: `248555000${id}`,
    email: `${first.toLowerCase()}@example.com`,
    status: "new",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as Contact;
}

const SAMANTHAS = [contact(1, "Samantha", "Reyes"), contact(2, "Samantha", "Okafor")];

function resolveWith(items: Contact[], total = items.length) {
  list.mockResolvedValue({
    items,
    total,
    page: 1,
    page_size: 6,
    pages: 1,
  });
}

function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function ComboboxHarness({ onSelect }: { onSelect?: (c: Contact) => void }) {
  const [value, setValue] = useState("");
  return (
    <Wrapper>
      <label htmlFor="client">Client</label>
      <ContactCombobox
        id="client"
        workspaceId={WORKSPACE_ID}
        value={value}
        onValueChange={setValue}
        onSelectContact={onSelect}
      />
      <span data-testid="stored">{value}</span>
    </Wrapper>
  );
}

function PickerHarness() {
  const [value, setValue] = useState("");
  return (
    <Wrapper>
      <label htmlFor="customer">Customer</label>
      <ContactPicker
        id="customer"
        workspaceId={WORKSPACE_ID}
        value={value}
        onChange={(next) => setValue(next)}
      />
      <span data-testid="stored">{value || "none"}</span>
    </Wrapper>
  );
}

beforeEach(() => {
  list.mockReset();
  resolveWith([]);
});

describe("ContactCombobox", () => {
  it("keeps a brand-new client name that matches nobody", async () => {
    resolveWith([]);
    render(<ComboboxHarness />);

    await userEvent.type(screen.getByLabelText("Client"), "Dara Whitfield");

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/No existing client matches/),
    );
    expect(screen.getByLabelText("Client")).toHaveValue("Dara Whitfield");
    expect(screen.getByTestId("stored")).toHaveTextContent("Dara Whitfield");
  });

  it("does not overwrite typed text until a suggestion is explicitly taken", async () => {
    resolveWith(SAMANTHAS);
    render(<ComboboxHarness />);

    const field = screen.getByLabelText("Client");
    await userEvent.type(field, "Samantha");
    await screen.findByRole("option", { name: /Samantha Reyes/ });

    // Suggestions are on screen and one is even highlighted by arrowing, but
    // the field still holds what the rep typed.
    await userEvent.keyboard("{ArrowDown}");
    expect(field).toHaveValue("Samantha");

    await userEvent.keyboard("{Enter}");
    expect(field).toHaveValue("Samantha Reyes");
    expect(screen.getByTestId("stored")).toHaveTextContent("Samantha Reyes");
  });

  it("reports the taken contact so the caller can fill the rest of the block", async () => {
    resolveWith(SAMANTHAS);
    const onSelect = vi.fn();
    render(<ComboboxHarness onSelect={onSelect} />);

    await userEvent.type(screen.getByLabelText("Client"), "Samantha");
    await userEvent.click(await screen.findByRole("option", { name: /Samantha Okafor/ }));

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 2, last_name: "Okafor" }));
  });

  it("stays usable when the customer lookup fails", async () => {
    list.mockRejectedValue(new Error("offline"));
    render(<ComboboxHarness />);

    await userEvent.type(screen.getByLabelText("Client"), "Dara");

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/Couldn't reach the customer list/),
    );
    expect(screen.getByLabelText("Client")).toHaveValue("Dara");
  });
});

describe("ContactPicker", () => {
  it("stores the id of the picked customer", async () => {
    resolveWith(SAMANTHAS);
    render(<PickerHarness />);

    await userEvent.click(screen.getByLabelText("Customer"));
    await userEvent.click(await screen.findByRole("option", { name: /Samantha Reyes/ }));

    expect(screen.getByLabelText("Customer")).toHaveValue("Samantha Reyes");
    expect(screen.getByTestId("stored")).toHaveTextContent("1");
  });

  it("clears the stored id when the name is typed over", async () => {
    resolveWith(SAMANTHAS);
    render(<PickerHarness />);

    await userEvent.click(screen.getByLabelText("Customer"));
    await userEvent.click(await screen.findByRole("option", { name: /Samantha Reyes/ }));
    expect(screen.getByTestId("stored")).toHaveTextContent("1");

    // The id must not survive the name it was chosen for.
    await userEvent.type(screen.getByLabelText("Customer"), "x");
    expect(screen.getByTestId("stored")).toHaveTextContent("none");
  });

  it("clears the selection with the clear button", async () => {
    resolveWith(SAMANTHAS);
    render(<PickerHarness />);

    await userEvent.click(screen.getByLabelText("Customer"));
    await userEvent.click(await screen.findByRole("option", { name: /Samantha Reyes/ }));

    await userEvent.click(screen.getByRole("button", { name: /Clear selected client/ }));

    expect(screen.getByLabelText("Customer")).toHaveValue("");
    expect(screen.getByTestId("stored")).toHaveTextContent("none");
  });

  it("searches the server rather than filtering one loaded page", async () => {
    resolveWith(SAMANTHAS);
    render(<PickerHarness />);

    await userEvent.type(screen.getByLabelText("Customer"), "Okafor");

    await waitFor(() =>
      expect(list).toHaveBeenCalledWith(
        WORKSPACE_ID,
        expect.objectContaining({ search: "Okafor" }),
      ),
    );
  });

  it("says so when more customers match than are shown", async () => {
    resolveWith(SAMANTHAS, 24);
    render(<PickerHarness />);

    await userEvent.type(screen.getByLabelText("Customer"), "Sam");

    expect(await screen.findByText(/Showing 2 of 24 matches/)).toBeVisible();
  });

  it("opens on click when the field was already focused", async () => {
    // Dialogs that autofocus this field (the review-request dialog does) leave
    // it focused before the user touches it, so the first click fires no focus
    // event. Without a click handler the panel would never open and the field
    // would look like a dead text box.
    resolveWith(SAMANTHAS);
    render(<PickerHarness />);

    const field = screen.getByLabelText("Customer");
    await act(async () => {
      field.focus();
    });
    await userEvent.click(field);

    expect(await screen.findByRole("option", { name: /Samantha Reyes/ })).toBeVisible();
  });

  it("exposes the ARIA combobox contract keyboard users rely on", async () => {
    resolveWith(SAMANTHAS);
    render(<PickerHarness />);

    const field = screen.getByLabelText("Customer");
    expect(field).toHaveAttribute("role", "combobox");
    expect(field).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(field);
    const first = await screen.findByRole("option", { name: /Samantha Reyes/ });
    expect(field).toHaveAttribute("aria-expanded", "true");

    // Focus stays in the input; the active option is named by id instead.
    await userEvent.keyboard("{ArrowDown}");
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("aria-activedescendant", first.id);
    expect(first).toHaveAttribute("aria-selected", "true");

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("option")).not.toBeInTheDocument());
    expect(field).toHaveAttribute("aria-expanded", "false");
  });
});
