import { ArrowRight, Phone } from "lucide-react";
import type { Metadata } from "next";
import Image from "next/image";

import { ConsultForm } from "@/components/landscape-landing/consult-form";
import { ProjectGallery } from "@/components/landscape-landing/project-gallery";

// Business facts shown to homeowners. Edit here, not inline: everything on this
// page that names the company, its phone, or its service area reads from this.
const BUSINESS = {
  name: "Maxteriors",
  phone: "(248) 877-4672",
  phoneHref: "tel:+12488774672",
  serviceArea: "Southeast Michigan",
} as const;

/**
 * Lead source public key from the CRM (Settings, Lead Sources). The lead
 * source's allowed domains must include this page's origin or the backend
 * rejects the submission. Unset, the page offers a phone call instead of a
 * form, so a homeowner is never handed a submit button that drops their info.
 */
const LEAD_FORM_KEY = process.env.NEXT_PUBLIC_LANDSCAPE_LEAD_FORM_KEY?.trim();

export const metadata: Metadata = {
  title: `Landscape Lighting Specialists | ${BUSINESS.name}`,
  description: `Custom landscape lighting design and installation in ${BUSINESS.serviceArea}. Lighting is all we do, and every design is drawn on your property after dark.`,
  // The CRM is noindex sitewide (app/layout.tsx). This marketing page is the
  // deliberate exception, so it overrides that here. The matching HTTP
  // `X-Robots-Tag` exception lives in next.config.ts and is what actually
  // decides indexing; both must agree or the header wins.
  robots: { index: true, follow: true },
};

const APPLICATIONS = [
  { title: "Paths and walkways", detail: "Safe footing from the driveway to the door" },
  { title: "Trees and uplighting", detail: "Depth and height once the sun drops" },
  { title: "Architecture and stone", detail: "Grazing light that shows off texture" },
  { title: "Patios and outdoor living", detail: "Usable evenings, not floodlit ones" },
];

const REASONS = [
  {
    // Honest social proof: this describes what the reader already sees on their
    // own street. Deliberately no invented count of "homes on your block" —
    // a number nobody can verify is the fastest way to lose a skeptical buyer.
    title: "You have already noticed it on your street",
    body: "One house on the block is lit and the rest go flat at dusk. You notice that house every time you drive past it, and so does everyone else on the street. Your neighbors have it. There is no reason your home should be the dark one.",
  },
  {
    title: "Lighting is all we do",
    body: `${BUSINESS.name} is a lighting specialist. Not a landscaper who also sells fixtures, not an electrician fitting it between service calls. Exterior lighting is the entire business, so it gets the whole of our attention.`,
  },
  {
    title: "Designed where it matters, on your property",
    body: "A design drawn at a desk is a guess. We design on site and after dark, standing in your yard, looking at the house from the street and from your own windows, because that is the only place the decisions are real.",
  },
  {
    title: "Your property is the canvas",
    body: "Every install is a canvas and every fixture is a brush stroke. Count, placement, beam spread, and aim are chosen for your trees, your elevations, and your beds, instead of a tiered package that treats every house the same.",
  },
  {
    title: "Fixtures you do not see, light you do",
    body: "Hardware sits low, tucked into beds and bases, with runs buried and glare aimed away from windows and the sidewalk. From the curb you notice the house, not the equipment lighting it.",
  },
  {
    title: "Built for Michigan ground",
    body: "Freeze, thaw, mowers, snow blowers, and mulch turnover all get considered before a single fixture goes in the ground. Materials and wiring are chosen for that reality, not for a showroom floor.",
  },
  {
    title: "One consultation tells you where you stand",
    body: "You get a custom design for the property, an honest scope, and the numbers to go with it. No pressure and no obligation. What happens next is your call.",
  },
];

const INCLUDED = [
  { title: "Custom on-site design", detail: "Drawn on your property after dark, around your beds, trees, and elevations" },
  { title: "Professional installation", detail: "Buried runs, hidden hardware, tidy beds when we leave" },
  { title: "Aiming and night walkthrough", detail: "We set the final aim after dark, with you" },
  { title: "Scheduling and timers", detail: "Set to your evenings and adjusted through the seasons" },
];

