"use client";

import { useRouter } from "next/navigation";
import { use, useEffect } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { ConversationLayout } from "@/components/layout/conversation-layout";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { useContact } from "@/hooks/useContacts";
import { useContactStore } from "@/lib/contact-store";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ConversationPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();
  const workspaceId = useWorkspaceId();
  const { setSelectedContact } = useContactStore();

  const contactId = parseInt(id, 10);

  // Fetch the specific contact
  const { data: contact, isPending: isLoadingContact } = useContact(
    workspaceId ?? "",
    contactId,
  );

  // Set selected contact when loaded; redirect if not found
  useEffect(() => {
    if (contact) {
      setSelectedContact(contact);
    } else if (!isLoadingContact && !contact) {
      router.push("/");
    }
  }, [contact, isLoadingContact, workspaceId, setSelectedContact, router]);

  return (
    <AppSidebar>
      <div className="h-full overflow-hidden">
        <ConversationLayout className="h-full" />
      </div>
    </AppSidebar>
  );
}
