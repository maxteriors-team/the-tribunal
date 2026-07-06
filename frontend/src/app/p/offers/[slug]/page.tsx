"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Check,
  Shield,
  Clock,
  Gift,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { useState, use } from "react";

import { LeadMagnetContent } from "@/components/lead-magnets/lead-magnet-content";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Separator } from "@/components/ui/separator";
import { publicOffersApi, OptInRequest } from "@/lib/api/public-offers";
import { queryKeys } from "@/lib/query-keys";
import { formatNumber } from "@/lib/utils/number";

interface PublicOfferPageProps {
  params: Promise<{ slug: string }>;
}

export default function PublicOfferPage({ params }: PublicOfferPageProps) {
  const { slug } = use(params);

  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  // 10DLC/TCR: SMS consent must be a separate, OPTIONAL, unchecked-by-default
  // checkbox. It is never required to submit the form (TCR error 803).
  const [smsConsent, setSmsConsent] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const { data: offer, isPending, error } = useQuery({
    queryKey: queryKeys.publicOffers.bySlug(slug),
    queryFn: () => publicOffersApi.get(slug),
    enabled: !!slug,
    retry: false,
  });

  const optInMutation = useMutation({
    mutationFn: (data: OptInRequest) => publicOffersApi.optIn(slug, data),
    onSuccess: () => {
      setSubmitted(true);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    optInMutation.mutate({
      email: email || undefined,
      phone_number: phone || undefined,
      name: name || undefined,
      sms_consent: smsConsent,
    });
  };

  const isFormValid = () => {
    if (offer?.require_email && !email) return false;
    if (offer?.require_phone && !phone) return false;
    if (offer?.require_name && !name) return false;
    return email || phone || name;
  };

  if (isPending) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background to-muted">
        <PageLoadingState className="min-h-screen" />
      </div>
    );
  }

  if (error || !offer) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background to-muted">
        <PageErrorState
          className="min-h-screen"
          message="This offer may have expired or the link is incorrect."
        />
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-muted p-4">
        <Card className="max-w-md w-full">
          <CardContent className="pt-6 text-center">
            <CheckCircle2 className="size-16 text-success mx-auto mb-4" />
            <h1 className="text-2xl font-bold mb-2">You&apos;re In!</h1>
            <p className="text-muted-foreground mb-4">
              Thank you for signing up. Check your email for next steps.
            </p>
            {offer.lead_magnets.length > 0 && (
              <p className="text-sm text-muted-foreground">
                Your bonuses will be delivered shortly.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-muted">
      <div className="container max-w-4xl py-8 px-4">
        {/* Hero Section */}
        <div className="text-center mb-8">
          {offer.headline && (
            <h1 className="text-3xl md:text-4xl font-bold mb-4 leading-tight">
              {offer.headline}
            </h1>
          )}
          {offer.subheadline && (
            <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto">
              {offer.subheadline}
            </p>
          )}
        </div>

        <div className="grid gap-8 lg:grid-cols-5">
          {/* Left Column - Value Stack & Bonuses */}
          <div className="lg:col-span-3 space-y-6">
            {/* Value Stack */}
            {offer.value_stack_items && offer.value_stack_items.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Here&apos;s Everything You Get</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {offer.value_stack_items.map((item, index) => (
                    <div
                      key={index}
                      className="flex items-start gap-3 p-3 rounded-lg bg-muted/50"
                    >
                      <Check className="size-5 text-success mt-0.5 flex-shrink-0" />
                      <div className="flex-1">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{item.name}</span>
                          {item.value > 0 && (
                            <span className="text-sm text-muted-foreground">
                              ${formatNumber(item.value)} value
                            </span>
                          )}
                        </div>
                        {item.description && (
                          <p className="text-sm text-muted-foreground mt-1">
                            {item.description}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Bonuses (Lead Magnets) */}
            {offer.lead_magnets.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Gift className="size-5 text-primary" />
                    Exclusive Bonuses
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {offer.lead_magnets.map((lm) => (
                    <div
                      key={lm.id}
                      className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/10"
                    >
                      <Gift className="size-5 text-primary mt-0.5 flex-shrink-0" />
                      <div className="flex-1 space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{lm.name}</span>
                          {lm.estimated_value && (
                            <Badge variant="secondary">
                              ${formatNumber(lm.estimated_value)} value
                            </Badge>
                          )}
                        </div>
                        {lm.description && (
                          <p className="text-sm text-muted-foreground">
                            {lm.description}
                          </p>
                        )}
                        <LeadMagnetContent magnet={lm} />
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Guarantee */}
            {offer.guarantee_type && (
              <Card className="border-success/20 bg-success/10">
                <CardContent className="pt-6">
                  <div className="flex items-start gap-4">
                    <div className="p-3 rounded-full bg-success/10">
                      <Shield className="size-6 text-success" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-lg mb-1">
                        {offer.guarantee_days}-Day{" "}
                        {offer.guarantee_type === "money_back"
                          ? "Money-Back"
                          : offer.guarantee_type === "satisfaction"
                          ? "Satisfaction"
                          : "Results"}{" "}
                        Guarantee
                      </h3>
                      {offer.guarantee_text && (
                        <p className="text-muted-foreground">
                          {offer.guarantee_text}
                        </p>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Right Column - Pricing & Form */}
          <div className="lg:col-span-2 space-y-6">
            {/* Pricing Card */}
            <Card className="sticky top-4">
              <CardHeader className="text-center pb-2">
                {offer.total_value && (
                  <p className="text-sm text-muted-foreground mb-1">
                    Total Value: ${formatNumber(offer.total_value)}
                  </p>
                )}
                {offer.regular_price && offer.offer_price && (
                  <div className="flex items-center justify-center gap-3 mb-2">
                    <span className="text-2xl text-muted-foreground line-through">
                      ${formatNumber(offer.regular_price)}
                    </span>
                    <span className="text-4xl font-bold text-primary">
                      ${formatNumber(offer.offer_price)}
                    </span>
                  </div>
                )}
                {offer.savings_amount && offer.savings_amount > 0 && (
                  <Badge variant="secondary" className="text-success">
                    Save ${formatNumber(offer.savings_amount)}
                  </Badge>
                )}
              </CardHeader>

              <CardContent className="space-y-4">
                <Separator />

                {/* Opt-in Form */}
                <form onSubmit={handleSubmit} className="space-y-4">
                  {(offer.require_name || (!offer.require_email && !offer.require_phone)) && (
                    <div className="space-y-2">
                      <Label htmlFor="name">
                        Name {offer.require_name && "*"}
                      </Label>
                      <Input
                        id="name"
                        placeholder="Your name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required={offer.require_name}
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="email">
                      Email {offer.require_email && "*"}
                    </Label>
                    <Input
                      id="email"
                      type="email"
                      placeholder="you@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required={offer.require_email}
                    />
                  </div>

                  {offer.require_phone && (
                    <div className="space-y-2">
                      <Label htmlFor="phone">Phone *</Label>
                      <Input
                        id="phone"
                        type="tel"
                        placeholder="+1 (555) 123-4567"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        required
                      />
                    </div>
                  )}

                  {offer.require_phone && (
                    <div className="flex items-start gap-2.5 rounded-md border p-3">
                      <Checkbox
                        id="sms-consent"
                        checked={smsConsent}
                        onCheckedChange={(checked) =>
                          setSmsConsent(checked === true)
                        }
                        className="mt-0.5"
                      />
                      <Label
                        htmlFor="sms-consent"
                        className="text-xs font-normal leading-relaxed text-muted-foreground cursor-pointer"
                      >
                        I agree to receive text messages from{" "}
                        {offer.business_name || "this business"} about my
                        inquiry, including follow-ups, offers, and appointment
                        reminders. Message frequency varies. Message & data
                        rates may apply. Reply STOP to opt out or HELP for
                        help. Consent is not a condition of purchase.
                        (Optional)
                      </Label>
                    </div>
                  )}

                  {optInMutation.isError && (
                    <Alert variant="destructive">
                      <AlertCircle className="size-4" />
                      <AlertTitle>Error</AlertTitle>
                      <AlertDescription>
                        Something went wrong. Please try again.
                      </AlertDescription>
                    </Alert>
                  )}

                  <Button
                    type="submit"
                    size="lg"
                    className="w-full text-lg py-6"
                    disabled={!isFormValid() || optInMutation.isPending}
                  >
                    {optInMutation.isPending ? (
                      <>
                        <Loader2 className="size-5 mr-2 animate-spin" />
                        Processing...
                      </>
                    ) : (
                      offer.cta_text || "Get Access Now"
                    )}
                  </Button>

                  {offer.cta_subtext && (
                    <p className="text-center text-sm text-muted-foreground">
                      {offer.cta_subtext}
                    </p>
                  )}
                </form>
              </CardContent>
            </Card>

            {/* Urgency Banner */}
            {offer.urgency_type && offer.urgency_text && (
              <Alert className="border-warning/20 bg-warning/10">
                <Clock className="size-4 text-warning" />
                <AlertDescription className="text-warning font-medium">
                  {offer.urgency_text}
                  {offer.scarcity_count && offer.scarcity_count > 0 && (
                    <span className="block mt-1">
                      Only {offer.scarcity_count} spots remaining!
                    </span>
                  )}
                </AlertDescription>
              </Alert>
            )}
          </div>
        </div>

        {/* Description */}
        {offer.description && (
          <Card className="mt-8">
            <CardContent className="pt-6 prose dark:prose-invert max-w-none">
              <p className="text-muted-foreground whitespace-pre-wrap">
                {offer.description}
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
