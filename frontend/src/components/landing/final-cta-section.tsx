"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Phone, MessageSquare, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { PhoneInput, normalizeToE164 } from "./phone-input";
import { publicDemoApi } from "@/lib/api/public-demo";

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

export function FinalCtaSection() {
  const [phone, setPhone] = useState("");

  const callMutation = useMutation({
    mutationFn: (phoneNumber: string) => publicDemoApi.triggerCall(phoneNumber),
  });

  const textMutation = useMutation({
    mutationFn: (phoneNumber: string) => publicDemoApi.triggerText(phoneNumber),
  });

  const handleCall = () => {
    const normalized = normalizeToE164(phone);
    if (normalized.length >= 12) {
      callMutation.mutate(normalized);
    }
  };

  const handleText = () => {
    const normalized = normalizeToE164(phone);
    if (normalized.length >= 12) {
      textMutation.mutate(normalized);
    }
  };

  const isPhoneValid = normalizeToE164(phone).length >= 12;
  const isPending = callMutation.isPending || textMutation.isPending;
  const isSuccess = callMutation.isSuccess || textMutation.isSuccess;
  const successMessage = callMutation.data?.message || textMutation.data?.message;
  const error = callMutation.error || textMutation.error;
  const isError = callMutation.isError || textMutation.isError;

  return (
    <section
      className="py-24 px-4 bg-[#0f0d15] relative overflow-hidden"
      aria-labelledby="cta-heading"
    >
      {/* Radial gradient emanating from center for depth */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse 80% 50% at 50% 50%, rgba(88, 28, 135, 0.15) 0%, transparent 70%)',
        }}
      />

      {/* Secondary subtle radial highlight */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(circle at 50% 30%, rgba(139, 92, 246, 0.08) 0%, transparent 50%)',
        }}
      />

      {/* Subtle gradient accent */}
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-purple-900/30 rounded-full blur-3xl pointer-events-none" />

      <motion.div
        className="max-w-3xl mx-auto text-center relative z-10"
        variants={containerVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true }}
      >
        <motion.div className="mb-10" variants={itemVariants}>
          <h2
            id="cta-heading"
            className="text-4xl md:text-5xl font-bold tracking-tight text-white mb-4 font-[family-name:var(--font-serif)]"
          >
            Ready to see what you&apos;re missing?
          </h2>
          <p className="text-xl text-gray-300 mb-2">
            Get a live demo. Our AI will call you in under 60 seconds.
          </p>
          <p className="text-gray-400">
            No credit card. No commitment. Just proof.
          </p>
        </motion.div>

        <motion.div variants={itemVariants}>
          <div className="max-w-md mx-auto p-6 rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm">
            <div aria-live="polite" role="status">
              {isSuccess && (
                <div className="py-6 space-y-3">
                  <CheckCircle2 className="size-12 text-green-400 mx-auto" aria-hidden="true" />
                  <p className="text-white font-medium text-lg">
                    {successMessage}
                  </p>
                </div>
              )}
            </div>

            {!isSuccess && (
              <div className="space-y-4">
                <div>
                  <label htmlFor="cta-phone-input" className="sr-only">
                    Phone number
                  </label>
                  <PhoneInput
                    id="cta-phone-input"
                    value={phone}
                    onChange={setPhone}
                    disabled={isPending}
                    aria-describedby={isError ? "cta-phone-error" : undefined}
                    aria-invalid={isError}
                    className="h-14 text-lg text-brand-ink bg-white"
                  />
                </div>

                {isError && (
                  <Alert id="cta-phone-error" variant="destructive" role="alert" className="bg-red-900/50 border-red-800 text-red-200">
                    <AlertCircle className="size-4" aria-hidden="true" />
                    <AlertDescription>
                      {(error as Error)?.message ||
                        "Something went wrong. Please try again."}
                    </AlertDescription>
                  </Alert>
                )}

                <div className="flex flex-col sm:flex-row gap-3">
                  <Button
                    type="button"
                    size="lg"
                    className="flex-1 h-12 bg-white hover:bg-gray-100 text-brand-ink font-semibold"
                    disabled={!isPhoneValid || isPending}
                    onClick={handleCall}
                  >
                    {callMutation.isPending ? (
                      <>
                        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                        <span>Calling...</span>
                      </>
                    ) : (
                      <>
                        <Phone className="size-4" aria-hidden="true" />
                        Call Me Now
                      </>
                    )}
                  </Button>

                  <Button
                    type="button"
                    size="lg"
                    className="flex-1 h-12 bg-transparent hover:bg-white/10 text-white font-semibold border border-white/30"
                    disabled={!isPhoneValid || isPending}
                    onClick={handleText}
                  >
                    {textMutation.isPending ? (
                      <>
                        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                        <span>Sending...</span>
                      </>
                    ) : (
                      <>
                        <MessageSquare className="size-4" aria-hidden="true" />
                        Text Me Instead
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </section>
  );
}
