/**
 * Sales-wizard domain types — aliased straight from the generated OpenAPI client
 * so they can never drift from the backend schemas
 * (`app/schemas/pricing.py`, `proposal_wizard.py`, `catalog.py`).
 */
import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

export type PricingSettings = Schemas["PricingSettings"];
export type TierConfig = Schemas["TierConfig"];
export type CatalogItemResponse = Schemas["CatalogItemResponse"];

export type ProposalWizardPayload = Schemas["ProposalWizardPayload"];
export type WizardClient = Schemas["WizardClient"];
export type WizardCharge = Schemas["WizardCharge"];
export type WizardFixtureQty = Schemas["WizardFixtureQty"];
export type WizardBistroSelection = Schemas["WizardBistroSelection"];

export type ProposalDocument = Schemas["ProposalDocument"];
export type ProposalTierView = Schemas["ProposalTierView"];
export type ProposalLine = Schemas["ProposalLine"];
export type ProposalCharge = Schemas["ProposalCharge"];
export type ProposalCarePlan = Schemas["ProposalCarePlan"];
export type ProposalFinancing = Schemas["ProposalFinancing"];
export type TierPricing = Schemas["TierPricing"];
export type CarePlanPricing = Schemas["CarePlanPricing"];
export type BistroPricing = Schemas["BistroPricing"];
export type FulfillmentPart = Schemas["FulfillmentPart"];

export type QuoteDetail = Schemas["QuoteDetailResponse"];
