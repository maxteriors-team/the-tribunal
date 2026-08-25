# Landscape inventory local review manifest

Generated from a **local-only** dry run on 2026-08-24:

```bash
cd backend
uv run python -m scripts.ops.upsert_landscape_inventory --workspace default
```

## Dry-run result

- Workspace observed: `default` / **Default Workspace** (local database, not the production target).
- Transaction result: **rolled back**; 24 would create, 0 kept, 0 linked, and 2 catalog links blocked because the local workspace had no matching catalog rows.
- Review split: 19 mapped, 5 unresolved, and 3 mapped exact-SKU name/role differences.
- Production, Railway, deployment, PR, merge, and inventory apply: **not contacted or performed**.
- IDs below are deterministic for this local workspace only. A later production dry run will produce target-workspace IDs and authoritative create/keep/link actions.

## Common would-create data for every row

| Field                  | Reviewed value                                                        |
| ---------------------- | --------------------------------------------------------------------- |
| `is_active`            | `true`                                                                |
| `unit_of_measure`      | `each`                                                                |
| `valuation_method`     | `weighted_average`                                                    |
| `supplier_name`        | `FX Luminaire`                                                        |
| `supplier_sku`         | Same approved numeric SKU                                             |
| `quantity_on_hand`     | `0.0000`                                                              |
| `avg_unit_cost`        | `0.0000`                                                              |
| `total_value`          | `0.00`                                                                |
| `notes`                | `null` — supplier costs are not stored in unredacted notes            |
| Ledger/opening balance | None; 0 ledger writes and 0 stock-level writes                        |
| Source quantity        | Not imported; the unverified total of 49 remains intake evidence only |

`59272804`, the 40-foot strip-light package, also remains one `each` until its per-foot valuation is explicitly approved.

## Complete 24-row manifest

