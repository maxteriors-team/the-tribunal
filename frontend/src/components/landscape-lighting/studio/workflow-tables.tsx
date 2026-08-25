"use client";

import { X } from "lucide-react";
import { useMemo, useState, type KeyboardEvent } from "react";

/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- Horizontally overflowing data regions must be keyboard-scrollable. */

import { formatFeet } from "@/lib/estimator/design";
import { FIXTURE_TYPES, type FixtureType } from "@/lib/estimator/fixtures";
import type { LandscapeProcurementRow } from "@/lib/estimator/landscape-procurement";
import type {
  LandscapeFixtureScheduleUpdate,
  LandscapeScheduleRow,
} from "@/lib/estimator/landscape-schedule";
import type { BistroInstallationType } from "@/lib/estimator/types";
import type { CatalogItemResponse } from "@/types/sales-wizard";

interface FixtureScheduleTableProps {
  rows: LandscapeScheduleRow[];
  catalog: CatalogItemResponse[];
  onUpdate: (itemId: string, update: LandscapeFixtureScheduleUpdate) => void;
  onCopyToType: (itemId: string) => void;
}

function catalogOptionLabel(item: CatalogItemResponse): string {
  return `${item.name}${item.sku ? ` (${item.sku})` : ""}`;
}

export function LandscapeFixtureScheduleTable({
  rows,
  catalog,
  onUpdate,
  onCopyToType,
}: FixtureScheduleTableProps) {
  const activeCatalog = useMemo(
    () => catalog.filter((item) => item.is_active).sort((a, b) => a.name.localeCompare(b.name)),
    [catalog],
  );
  const catalogById = useMemo(
    () => new Map(activeCatalog.map((item) => [item.id, item])),
    [activeCatalog],
  );
  const lampCatalog = useMemo(() => {
    const likelyLamps = activeCatalog.filter((item) =>
      /(^|\b)(lamp|bulb|mr\d{2}|led)(\b|$)/i.test(
        `${item.name} ${item.sku ?? ""} ${item.description ?? ""}`,
      ),
    );
    return likelyLamps.length ? likelyLamps : activeCatalog;
  }, [activeCatalog]);
  const accessoryCatalog = useMemo(() => {
    const attachable = activeCatalog.filter((item) =>
      item.attach_targets?.some((target) => /landscape|fixture/i.test(target)),
    );
    return attachable.length ? attachable : activeCatalog;
  }, [activeCatalog]);

  return (
    <div
      className="ll-data-table-wrap"
      role="region"
      aria-label="Fixture schedule table"
      tabIndex={0}
    >
      <table className="ll-data-table ll-fixture-schedule-table">
        <caption className="sr-only">
          Fixture schedule with editable lamp and accessory assignments, plus fixture type
        </caption>
        <thead>
          <tr>
            <th scope="col">No.</th>
            <th scope="col">Sheet</th>
            <th scope="col">Fixture</th>
            <th scope="col">Lamp</th>
            <th scope="col">Accessories</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selectedAccessoryIds = row.accessoryCatalogItemIds;
            const selectedAccessories = selectedAccessoryIds.map((id, index) => ({
              id,
              label:
                catalogById.get(id)?.name ?? row.accessoryNames[index] ?? "Unavailable accessory",
            }));
            const accessoryOptions = accessoryCatalog.filter(
              (item) =>
                item.id !== row.fixtureCatalogItemId &&
                item.id !== row.lampCatalogItemId &&
                !selectedAccessoryIds.includes(item.id),
            );
            return (
              <tr key={row.itemId}>
                <td className="ll-row-number">{row.number}</td>
                <td>{row.sheetLabel}</td>
                <td>
                  <label className="ll-field-select">
                    <span className="sr-only">Fixture type for fixture {row.number}</span>
                    <select
                      value={row.fixtureType}
                      aria-label={`Fixture type for fixture ${row.number}`}
                      onChange={(event) => {
                        const fixtureType = event.target.value as FixtureType;
                        onUpdate(row.itemId, {
                          productId: `fixture-${fixtureType}`,
                          catalogItemId: undefined,
                          catalogSku: undefined,
                          lampCatalogItemId: undefined,
                          accessoryCatalogItemIds: [],
                        });
                      }}
                    >
                      {FIXTURE_TYPES.map((fixture) => (
                        <option key={fixture.type} value={fixture.type}>
                          {fixture.type === "pathlight" ? "Pathlight" : fixture.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <strong>{row.fixtureName}</strong>
                  <span>{row.fixtureSku || "SKU not assigned"}</span>
                  {row.unresolved.length ? (
                    <span className="ll-inline-warning">{row.unresolved.join(". ")}</span>
                  ) : null}
                </td>
                <td>
                  <label className="ll-field-select">
                    <span className="sr-only">Lamp for fixture {row.number}</span>
                    <select
                      value={row.lampCatalogItemId ?? ""}
                      aria-label={`Lamp for fixture ${row.number}`}
                      onChange={(event) =>
                        onUpdate(row.itemId, {
                          lampCatalogItemId: event.target.value || undefined,
                        })
                      }
                    >
                      <option value="">Use fixture specification</option>
                      {lampCatalog.map((item) => (
                        <option key={item.id} value={item.id}>
                          {catalogOptionLabel(item)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <span>{row.lampName ?? "No lamp selected"}</span>
                </td>
                <td>
                  <div className="ll-accessory-editor">
                    {selectedAccessories.length ? (
                      <ul aria-label={`Accessories for fixture ${row.number}`}>
                        {selectedAccessories.map((accessory) => (
                          <li key={accessory.id}>
                            <span>{accessory.label}</span>
                            <button
                              type="button"
                              aria-label={`Remove ${accessory.label} from fixture ${row.number}`}
                              onClick={() =>
                                onUpdate(row.itemId, {
                                  accessoryCatalogItemIds: selectedAccessoryIds.filter(
                                    (id) => id !== accessory.id,
                                  ),
                                })
                              }
                            >
                              <X aria-hidden="true" />
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : row.accessoryNames.length ? (
                      <span>{row.accessoryNames.join(", ")} from fixture specification</span>
                    ) : (
                      <span>No accessories selected</span>
                    )}
                    <label className="ll-field-select">
                      <span className="sr-only">Add accessory to fixture {row.number}</span>
                      <select
                        value=""
                        aria-label={`Add accessory to fixture ${row.number}`}
                        disabled={!accessoryOptions.length}
                        onChange={(event) => {
                          if (!event.target.value) return;
                          onUpdate(row.itemId, {
                            accessoryCatalogItemIds: [...selectedAccessoryIds, event.target.value],
                          });
                        }}
                      >
                        <option value="">Add accessory</option>
                        {accessoryOptions.map((item) => (
                          <option key={item.id} value={item.id}>
                            {catalogOptionLabel(item)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </td>
                <td>
                  <button
                    type="button"
                    className="est-btn ghost ll-copy-type-button"
                    onClick={() => onCopyToType(row.itemId)}
                  >
                    Apply to matching fixtures
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export interface LandscapeBistroRunRow {
  runId: string;
  number: number;
  sheetLabel: string;
  installation: BistroInstallationType | null;
  productName: string;
  sku: string | null;
  anchorCount: number;
  lengthFeet: number | null;
}

export function LandscapeBistroRunScheduleTable({ rows }: { rows: LandscapeBistroRunRow[] }) {
  return (
    <div
      className="ll-data-table-wrap"
      role="region"
      aria-label="Bistro lighting run schedule"
      tabIndex={0}
    >
      <table className="ll-data-table ll-bistro-schedule-table">
        <caption className="sr-only">
          Temporary and permanent bistro lighting runs by plan sheet
        </caption>
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Sheet</th>
            <th scope="col">Installation</th>
            <th scope="col">Bistro product</th>
            <th scope="col">Anchors</th>
            <th scope="col">Length</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.runId}>
              <td className="ll-row-number">B{row.number}</td>
              <td>{row.sheetLabel}</td>
              <td>
                <strong>
                  {row.installation === "temporary"
                    ? "Temporary"
                    : row.installation === "permanent"
                      ? "Permanent"
                      : "Unspecified"}
                </strong>
              </td>
              <td>
                <strong>{row.productName}</strong>
                <span>{row.sku || "Layout-only product"}</span>
              </td>
              <td>{row.anchorCount}</td>
              <td>{row.lengthFeet === null ? "Set scale" : formatFeet(row.lengthFeet)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function commitOnEnter(event: KeyboardEvent<HTMLInputElement>) {
  if (event.key === "Enter") event.currentTarget.blur();
}

const PURCHASE_STATUS_LABELS: Record<LandscapeProcurementRow["status"], string> = {
  unresolved: "Needs catalog details",
  "not-ordered": "Not ordered",
  partial: "Partially received",
  ordered: "Ordered",
  received: "Received",
};

interface EditableTextInputProps {
  value: string;
  label: string;
  className?: string;
  onCommit: (value: string) => void;
}

function EditableTextInput(props: EditableTextInputProps) {
  return <EditableTextInputDraft key={props.value} {...props} />;
}

function EditableTextInputDraft({ value, label, className, onCommit }: EditableTextInputProps) {
  const [draft, setDraft] = useState(value);
  return (
    <input
      className={className}
      type="text"
      value={draft}
      aria-label={label}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        if (draft !== value) onCommit(draft.trim());
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setDraft(value);
          event.currentTarget.blur();
          return;
        }
        commitOnEnter(event);
      }}
    />
  );
}

interface EditableNumberInputProps {
  value: number | null;
  label: string;
  nullable?: boolean;
  onCommit: (value: number | null) => void;
}

function EditableNumberInput(props: EditableNumberInputProps) {
  return <EditableNumberInputDraft key={props.value ?? "null"} {...props} />;
}

function EditableNumberInputDraft({
  value,
  label,
  nullable = false,
  onCommit,
}: EditableNumberInputProps) {
  const externalValue = value === null ? "" : String(value);
  const [draft, setDraft] = useState(externalValue);

  const commit = () => {
    const normalized = draft.trim();
    if (!normalized && nullable) {
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed) || parsed < 0) {
      setDraft(externalValue);
      return;
    }
    const next = Math.round((parsed + Number.EPSILON) * 100) / 100;
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };

  return (
    <input
      className="ll-bom-number-input"
      type="number"
      min={0}
      max={1_000_000}
      step="0.01"
      inputMode="decimal"
      value={draft}
      aria-label={label}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setDraft(externalValue);
          event.currentTarget.blur();
          return;
        }
        commitOnEnter(event);
      }}
    />
  );
}

interface BomTableProps {
  rows: LandscapeProcurementRow[];
  onUpdate: (row: LandscapeProcurementRow, patch: Partial<LandscapeProcurementRow>) => void;
}

export function LandscapeBomTable({ rows, onUpdate }: BomTableProps) {
  const total = rows.reduce((sum, row) => sum + (row.totalCost ?? 0), 0);
  const hasUnknownCost = rows.some((row) => row.unitCost === null);

  return (
    <div
      className="ll-data-table-wrap"
      role="region"
      aria-label="Bill of materials table"
      tabIndex={0}
    >
      <table className="ll-data-table ll-bom-table">
        <caption className="sr-only">Editable bill of materials tallied from the drawing</caption>
        <thead>
          <tr>
            <th scope="col">Material</th>
            <th scope="col">SKU</th>
            <th scope="col">Manufacturer</th>
            <th scope="col">Need</th>
            <th scope="col">Ordered</th>
            <th scope="col">Received</th>
            <th scope="col">Unit cost</th>
            <th scope="col">Total</th>
            <th scope="col">Supplier</th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const identity = row.name || row.sku || row.key;
            return (
              <tr key={row.key}>
                <th scope="row">
                  <EditableTextInput
                    className="ll-bom-description-input"
                    value={row.name}
                    label={`Material description for ${identity}`}
                    onCommit={(name) => onUpdate(row, { name })}
                  />
                  <span>
                    {row.category} · {row.planSource}
                  </span>
                </th>
                <td>
                  <EditableTextInput
                    value={row.sku ?? ""}
                    label={`SKU for ${identity}`}
                    onCommit={(sku) => onUpdate(row, { sku: sku || null })}
                  />
                  <span className={row.sourceStatus === "Ready" ? "" : "ll-inline-warning"}>
                    {row.sourceStatus}
                  </span>
                </td>
                <td>
                  <EditableTextInput
                    value={row.manufacturer ?? ""}
                    label={`Manufacturer for ${identity}`}
                    onCommit={(manufacturer) => onUpdate(row, { manufacturer })}
                  />
                </td>
                <td>
                  <EditableNumberInput
                    value={row.needed}
                    label={`Quantity needed for ${identity}`}
                    onCommit={(needed) => onUpdate(row, { needed: needed ?? 0 })}
                  />
                  <span>{row.unit}</span>
                </td>
                <td>
                  <EditableNumberInput
                    value={row.ordered}
                    label={`Quantity ordered for ${identity}`}
                    onCommit={(ordered) => onUpdate(row, { ordered: ordered ?? 0 })}
                  />
                </td>
                <td>
                  <EditableNumberInput
                    value={row.received}
                    label={`Quantity received for ${identity}`}
                    onCommit={(received) => onUpdate(row, { received: received ?? 0 })}
                  />
                  <span>{PURCHASE_STATUS_LABELS[row.status]}</span>
                </td>
                <td>
                  <EditableNumberInput
                    value={row.unitCost}
                    label={`Unit cost for ${identity}`}
                    nullable
                    onCommit={(unitCost) => onUpdate(row, { unitCost })}
                  />
                </td>
                <td className="ll-bom-total-cell">
                  {row.totalCost === null ? "Pending" : `$${row.totalCost.toFixed(2)}`}
                </td>
                <td>
                  <EditableTextInput
                    value={row.supplier ?? ""}
                    label={`Supplier for ${identity}`}
                    onCommit={(supplier) => onUpdate(row, { supplier })}
                  />
                </td>
                <td>
                  <EditableTextInput
                    value={row.supplierNote}
                    label={`Notes for ${identity}`}
                    onCommit={(supplierNote) => onUpdate(row, { supplierNote })}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={7}>
              Material total{hasUnknownCost ? " (priced lines only)" : ""}
            </th>
            <td className="ll-bom-total-cell">${total.toFixed(2)}</td>
            <td colSpan={2}>{rows.length} line items</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
