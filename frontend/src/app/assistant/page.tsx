import { AssistantChat } from "@/components/assistant/assistant-chat";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function AssistantPage() {
  return (
    <AppSidebar>
      <div className="flex h-full min-h-0 flex-col">
        <div className="border-b px-6 py-4">
          <h1 className="text-xl font-semibold">CRM Assistant</h1>
          <p className="text-sm text-muted-foreground">
            Your personal AI assistant for managing contacts, campaigns, and
            conversations.
          </p>
        </div>
        <AssistantChat className="min-h-0 flex-1" />
      </div>
    </AppSidebar>
  );
}