| SKU        | Local deterministic ID                 | Supplier item name                                         | Tribunal mapping                               | Review                                    | Local catalog-link result                        |
| ---------- | -------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------- | ------------------------------------------------ |
| `59009035` | `94f785a6-e2b7-580f-b21a-19fe50b45c76` | DX-300-M 300w Transformer w/ Astronomical Timer Matte Gray | DX 300W Transformer                            | Mapped — exact component                  | Not applicable                                   |
| `59009050` | `544ba2ef-c253-51da-8554-71f38830f65a` | EX-150-SS 150w Transformer Stainless Steel                 | EX 150W Transformer                            | Mapped — exact component                  | Not applicable                                   |
| `59203512` | `f1ecc948-b73b-5224-8ce2-6f8ae3c04892` | M-PL-1LED-FB Path Light Black                              | Modern Path Light                              | Mapped — exact component                  | Not applicable                                   |
| `59205842` | `3ce6e9d4-824b-5b92-b190-7f339fe520d3` | TM-LED-20W-18R-FB Path Light Black                         | Pathway Light                                  | Mapped — exact component                  | Not applicable                                   |
| `59213082` | `7a676b89-88f5-593f-bbcb-8b00d5ed1c91` | CA-51-P4WFL-FB CORA ACCENT BLACK                           | ZD Down Light                                  | **Mapped — name/role approval needed**    | Not applicable                                   |
| `59213092` | `3c383026-8adb-5646-888d-d58f744f49ca` | CA-51-E6WWF-FB CORA ACCENT BLACK                           | ZD Uplight / Accent Uplight                    | Mapped — exact component                  | Not applicable                                   |
| `59213350` | `bb590070-8d4b-5c28-9262-489e3be39a66` | CN-51-E6WFL-CW-FB CORA IN-GRADE BLACK                      | CORA In-Grade / ZD In-Grade Uplight            | **Unresolved — package/config drift**     | Not applicable                                   |
| `59213632` | `af079814-de0b-5199-acb8-c88f6e10ca33` | HC-LED-TA-FB Top Assembly Black                            | ZDC Path Light / ZD Path Light top assembly    | Mapped — exact component                  | Not applicable                                   |
| `59213710` | `3f520133-dcb0-5e59-beb4-edb6911f885d` | CN-73-E9-W-FL-LG-FB CORA WELL BLACK                        | CORA Well Light                                | **Unresolved — placeholder match**        | Not applicable                                   |
| `59214042` | `5c6aa0b2-9599-590f-b7b4-bb529b37f8ea` | EA-51-E-4W-FL-BC EVO ACCENT BLACK COMP                     | EVO Accent Uplight                             | Mapped — exact component                  | Not applicable                                   |
| `59272804` | `ea6ed787-8617-54de-b3df-08df79c2527f` | SRP-40-W 40 ft Strip Light Warm White                      | Warm White Strip Light                         | **Unresolved — missing from Tribunal**    | Not applicable                                   |
| `59303512` | `32840dac-810f-580b-80f2-4f752d6f0ebf` | M-PL-ZD-1LED-FB Path Light Black                           | ZD Modern Path Light                           | Mapped — exact component                  | Not applicable                                   |
| `59304101` | `a68baa76-1a95-5efc-ac17-ed3b4b961e97` | VO-ZD-1LED-RD-SS ROUND FACE                                | Silver Wall Light                              | **Unresolved — missing from Tribunal**    | Not applicable                                   |
| `59306832` | `badd99f2-8b34-5282-95e2-a8f40ce22b0b` | PO-ZD-1LED-RD-FB Wall Light Black                          | FX PO ZD Round Core-Drilled Wall Light — Black | Mapped — exact catalog/component          | **Catalog missing locally; safe-link candidate** |
| `59308530` | `e2fd024b-3807-5528-a04e-a3c96d6ef97b` | ZD MR-16 5-Watt Warm Flood LED Lamp                        | ZD MR16 5W Lamp                                | Mapped — exact component                  | Not applicable                                   |
| `59311122` | `403698c2-9114-544a-a061-c80eb6ad9dcf` | P-ZD-1LED-18RA-FB Path Light 18 in Riser Black             | ZD Path Light — 18in riser                     | Mapped — exact component                  | Not applicable                                   |
| `59320292` | `b7c16699-0bf0-56c2-ae6b-a772b53f508e` | NP-ZD-9LED-LS-FB Up Light Black                            | ZD Narrow Beam Accent                          | **Unresolved — near match to `59320262`** | Not applicable                                   |
| `59400232` | `9d79955c-7786-5906-b771-7c64c1ab7a76` | NP-ZDC-FB Up Light Black                                   | ZDC Color Uplight                              | Mapped — exact component                  | Not applicable                                   |
| `59403532` | `9504c4de-1657-5755-b944-1df897328bc3` | M-PL-ZDC-FB Path Light Black                               | ZDC Modern Color Path Light                    | Mapped — exact component                  | Not applicable                                   |
| `59407330` | `2b5d9fba-f719-5a64-b9b4-f0156a5cbbc0` | LL-ZDC-BS UNDERWATER LIGHT                                 | FX LL ZDC Underwater Light — Brass             | Mapped — exact catalog/component          | **Catalog missing locally; safe-link candidate** |
| `59409010` | `46e0c4eb-bc9c-50b7-ab1d-1c015966dc3b` | WIFI-MOD-2 Luxor Wi-Fi Module                              | Luxor WiFi Module                              | Mapped — exact component                  | Not applicable                                   |
| `59409312` | `b7ecd211-e9ed-5789-93bc-554a922cf9ce` | LUX-300-M LUXOR 2.0 300W XFMR                              | Luxor Smart 300W Transformer                   | Mapped — exact component                  | Not applicable                                   |
| `59412322` | `cafb2ef9-024f-528c-97a3-7bf0f6a8c817` | G-ZDC-18RA-FB 18 in Riser Black                            | ZDC Path Light — 18in riser                    | **Mapped — name/role approval needed**    | Not applicable                                   |
| `59413032` | `78e52328-ec52-5758-a83c-58ad97ebf70c` | XA-70-ZDC-WF-FB ACCENT LIGHT BLACK                         | ZDC Down Light                                 | **Mapped — name/role approval needed**    | Not applicable                                   |

## Approval gate for any later phase

A human must explicitly approve the intended target workspace, all five unresolved rows, all three name/role differences, the zero-stock/no-cost policy, and the two conditional catalog links. After that decision, create a separate protected-branch release/import plan; collect a production dry run before offering a final apply checkpoint.
