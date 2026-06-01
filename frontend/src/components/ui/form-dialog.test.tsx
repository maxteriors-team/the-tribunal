import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import * as z from "zod";

import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { FormDialog } from "@/components/ui/form-dialog";
import { Input } from "@/components/ui/input";
import { useFormDialog } from "@/lib/forms/use-form-dialog";

const schema = z.object({
  name: z.string().min(1, { error: "Name is required" }),
});
type Values = z.infer<typeof schema>;

interface HarnessProps {
  onSubmit: (values: Values) => Promise<void> | void;
  onTopLevelError?: (message: string) => void;
  defaultName?: string;
  initialOpen?: boolean;
}

/**
 * A minimal consumer that mirrors how real dialogs use the shell: controlled
 * `open` state owned by the parent, fields rendered as children.
 */
function Harness({ onSubmit, onTopLevelError, defaultName = "", initialOpen = true }: HarnessProps) {
  const [open, setOpen] = useState(initialOpen);
  const dialog = useFormDialog<Values>({
    open,
    onOpenChange: setOpen,
    schema,
    defaultValues: { name: defaultName },
    errorFallback: "Something went wrong",
    onTopLevelError,
    onSubmit: async (values) => {
      await onSubmit(values);
      setOpen(false);
    },
  });

  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        open
      </button>
      <FormDialog
        dialog={dialog}
        open={open}
        title="Test Dialog"
        description="A test description"
        submitLabel="Save"
        submitBusyLabel="Saving..."
      >
        <FormField
          control={dialog.form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input placeholder="Name" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </FormDialog>
    </div>
  );
}

describe("FormDialog + useFormDialog", () => {
  it("renders the title, description and fields", () => {
    render(<Harness onSubmit={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Test Dialog" })).toBeInTheDocument();
    expect(screen.getByText("A test description")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("blocks submit and shows a validation message for invalid input", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Name is required")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits valid values and closes the dialog", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ name: "Acme" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows the busy label and disables the submit button while submitting", async () => {
    let resolveSubmit: (() => void) | undefined;
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const busyButton = await screen.findByRole("button", { name: "Saving..." });
    expect(busyButton).toBeDisabled();

    resolveSubmit?.();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("resets the form when the dialog is closed and reopened", async () => {
    const user = userEvent.setup();
    render(<Harness onSubmit={vi.fn()} />);

    const input = screen.getByPlaceholderText("Name");
    await user.type(input, "Typed value");
    expect(input).toHaveValue("Typed value");

    // Cancel closes the dialog (and should reset the form).
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    // Reopen — the field should be back to its empty default.
    await user.click(screen.getByRole("button", { name: "open" }));
    expect(await screen.findByPlaceholderText("Name")).toHaveValue("");
  });

  it("resets the form after a successful submit closes the dialog programmatically", async () => {
    // Regression: a successful submit closes via the parent's `onOpenChange`,
    // which Radix never routes through the dialog's close handler. Reset must
    // still run so reopening shows pristine defaults rather than stale values.
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "open" }));
    expect(await screen.findByPlaceholderText("Name")).toHaveValue("");
  });

  it("routes a thrown server error to the top-level handler and keeps the dialog open", async () => {
    const onTopLevelError = vi.fn();
    const onSubmit = vi.fn().mockRejectedValue({
      isAxiosError: true,
      response: { data: { code: "internal_error", message: "Server exploded" } },
    });
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} onTopLevelError={onTopLevelError} />);

    await user.type(screen.getByPlaceholderText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onTopLevelError).toHaveBeenCalledWith("Server exploded"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("maps a thrown field error onto the corresponding field", async () => {
    const onSubmit = vi.fn().mockRejectedValue({
      isAxiosError: true,
      response: { data: { message: "Validation failed", details: { name: "already taken" } } },
    });
    const user = userEvent.setup();
    render(<Harness onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("already taken")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
