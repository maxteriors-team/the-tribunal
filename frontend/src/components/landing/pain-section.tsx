"use client";

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
      duration: 0.6,
      ease: "easeOut" as const,
    },
  },
} as const;

export function PainSection() {
  return (
    <section className="py-32 md:py-40 px-4 bg-[#0a0a0a] relative overflow-hidden">
      {/* Subtle gradient accents */}
      <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-yellow-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-amber-500/10 rounded-full blur-3xl pointer-events-none" />

      {/* Subtle animated gradient orbs */}
      <motion.div
        className="absolute top-1/4 left-1/4 w-[300px] h-[300px] bg-yellow-400/5 rounded-full blur-3xl pointer-events-none"
        animate={{
          scale: [1, 1.2, 1],
          opacity: [0.05, 0.08, 0.05],
        }}
        transition={{
          duration: 8,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      />
      <motion.div
        className="absolute bottom-1/3 right-1/4 w-[250px] h-[250px] bg-amber-400/5 rounded-full blur-3xl pointer-events-none"
        animate={{
          scale: [1, 1.15, 1],
          opacity: [0.05, 0.1, 0.05],
        }}
        transition={{
          duration: 10,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 2,
        }}
      />
      <motion.div
        className="absolute top-1/2 right-1/3 w-[200px] h-[200px] bg-yellow-500/5 rounded-full blur-3xl pointer-events-none"
        animate={{
          scale: [1, 1.1, 1],
          opacity: [0.03, 0.06, 0.03],
        }}
        transition={{
          duration: 12,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 4,
        }}
      />

      {/* Starfield-like subtle dots */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.15]"
        style={{
          backgroundImage: `radial-gradient(1px 1px at 20px 30px, rgba(255,255,255,0.3) 0%, transparent 50%),
                           radial-gradient(1px 1px at 40px 70px, rgba(255,255,255,0.2) 0%, transparent 50%),
                           radial-gradient(1px 1px at 90px 40px, rgba(255,255,255,0.25) 0%, transparent 50%),
                           radial-gradient(1px 1px at 130px 80px, rgba(255,255,255,0.2) 0%, transparent 50%),
                           radial-gradient(1px 1px at 160px 30px, rgba(255,255,255,0.15) 0%, transparent 50%)`,
          backgroundSize: '200px 100px',
        }}
      />

      <motion.div
        className="max-w-5xl mx-auto relative z-10"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div className="text-center" variants={itemVariants}>
          <p className="text-sm font-medium text-brand-mute tracking-widest uppercase mb-8">
            The Problem
          </p>
          <h2 className="text-4xl md:text-6xl lg:text-7xl font-bold tracking-tight text-white leading-[1.1] font-[family-name:var(--font-serif)] mb-10">
            Your database is a gold mine. You&apos;re just not mining it.
          </h2>
          <p className="text-xl md:text-2xl text-gray-400 max-w-3xl mx-auto leading-relaxed">
            Right now, thousands of leads sit in your CRM collecting dust. Old inquiries.
            Past customers. People who said &quot;not right now.&quot; That&apos;s not dead data.
            That&apos;s dormant revenue.
          </p>
        </motion.div>
      </motion.div>
    </section>
  );
}
