"use client";

import {
  ClipboardList,
  MapPin,
  Navigation,
  Phone,
  StickyNote,
  TriangleAlert,
  User,
} from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { Job } from "@/lib/api/jobs";
import {
  formatLineItemQuantity,
  jobSiteAddressLines,
  jobSiteMapsUrl,
} from "@/lib/jobs/job-derivations";
import { formatPhoneNumber } from "@/lib/utils/phone";

/**
 * The field technician's answer to "what am I doing, and where".
 *
 * A worker holds `jobs:read` and nothing else — `/contacts` and
 * `/service-locations` are both 403 for them — so the site, the customer's
 * direct line, and the scope of work only reach them through the job payload's
 * embedded projections. Rendered for dispatchers too: the address, phone and
 * scope are just as useful when you're the one assigning the work.
 *
 * Never render money in here. `line_items` is the API's deliberately price-free
 * projection (no unit_price, discount or total) because this component is what
 * the field tier sees; adding a currency here would leak pricing to every
 * technician.
 */
export function JobBrief({ job }: { job: Job }) {
  const site = job.service_location ?? null;
  const customer = job.customer ?? null;
  const addressLines = jobSiteAddressLines(site);
  const mapsUrl = jobSiteMapsUrl(site);
  const phoneNumber = customer?.phone_number?.trim() ?? "";
  const lineItems = job.line_items ?? [];

  return (
    <div className="space-y-4">
      {/* Where and who — one card so the two facts a worker checks before
          leaving stay together on a phone screen. */}
      <div className="rounded-lg border">
        <section className="space-y-2 p-3">
          <SectionHeading icon={<MapPin className="size-4" />}>Site</SectionHeading>
          {site && (site.name || addressLines.length > 0) ? (
            <address className="text-sm not-italic">
              {site.name && <span className="block font-medium">{site.name}</span>}
              {/* Index key: the lines are a fixed, never-reordered projection,
                  and bad data can repeat one (line2 typed same as line1). */}
              {addressLines.map((line, index) => (
                <span key={index} className="block text-muted-foreground">
                  {line}
                </span>
              ))}
            </address>
          ) : (
            <EmptyLine>No site address on this job.</EmptyLine>
          )}
          {mapsUrl && (
            <Button variant="outline" asChild className="h-10 w-full justify-start sm:h-9 sm:w-auto">
              <a href={mapsUrl} target="_blank" rel="noopener noreferrer">
                <Navigation className="mr-2 size-4" />
                Navigate
              </a>
            </Button>
          )}
        </section>

        <section className="space-y-2 border-t p-3">
          <SectionHeading icon={<User className="size-4" />}>Customer</SectionHeading>
          {customer ? (
            <p className="text-sm font-medium">{customer.name}</p>
          ) : (
            <EmptyLine>No customer contact on this job.</EmptyLine>
          )}
          {phoneNumber ? (
            <Button variant="outline" asChild className="h-10 w-full justify-start sm:h-9 sm:w-auto">
              <a href={`tel:${phoneNumber}`}>
                <Phone className="mr-2 size-4" />
                Call {formatPhoneNumber(phoneNumber)}
              </a>
            </Button>
          ) : (
            customer && <EmptyLine>No phone number on file.</EmptyLine>
          )}
        </section>
      </div>

      {/* Access notes are entry and safety instructions — gate codes, dogs — so
          they get the warning treatment instead of blending into the card. */}
      {site?.access_notes && (
        <section className="rounded-lg border border-warning/30 bg-warning/10 p-3">
          <SectionHeading icon={<TriangleAlert className="size-4" />} className="text-warning">
            Access notes
          </SectionHeading>
          <p className="mt-1.5 text-sm whitespace-pre-wrap">{site.access_notes}</p>
        </section>
      )}

      {job.description && (
        <section className="space-y-1.5">
          <SectionHeading icon={<StickyNote className="size-4" />}>Job notes</SectionHeading>
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">{job.description}</p>
        </section>
      )}

      <section className="space-y-2">
        <SectionHeading icon={<ClipboardList className="size-4" />}>
          Scope of work
        </SectionHeading>
        {lineItems.length === 0 ? (
          <EmptyLine>No scope items on this job yet.</EmptyLine>
        ) : (
          <ul className="divide-y rounded-md border text-sm">
            {lineItems.map((item) => (
              <li key={item.id} className="flex items-start justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="font-medium">{item.name}</p>
                  {item.description && (
                    <p className="text-xs text-muted-foreground">{item.description}</p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  &times;&nbsp;{formatLineItemQuantity(item.quantity)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Section label styled like the dialog's form labels, but a real heading. */
function SectionHeading({
  icon,
  className = "",
  children,
}: {
  icon: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <h3 className={`flex items-center gap-2 text-sm leading-none font-medium ${className}`}>
      {icon}
      {children}
    </h3>
  );
}

function EmptyLine({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
