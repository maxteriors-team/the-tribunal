import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ONBOARDING_DEFAULTS, type OnboardingFormValues } from "../_state";

import { LeadsStep } from "./leads-step";
import { OnboardingExtrasProvider, useOnboardingExtras } from "./onboarding-context";

const { toastErrorMock } = vi.hoisted(() => ({
  toastErrorMock: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: toastErrorMock },
}));

const REQUIRED_FILE_ERROR = "Upload a CSV file of your customers.";
const ORIGINAL_VIEWPORT = {
  width: window.innerWidth,
  height: window.innerHeight,
};
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

function setViewport(width: number, height: number) {
  Object.defineProperties(window, {
    innerWidth: { configurable: true, value: width },
    innerHeight: { configurable: true, value: height },
  });
  window.dispatchEvent(new Event("resize"));
}

function SeedLeadsError({ message }: { message: string }) {
  const { setLeadsError } = useOnboardingExtras();

  useEffect(() => {
    setLeadsError(message);
  }, [message, setLeadsError]);

  return null;
}

function LeadsStepHarness({ initialLeadsError }: { initialLeadsError?: string }) {
  const form = useForm<OnboardingFormValues>({
    defaultValues: ONBOARDING_DEFAULTS,
  });

  return (
    <FormProvider {...form}>
      <OnboardingExtrasProvider>
        {initialLeadsError && <SeedLeadsError message={initialLeadsError} />}
        <LeadsStep />
      </OnboardingExtrasProvider>
    </FormProvider>
  );
}

function getFileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Expected the CSV file input to exist");
  return input;
}

function makeCsvFile(name = "dead-leads.csv") {
  return new File(["first_name,phone\nAda,2125550101\nGrace,2125550102\n"], name, {
    type: "text/csv",
  });
}

async function expectSelectedFile(name = "dead-leads.csv") {
  expect(await screen.findByText(name)).toBeVisible();
  expect(await screen.findByText("~2 leads detected")).toBeVisible();
}

beforeEach(() => {
  toastErrorMock.mockReset();
});

afterAll(() => {
  setViewport(ORIGINAL_VIEWPORT.width, ORIGINAL_VIEWPORT.height);
});

describe.each(VIEWPORTS)("LeadsStep — $name onboarding", ({ width, height }) => {
  beforeEach(() => {
    setViewport(width, height);
  });

  it("shows one actionable empty dropzone and keeps required-file feedback", async () => {
    render(<LeadsStepHarness initialLeadsError={REQUIRED_FILE_ERROR} />);

    expect(screen.getAllByRole("button", { name: "Upload CSV file" })).toHaveLength(1);
    expect(screen.queryByText("Upload CSV")).not.toBeInTheDocument();
    expect(screen.getByText("Accepts .csv files")).toBeVisible();
    expect(screen.queryByText(/leads detected/)).not.toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(REQUIRED_FILE_ERROR);
  });

  it("rejects an invalid file with inline and toast feedback", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { container } = render(<LeadsStepHarness />);
    const invalidFile = new File(["not csv"], "dead-leads.txt", { type: "text/plain" });

    await user.upload(getFileInput(container), invalidFile);

    expect(await screen.findByRole("alert")).toHaveTextContent("Please select a .csv file.");
    expect(toastErrorMock).toHaveBeenCalledWith("Please select a .csv file.");
    expect(screen.queryByText("dead-leads.txt")).not.toBeInTheDocument();
  });

  it("accepts a valid file and clears prior required-file feedback", async () => {
    const user = userEvent.setup();
    const { container } = render(<LeadsStepHarness initialLeadsError={REQUIRED_FILE_ERROR} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(REQUIRED_FILE_ERROR);

    await user.upload(getFileInput(container), makeCsvFile());

    await expectSelectedFile();
    await waitFor(() => {
      expect(screen.queryByText(REQUIRED_FILE_ERROR)).not.toBeInTheDocument();
    });
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it("accepts a CSV by drag and drop", async () => {
    render(<LeadsStepHarness />);
    const dropzone = screen.getByRole("button", { name: "Upload CSV file" });
    const file = makeCsvFile("dropped-leads.csv");
    const dataTransfer = { files: [file], types: ["Files"] };

    fireEvent.dragEnter(dropzone, { dataTransfer });
    expect(dropzone).toHaveClass("border-primary");
    fireEvent.drop(dropzone, { dataTransfer });

    await expectSelectedFile("dropped-leads.csv");
    expect(dropzone).not.toHaveClass("border-primary");
  });

  it("opens the file picker with Enter and Space, then handles the chosen CSV", async () => {
    const user = userEvent.setup();
    const { container } = render(<LeadsStepHarness />);
    const dropzone = screen.getByRole("button", { name: "Upload CSV file" });
    const fileInput = getFileInput(container);
    const pickerSpy = vi.spyOn(fileInput, "click");

    dropzone.focus();
    await user.keyboard("{Enter}");
    expect(pickerSpy).toHaveBeenCalledTimes(1);

    await user.keyboard(" ");
    expect(pickerSpy).toHaveBeenCalledTimes(2);

    fireEvent.change(fileInput, { target: { files: [makeCsvFile("keyboard-leads.csv")] } });
    await expectSelectedFile("keyboard-leads.csv");
  });

  it("normalizes mixed-format area-code pastes", async () => {
    const user = userEvent.setup();
    render(<LeadsStepHarness />);
    const input = screen.getByRole("textbox", { name: "Preferred Area Code (optional)" });

    expect(input).toHaveAttribute("inputmode", "numeric");
    expect(input).toHaveAttribute("autocomplete", "tel-area-code");

    for (const [pasted, expected] of [
      ["(212)", "212"],
      ["415.555.0199", "415"],
      ["+1 (646) 555-0100", "646"],
    ]) {
      await user.clear(input);
      await user.paste(pasted);
      expect(input).toHaveValue(expected);
    }
  });
});
