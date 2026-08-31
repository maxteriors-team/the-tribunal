import { AppSidebar } from "@/components/layout/app-sidebar";
import { MessagesList } from "@/components/messages/messages-list";

export default function MessagesPage() {
  return (
    <AppSidebar>
      <MessagesList />
    </AppSidebar>
  );
}
