import { renderHook } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";

import { applyApiErrorsToForm, getApiFieldErrors } from "@/lib/forms/api-errors";

/** Build an axios-style error with a `response.data` body. */
function axiosError(data: unknown) {
  return { isAxiosError: true, response: { data } };
}

interface DemoValues {
  email: string;
  slug: string;
}

function makeForm() {
  return renderHook(() =>
    useForm<DemoValues>({ defaultValues: { email: "", slug: "" } }),
  ).result.current;
}

describe("getApiFieldErrors", () => {
  it("extracts fields from a FastAPI 422 validation payload", () => {
    const err = axiosError({
      detail: [
        { loc: ["body", "email"], msg: "value is not a valid email", type: "value_error" },
        { loc: ["body", "slug"], msg: "string too short", type: "value_error" },
      ],
    });

    expect(getApiFieldErrors(err)).toEqual({
      email: "value is not a valid email",
      slug: "string too short",
    });
  });

  it("keeps the first message when a field appears twice in 422 detail", () => {
    const err = axiosError({
      detail: [
        { loc: ["body", "email"], msg: "first", type: "value_error" },
        { loc: ["body", "email"], msg: "second", type: "value_error" },
      ],
    });

    expect(getApiFieldErrors(err)).toEqual({ email: "first" });
  });

  it("extracts fields from the canonical envelope `details` map (string values)", () => {
    const err = axiosError({
      code: "conflict",
      message: "Validation failed",
      details: { email: "already taken" },
    });

    expect(getApiFieldErrors(err)).toEqual({ email: "already taken" });
  });

  it("extracts the first message when `details` values are arrays", () => {
    const err = axiosError({
      code: "validation_error",
      message: "Validation failed",
      details: { slug: ["too short", "reserved"] },
    });

    expect(getApiFieldErrors(err)).toEqual({ slug: "too short" });
  });

  it("returns an empty object when there is no per-field information", () => {
    expect(getApiFieldErrors(axiosError({ code: "internal_error", message: "boom" }))).toEqual({});
    expect(getApiFieldErrors(new Error("offline"))).toEqual({});
    expect(getApiFieldErrors(null)).toEqual({});
    expect(getApiFieldErrors("nope")).toEqual({});
  });
});

describe("applyApiErrorsToForm", () => {
  it("sets server field errors on the form", () => {
    const form = makeForm();
    const err = axiosError({ details: { email: "already taken", slug: "reserved" } });

    const { handledFields } = applyApiErrorsToForm(form, err, { fallback: "fallback" });

    expect(handledFields).toEqual(["email", "slug"]);
    expect(form.getFieldState("email").error?.message).toBe("already taken");
    expect(form.getFieldState("email").error?.type).toBe("server");
    expect(form.getFieldState("slug").error?.message).toBe("reserved");
  });

  it("respects the `fields` allowlist and routes excluded fields to the top-level handler", () => {
    const form = makeForm();
    const onTopLevelError = vi.fn();
    const err = axiosError({ message: "Bad request", details: { slug: "reserved" } });

    const { handledFields } = applyApiErrorsToForm(form, err, {
      fallback: "fallback",
      fields: ["email"],
      onTopLevelError,
    });

    expect(handledFields).toEqual([]);
    expect(form.getFieldState("slug").error).toBeUndefined();
    expect(onTopLevelError).toHaveBeenCalledWith("Bad request");
  });

  it("remaps backend field names via `fieldMap`", () => {
    const form = makeForm();
    const err = axiosError({ details: { email_address: "already taken" } });

    const { handledFields } = applyApiErrorsToForm(form, err, {
      fallback: "fallback",
      fieldMap: { email_address: "email" },
    });

    expect(handledFields).toEqual(["email"]);
    expect(form.getFieldState("email").error?.message).toBe("already taken");
  });

  it("calls onTopLevelError with the resolved message when no field error applies", () => {
    const form = makeForm();
    const onTopLevelError = vi.fn();
    const err = axiosError({ code: "internal_error", message: "Server exploded" });

    applyApiErrorsToForm(form, err, { fallback: "fallback", onTopLevelError });

    expect(onTopLevelError).toHaveBeenCalledWith("Server exploded");
  });

  it("uses the fallback message when the error carries no readable message", () => {
    const form = makeForm();
    const onTopLevelError = vi.fn();

    applyApiErrorsToForm(form, {}, { fallback: "Please try again.", onTopLevelError });

    expect(onTopLevelError).toHaveBeenCalledWith("Please try again.");
  });

  it("does not call onTopLevelError when a field error is applied", () => {
    const form = makeForm();
    const onTopLevelError = vi.fn();
    const err = axiosError({ message: "Bad request", details: { email: "already taken" } });

    applyApiErrorsToForm(form, err, { fallback: "fallback", onTopLevelError });

    expect(onTopLevelError).not.toHaveBeenCalled();
  });
});
