"use client";

import { Database, AlertTriangle, TrendingDown } from "lucide-react";
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

const stats = [
  {
    value: "67%",
    label: "of leads never get a second follow-up",
    icon: AlertTriangle,
  },
  {
    value: "$1.2M",
    label: "average revenue hiding in a 10K contact database",
    icon: Database,
  },
  {
    value: "23x",
    label: "cheaper to reactivate than acquire new",
    icon: TrendingDown,
  },
];

export function StatsSection() {
  return (
    <section className="py-20 px-4" aria-label="Key statistics">
      <motion.div
        className="max-w-6xl mx-auto"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div
          className="grid md:grid-cols-3 gap-8"
          variants={containerVariants}
          role="list"
          aria-label="Statistics"
        >
          {stats.map((stat) => (
            <motion.div
              key={stat.value}
              className="text-center p-8 bg-brand-bg rounded-3xl transition-all duration-300 hover:shadow-xl hover:shadow-black/5 hover:-translate-y-1 hover:bg-brand-bg-2"
              variants={itemVariants}
              role="listitem"
            >
              <stat.icon className="size-7 text-brand-mute mx-auto mb-5" aria-hidden="true" />
              <div className="text-4xl md:text-5xl font-bold text-brand-ink mb-3 font-[family-name:var(--font-serif)]">
                {stat.value}
              </div>
              <p className="text-brand-body">{stat.label}</p>
            </motion.div>
          ))}
        </motion.div>
      </motion.div>
    </section>
  );
}
