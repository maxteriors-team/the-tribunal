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

const BRIEFING_PROMPT = "Give me my morning briefing";

export function AssistantChat({ className }: { className?: string }) {
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
    scrollRef,
    handleNewConversation,
    handleSelectConversation,
    handleDeleteConversation,
    sendMessage,
    handleEnhancePrompt,
    handleSubmit,
    handleKeyDown,
    handleStop,
  } = useAssistantChat();

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
      <ConversationSidebar
        conversations={conversations}
        activeConversationId={resolvedActiveConversationId}
        runtimes={runtimes}
        isLoading={conversationsLoading}
        onNewConversation={handleNewConversation}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
      />

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
          onPrompt={sendMessage}
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
