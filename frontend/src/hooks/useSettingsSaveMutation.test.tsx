import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ReactNode } from "react";
import { toast, Toaster } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSettingsSaveMutation } from "./useSettingsSaveMutation";

function makeWrapper(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false, throwOnError: true },
      queries: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster duration={60_000} />
    </QueryClientProvider>
  );
}

function SaveButton({ save }: { save: () => Promise<unknown> }) {
  const mutation = useSettingsSaveMutation({
    mutationFn: save,
    successMessage: "Profile settings are up to date.",
    errorMessage: "We couldn't save profile settings. Check your connection and try again.",
  });

  return (
    <button type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
      Save changes
    </button>
  );
}

afterEach(() => {
  toast.dismiss();
});

describe("useSettingsSaveMutation", () => {
  it("announces a successful save and restores keyboard focus", async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockImplementation(async () => {
      (document.activeElement as HTMLElement | null)?.blur();
      return {};
    });
    render(makeWrapper(<SaveButton save={save} />));

    const button = screen.getByRole("button", { name: "Save changes" });
    await user.click(button);

    const liveRegion = screen.getByLabelText(/Notifications/);
    expect(liveRegion).toHaveAttribute("aria-live", "polite");
    expect(await within(liveRegion).findByText("Changes saved")).toBeVisible();
    expect(within(liveRegion).getByText("Profile settings are up to date.")).toBeVisible();
    await waitFor(() => expect(button).toHaveFocus());
  });

  it("keeps an API failure local and announces actionable recovery copy", async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockImplementation(async () => {
      (document.activeElement as HTMLElement | null)?.blur();
      throw {
        message: "Request failed with status code 500",
        response: { status: 500, data: { detail: "Internal Server Error" } },
      };
    });
    render(makeWrapper(<SaveButton save={save} />));

    const button = screen.getByRole("button", { name: "Save changes" });
    await user.click(button);

    const liveRegion = screen.getByLabelText(/Notifications/);
    expect(await within(liveRegion).findByText("Changes not saved")).toBeVisible();
    expect(
      within(liveRegion).getByText(
        "We couldn't save profile settings. Check your connection and try again.",
      ),
    ).toBeVisible();
    expect(liveRegion).not.toHaveTextContent("Request failed with status code 500");
    await waitFor(() => expect(button).toHaveFocus());
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
  });
});
