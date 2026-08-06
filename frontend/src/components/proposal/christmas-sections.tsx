/**
 * Christmas-specific sections of the client proposal.
 *
 * The default proposal copy pitches a designed, permanent installation ("a
 * designer, not a salesperson", "1-year workmanship warranty"). None of that is
 * what a homeowner buying seasonal lighting is deciding about: they want to know
 * who climbs the ladder, what happens when a bulb dies in a storm, who owns the
 * lights, and who takes them down. These blocks answer that instead, and the
 * view swaps them in wholesale when `isChristmasProposal(doc)`.
 *
 * The selling points themselves are workspace config (`ChristmasConfig.
 * value_props`, snapshot onto the quote at save time), so an operator can
 * reword the promises in Settings without a deploy. Everything here is the
 * surrounding structure, which is the same for every seasonal quote.
 */
import type { ProposalValueProp } from "./document";

/** The block that answers "why you, and what am I actually getting". */
export function ChristmasValueProps({
  brandName,
  valueProps,
}: {
  brandName: string;
  valueProps: ProposalValueProp[];
}) {
  if (!valueProps.length) return null;
  return (
    <section className="xv-section" aria-labelledby="xv-heading">
      <div className="xv-head">
        {/* Decorative wreath; the heading beside it carries the meaning. */}
        <div className="xv-wreath" aria-hidden="true" />
        <div>
          <h2 className="xv-title" id="xv-heading">
            The <em>worry-free</em> Christmas
          </h2>
          {/* Explicit `{" "}`: a formatter can wrap this line after the
              expression, and JSX drops a newline adjacent to an expression
              entirely — which silently renders "AcmeLightinghandles". */}
          <p className="xv-sub">
            What {brandName}{" "}handles, so you don&rsquo;t have to.
          </p>
        </div>
      </div>
      <div className="xv-grid">
        {valueProps.map((prop) => (
          <div className="xv-item" key={prop.title}>
            <span className="xv-bulb" aria-hidden="true" />
            <div>
              <h3 className="xv-item-title">{prop.title}</h3>
              <p className="xv-item-body">{prop.body}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** The seasonal guarantee: the display stays lit, or we come back. */
export function ChristmasGuarantee() {
  return (
    <div className="guarantee-section">
      <div className="guarantee-badge">
        <div className="guarantee-badge-star">&#9733;</div>
        <div className="guarantee-badge-text">
          Lit All
          <br />
          Season
        </div>
      </div>
      <div className="guarantee-content">
        <div className="guarantee-title">
          <em>Lit</em>{" "}All Season
        </div>
        <div className="guarantee-body">
          If a bulb goes dark, a strand sags, or the wind moves something out of
          place,{" "}
          <strong>we come out and fix it at no charge.</strong>{" "}That is what
          maintenance included actually means. You should be looking at your
          lights, not troubleshooting them.
        </div>
      </div>
    </div>
  );
}

/** What every seasonal install covers. */
export function ChristmasIncluded() {
  const items = [
    "Commercial-grade bulbs, strands, and clips, all owned by us",
    "Custom cut and fit to your rooflines, peaks, and gables",
    "Professional installation by our own trained crew",
    "In-season maintenance if anything goes out",
    "Full takedown after the season, on our schedule",
    "Off-season storage of your entire display",
  ];
  return (
    <div className="included-section">
      <div className="section-heading">Every Install Includes</div>
      <div className="included-grid">
        {items.map((item) => (
          <div className="included-item" key={item}>
            <span className="included-check">&#9670;</span> {item}
          </div>
        ))}
      </div>
    </div>
  );
}

/** The seasonal arc, which ends with takedown rather than with a handover. */
export function ChristmasSteps() {
  const steps = [
    [
      "I",
      "You Approve",
      "Approving holds your spot on the install calendar. The earliest approvals get the earliest dates.",
    ],
    [
      "II",
      "We Install",
      "Our crew measures, cuts, hangs, times, and tests every strand. You never touch a ladder.",
    ],
    [
      "III",
      "We Take It Down",
      "After the season we remove all of it, leave no trace on your home, and store it until next year.",
    ],
  ];
  return (
    <div className="steps-section">
      <div className="section-heading">How Your Season Works</div>
      <div className="steps-grid">
        {steps.map(([num, title, desc]) => (
          <div className="step-card" key={num}>
            <div className="step-num">{num}</div>
            <div className="step-title">{title}</div>
            <div className="step-desc">{desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Closing argument, in the homeowner's terms. */
export function ChristmasTrust({ brandName }: { brandName: string }) {
  return (
    <div className="trust-section">
      <div className="trust-heading">Why {brandName}</div>
      <div className="trust-body">
        Holiday lighting is what we do this time of year. We measure your
        rooflines, cut every strand to fit the house, and hang it with clips that
        come off clean in January.{" "}
        <strong>You get the house people slow down for</strong>, without buying
        a single bulb, climbing a ladder, or finding room in the garage for six
        bins in February.
      </div>
    </div>
  );
}
