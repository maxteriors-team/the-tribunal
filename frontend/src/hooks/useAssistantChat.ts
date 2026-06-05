"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  useAssistantConversation,
  useAssistantConversations,
  useDeleteAssistantConversation,
} from "@/hooks/useAssistant";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  assistantApi,
  type AssistantConversationMetaResponse,
  type AssistantMessageResponse,
  type AssistantStreamEvent,
} from "@/lib/api/assistant";
import {
  applyStreamResult,
  createRuntimeId,
  emptyAccumulator,
  emptyRuntime,
  mergeRuntimePatch,
  reduceStreamEvent,
  resolveActiveConversationId,
  resolveActiveRuntime,
  selectVisibleMessages,
  startUserTurn,
  type ConversationRuntime,
  type StreamAccumulator,
} from "@/lib/assistant/conversation-runtime";

export interface UseAssistantChatResult {
  workspaceId: string | null;
  conversations: AssistantConversationMetaResponse[];
  conversationsLoading: boolean;
  activeConversation: AssistantConversationMetaResponse | undefined;
  resolvedActiveConversationId: string;
  runtimes: Record<string, ConversationRuntime>;
  activeRuntime: ConversationRuntime;
  visibleMessages: AssistantMessageResponse[];
  input: string;
  setInput: (value: string) => void;
  imageDataUrl: string | null;
  setImageDataUrl: (value: string | null) => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  handleNewConversation: () => void;
  handleSelectConversation: (conversationId: string) => void;
  handleDeleteConversation: (conversationId: string) => void;
  sendMessage: (message: string) => Promise<void>;
  handleSubmit: (event: React.FormEvent) => void;
  handleKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  handleStop: () => void;
}

/**
 * Container hook for {@link AssistantChat}: owns conversation selection,
 * per-conversation streaming runtimes, and the abort/accumulator refs while
 * delegating event folding to the pure `reduceStreamEvent` reducer.
 */
