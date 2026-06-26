"use client";

import { Home, Shield, Wrench, Sun, Car, Heart } from "lucide-react";
import { motion } from "motion/react";

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
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

const industries = [
  {
    icon: Home,
    title: "Real Estate",
    description: "Reactivate past buyers and expired listings",
  },
  {
    icon: Shield,
    title: "Insurance",
    description: "Policy renewals and cross-sell campaigns",
  },
  {
    icon: Wrench,
    title: "Home Services",
    description: "Past customers ready for repeat business",
  },
  {
    icon: Sun,
    title: "Solar/HVAC",
    description: "Old quotes and unconverted estimates",
  },
  {
    icon: Car,
    title: "Auto Dealers",
    description: "Service reminders and trade-in outreach",
  },
  {
    icon: Heart,
    title: "Med Spas",
    description: "Lapsed clients and treatment follow-ups",
  },
];

export function UseCasesSection() {
  return (
    <section className="py-28 md:py-36 px-4" aria-labelledby="use-cases-heading">
      <motion.div
        className="max-w-6xl mx-auto"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div className="text-center max-w-4xl mx-auto mb-20" variants={itemVariants}>
          <p className="text-sm font-medium text-brand-mute tracking-widest uppercase mb-6">
            Who It&apos;s For
          </p>
          <h2
            id="use-cases-heading"
            className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-brand-ink font-[family-name:var(--font-serif)] leading-[1.1]"
          >
            If you have a database, you have untapped revenue.
          </h2>
        </motion.div>

        <motion.div
          className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6"
          variants={containerVariants}
          role="list"
          aria-label="Industries we serve"
        >
          {industries.map((industry) => (
            <motion.article
              key={industry.title}
              variants={itemVariants}
              role="listitem"
              className="bg-brand-bg rounded-3xl p-8 transition-all duration-300 hover:shadow-xl hover:shadow-black/5 hover:-translate-y-1 hover:bg-brand-bg-2"
            >
              <div className="flex items-start gap-5">
                <div
                  className="size-14 bg-brand-line rounded-2xl flex items-center justify-center shrink-0"
                  aria-hidden="true"
                >
                  <industry.icon className="size-7 text-brand-mute-2" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-brand-ink mb-2 font-[family-name:var(--font-serif)]">
                    {industry.title}
                  </h3>
                  <p className="text-brand-body">{industry.description}</p>
                </div>
              </div>
            </motion.article>
          ))}
        </motion.div>
      </motion.div>
    </section>
  );
}
