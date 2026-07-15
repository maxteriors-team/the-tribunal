"use client";

import { TrendingUp, BarChart3, Clock, DollarSign } from "lucide-react";
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

const metrics = [
  {
    value: "47%",
    label: "average response rate from dormant leads",
    icon: TrendingUp,
  },
  {
    value: "12x",
    label: "ROI in the first 90 days",
    icon: BarChart3,
  },
  {
    value: "< 3 days",
    label: "to launch your first campaign",
    icon: Clock,
  },
  {
    value: "$127K",
    label: "average recovered revenue per client",
    icon: DollarSign,
  },
];

export function ResultsSection() {
  return (
    <section className="py-28 md:py-36 px-4" aria-labelledby="results-heading">
      <motion.div
        className="max-w-6xl mx-auto"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div className="text-center max-w-3xl mx-auto mb-20" variants={itemVariants}>
          <p className="text-sm font-medium text-brand-mute tracking-widest uppercase mb-6">
            Results
          </p>
          <h2
            id="results-heading"
            className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-brand-ink font-[family-name:var(--font-serif)]"
          >
            Numbers don&apos;t lie.
          </h2>
        </motion.div>

        <motion.div
          className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8 mb-20"
          variants={containerVariants}
          role="list"
          aria-label="Key metrics"
        >
          {metrics.map((metric) => (
            <motion.div
              key={metric.label}
              variants={itemVariants}
              role="listitem"
              className="text-center p-8 bg-white rounded-3xl transition-all duration-300 hover:shadow-xl hover:shadow-black/5 hover:-translate-y-1 hover:bg-[#f5f5f4]"
            >
              <metric.icon
                className="size-8 text-brand-mute mx-auto mb-5"
                aria-hidden="true"
              />
              <div className="text-4xl md:text-5xl font-bold text-brand-ink mb-3 font-[family-name:var(--font-serif)]">
                {metric.value}
              </div>
              <p className="text-brand-body">{metric.label}</p>
            </motion.div>
          ))}
        </motion.div>

        <motion.figure variants={itemVariants}>
          <blockquote className="max-w-3xl mx-auto text-center">
            <p className="text-2xl md:text-3xl text-brand-ink mb-8 font-[family-name:var(--font-serif)] italic leading-relaxed">
              &quot;We had 8,000 contacts just sitting there. Within 60 days, we booked 340
              appointments and closed $180K in new business.&quot;
            </p>
            <figcaption className="text-brand-body font-medium text-lg">
              &mdash; Home Services Owner
            </figcaption>
          </blockquote>
        </motion.figure>
      </motion.div>
    </section>
  );
}
