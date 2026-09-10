"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import {
  ChatHeader,
  ConversationSidebar,
  MessageComposer,
  MessageList,
} from "@/components/assistant/assistant-chat-views";
import { useAssistantChat } from "@/hooks/useAssistantChat";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/providers/workspace-provider";

const BRIEFING_PROMPT = "Give me my morning briefing";

export function AssistantChat({
  className,
  showConversationList = true,
}: {
  className?: string;
  /**
   * Show the saved-chats rail beside the conversation.
   *
   * The rail is a fixed `w-72` revealed at the `md:` *viewport* breakpoint, so
   * it cannot tell it is inside a narrow side panel on a wide screen — it
   * renders anyway and squeezes the composer down to one word per line.
   * Callers mounting this in a panel turn it off; switching between saved chats
   * stays on the full page.
   */
  showConversationList?: boolean;
}) {
  const {
    workspaceId,
    conversations,
    conversationsLoading,
    activeConversation,
    resolvedActiveConversationId,
    runtimes,
    activeRuntime,
    visibleMessages,
    input,
    setInput,
    imageDataUrl,
    setImageDataUrl,
    isEnhancing,
    enhancementError,
    actionReviewStates,
    scrollRef,
    handleNewConversation,
    handleSelectConversation,
    handleDeleteConversation,
    sendMessage,
    handleEnhancePrompt,
    handleSubmit,
    handleKeyDown,
    handleStop,
    handleRetry,
    handleApprovePendingAction,
    handleRejectPendingAction,
  } = useAssistantChat();
  const { currentWorkspace } = useWorkspace();

  // /assistant?briefing=1 auto-sends the morning-briefing prompt once, then
  // strips the param so a refresh doesn't re-trigger it.
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const briefingRequested = searchParams.get("briefing") === "1";
  const briefingSentRef = useRef(false);
  useEffect(() => {
    if (!briefingRequested || briefingSentRef.current || !workspaceId) return;
    briefingSentRef.current = true;
    void sendMessage(BRIEFING_PROMPT);
    router.replace(pathname);
  }, [briefingRequested, workspaceId, sendMessage, router, pathname]);

  return (
    <div className={cn("flex h-full min-h-0 overflow-hidden", className)}>
      {showConversationList ? (
        <ConversationSidebar
          conversations={conversations}
          activeConversationId={resolvedActiveConversationId}
          runtimes={runtimes}
          isLoading={conversationsLoading}
          onNewConversation={handleNewConversation}
          onSelectConversation={handleSelectConversation}
          onDeleteConversation={handleDeleteConversation}
        />
      ) : null}

      <section className="flex min-w-0 flex-1 flex-col bg-background">
        <ChatHeader
          conversation={activeConversation}
          runtime={activeRuntime}
          onNewConversation={handleNewConversation}
        />

        <MessageList
          messages={visibleMessages}
          runtime={activeRuntime}
          scrollRef={scrollRef}
          workspaceName={currentWorkspace?.workspace.name ?? null}
          actionReviewStates={actionReviewStates}
          onPrompt={setInput}
          onApproveAction={handleApprovePendingAction}
          onRejectAction={handleRejectPendingAction}
          onRetry={handleRetry}
          hasConversationList={showConversationList}
        />

        <MessageComposer
          input={input}
          isStreaming={activeRuntime.isStreaming}
          canSend={Boolean(workspaceId)}
          imageDataUrl={imageDataUrl}
          isEnhancing={isEnhancing}
          enhancementError={enhancementError}
          onInputChange={setInput}
          onImageChange={setImageDataUrl}
          onEnhance={() => void handleEnhancePrompt()}
          onSubmit={handleSubmit}
          onKeyDown={handleKeyDown}
          onStop={handleStop}
        />
      </section>
    </div>
  );
}
