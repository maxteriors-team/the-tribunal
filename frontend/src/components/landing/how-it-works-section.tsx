"use client";

import { Upload, Sparkles, Calendar } from "lucide-react";
import { motion } from "motion/react";

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

const steps = [
  {
    icon: Upload,
    title: "Upload your contacts",
    description: "CSV, CRM sync, or manual. We take whatever you've got.",
    step: 1,
  },
  {
    icon: Sparkles,
    title: "AI does the work",
    description: "Personalized calls and texts. Handles objections. Books meetings.",
    step: 2,
  },
  {
    icon: Calendar,
    title: "You close deals",
    description: "Show up to qualified appointments. That's your only job.",
    step: 3,
  },
];

export function HowItWorksSection() {
  return (
    <section className="py-28 md:py-36 px-4" aria-labelledby="how-it-works-heading">
      <motion.div
        className="max-w-6xl mx-auto"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div className="text-center max-w-3xl mx-auto mb-20" variants={itemVariants}>
          <p className="text-sm font-medium text-brand-mute tracking-widest uppercase mb-6">
            How It Works
          </p>
          <h2
            id="how-it-works-heading"
            className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-brand-ink font-[family-name:var(--font-serif)]"
          >
            3 steps. That&apos;s it.
          </h2>
        </motion.div>

        <motion.ol
          className="grid md:grid-cols-3 gap-10"
          variants={containerVariants}
          aria-label="Three steps to get started"
        >
          {steps.map((step) => (
            <motion.li
              key={step.step}
              className="text-center relative"
              variants={itemVariants}
            >
              <div className="bg-brand-bg rounded-3xl p-10 h-full transition-all duration-300 hover:shadow-xl hover:shadow-black/5 hover:-translate-y-1 hover:bg-brand-bg-2">
                <div
                  className="absolute -top-5 left-1/2 -translate-x-1/2 size-10 bg-brand-ink text-white rounded-full flex items-center justify-center font-bold text-sm"
                  aria-hidden="true"
                >
                  {step.step}
                </div>
                <div className="pt-2">
                  <div
                    className="size-20 bg-brand-line rounded-2xl flex items-center justify-center mx-auto mb-8"
                    aria-hidden="true"
                  >
                    <step.icon className="size-10 text-brand-mute-2" />
                  </div>
                  <h3 className="text-xl md:text-2xl font-bold text-brand-ink mb-3 font-[family-name:var(--font-serif)]">
                    <span className="sr-only">Step {step.step}: </span>
                    {step.title}
                  </h3>
                  <p className="text-brand-body text-lg">{step.description}</p>
                </div>
              </div>
            </motion.li>
          ))}
        </motion.ol>
      </motion.div>
    </section>
  );
}
