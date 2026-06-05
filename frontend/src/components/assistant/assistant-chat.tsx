"use client";

import {
  ChatHeader,
  ConversationSidebar,
  MessageComposer,
  MessageList,
} from "@/components/assistant/assistant-chat-views";
import { useAssistantChat } from "@/hooks/useAssistantChat";
import { cn } from "@/lib/utils";

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
    scrollRef,
    handleNewConversation,
    handleSelectConversation,
    handleDeleteConversation,
    sendMessage,
    handleSubmit,
    handleKeyDown,
    handleStop,
  } = useAssistantChat();

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
          onInputChange={setInput}
          onImageChange={setImageDataUrl}
          onSubmit={handleSubmit}
          onKeyDown={handleKeyDown}
          onStop={handleStop}
        />
      </section>
    </div>
  );
}
