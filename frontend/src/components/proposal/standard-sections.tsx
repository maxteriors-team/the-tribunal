/**
 * The default (non-seasonal) pitch sections of the client proposal.
 *
 * Moved out of `client-proposal-view.tsx` verbatim when the seasonal Christmas
 * variant landed, so the two pitches are siblings the view picks between rather
 * than one being a special case buried inside the other. Copy is unchanged.
 *
 * This is the permanent-installation story: design, craftsmanship, workmanship
 * warranty, and a completion walkthrough. See `./christmas-sections.tsx` for the
 * seasonal counterpart, which sells maintenance, takedown, and storage instead.
 */

/** "The {brand} Experience" — how the company works. */
export function StandardExperience({ brandName }: { brandName: string }) {
  return (
    <div className="wg-section">
      <div className="section-heading">The {brandName} Experience</div>
      <div className="wg-grid">
        {[
          [
            "A designer, not a salesperson",
            "Your project is designed around your home and how you live in it — never a template. We walk the property, listen, and compose the plan by hand.",
          ],
          [
            "We treat your home like ours",
            "Shoe covers indoors, drop cloths where they matter, and your property left exactly as we found it — every footprint gone before we pull away.",
          ],
          [
            "Craftsmanship you can see",
            "Premium materials, clean lines, and meticulous install work. The details you notice up close are the ones we obsess over.",
          ],
          [
            "The reveal walkthrough",
            "We don\u2019t call it finished until you\u2019ve seen it and love it. Your first look is a guided walkthrough with the person who designed it.",
          ],
          [
            "One call, handled",
            "A question, a tweak, something that needs attention — you reach us directly. No ticket queues, no call centers.",
          ],
          [
            "Here for the long run",
            "A growing local company that stands behind every project it delivers — this year and years from now.",
          ],
        ].map(([title, desc]) => (
          <div className="wg-item" key={title}>
            <div className="wg-item-title">{title}</div>
            <div className="wg-item-desc">{desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Satisfaction guarantee on the finished installation. */
export function StandardGuarantee() {
  return (
    <div className="guarantee-section">
      <div className="guarantee-badge">
        <div className="guarantee-badge-star">&#9733;</div>
        <div className="guarantee-badge-text">
          Satisfaction
          <br />
          Guaranteed
        </div>
      </div>
      <div className="guarantee-content">
        <div className="guarantee-title">
          <em>Satisfaction</em>{" "}Guaranteed
        </div>
        <div className="guarantee-body">
          We don&rsquo;t consider the job done until you&rsquo;re completely
          happy with your project. If anything isn&rsquo;t right after
          installation,{" "}
          <strong>
            we come back and make it right &#8212; no questions asked.
          </strong>{" "}
          Your home deserves to look exactly the way you imagined it.
        </div>
      </div>
    </div>
  );
}

/** What every project covers. */
export function StandardIncluded() {
  return (
    <div className="included-section">
      <div className="section-heading">Every Project Includes</div>
      <div className="included-grid">
        {[
          "Custom design tailored to your property",
          "Professional installation by our own crew",
          "Premium, commercial-grade materials",
          "Meticulous cleanup — left better than we found it",
          "1-year workmanship warranty on all work",
          "A completion walkthrough before we call it done",
        ].map((item) => (
          <div className="included-item" key={item}>
            <span className="included-check">&#9670;</span> {item}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Choose, install, maintain. */
export function StandardSteps() {
  return (
    <div className="steps-section">
      <div className="section-heading">How It Works</div>
      <div className="steps-grid">
        <div className="step-card">
          <div className="step-num" aria-hidden="true">I</div>
          <div className="step-title">You Choose</div>
          <div className="step-desc">
            Pick the option that fits your vision and your home.
          </div>
        </div>
        <div className="step-card">
          <div className="step-num" aria-hidden="true">II</div>
          <div className="step-title">We Install</div>
          <div className="step-desc">
            Our team handles everything — expertly, cleanly, and on schedule.
          </div>
        </div>
        <div className="step-card">
          <div className="step-num" aria-hidden="true">III</div>
          <div className="step-title">We Maintain</div>
          <div className="step-desc">
            Our Care Plan keeps your display looking its best, so you can enjoy
            it every night.
          </div>
        </div>
      </div>
    </div>
  );
}

/** Closing argument. */
export function StandardTrust({ brandName }: { brandName: string }) {
  return (
    <div className="trust-section">
      <div className="trust-heading">Why {brandName}</div>
      <div className="trust-body">
        We&rsquo;ve designed and installed projects across hundreds of homes in
        this area. Our team aren&rsquo;t salespeople &#8212; they&rsquo;re{" "}
        <strong>designers and craftspeople</strong>. When we walk your property,
        we&rsquo;re thinking about proportion, detail, and the story your home
        tells.{" "}
        <strong>The result is the artwork.</strong>
      </div>
    </div>
  );
}
