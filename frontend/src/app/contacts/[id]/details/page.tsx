"use client";

import { notFound } from "next/navigation";
import { use } from "react";

import { ContactDetailPage } from "@/components/contacts/contact-detail/contact-detail-page";
import { AppSidebar } from "@/components/layout/app-sidebar";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ContactDetailsRoute({ params }: PageProps) {
  const { id } = use(params);
  const contactId = Number.parseInt(id, 10);

  if (!Number.isInteger(contactId) || contactId <= 0) {
    notFound();
  }

  return (
    <AppSidebar>
      <ContactDetailPage contactId={contactId} />
    </AppSidebar>
  );
}
