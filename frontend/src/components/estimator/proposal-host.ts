/**
 * The contract the Quote Builder uses to host the Light Designer.
 *
 * Kept as its own module so the designer never imports the sales-wizard hook
 * (and the wizard never imports the designer's internals). The designer hands
 * back geometry and one composited image per photo; the wizard decides what
 * that means for the proposal and lets the server price it.
 */
import type { FixtureType } from "@/lib/estimator/fixtures";
import type { ServiceKey } from "@/lib/estimator/services";
import type { Design, PhotoInfo } from "@/lib/estimator/types";

/**
 * One photo of the job and what the rep drew on it. A job is usually more than
 * one shot — front elevation, back patio, the walkway — so the designer keeps a
 * list of these and every one becomes a mockup on the proposal.
 */
export interface DesignerShot {
  /** Stable id, so switching between shots survives reordering/removal. */
  id: string;
  /** The uploaded photo (memory-only data URL). */
  photo: PhotoInfo;
  /** The drawing on this photo. */
  design: Design;
  /** Dusk level this shot is shown at. */
  dusk: number;
}

/** A rendered shot: the composite the client sees, kept with its drawing. */
export interface DesignerShotSnapshot {
  /** Composited "lit at night" JPEG data URL. */
  image: string;
  design: Design;
  dusk: number;
}

export interface DesignerProposalSnapshot {
  /**
   * Every drawn photo, in the order the rep built them. The first one is the
   * proposal's hero image; the rest render beside it as a gallery.
   */
  shots: DesignerShotSnapshot[];
  /** Which services the design covers, for the client's value propositions. */
  services: ServiceKey[];
  /**
   * Placed landscape fixtures counted by *type*, totalled across every shot.
   * The host resolves each type to the price-book product its chosen package
   * sells, which is what carries the SKU into the quote and the technician's
   * parts list.
   */
  fixtures: Partial<Record<FixtureType, number>>;
  /** Measured roofline feet across every shot (0 when no roofline is traced). */
  rooflineFeet: number;
  /** Traced bistro / festoon feet across every shot. */
  bistroFeet: number;
}

export interface DesignerProposalHost {
  /** Restored state from the rep's previous visit to the designer. */
  initial?: {
    /** Photos + drawings the rep already had open. Empty on a first visit. */
    shots?: DesignerShot[] | null;
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
  /**
   * Keep the loaded photos + drawings alive in the host so leaving the designer
   * and coming back resumes every shot, not just the last saved one.
   */
  onShotsChange: (shots: DesignerShot[]) => void;
  /** Return to the quote. */
  onClose: () => void;
}
