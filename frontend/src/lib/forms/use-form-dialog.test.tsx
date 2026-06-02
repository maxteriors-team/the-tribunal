import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as z from "zod";

import { useFormDialog } from "@/lib/forms/use-form-dialog";

const schema = z.object({
  name: z.string().min(1, { error: "Name is required" }),
  slug: z.string().optional(),
});
type Values = z.infer<typeof schema>;

/** Build an axios-style error with a `response.data` body. */
function axiosError(data: unknown) {
  return { isAxiosError: true, response: { data } };
}

interface HookOptions {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  defaultValues?: Values;
  onSubmit?: (values: Values) => Promise<void> | void;
  onTopLevelError?: (message: string) => void;
  resetOnClose?: boolean;
  serverErrorFields?: (keyof Values)[];
  serverErrorFieldMap?: Partial<Record<string, keyof Values>>;
}

function setup(initial: HookOptions = {}) {
  return renderHook(
    (props: HookOptions) =>
      useFormDialog<Values>({
        open: props.open ?? true,
        onOpenChange: props.onOpenChange ?? (() => {}),
        schema,
        defaultValues: props.defaultValues ?? { name: "", slug: "" },
        onSubmit: props.onSubmit ?? (async () => {}),
        onTopLevelError: props.onTopLevelError,
        resetOnClose: props.resetOnClose,
        serverErrorFields: props.serverErrorFields as never,
        serverErrorFieldMap: props.serverErrorFieldMap as never,
        errorFallback: "Something went wrong",
      }),
    { initialProps: initial },
  );
}

describe("useFormDialog — submission", () => {
  it("validates and blocks submit for invalid input", async () => {
    const onSubmit = vi.fn();
    const { result } = setup({ onSubmit });

    await act(async () => {
      await result.current.handleSubmit();
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(result.current.form.getFieldState("name").error?.message).toBe("Name is required");
  });

  it("calls onSubmit with valid values", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { result } = setup({ onSubmit, defaultValues: { name: "Acme", slug: "" } });

    await act(async () => {
      await result.current.handleSubmit();
    });

    expect(onSubmit).toHaveBeenCalledWith(
      { name: "Acme", slug: "" },
      expect.anything(),
    );
  });
});

describe("useFormDialog — close guard and reset", () => {
  it("ignores a close request while a submit is in flight", async () => {
    let resolveSubmit: (() => void) | undefined;
    const onOpenChange = vi.fn();
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    const { result } = setup({
      onSubmit,
      onOpenChange,
      defaultValues: { name: "Acme", slug: "" },
    });

    let submitPromise: Promise<void>;
    act(() => {
      submitPromise = result.current.handleSubmit();
    });

    await waitFor(() => expect(result.current.isSubmitting).toBe(true));

    // Attempting to close mid-flight is a no-op.
    act(() => result.current.onOpenChange(false));
    expect(onOpenChange).not.toHaveBeenCalled();

    await act(async () => {
      resolveSubmit?.();
      await submitPromise;
    });
  });

  it("forwards close requests to onOpenChange when idle", () => {
    const onOpenChange = vi.fn();
    const { result } = setup({ onOpenChange });

    act(() => result.current.close());

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("resets the form to fresh defaults when defaults change while open (edit dialog)", () => {
    const { result, rerender } = setup({
      open: true,
      defaultValues: { name: "First", slug: "first" },
    });

    act(() => result.current.form.setValue("name", "edited"));
    expect(result.current.form.getValues("name")).toBe("edited");

    // Adopt a different record while the dialog stays open.
    rerender({ open: true, defaultValues: { name: "Second", slug: "second" } });

    expect(result.current.form.getValues("name")).toBe("Second");
    expect(result.current.form.getValues("slug")).toBe("second");
  });

  it("resets the form on close by default", () => {
    const { result, rerender } = setup({
      open: true,
      defaultValues: { name: "Start", slug: "" },
    });

    act(() => result.current.form.setValue("name", "dirty"));
    rerender({ open: false, defaultValues: { name: "Start", slug: "" } });

    expect(result.current.form.getValues("name")).toBe("Start");
  });

  it("keeps dirty values on close when resetOnClose is false", () => {
    const { result, rerender } = setup({
      open: true,
      resetOnClose: false,
      defaultValues: { name: "Start", slug: "" },
    });

    act(() => result.current.form.setValue("name", "dirty"));
    rerender({ open: false, resetOnClose: false, defaultValues: { name: "Start", slug: "" } });

    expect(result.current.form.getValues("name")).toBe("dirty");
  });
});

describe("useFormDialog — server error routing", () => {
  it("maps a thrown field error onto the matching form field", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(axiosError({ message: "Validation failed", details: { name: "taken" } }));
    const { result } = setup({ onSubmit, defaultValues: { name: "Acme", slug: "" } });

    await act(async () => {
      await result.current.handleSubmit();
    });

    expect(result.current.form.getFieldState("name").error?.message).toBe("taken");
    expect(result.current.form.getFieldState("name").error?.type).toBe("server");
  });

  it("routes a non-field server error to onTopLevelError", async () => {
    const onTopLevelError = vi.fn();
    const onSubmit = vi
      .fn()
      .mockRejectedValue(axiosError({ code: "internal_error", message: "Server exploded" }));
    const { result } = setup({
      onSubmit,
      onTopLevelError,
      defaultValues: { name: "Acme", slug: "" },
    });

    await act(async () => {
      await result.current.handleSubmit();
    });

    expect(onTopLevelError).toHaveBeenCalledWith("Server exploded");
  });

  it("remaps backend field names through serverErrorFieldMap", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(axiosError({ details: { display_name: "too long" } }));
    const { result } = setup({
      onSubmit,
      defaultValues: { name: "Acme", slug: "" },
      serverErrorFieldMap: { display_name: "name" },
    });

    await act(async () => {
      await result.current.handleSubmit();
    });

    expect(result.current.form.getFieldState("name").error?.message).toBe("too long");
  });
});
