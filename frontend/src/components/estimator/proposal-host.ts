/**
 * The contract the Quote Builder uses to host the Light Designer.
 *
 * Kept as its own module so the designer never imports the sales-wizard hook
 * (and the wizard never imports the designer's internals). The designer hands
 * back geometry and one composited image; the wizard decides what that means
 * for the proposal and lets the server price it.
 */
import type { FixtureType } from "@/lib/estimator/fixtures";
import type { ServiceKey } from "@/lib/estimator/services";
import type { Design, PhotoInfo } from "@/lib/estimator/types";

export interface DesignerProposalSnapshot {
  /** Composited "lit at night" JPEG data URL saved onto the proposal. */
  image: string;
  /** The drawing itself, so re-opening the designer restores it. */
  design: Design;
  /** Dusk level the composite was rendered at. */
  dusk: number;
  /** Which services the design covers, for the client's value propositions. */
  services: ServiceKey[];
  /**
   * Placed landscape fixtures counted by *type*. The host resolves each type to
   * the price-book product its chosen package sells, which is what carries the
   * SKU into the quote and the technician's parts list.
   */
  fixtures: Partial<Record<FixtureType, number>>;
  /** Measured roofline feet (0 when no roofline product is traced). */
  rooflineFeet: number;
  /** Traced bistro / festoon feet. */
  bistroFeet: number;
}

export interface DesignerProposalHost {
  /** Restored state from the rep's previous visit to the designer. */
  initial?: {
    design: Design | null;
    dusk: number | null;
    photo: PhotoInfo | null;
    services?: ServiceKey[] | null;
  };
  /**
   * The package (tier) this quote is selling. Fixture types resolve to that
   * package's products, so switching package re-resolves every drawn fixture
   * without the rep redrawing anything.
   */
  tierKey?: string | null;
  /** Persist the composite + measurements onto the in-progress proposal. */
  onSave: (snapshot: DesignerProposalSnapshot) => void;
  /** Keep the loaded photo alive in the host so re-opening resumes the design. */
  onPhotoChange: (photo: PhotoInfo | null) => void;
  /** Return to the quote. */
  onClose: () => void;
}
