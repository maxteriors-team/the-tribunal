import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocumentActionButton, DocumentViewport } from "./document-viewport";

describe("DocumentViewport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fits the whole sheet and preserves its visual center during manual zoom", async () => {
    let notifyResize: (() => void) | null = null;
    class ControlledResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as unknown as ResizeObserver);
      }
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    }
    vi.stubGlobal("ResizeObserver", ControlledResizeObserver);

    const onPrint = vi.fn();
    const { container } = render(
      <DocumentViewport
        label="Fixture schedule"
        paperWidth={1000}
        minimumPaperHeight={800}
        actions={<DocumentActionButton onClick={onPrint}>Print</DocumentActionButton>}
      >
        <article>Installation document</article>
      </DocumentViewport>,
    );

    const viewport = container.querySelector(".ll-document-viewport") as HTMLElement;
    const stage = container.querySelector(".ll-document-stage") as HTMLDivElement;
    const paper = container.querySelector(".ll-document-paper") as HTMLDivElement;
    Object.defineProperties(stage, {
      clientWidth: { configurable: true, value: 532 },
      clientHeight: { configurable: true, value: 432 },
    });
    Object.defineProperties(paper, {
      offsetHeight: { configurable: true, value: 800 },
      scrollHeight: { configurable: true, value: 800 },
    });

    act(() => notifyResize?.());
    await waitFor(() => expect(viewport.dataset.documentZoom).toBe("50"));
    expect(screen.getByRole("slider", { name: "Fixture schedule zoom percentage" })).toHaveValue(
      "50",
    );

    stage.scrollLeft = 100;
    stage.scrollTop = 50;
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await waitFor(() => expect(viewport.dataset.documentZoom).toBe("60"));
    await waitFor(() => {
      expect(stage.scrollLeft).toBeCloseTo(173.2);
      expect(stage.scrollTop).toBeCloseTo(103.2);
    });

    expect(screen.getByRole("button", { name: "Fit document" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: "Fit document" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Fit document" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(onPrint).toHaveBeenCalledOnce();
  });
});