export function useAssistantChat(): UseAssistantChatResult {
  const workspaceId = useWorkspaceId();
  const conversationsQuery = useAssistantConversations();
  const conversations = useMemo(
    () => conversationsQuery.data ?? [],
    [conversationsQuery.data],
  );
  const [draftConversationId, setDraftConversationId] = useState(() =>
    createRuntimeId(),
  );
  const [activeConversationId, setActiveConversationId] = useState<string | null>(
    null,
  );
  const [runtimes, setRuntimes] = useState<Record<string, ConversationRuntime>>(
    {},
  );
  const [input, setInput] = useState("");
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllersRef = useRef<Record<string, AbortController>>({});
  const accumulatorsRef = useRef<Record<string, StreamAccumulator>>({});
  const isDraftActive = activeConversationId === draftConversationId;
  const resolvedActiveConversationId = resolveActiveConversationId(
    activeConversationId,
    conversations,
    draftConversationId,
  );
  const activeConversation = useMemo(
    () =>
      isDraftActive
        ? undefined
        : conversations.find(
            (conversation) => conversation.id === resolvedActiveConversationId,
          ),
    [isDraftActive, resolvedActiveConversationId, conversations],
  );
  const conversationQuery = useAssistantConversation(
    activeConversation && !runtimes[activeConversation.id]?.isStreaming
      ? activeConversation.id
      : null,
  );
  const deleteConversation = useDeleteAssistantConversation();

  const activeRuntime = useMemo(
    () =>
      resolveActiveRuntime({
        storedRuntime: runtimes[resolvedActiveConversationId],
        isDraftActive,
        hydratedMessages:
          conversationQuery.data?.id === resolvedActiveConversationId
            ? conversationQuery.data.messages
            : null,
      }),
    [conversationQuery.data, isDraftActive, resolvedActiveConversationId, runtimes],
  );
  const visibleMessages = useMemo(
    () => selectVisibleMessages(activeRuntime.messages),
    [activeRuntime.messages],
  );

  const patchRuntime = useCallback(
    (conversationId: string, patch: Partial<ConversationRuntime>) => {
      setRuntimes((current) => ({
        ...current,
        [conversationId]: mergeRuntimePatch(current[conversationId], patch),
      }));
    },
    [],
  );

  const createConversationRuntime = useCallback((conversationId: string) => {
    setRuntimes((current) => ({
      ...current,
      [conversationId]: current[conversationId] ?? emptyRuntime(),
    }));
    setActiveConversationId(conversationId);
  }, []);

  const handleNewConversation = useCallback(() => {
    const conversationId = createRuntimeId();
    setDraftConversationId(conversationId);
    createConversationRuntime(conversationId);
  }, [createConversationRuntime]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [
    visibleMessages.length,
    activeRuntime.streamingText,
    activeRuntime.activeTools.length,
    activeRuntime.completedTools.length,
  ]);

  useEffect(() => {
    const abortControllers = abortControllersRef.current;
    return () => {
      Object.values(abortControllers).forEach((controller) => controller.abort());
    };
  }, []);

  const handleSelectConversation = useCallback((conversationId: string) => {
    setActiveConversationId(conversationId);
  }, []);

  const applyStreamEvent = useCallback(
    (conversationId: string, event: AssistantStreamEvent) => {
      const accumulator = accumulatorsRef.current[conversationId];
      if (!accumulator) return;

      const result = reduceStreamEvent(accumulator, event);
      accumulatorsRef.current[conversationId] = result.accumulator;

      if (!result.finished) {
        patchRuntime(conversationId, result.patch);
        return;
      }

      setRuntimes((current) => ({
        ...current,
        [conversationId]: applyStreamResult(
          current[conversationId] ?? emptyRuntime(),
          result,
        ),
      }));
      delete abortControllersRef.current[conversationId];
      delete accumulatorsRef.current[conversationId];
    },
    [patchRuntime],
  );

  const sendMessage = useCallback(
    async (rawMessage: string) => {
      const trimmed = rawMessage.trim();
      const attachedImage = imageDataUrl;
      if ((!trimmed && !attachedImage) || !workspaceId) return;

      const conversationId = resolvedActiveConversationId;
      setActiveConversationId(conversationId);
      if (conversationId === draftConversationId && !runtimes[conversationId]) {
        createConversationRuntime(conversationId);
      }
      const requestId = createRuntimeId();
      const userMessage: AssistantMessageResponse = {
        id: `user-${requestId}`,
        role: "user",
        content: trimmed,
        image: attachedImage,
        created_at: new Date().toISOString(),
      };
      const controller = new AbortController();
      abortControllersRef.current[conversationId] = controller;
      accumulatorsRef.current[conversationId] = emptyAccumulator();

      setInput("");
      setImageDataUrl(null);
      setRuntimes((current) => {
        const runtime =
          current[conversationId] ??
          (conversationQuery.data?.id === conversationId
            ? { ...emptyRuntime(), messages: conversationQuery.data.messages }
            : emptyRuntime());
        return {
          ...current,
          [conversationId]: startUserTurn(runtime, userMessage, requestId),
        };
      });

      try {
        await assistantApi.streamChat({
          workspaceId,
          conversationId,
          message: trimmed,
          image: attachedImage,
          signal: controller.signal,
          onEvent: (event) => applyStreamEvent(conversationId, event),
        });
        void conversationsQuery.refetch();
      } catch (error) {
        if (controller.signal.aborted) {
          patchRuntime(conversationId, {
            isStreaming: false,
            streamingText: "",
            activeTools: [],
            requestId: null,
          });
          return;
        }
        patchRuntime(conversationId, {
          isStreaming: false,
          error: error instanceof Error ? error.message : "Assistant stream failed.",
          requestId: null,
        });
      } finally {
        delete abortControllersRef.current[conversationId];
      }
    },
    [
      applyStreamEvent,
      conversationQuery.data,
      conversationsQuery,
      createConversationRuntime,
      draftConversationId,
      imageDataUrl,
      patchRuntime,
      resolvedActiveConversationId,
      runtimes,
      workspaceId,
    ],
  );

  const handleDeleteConversation = useCallback(
    async (conversationId: string) => {
      abortControllersRef.current[conversationId]?.abort();
      delete abortControllersRef.current[conversationId];
      delete accumulatorsRef.current[conversationId];
      await deleteConversation.mutateAsync(conversationId);
      setRuntimes((current) => {
        const next = { ...current };
        delete next[conversationId];
        return next;
      });
      if (resolvedActiveConversationId === conversationId) {
        handleNewConversation();
      }
    },
    [deleteConversation, handleNewConversation, resolvedActiveConversationId],
  );

  const handleSubmit = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      if (activeRuntime.isStreaming) return;
      void sendMessage(input);
    },
    [activeRuntime.isStreaming, input, sendMessage],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (!activeRuntime.isStreaming) void sendMessage(input);
      }
    },
    [activeRuntime.isStreaming, input, sendMessage],
  );

  const handleStop = useCallback(() => {
    abortControllersRef.current[resolvedActiveConversationId]?.abort();
    patchRuntime(resolvedActiveConversationId, {
      isStreaming: false,
      streamingText: "",
      activeTools: [],
      requestId: null,
    });
  }, [patchRuntime, resolvedActiveConversationId]);

  return {
    workspaceId,
    conversations,
    conversationsLoading: conversationsQuery.isLoading,
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
    handleDeleteConversation: (conversationId) =>
      void handleDeleteConversation(conversationId),
    sendMessage,
    handleSubmit,
    handleKeyDown,
    handleStop,
  };
}
