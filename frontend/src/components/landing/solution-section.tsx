"use client";

import { motion } from "motion/react";
import { Database, Phone, CheckCircle2 } from "lucide-react";

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.15,
    },
  },
} as const;

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.5,
      ease: "easeOut" as const,
    },
  },
} as const;

const primaryFeatures = [
  "Works while you sleep",
  "Personalized to each contact's history",
  "Books directly to your calendar",
];

const secondaryFeatures = [
  "Answers in under 1 second",
  "Sounds human, not robotic",
  "Instant lead qualification",
];

export function SolutionSection() {
  return (
    <section className="py-28 md:py-36 px-4 relative overflow-hidden">

      <motion.div
        className="max-w-6xl mx-auto relative z-10"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div className="text-center max-w-4xl mx-auto mb-20" variants={itemVariants}>
          <p className="text-sm font-medium text-brand-mute tracking-widest uppercase mb-6">
            The Solution
          </p>
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-brand-ink font-[family-name:var(--font-serif)] leading-[1.1]">
            Turn old leads into new revenue. Automatically.
          </h2>
        </motion.div>

        <div className="grid lg:grid-cols-3 gap-6 lg:gap-8" role="list" aria-label="Solution features">
          {/* Primary Card - 2/3 width */}
          <motion.article
            className="lg:col-span-2 bg-gradient-to-br from-brand-bg via-[#f0ebf5] to-[#ebe4f2] rounded-3xl p-10 lg:p-12 relative overflow-hidden min-h-[400px] lg:min-h-[480px]"
            variants={itemVariants}
            role="listitem"
          >
            {/* Subtle gradient overlay */}
            <div className="absolute top-0 right-0 w-1/2 h-full bg-gradient-to-l from-[#e5dff0]/40 to-transparent pointer-events-none" />
            {/* Decorative circle */}
            <div className="absolute -bottom-20 -right-20 w-64 h-64 bg-brand-mute-2/5 rounded-full blur-2xl pointer-events-none" />

            <div className="relative z-10">
              <div className="mb-8">
                <span className="inline-block px-4 py-1.5 bg-brand-mute-2 text-white text-xs font-medium rounded-full mb-5">
                  Primary Use Case
                </span>
                <div className="flex items-center gap-4">
                  <div className="size-14 lg:size-16 bg-brand-line rounded-2xl flex items-center justify-center shadow-sm" aria-hidden="true">
                    <Database className="size-7 lg:size-8 text-brand-mute-2" />
                  </div>
                  <h3 className="text-2xl md:text-3xl lg:text-4xl font-bold text-brand-ink font-[family-name:var(--font-serif)]">
                    AI Database Reactivation
                  </h3>
                </div>
              </div>
              <p className="text-brand-body text-lg lg:text-xl mb-8 lg:mb-10 leading-relaxed max-w-2xl">
                Upload your contacts. Our AI calls and texts them with personalized outreach.
                It handles objections, books appointments, and resurfaces buyers you forgot you had.
              </p>
              <ul className="space-y-4 lg:space-y-5" aria-label="Features of AI Database Reactivation">
                {primaryFeatures.map((feature) => (
                  <li key={feature} className="flex items-center gap-3 text-brand-ink text-base lg:text-lg">
                    <CheckCircle2 className="size-5 lg:size-6 text-brand-mute-2 shrink-0" aria-hidden="true" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </div>
          </motion.article>

          {/* Secondary Card - 1/3 width, stacked vertically */}
          <motion.article
            className="lg:col-span-1 bg-brand-bg rounded-3xl p-10 flex flex-col min-h-[400px] lg:min-h-[480px]"
            variants={itemVariants}
            role="listitem"
          >
            <div className="mb-8">
              <span className="inline-block px-4 py-1.5 bg-brand-line text-brand-body text-xs font-medium rounded-full mb-5">
                Also Included
              </span>
              <div className="flex items-center gap-4">
                <div className="size-14 bg-brand-line rounded-2xl flex items-center justify-center" aria-hidden="true">
                  <Phone className="size-7 text-brand-mute-2" />
                </div>
                <h3 className="text-2xl md:text-3xl font-bold text-brand-ink font-[family-name:var(--font-serif)]">
                  AI Voice Agents
                </h3>
              </div>
            </div>
            <p className="text-brand-body text-lg mb-8 leading-relaxed flex-grow">
              Never miss another call. AI answers 24/7, qualifies leads, and transfers
              hot prospects to your team in real-time.
            </p>
            <ul className="space-y-4 mt-auto" aria-label="Features of AI Voice Agents">
              {secondaryFeatures.map((feature) => (
                <li key={feature} className="flex items-center gap-3 text-brand-ink">
                  <CheckCircle2 className="size-5 text-brand-mute shrink-0" aria-hidden="true" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
          </motion.article>
        </div>
      </motion.div>
    </section>
  );
}
