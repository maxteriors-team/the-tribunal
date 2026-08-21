import { act, fireEvent, screen } from "@testing-library/react";

/**
 * Pick a Radix Select option without user-event's synchronous React 19 act wrapper.
 * The awaited outer act also drains Radix's portal and focus updates.
 */
export async function openSelect(trigger: HTMLElement) {
  await act(async () => {
    fireEvent.pointerDown(trigger, {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
  });
}

export async function clickOption(optionName: string | RegExp) {
  const option = await screen.findByRole("option", { name: optionName });
  await act(async () => {
    fireEvent.click(option);
  });
}

export async function selectOption(trigger: HTMLElement, optionName: string | RegExp) {
  await openSelect(trigger);
  await clickOption(optionName);
}