const FAQS = [
  {
    q: "How much does landscape lighting cost?",
    a: "Most projects land between $5,000 and $15,000, and more elaborate designs are a bigger investment. Where yours falls depends on the property: how many trees, how much frontage, how far the runs have to reach. That is exactly what the design consultation answers. You get a custom scope and a price for your yard, with no obligation to move forward.",
  },
  {
    q: "How long does installation take?",
    a: "Most residential installations are finished in one to two days depending on the size of the property and the length of the wire runs. You do not need to be home for the install, only for the walkthrough.",
  },
  {
    q: "Will it tear up my yard?",
    a: "Wire is trenched shallow along bed lines and edges, and beds are put back the way we found them. In most yards you cannot tell where the runs went once the work is done.",
  },
  {
    q: "Can I control it myself?",
    a: "Yes. We set the schedule with you at the walkthrough so the lights come on and off when you want them, and we show you how to adjust it as the seasons change.",
  },
  {
    q: "Do you service the system later?",
    a: "We do. Aiming drifts as plantings grow and bulbs eventually age out, so we come back to re-aim, adjust, and repair. Ask about coverage and service options at your consultation.",
  },
];

export default function LandscapeLightingLandingPage() {
  return (
    <main className="min-h-screen bg-black text-zinc-200">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-5 py-5">
        {/* `priority`: the logo is the topmost element, so lazy-loading it would
            leave the header visibly empty on first paint. */}
        <Image
          src="/landscape-lighting/maxteriors-logo.png"
          alt={`${BUSINESS.name}: landscape, permanent, holiday, and event lighting`}
          width={900}
          height={214}
          priority
          className="h-9 w-auto sm:h-11"
        />
        <a
          href={BUSINESS.phoneHref}
          className="inline-flex items-center gap-2 text-sm font-medium text-zinc-300 transition-colors duration-150 hover:text-brand-gold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
        >
          <Phone className="size-4" aria-hidden="true" />
          {BUSINESS.phone}
        </a>
      </header>

      {/* Hero. The wash behind it is the one decorative device on the page: warm
          pools rising from the bottom edge, the way uplights actually land. */}
      <section className="relative overflow-hidden border-b border-white/10">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 h-[420px]"
          style={{
            background:
              "radial-gradient(28rem 20rem at 18% 100%, rgba(251,181,5,0.16), transparent 70%), radial-gradient(24rem 18rem at 52% 100%, rgba(251,181,5,0.12), transparent 70%), radial-gradient(30rem 22rem at 86% 100%, rgba(251,181,5,0.14), transparent 70%)",
          }}
        />
        <div className="relative mx-auto w-full max-w-5xl px-5 pb-16 pt-10 sm:pt-16">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-gold/90">
            {BUSINESS.serviceArea} landscape lighting specialists
          </p>
          <h1 className="mt-4 max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-white sm:text-5xl lg:text-6xl">
            Your home does not have to disappear at sunset
          </h1>
          <p className="mt-5 max-w-xl text-lg text-zinc-300">
            Lighting is all we do. We design it on your property, after dark, where the decisions
            are real, then build it custom to your yard.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            <a
              href="#design-visit"
              className="inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-brand-gold px-6 font-semibold text-zinc-950 transition-colors duration-150 hover:bg-brand-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
            >
              Book your design consultation
              <ArrowRight className="size-4" aria-hidden="true" />
            </a>
            <p className="text-sm text-zinc-400">
              {BUSINESS.serviceArea}&rsquo;s number one choice for landscape lighting.
            </p>
          </div>

          <ul className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-2 lg:grid-cols-4">
            {APPLICATIONS.map((item) => (
              <li key={item.title} className="bg-[#0a0a0a] px-5 py-4">
                <p className="font-medium text-white">{item.title}</p>
                <p className="mt-1 text-sm text-zinc-400">{item.detail}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Photos sit directly under the hero: a homeowner judges lighting with
       their eyes first, so the proof lands before any argument for it.
       Renders only when real install photos exist; see project-gallery.tsx. */}
      <ProjectGallery />

      <section className="mx-auto w-full max-w-5xl px-5 py-16" aria-labelledby="why-heading">
        <h2 id="why-heading" className="max-w-2xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          What you are actually buying
        </h2>
        <ol className="mt-10 space-y-px overflow-hidden rounded-xl border border-white/10 bg-white/10">
          {REASONS.map((reason, index) => (
            <li key={reason.title} className="flex gap-5 bg-[#0a0a0a] px-5 py-6 sm:px-8 sm:py-8">
              <span className="font-mono text-sm text-brand-gold/80" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="max-w-2xl">
                <h3 className="text-xl font-semibold text-white">{reason.title}</h3>
                <p className="mt-2 text-zinc-300">{reason.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section
        id="design-visit"
        className="scroll-mt-4 border-y border-white/10 bg-[#050505]"
        aria-labelledby="visit-heading"
      >
        <div className="mx-auto grid w-full max-w-5xl gap-10 px-5 py-16 lg:grid-cols-2 lg:gap-16">
          <div>
            <h2 id="visit-heading" className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              Book your design consultation
            </h2>
            <p className="mt-4 text-zinc-300">
              Three quick questions, then we text you to lock in a time. Here is what comes with the work if
              you decide to move forward.
            </p>
            <ul className="mt-8 space-y-5">
              {INCLUDED.map((item) => (
                <li key={item.title} className="border-l-2 border-brand-gold/60 pl-4">
                  <p className="font-medium text-white">{item.title}</p>
                  <p className="mt-1 text-sm text-zinc-400">{item.detail}</p>
                </li>
              ))}
            </ul>
          </div>

          {LEAD_FORM_KEY ? (
            <ConsultForm
              publicKey={LEAD_FORM_KEY}
              businessPhone={BUSINESS.phone}
              businessPhoneHref={BUSINESS.phoneHref}
            />
          ) : (
            // No lead source configured: send the homeowner to the phone rather
            // than collect details this page cannot deliver anywhere.
            <div className="rounded-2xl border border-white/12 bg-white/[0.04] p-6 sm:p-8">
              <h3 className="text-2xl font-semibold text-white">Call to book your consultation</h3>
              <p className="mt-2 text-zinc-300">
                Reach {BUSINESS.name} directly and we will find a time that works for your property.
              </p>
              <a
                href={BUSINESS.phoneHref}
                className="mt-6 inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-brand-gold px-6 font-semibold text-zinc-950 transition-colors duration-150 hover:bg-brand-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
              >
                <Phone className="size-4" aria-hidden="true" />
                Call {BUSINESS.phone}
              </a>
            </div>
          )}
        </div>
      </section>

      <section className="mx-auto w-full max-w-5xl px-5 py-16" aria-labelledby="faq-heading">
        <h2 id="faq-heading" className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          Questions homeowners ask first
        </h2>
        <div className="mt-10 overflow-hidden rounded-xl border border-white/10 bg-white/10">
          {FAQS.map((faq) => (
            // Native disclosure: keyboard operable and open to find-in-page
            // without shipping a byte of JavaScript for it.
            <details key={faq.q} className="group bg-[#0a0a0a] not-last:border-b not-last:border-white/10">
              <summary className="cursor-pointer list-none px-5 py-5 font-medium text-white transition-colors duration-150 hover:text-brand-gold focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brand-gold sm:px-8">
                <span className="flex items-start justify-between gap-4">
                  {faq.q}
                  <span
                    className="mt-1 text-brand-gold transition-transform duration-150 group-open:rotate-45"
                    aria-hidden="true"
                  >
                    +
                  </span>
                </span>
              </summary>
              <p className="max-w-2xl px-5 pb-6 text-zinc-300 sm:px-8">{faq.a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="border-t border-white/10">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-5 py-8 text-sm text-zinc-400 sm:flex-row sm:items-center sm:justify-between">
          <p>
            {BUSINESS.name}, serving {BUSINESS.serviceArea}
          </p>
          <a
            href={BUSINESS.phoneHref}
            className="inline-flex items-center gap-2 transition-colors duration-150 hover:text-brand-gold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
          >
            <Phone className="size-4" aria-hidden="true" />
            {BUSINESS.phone}
          </a>
        </div>
      </footer>
    </main>
  );
}
