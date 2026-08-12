"use client";

import { calculatePreconProgress, groupPreconItems, preconResponseMap } from "@/lib/estimator/landscape-precon";
import type { LandscapePreconResponseValue, LandscapePreconState } from "@/lib/estimator/types";

export function PreconChecklist({
  state,
  contractAmount,
  onChange,
}: {
  state: LandscapePreconState;
  contractAmount: number | null;
  onChange: (state: LandscapePreconState) => void;
}) {
  const responses = preconResponseMap(state);
  const progress = calculatePreconProgress(state);
  return (
    <section className="ll-panel-sheet" aria-labelledby="ll-precon-title">
      <header className="ll-panel-heading">
        <div><span>Install readiness</span><h2 id="ll-precon-title">Pre-Con Checklist</h2></div>
        <strong>{progress.completed}/{progress.total} complete</strong>
      </header>
      <div className="ll-electrical-metrics" aria-label="Pre-con summary">
        <div><span>Completion</span><strong>{progress.percent}%</strong></div>
        <div><span>Ready</span><strong>{progress.ready}</strong></div>
        <div><span>Blocked</span><strong>{progress.blocked}</strong></div>
        <div><span>Contract</span><strong>{contractAmount === null ? "Create quote" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(contractAmount)}</strong></div>
      </div>
      <label className="grid gap-1 py-3">
        <span className="font-semibold">Lead installer</span>
        <input value={state.leadInstaller} onChange={(event) => onChange({ ...state, leadInstaller: event.target.value })} />
      </label>
      <div className="grid gap-6">
        {groupPreconItems().map(({ group, items }) => (
          <fieldset key={group} className="ll-proposal-fieldset">
            <legend>{group}</legend>
            <div className="grid gap-4">
              {items.map((item) => {
                const response = responses.get(item.id) ?? { itemId: item.id, value: null, comment: "" };
                return (
                  <div key={item.id} className="grid gap-2 border-b pb-3 last:border-b-0">
                    <span className="font-medium">{item.label}</span>
                    <div className="flex flex-wrap gap-2" role="group" aria-label={item.label}>
                      {(["yes", "no", "na"] as const).map((value) => (
                        <button
                          key={value}
                          type="button"
                          className={response.value === value ? "est-btn primary" : "est-btn"}
                          aria-pressed={response.value === value}
                          onClick={() =>
                            onChange({
                              ...state,
                              responses: [
                                ...state.responses.filter((entry) => entry.itemId !== item.id),
                                { ...response, value: value as LandscapePreconResponseValue },
                              ],
                            })
                          }
                        >
                          {value === "na" ? "N/A" : value === "yes" ? "Yes" : "No"}
                        </button>
                      ))}
                    </div>
                    <label>
                      <span className="sr-only">Comment for {item.label}</span>
                      <input
                        value={response.comment}
                        placeholder="Comment"
                        onChange={(event) =>
                          onChange({
                            ...state,
                            responses: [
                              ...state.responses.filter((entry) => entry.itemId !== item.id),
                              { ...response, comment: event.target.value },
                            ],
                          })
                        }
                      />
                    </label>
                  </div>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>
      <label className="grid gap-1 py-4">
        <span className="font-semibold">Crew notes</span>
        <textarea rows={4} value={state.notes} onChange={(event) => onChange({ ...state, notes: event.target.value })} />
      </label>
      <div className="flex justify-end"><button type="button" className="est-btn" onClick={() => window.print()}>Print / PDF</button></div>
    </section>
  );
}
