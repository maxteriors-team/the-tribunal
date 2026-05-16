"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  Phone,
  MessageSquare,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

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

export function HeroSection() {
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
    <div className="min-h-screen flex items-center justify-center px-4 py-16 relative overflow-hidden">

      <motion.div
        className="max-w-6xl w-full grid lg:grid-cols-2 gap-12 lg:gap-20 items-center relative z-10"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {/* Left side - Headline */}
        <motion.div className="space-y-6" variants={itemVariants}>
          <p className="text-sm font-medium text-brand-mute tracking-widest uppercase">
            AI Voice Agent
          </p>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-brand-ink leading-[1.1] font-[family-name:var(--font-serif)]">
            Voice AI built for every customer conversation
          </h1>
          <p className="text-lg text-brand-body max-w-md">
            Let our AI handle calls and texts so you can focus on closing deals.
          </p>
        </motion.div>

        {/* Right side - Form */}
        <motion.div variants={itemVariants} className="relative">
          {/* Decorative abstract shape behind form */}
          <div className="absolute -top-6 -right-6 w-32 h-32 bg-gradient-to-br from-purple-300/30 to-pink-200/20 rounded-full blur-2xl pointer-events-none" />
          <div className="absolute -bottom-4 -left-4 w-24 h-24 bg-gradient-to-tr from-indigo-200/30 to-purple-200/20 rounded-full blur-xl pointer-events-none" />
          <div className="bg-brand-bg p-8 rounded-2xl relative border border-purple-200/30">
            <div className="space-y-3 mb-8">
              <h2 className="text-3xl md:text-4xl font-bold text-brand-ink font-[family-name:var(--font-serif)]">
                Don&apos;t believe us?
              </h2>
              <p className="text-xl md:text-2xl text-brand-body">
                Have our AI give you a call.
              </p>
            </div>

              <div aria-live="polite" role="status">
                {isSuccess && (
                  <div className="py-6 space-y-3">
                    <CheckCircle2 className="size-12 text-green-500" aria-hidden="true" />
                    <p className="text-green-600 font-medium text-lg">
                      {successMessage}
                    </p>
                  </div>
                )}
              </div>

              {!isSuccess && (
                <div className="space-y-4">
                  <div>
                    <PhoneInput
                      id="phone-input"
                      value={phone}
                      onChange={setPhone}
                      disabled={isPending}
                      aria-describedby={isError ? "phone-error" : undefined}
                      aria-invalid={isError}
                      className="h-14 text-lg text-brand-ink bg-white"
                    />
                  </div>

                  {isError && (
                    <Alert id="phone-error" variant="destructive" role="alert">
                      <AlertCircle className="size-4" aria-hidden="true" />
                      <AlertDescription>
                        {(error as Error)?.message ||
                          "Something went wrong. Please try again."}
                      </AlertDescription>
                    </Alert>
                  )}

                  <Button
                    type="button"
                    size="lg"
                    className="w-full h-12 bg-brand-ink hover:bg-brand-ink-hover text-white font-semibold"
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
                        Let&apos;s Talk
                      </>
                    )}
                  </Button>

                  <Button
                    type="button"
                    size="lg"
                    className="w-full h-12 bg-white hover:bg-gray-50 text-brand-ink font-semibold border border-brand-line"
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
                        I&apos;d rather text
                      </>
                    )}
                  </Button>
                </div>
              )}
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
