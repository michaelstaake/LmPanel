import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { apiDelete, apiGet, apiPost, apiPostForm, handleBackendUnavailableError, isBackendUnavailableResponse } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useModelsCatalog } from "../context/ModelsCatalogContext";
import { useMobileNav } from "../context/MobileNavContext";
import { useToast } from "../context/ToastContext";
import { getStoredToken } from "../lib/session";
import ChatSidebarContent from "../components/ui/ChatSidebarContent";
import MessageContent from "../components/ui/MessageContent";

type ChatRole = "system" | "user" | "assistant";

type ChatContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } };

type ChatMessageContent = string | ChatContentPart[];

type ChatMessage = {
  role: ChatRole;
  content: string;
  apiContent?: ChatMessageContent;
  thinking?: string;
  thinkingElapsedSeconds?: number | null;
  phase?: "uploading" | "thinking" | "streaming" | "complete";
  modelName?: string;
  stats?: ChatCompletionStats | null;
};

type ChatCompletionStats = {
  model: string;
  elapsedSeconds: number;
  promptTokens: number | null;
  completionTokens: number | null;
  totalTokens: number | null;
  tokensPerSecond: number | null;
};

type ChatSummary = {
  id: number;
  title: string;
  user_id: number;
  created_at: string | null;
};

type ChatDetailResponse = {
  chat: ChatSummary;
  messages: {
    id: number;
    chat_id: number;
    role: ChatRole;
    content: string;
    modelName?: string | null;
    stats?: ChatCompletionStats | null;
    created_at: string | null;
  }[];
};

type ChatCreateResponse = {
  status: string;
  chat: ChatSummary;
};

type AttachmentKind = "text" | "image" | "document" | "binary";

type AttachmentExtractionResponse = {
  attachments: {
    name: string;
    contentType?: string | null;
    size: number;
    status: "ok" | "unsupported" | "error";
    content?: string | null;
    detail?: string | null;
    truncated: boolean;
    extractor?: string | null;
  }[];
};

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

type Attachment = {
  name: string;
  size: number;
  type: string;
  kind: AttachmentKind;
  sourceFile: File;
  content?: string;
  dataUrl?: string;
  extractionStatus?: "pending" | "ready" | "unsupported" | "error";
  extractionDetail?: string;
  truncated?: boolean;
};

const TEXT_ATTACHMENT_SUFFIXES = new Set([
  ".conf",
  ".css",
  ".csv",
  ".html",
  ".ini",
  ".js",
  ".json",
  ".log",
  ".md",
  ".py",
  ".sh",
  ".ts",
  ".tsx",
  ".txt",
  ".yaml",
  ".yml",
]);

const DOCUMENT_ATTACHMENT_SUFFIXES = new Set([".docx", ".ods", ".odt", ".pdf", ".xlsx"]);

const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 48;

function hasKnownSuffix(name: string, suffixes: Set<string>): boolean {
  const lowerName = name.toLowerCase();
  for (const suffix of suffixes) {
    if (lowerName.endsWith(suffix)) {
      return true;
    }
  }

  return false;
}

function isTextAttachment(file: File): boolean {
  if (file.type.startsWith("text/")) {
    return true;
  }

  return hasKnownSuffix(file.name, TEXT_ATTACHMENT_SUFFIXES);
}

function isBackendExtractableAttachment(file: File): boolean {
  return (
    file.type === "application/pdf" ||
    file.type === "application/vnd.oasis.opendocument.spreadsheet" ||
    file.type === "application/vnd.oasis.opendocument.text" ||
    file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    file.type === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    hasKnownSuffix(file.name, DOCUMENT_ATTACHMENT_SUFFIXES)
  );
}

function classifyAttachment(file: File): AttachmentKind {
  if (isTextAttachment(file)) {
    return "text";
  }

  if (file.type.startsWith("image/")) {
    return "image";
  }

  if (isBackendExtractableAttachment(file)) {
    return "document";
  }

  return "binary";
}

async function resolveDocumentAttachments(attachments: Attachment[], token?: string): Promise<Attachment[]> {
  const pendingDocuments = attachments.filter((attachment) => attachment.kind === "document" && !attachment.content);
  if (pendingDocuments.length === 0) {
    return attachments;
  }

  const formData = new FormData();
  pendingDocuments.forEach((attachment) => {
    formData.append("files", attachment.sourceFile);
  });

  const response = await apiPostForm<AttachmentExtractionResponse>("/api/chat/attachments/extract", formData, token);
  if (response.attachments.length !== pendingDocuments.length) {
    throw new Error("Attachment extraction returned an unexpected number of results.");
  }

  let responseIndex = 0;
  return attachments.map((attachment) => {
    if (attachment.kind !== "document" || attachment.content) {
      return attachment;
    }

    const result = response.attachments[responseIndex++];
    const extractionDetail = result.detail ?? undefined;

    if (result.status === "ok" && result.content) {
      return {
        ...attachment,
        type: result.contentType ?? attachment.type,
        content: result.content,
        extractionStatus: "ready",
        extractionDetail,
        truncated: result.truncated,
      };
    }

    return {
      ...attachment,
      extractionStatus: result.status === "unsupported" ? "unsupported" : "error",
      extractionDetail,
      truncated: false,
    };
  });
}

function formatAttachmentFallbackText(file: Attachment): string {
  const sizeLabel = formatAttachmentSize(file.size);

  if (file.extractionStatus === "unsupported") {
    return `[Attached File: ${file.name} (${file.extractionDetail ?? "Unsupported for text extraction"}, ${sizeLabel})]`;
  }

  if (file.extractionStatus === "error") {
    return `[Attached File: ${file.name} (${file.extractionDetail ?? "Text extraction failed"}, ${sizeLabel})]`;
  }

  return `[Attached File: ${file.name} (Binary File, ${sizeLabel})]`;
}

function formatAttachmentLabel(file: Attachment): string {
  const sizeLabel = formatAttachmentSize(file.size);
  return `[Attached File: ${file.name} (${sizeLabel})]`;
}

function formatAttachmentSize(size: number): string {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  return `${(size / 1024).toFixed(1)} KB`;
}

function describeAttachment(file: Attachment): string {
  if (file.kind === "image") {
    return "Image attachment";
  }

  if (file.kind === "text") {
    return "Text ready";
  }

  if (file.kind === "document") {
    if (file.extractionStatus === "ready") {
      return file.truncated ? "Text extracted, truncated" : "Text extracted";
    }
    if (file.extractionStatus === "error") {
      return "Extraction failed";
    }
    return "Text will be extracted on send";
  }

  return "Metadata only";
}

function formatContextLength(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) {
    return "Unknown Context";
  }

  if (value >= 1_048_576) {
    return `${Math.floor(value / 1_048_576)}M Context`;
  }

  if (value >= 1_024) {
    return `${Math.floor(value / 1_024)}K Context`;
  }

  return `${Math.floor(value)} Context`;
}

function getModelThinkingTagLabel(discourageThinking: boolean, capability: string): string | null {
  if (discourageThinking) {
    return null;
  }
  if (capability === "always") {
    return "Always Thinks";
  }
  if (capability === "hybrid") {
    return "Can Think";
  }
  return null;
}

function ModelCardSkeleton() {
  return (
    <div
      className="flex min-h-[172px] animate-pulse flex-col rounded-[24px] border border-black/10 bg-[#fffdf7] p-5 shadow-sm"
      aria-hidden="true"
    >
      <div className="h-6 w-2/3 rounded-lg bg-black/10" />
      <div className="mt-4 h-4 w-full rounded bg-black/5" />
      <div className="mt-2 h-4 w-4/5 rounded bg-black/5" />
      <div className="mt-6 flex gap-2">
        <div className="h-8 w-24 rounded-full bg-black/5" />
        <div className="h-8 w-28 rounded-full bg-black/5" />
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { token, user } = useAuth();
  const { closeMobileNav, setMobileNavSection } = useMobileNav();
  const { showError } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const {
    models,
    modelCardDetails,
    modelVisionDefaults,
    modelSearchAvailability,
    modelThinkingDisabledDefaults,
    modelThinkingDefaults,
    modelThinkingControllable,
    modelThinkingCapabilities,
    isLoadingModels,
  } = useModelsCatalog();
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [thinkingExpandedByIndex, setThinkingExpandedByIndex] = useState<Record<number, boolean>>({});
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [savedChats, setSavedChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<number | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isLoadingChats, setIsLoadingChats] = useState(false);
  const prevLocationRef = useRef(location.pathname);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [useThinking, setUseThinking] = useState(true);
  const selectedModelSupportsVision = selectedModel ? (modelVisionDefaults[selectedModel] ?? false) : false;
  const selectedModelSupportsWebSearch = selectedModel ? (modelSearchAvailability[selectedModel] ?? false) : false;
  const selectedModelDiscouragesThinking = selectedModel ? (modelThinkingDisabledDefaults[selectedModel] ?? false) : false;
  const selectedModelThinkingCapability = selectedModel ? (modelThinkingCapabilities[selectedModel] ?? "none") : "none";
  const selectedModelAllowsThinkingPreference = selectedModel !== "" && (modelThinkingControllable[selectedModel] ?? false);
  const selectedModelAlwaysThinks = selectedModelThinkingCapability === "always";
  const effectiveUseThinking = selectedModelAllowsThinkingPreference ? useThinking : selectedModelAlwaysThinks;
  const shouldShowTranscript = activeChatId !== null || messages.length > 0;
  const isNewChatEmptyState = activeChatId === null && messages.length === 0;
  const shouldShowNoModelsEmptyState = isNewChatEmptyState && !isLoadingModels && models.length === 0;
  const isModelsUnavailable = isLoadingModels || models.length === 0;
  const newChatSubtitle =
    isLoadingModels && models.length === 0
      ? "Loading models..."
      : models.length <= 1
        ? "New chat"
        : "New chat - choose a model";
  const inputPlaceholder = isLoadingModels
    ? "Loading models..."
    : models.length === 0
      ? "No active models available"
      : "Ask AI...";
  const skeletonCardCount = 3;
  const newChatModelGridClassName =
    models.length >= 3 || (isLoadingModels && models.length === 0)
      ? "grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
      : models.length === 2
        ? "grid gap-3 sm:grid-cols-2"
        : "mx-auto grid max-w-xl place-items-center gap-3";

  useEffect(() => {
    if (token) {
      void refreshChats(token);
    } else {
      setSavedChats([]);
      setActiveChatId(null);
    }
  }, [token]);

  useEffect(() => {
    const prev = prevLocationRef.current;
    const current = location.pathname;
    if (prev !== "/" && current === "/" && activeChatId !== null) {
      startNewChat();
      navigate("/new-chat", { replace: true });
    }
    prevLocationRef.current = current;
  }, [location.pathname, activeChatId, navigate]);

  useEffect(() => {
    if (models.length === 0) {
      return;
    }
    setSelectedModel((current) => (current && models.includes(current) ? current : models[0]));
  }, [models]);

  useEffect(() => {
    if (shouldAutoScrollRef.current && transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
    updateTranscriptScrollState();
  }, [messages]);

  useEffect(() => {
    updateTranscriptScrollState();
  }, [shouldShowTranscript]);

  useEffect(() => {
    if (!shouldShowTranscript) {
      setShowScrollToBottom(false);
      return;
    }

    const handleResize = () => {
      updateTranscriptScrollState();
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [shouldShowTranscript]);

  useEffect(() => {
    if (!selectedModel) {
      return;
    }
    setUseThinking(modelThinkingDefaults[selectedModel] ?? true);
  }, [selectedModel, modelThinkingDefaults]);

  useEffect(() => {
    if (!isLoadingModels && models.length > 0 && !isSending) {
      inputRef.current?.focus();
    }
  }, [isLoadingModels, models, isSending]);

  useEffect(() => {
    if (!selectedModelSupportsWebSearch) {
      setUseWebSearch(false);
    }

    if (!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks) {
      setUseThinking(true);
    }
  }, [selectedModelSupportsWebSearch, selectedModelAllowsThinkingPreference, selectedModelAlwaysThinks]);

  useEffect(() => {
    setMobileNavSection({
      title: "Chats",
      content: (
        <ChatSidebarContent
          token={token}
          isLoadingChats={isLoadingChats}
          savedChats={savedChats}
          activeChatId={activeChatId}
          onNewChat={() => {
            startNewChat();
            closeMobileNav();
          }}
          onOpenChat={openChat}
          onDeleteChat={deleteChat}
          onAfterSelectChat={closeMobileNav}
          className="space-y-2 text-sm text-black/70"
          listClassName="max-h-[42vh] space-y-1 overflow-y-auto"
        />
      ),
    });

    return () => {
      setMobileNavSection(null);
    };
  }, [activeChatId, closeMobileNav, isLoadingChats, savedChats, setMobileNavSection, token]);

  async function refreshChats(activeToken: string) {
    setIsLoadingChats(true);
    try {
      const rows = await apiGet<ChatSummary[]>("/api/chat", activeToken);
      setSavedChats(rows);
    } catch {
      setSavedChats([]);
    } finally {
      setIsLoadingChats(false);
    }
  }

  function isNearTranscriptBottom(element: HTMLDivElement): boolean {
    return element.scrollHeight - element.scrollTop - element.clientHeight <= AUTO_SCROLL_BOTTOM_THRESHOLD_PX;
  }

  function enableTranscriptAutoScroll() {
    shouldAutoScrollRef.current = true;
  }

  function handleTranscriptScroll() {
    updateTranscriptScrollState();
  }

  function updateTranscriptScrollState() {
    const element = transcriptRef.current;
    if (!element) {
      setShowScrollToBottom(false);
      return;
    }

    const isNearBottom = isNearTranscriptBottom(element);
    const isScrollable = element.scrollHeight - element.clientHeight > AUTO_SCROLL_BOTTOM_THRESHOLD_PX;
    shouldAutoScrollRef.current = isNearBottom;
    setShowScrollToBottom(isScrollable && !isNearBottom);
  }

  function scrollTranscriptToBottom() {
    const element = transcriptRef.current;
    if (!element) {
      return;
    }

    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    shouldAutoScrollRef.current = true;
    setShowScrollToBottom(false);
  }

  function startNewChat() {
    enableTranscriptAutoScroll();
    setMessages([]);
    setInput("");
    setActiveChatId(null);
    setAttachments([]);
  }

  async function openChat(chatId: number) {
    if (!token) {
      return;
    }
    try {
      const detail = await apiGet<ChatDetailResponse>(`/api/chat/${chatId}`, token);
      enableTranscriptAutoScroll();
      setActiveChatId(detail.chat.id);
      setMessages(
        detail.messages.map((message) => ({
          role: message.role,
          content: message.content,
          modelName: message.modelName ?? undefined,
          stats: message.stats ?? null,
          phase: "complete",
        }))
      );
      setInput("");
      setAttachments([]);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load chat");
    }
  }

  async function deleteChat(chatId: number) {
    if (!token) {
      return;
    }
    try {
      await apiDelete<{ status: string }>(`/api/chat/${chatId}`, token);
      setSavedChats((current: ChatSummary[]) => current.filter((chat: ChatSummary) => chat.id !== chatId));
      if (activeChatId === chatId) {
        startNewChat();
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to delete chat");
    }
  }

  async function persistMessage(
    chatId: number,
    role: ChatRole,
    content: string,
    options?: { modelName?: string; stats?: ChatCompletionStats | null }
  ): Promise<void> {
    if (!token || !content) {
      return;
    }
    try {
      await apiPost(
        `/api/chat/${chatId}/messages`,
        {
          role,
          content,
          ...(options?.modelName ? { modelName: options.modelName } : {}),
          ...(options?.stats ? { stats: options.stats } : {}),
        },
        token
      );
    } catch {
      // Best-effort persistence.
    }
  }

  async function ensureChat(firstMessage: string): Promise<number | null> {
    if (!token) {
      return null;
    }
    if (activeChatId !== null) {
      return activeChatId;
    }
    try {
      const title = firstMessage.slice(0, 60);
      const response = await apiPost<{ title: string }, ChatCreateResponse>(
        "/api/chat",
        { title },
        token
      );
      setActiveChatId(response.chat.id);
      setSavedChats((current: ChatSummary[]) => [response.chat, ...current]);
      return response.chat.id;
    } catch {
      return null;
    }
  }

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const filesArray = Array.from<File>(e.target.files);

    filesArray.forEach((file) => {
      const attachmentKind = classifyAttachment(file);

      if (attachmentKind === "text") {
        const reader = new FileReader();
        reader.onload = (event) => {
          setAttachments((prev: Attachment[]) => [
            ...prev,
            {
              name: file.name,
              size: file.size,
              type: file.type,
              kind: attachmentKind,
              sourceFile: file,
              content: event.target?.result as string,
              extractionStatus: "ready",
            },
          ]);
        };
        reader.readAsText(file);
      } else if (attachmentKind === "image") {
        const reader = new FileReader();
        reader.onload = (event) => {
          setAttachments((prev: Attachment[]) => [
            ...prev,
            {
              name: file.name,
              size: file.size,
              type: file.type,
              kind: attachmentKind,
              sourceFile: file,
              dataUrl: event.target?.result as string,
            },
          ]);
        };
        reader.readAsDataURL(file);
      } else {
        setAttachments((prev: Attachment[]) => [
          ...prev,
          {
            name: file.name,
            size: file.size,
            type: file.type,
            kind: attachmentKind,
            sourceFile: file,
            extractionStatus: attachmentKind === "document" ? "pending" : "unsupported",
            extractionDetail:
              attachmentKind === "document"
                ? "Text will be extracted when you send this message."
                : "This file will be sent as metadata only.",
          },
        ]);
      }
    });

    e.target.value = "";
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev: Attachment[]) => prev.filter((_: Attachment, itemIndex: number) => itemIndex !== index));
  };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed && attachments.length === 0) {
      return;
    }
    if (!selectedModel) {
      showError("Activate a model on the Models page before chatting.");
      return;
    }

    if (attachments.some((file: Attachment) => file.type.startsWith("image/") && file.dataUrl) && !selectedModelSupportsVision) {
      showError("Vision is disabled for the selected model. Enable vision in the model settings or switch to a vision-enabled model before sending images.");
      return;
    }

    setIsSending(true);

    let preparedAttachments: Attachment[];
    try {
      preparedAttachments = await resolveDocumentAttachments(attachments, token ?? undefined);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to extract attachment text");
      setIsSending(false);
      return;
    }

    const { displayContent, apiContent } = buildUserMessageContent(trimmed, preparedAttachments);

    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: "user", content: displayContent, apiContent, phase: "complete" },
    ];
    const hasUploadStage = preparedAttachments.length > 0;
    enableTranscriptAutoScroll();
    setMessages([
      ...nextMessages,
      { role: "assistant", content: "", phase: hasUploadStage ? "uploading" : effectiveUseThinking ? "thinking" : "streaming", modelName: selectedModel, stats: null },
    ]);
    setInput("");
    setAttachments([]);

    const chatId = await ensureChat(trimmed ? trimmed : "Sent attachments");
    if (chatId !== null) {
      void persistMessage(chatId, "user", displayContent);
    }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    let assistantBuffer = "";
    let thinkingBuffer = "";
    let thinkingStartedAt: number | null = null;
    let thinkingElapsedSeconds: number | null = null;
    try {
      const stats = await streamCompletion(
        selectedModel,
        nextMessages.map((message) => ({ role: message.role, content: message.apiContent ?? message.content })),
        useWebSearch && selectedModelSupportsWebSearch,
        effectiveUseThinking,
        abortController.signal,
        (phase) => {
          if (phase === "thinking" && thinkingStartedAt === null) {
            thinkingStartedAt = performance.now();
          }
          setMessages((current: ChatMessage[]) => {
            if (current.length === 0) {
              return current;
            }
            const updated = [...current];
            const last = updated[updated.length - 1];
            if (last.role !== "assistant" || last.phase === "streaming" || last.phase === "complete") {
              return current;
            }
            updated[updated.length - 1] = { ...last, phase };
            return updated;
          });
        },
        (delta, type) => {
        if (type === "thinking") {
          if (thinkingStartedAt === null) {
            thinkingStartedAt = performance.now();
          }
          thinkingBuffer += delta;
          setMessages((current: ChatMessage[]) => {
            if (current.length === 0) return current;
            const updated = [...current];
            const last = updated[updated.length - 1];
            updated[updated.length - 1] = { ...last, thinking: (last.thinking ?? "") + delta, phase: "thinking" };
            return updated;
          });
          setThinkingExpandedByIndex((current: Record<number, boolean>) => ({ ...current, [nextMessages.length]: current[nextMessages.length] ?? false }));
        } else {
          if (thinkingElapsedSeconds === null && thinkingStartedAt !== null) {
            thinkingElapsedSeconds = Math.max((performance.now() - thinkingStartedAt) / 1000, 0.001);
          }
          assistantBuffer += delta;
          setMessages((current: ChatMessage[]) => {
            if (current.length === 0) {
              return current;
            }
            const updated = [...current];
            const last = updated[updated.length - 1];
            updated[updated.length - 1] = {
              ...last,
              content: last.content + delta,
              thinkingElapsedSeconds: thinkingElapsedSeconds ?? last.thinkingElapsedSeconds,
              phase: "streaming",
            };
            return updated;
          });
        }
        }
      );
      if (thinkingElapsedSeconds === null && thinkingStartedAt !== null) {
        thinkingElapsedSeconds = Math.max((performance.now() - thinkingStartedAt) / 1000, 0.001);
      }
      setMessages((current: ChatMessage[]) => {
        if (current.length === 0) {
          return current;
        }
        const updated = [...current];
        const last = updated[updated.length - 1];
        updated[updated.length - 1] = {
          ...last,
          thinking: thinkingBuffer || last.thinking,
          thinkingElapsedSeconds: thinkingElapsedSeconds ?? last.thinkingElapsedSeconds ?? null,
          content: assistantBuffer,
          modelName: last.modelName || stats.model,
          phase: "complete",
          stats,
        };
        return updated;
      });
      setThinkingExpandedByIndex((current: Record<number, boolean>) => ({ ...current, [nextMessages.length]: false }));
      if (chatId !== null && assistantBuffer) {
        void persistMessage(chatId, "assistant", assistantBuffer, {
          modelName: stats.model,
          stats,
        });
      }
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        setMessages((current: ChatMessage[]) => {
          if (current.length === 0) return current;
          const last = current[current.length - 1];
          if (last.role === "assistant") {
            if (!last.content && !last.thinking) return current.slice(0, -1);
            const updated = [...current];
            updated[updated.length - 1] = {
              ...last,
              thinkingElapsedSeconds: thinkingElapsedSeconds ?? last.thinkingElapsedSeconds ?? null,
              phase: "complete"
            };
            return updated;
          }
          return current;
        });
        if (chatId !== null && assistantBuffer) {
          void persistMessage(chatId, "assistant", assistantBuffer, {
            modelName: selectedModel,
          });
        }
      } else {
        const detail = error instanceof Error ? error.message : "Chat request failed";
        showError(detail);
        setMessages((current: ChatMessage[]) => {
          if (current.length === 0) {
            return current;
          }
          const last = current[current.length - 1];
          if (last.role === "assistant" && last.content === "") {
            return current.slice(0, -1);
          }
          if (last.role === "assistant") {
            const updated = [...current];
            updated[updated.length - 1] = { ...last, phase: "complete" };
            return updated;
          }
          return current;
        });
      }
    } finally {
      abortControllerRef.current = null;
      setIsSending(false);
    }
  }

  return (
    <section className={`grid gap-4 ${isSidebarOpen ? "xl:grid-cols-[280px_minmax(0,1fr)]" : "xl:grid-cols-[72px_minmax(0,1fr)]"}`}>
      <aside
        className={`rounded-2xl border border-black/10 bg-white/80 shadow-sm transition-all ${
          isSidebarOpen ? "hidden p-4 xl:block" : "hidden p-3 xl:block"
        }`}
      >
        {isSidebarOpen ? (
          <ChatSidebarContent
            token={token}
            isLoadingChats={isLoadingChats}
            savedChats={savedChats}
            activeChatId={activeChatId}
            onNewChat={startNewChat}
            onOpenChat={openChat}
            onDeleteChat={deleteChat}
            onCollapse={() => setIsSidebarOpen(false)}
          />
        ) : (
          <div className="flex h-full flex-col items-center gap-2">
            <button
              type="button"
              onClick={startNewChat}
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink text-white transition hover:bg-black"
              aria-label="Start a new chat"
              title="New chat"
            >
              <i className="bi bi-pencil-square text-[18px] leading-none" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => setIsSidebarOpen(true)}
              className="flex h-11 w-11 items-center justify-center rounded-xl border border-black/10 bg-white text-black/60 transition hover:border-black/20 hover:bg-black/5 hover:text-black"
              aria-label="Expand sidebar"
              title="Expand sidebar"
            >
              <i className="bi bi-layout-sidebar-inset text-[18px] leading-none" aria-hidden="true" />
            </button>
          </div>
        )}
      </aside>
      <main className={`min-w-0 rounded-2xl border border-black/10 bg-white/80 p-4 shadow-sm ${isNewChatEmptyState ? "flex min-h-[68vh] flex-col justify-center" : ""}`}>
        {!isNewChatEmptyState ? (
          <div className="mb-4 flex items-center justify-between gap-2">
            <div>
              <h2 className="font-display text-lg">Chat</h2>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={isLoadingModels || models.length === 0}
                className="rounded-lg border border-black/20 bg-white px-3 py-2 text-sm"
              >
                {models.length === 0 ? (
                  <option value="">{isLoadingModels ? "Loading models..." : "No active models"}</option>
                ) : (
                  models.map((alias) => (
                    <option key={alias} value={alias}>
                      {alias}
                    </option>
                  ))
                )}
              </select>
            </div>
          </div>
        ) : null}

        {!shouldShowNoModelsEmptyState && !isLoadingModels && models.length === 0 && (
          <div className="mb-3 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-sm text-black/70">
            {user?.is_admin ? (
              <>
                No models are active yet. Open the{" "}
                <a className="font-semibold underline" href="/models">
                  Models
                </a>{" "}
                page to get started.
              </>
            ) : (
              "No models are active. Contact your system administrator for assistance."
            )}
          </div>
        )}

        {shouldShowNoModelsEmptyState ? (
          <div className="mx-auto w-full max-w-2xl rounded-[28px] bg-white/40 px-8 py-10 text-center">
            <i
              className="bi bi-emoji-frown text-[72px] leading-none text-ink"
              aria-hidden="true"
            />
            <div className="mt-6 text-xl font-semibold text-ink md:text-2xl">No active models</div>
            <div className="mt-3 text-sm leading-7 text-black/68 md:text-[15px]">
              {user?.is_admin ? (
                <>
                  No models are active yet. Open the <a className="font-semibold underline" href="/models">Models</a> page to get started.
                </>
              ) : (
                "No models are active. Contact your system administrator for assistance."
              )}
            </div>
          </div>
        ) : isNewChatEmptyState ? (
          <div className="mx-auto mb-6 w-full max-w-5xl">
            <div className="mb-4 text-center">
              <p className="mt-2 text-sm text-black/60 md:text-[15px]">{newChatSubtitle}</p>
            </div>
            <div className={newChatModelGridClassName}>
              {isLoadingModels && models.length === 0
                ? Array.from({ length: skeletonCardCount }, (_, index) => <ModelCardSkeleton key={`skeleton-${index}`} />)
                : null}
              {models.map((alias) => {
                const details = modelCardDetails[alias];
                const isSelected = selectedModel === alias;
                const thinkingTagLabel = getModelThinkingTagLabel(
                  modelThinkingDisabledDefaults[alias] ?? false,
                  modelThinkingCapabilities[alias] ?? "none"
                );

                return (
                  <button
                    key={alias}
                    type="button"
                    onClick={() => setSelectedModel(alias)}
                    className={`group flex min-h-[172px] flex-col rounded-[24px] border p-5 text-left shadow-sm transition-all ${
                      isSelected
                        ? "border-ink bg-ink text-white shadow-lg shadow-black/10"
                        : "border-black/10 bg-[#fffdf7] text-ink hover:border-black/20 hover:shadow-md"
                    }`}
                    aria-pressed={isSelected}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="font-display text-lg leading-tight">{alias}</div>
                        {details?.description ? (
                          <p className={`mt-2 text-sm leading-6 ${isSelected ? "text-white/80" : "text-black/65"}`}>
                            {details.description}
                          </p>
                        ) : null}
                      </div>
                      <span
                        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border ${
                          isSelected ? "border-white/20 bg-white/10 text-white" : "border-transparent bg-transparent text-transparent"
                        }`}
                      >
                        {isSelected && <i className="bi bi-check2 text-[18px] leading-none" aria-hidden="true" />}
                      </span>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <span
                        className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
                          isSelected ? "bg-white/10 text-white/90" : "bg-black/5 text-black/70"
                        }`}
                      >
                        <i className="bi bi-box text-[13px] leading-none" aria-hidden="true" />
                        <span>{formatContextLength(details?.contextLength ?? null)}</span>
                      </span>
                      {details?.toolCallingEnabled ? (
                        <span
                          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
                            isSelected ? "bg-white/10 text-white/90" : "bg-black/5 text-black/70"
                          }`}
                        >
                          <i className="bi bi-tools text-[13px] leading-none" aria-hidden="true" />
                          <span>Tool Calling</span>
                        </span>
                      ) : null}
                      {details?.webSearchEnabled ? (
                        <span
                          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
                            isSelected ? "bg-white/10 text-white/90" : "bg-black/5 text-black/70"
                          }`}
                        >
                          <i className="bi bi-globe2 text-[13px] leading-none" aria-hidden="true" />
                          <span>Web Search</span>
                        </span>
                      ) : null}
                      {details?.visionEnabled ? (
                        <span
                          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
                            isSelected ? "bg-white/10 text-white/90" : "bg-black/5 text-black/70"
                          }`}
                        >
                          <i className="bi bi-image text-[13px] leading-none" aria-hidden="true" />
                          <span>Vision Capable</span>
                        </span>
                      ) : null}
                      {details?.ragEnabled ? (
                        <span
                          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
                            isSelected ? "bg-white/10 text-white/90" : "bg-black/5 text-black/70"
                          }`}
                        >
                          <i className="bi bi-book-half text-[13px] leading-none" aria-hidden="true" />
                          <span>RAG</span>
                        </span>
                      ) : null}
                      {thinkingTagLabel ? (
                        <span
                          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
                            isSelected ? "bg-white/10 text-white/90" : "bg-black/5 text-black/70"
                          }`}
                        >
                          <i className="bi bi-stars text-[13px] leading-none" aria-hidden="true" />
                          <span>{thinkingTagLabel}</span>
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ) : shouldShowTranscript ? (
          <div className="relative min-w-0">
            <div
              ref={transcriptRef}
              onScroll={handleTranscriptScroll}
              className="min-h-[360px] max-h-[55vh] overflow-y-auto rounded-xl border border-dashed border-black/20 bg-sand p-4 text-sm text-black/80"
            >
              {messages.length === 0 ? (
                <div className="text-black/50">Nothing to see here yet.</div>
              ) : (
                <div className="space-y-3">
                  {messages.map((message, index) => (
                  message.role === "assistant" && (message.phase === "uploading" || message.phase === "thinking" || message.phase === "streaming") && !message.content && !message.thinking ? (
                    <div key={index} className="px-1 py-1 text-sm font-medium text-black/45">
                      <span className="inline-flex items-center gap-2">
                        <span className="animate-pulse">{message.phase === "uploading" ? "Uploading..." : "Processing..."}</span>
                      </span>
                    </div>
                  ) : (
                    <div
                      key={index}
                      className={
                        message.role === "user"
                          ? "rounded-2xl border border-black/5 bg-white/90 p-4 shadow-sm"
                          : "rounded-2xl border border-black/5 bg-white/55 p-4 shadow-sm shadow-black/5"
                      }
                    >
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-black/45">
                        {formatSpeakerLabel(message, user?.username ?? null)}
                      </div>
                      {message.role === "assistant" && message.thinking ? (
                        <div className="mb-3">
                          <button
                            type="button"
                            onClick={() => setThinkingExpandedByIndex((current: Record<number, boolean>) => ({ ...current, [index]: !current[index] }))}
                            className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-xs font-medium text-black/40 hover:bg-black/5"
                          >
                            <span className="flex-1">
                              {message.phase === "thinking" ? (
                                <span className="animate-pulse">Thinking...</span>
                              ) : (
                                formatThoughtLabel(message.thinkingElapsedSeconds ?? null)
                              )}
                            </span>
                            <i
                              className={`bi bi-chevron-down shrink-0 text-[14px] leading-none transition-transform ${thinkingExpandedByIndex[index] ? "rotate-180" : ""}`}
                              aria-hidden="true"
                            />
                          </button>
                          {thinkingExpandedByIndex[index] ? (
                            <div className="ml-2 mt-1 border-l-2 border-dashed border-amber-300/60 pl-3">
                              <div className="whitespace-pre-wrap text-[13px] leading-6 text-black/40 italic">
                                {message.thinking}
                                {(message.phase === "streaming" || message.phase === "thinking") && !message.content ? (
                                  <span className="ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-amber/50 align-middle" />
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="min-w-0 max-w-full leading-7 text-[15px] text-black/85">
                        {message.role === "assistant" ? (
                          <MessageContent
                            content={message.content}
                            showStreamingCursor={message.phase === "streaming" && Boolean(message.content)}
                          />
                        ) : (
                          <span className="whitespace-pre-wrap">{message.content}</span>
                        )}
                      </div>
                      {message.role === "assistant" && message.phase === "complete" && message.stats ? (
                        <div className="mt-3 border-t border-black/8 pt-2 text-[11px] text-black/45">
                          {(() => {
                            const tokenCount = formatInteger(message.stats.completionTokens ?? message.stats.totalTokens);
                            const tokenRate = formatRate(message.stats.tokensPerSecond);

                            return (
                              <>
                          <span
                            title={
                              message.stats.completionTokens !== null && message.stats.totalTokens !== null
                                ? `${formatInteger(message.stats.totalTokens)} total tokens`
                                : undefined
                            }
                          >
                            {tokenCount === "n/a" ? tokenCount : `${tokenCount}t`}
                          </span>
                          <span className="mx-2 text-black/20">/</span>
                          <span>{formatDuration(message.stats.elapsedSeconds)}</span>
                          <span className="mx-2 text-black/20">/</span>
                          <span className="font-medium text-black/55">{tokenRate === "n/a" ? tokenRate : `${tokenRate}t/s`}</span>
                              </>
                            );
                          })()}
                        </div>
                      ) : null}
                    </div>
                  )
                  ))}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={scrollTranscriptToBottom}
              className={`absolute bottom-4 right-4 flex h-11 w-11 items-center justify-center rounded-full border border-black/10 bg-ink text-white shadow-lg shadow-black/15 transition-all duration-150 ease-out hover:bg-black ${
                showScrollToBottom
                  ? "translate-y-0 scale-100 opacity-100"
                  : "pointer-events-none translate-y-2 scale-95 opacity-0"
              }`}
              aria-label="Scroll to latest message"
              title="Scroll to latest message"
            >
              <i className="bi bi-arrow-down text-[18px] leading-none" aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {!shouldShowNoModelsEmptyState ? (
          <form className={`${isNewChatEmptyState ? "mx-auto w-full max-w-xl" : "mt-4"} flex flex-col gap-2`} onSubmit={handleSubmit}>
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 rounded-xl border border-black/10 bg-black/5 p-2">
              {attachments.map((file, idx) => (
                <div key={idx} className="relative flex items-center gap-2 rounded-lg bg-white p-2 shadow-sm pr-8 text-xs font-semibold text-black/70">
                  {file.kind === "image" && file.dataUrl ? (
                    <img src={file.dataUrl} alt={file.name} className="h-8 w-8 rounded object-cover" />
                  ) : (
                    <span className="text-xl">📄</span>
                  )}
                  <div className="truncate max-w-[150px]">
                    <div className="truncate">{file.name}</div>
                    <div className="text-[10px] text-black/40" title={file.extractionDetail || undefined}>
                      {(file.size / 1024).toFixed(1)} KB • {describeAttachment(file)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeAttachment(idx)}
                    className="absolute right-1 top-1 rounded-full p-1 text-black/40 hover:bg-black/5 hover:text-black/80"
                    aria-label="Remove attachment"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                if (!selectedModelSupportsWebSearch) return;
                setUseWebSearch((current) => !current);
              }}
              disabled={isSending || isModelsUnavailable || !selectedModelSupportsWebSearch}
              className={`flex h-12 w-12 items-center justify-center rounded-xl border text-black transition disabled:opacity-50 ${!selectedModelSupportsWebSearch ? "border-black/20 bg-white" : useWebSearch ? "border-purple-700/70 bg-purple-700/15 text-black" : "border-black/20 bg-white hover:bg-black/5"}`}
              title={selectedModelSupportsWebSearch ? (useWebSearch ? "Disable Web Search" : "Enable Web Search") : "Web Search not available for this model"}
              aria-label={selectedModelSupportsWebSearch ? (useWebSearch ? "Disable Web Search" : "Enable Web Search") : "Web Search not available for this model"}
              aria-pressed={useWebSearch}
              aria-disabled={!selectedModelSupportsWebSearch}
            >
              <i className="bi bi-globe text-[18px] leading-none" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => {
                if (!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks) return;
                if (selectedModelAllowsThinkingPreference) {
                  setUseThinking((current) => !current);
                }
              }}
              disabled={isSending || isModelsUnavailable || (!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks)}
              className={`flex h-12 w-12 items-center justify-center rounded-xl border text-black transition disabled:opacity-50 ${!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks ? "border-black/20 bg-white" : useThinking ? "border-purple-700/70 bg-purple-700/15 text-black" : "border-black/20 bg-white hover:bg-black/5"}`}
              title={!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks ? "Thinking not available for this model" : selectedModelAlwaysThinks ? "Thinking enabled by default" : (useThinking ? "Disable Thinking" : "Enable Thinking")}
              aria-label={!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks ? "Thinking not available for this model" : selectedModelAlwaysThinks ? "Thinking enabled by default" : (useThinking ? "Disable Thinking" : "Enable Thinking")}
              aria-pressed={useThinking || selectedModelAlwaysThinks}
              aria-disabled={!selectedModelAllowsThinkingPreference && !selectedModelAlwaysThinks}
            >
              <i className="bi bi-stars text-[18px] leading-none" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isSending || isModelsUnavailable}
              className="flex h-12 w-12 items-center justify-center rounded-xl border border-black/20 bg-white hover:bg-black/5 text-black disabled:opacity-50"
              title="Attach files"
            >
              <i className="bi bi-paperclip text-[20px] leading-none" aria-hidden="true" />
            </button>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              multiple
              className="hidden"
            />
            <input
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              disabled={isSending || isModelsUnavailable}
              className="flex-1 rounded-xl border border-black/20 bg-white px-4 py-3 text-sm h-12 disabled:opacity-50"
              placeholder={inputPlaceholder}
            />
            {isSending ? (
              <button
                type="button"
                onClick={() => abortControllerRef.current?.abort()}
                className="rounded-xl bg-red-500 px-4 h-12 text-sm font-semibold text-white hover:bg-red-600"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!selectedModel || (!input.trim() && attachments.length === 0)}
                className="rounded-xl bg-amber px-4 h-12 text-sm font-semibold text-black disabled:opacity-50"
              >
                Send
              </button>
            )}
          </div>
          </form>
        ) : null}
      </main>
    </section>
  );
}

const THINKING_MARKUP_BLOCK =
  /<\|?(?:think|thinking|redacted_thinking)\|?>[\s\S]*?<\/\|?(?:think|thinking|redacted_thinking)\|?>/gi;
const EMPTY_THINKING_MARKUP_PAIR =
  /<\|?(?:think|thinking|redacted_thinking)\|?>\s*<\/\|?(?:think|thinking|redacted_thinking)\|?>/gi;

function stripThinkingMarkupFromText(text: string): string {
  return text.replace(THINKING_MARKUP_BLOCK, "").replace(EMPTY_THINKING_MARKUP_PAIR, "");
}

async function streamCompletion(
  model: string,
  messages: { role: ChatRole; content: ChatMessageContent }[],
  useWebSearch: boolean,
  enableThinking: boolean,
  signal: AbortSignal,
  onStageChange: (phase: "thinking") => void,
  onDelta: (delta: string, type: "thinking" | "content") => void
): Promise<ChatCompletionStats> {
  type StreamDelta = {
    content?: string;
    reasoning_content?: string;
    reasoning?: string;
    thought?: string;
  };

  const token = getStoredToken() || undefined;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const startedAt = performance.now();

  let response: Response;

  try {
    response = await fetch(`${BASE_URL}/v1/chat/completions`, {
      method: "POST",
      headers,
      signal,
      body: JSON.stringify({ model, messages, stream: true, use_web_search: useWebSearch, enable_thinking: enableThinking })
    });
  } catch (error) {
    handleBackendUnavailableError(error);
  }

  if (isBackendUnavailableResponse(response.status)) {
    handleBackendUnavailableError(new TypeError("Backend unavailable"));
  }

  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  if (enableThinking) {
    onStageChange("thinking");
  }

  if (!response.body) {
    throw new Error("Streaming response has no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let usage: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  } | null = null;
  while (true) {
    if (signal.aborted) {
      await reader.cancel();
      throw new DOMException("Aborted", "AbortError");
    }
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");

    let separatorIndex = buffer.indexOf("\n\n");
    while (separatorIndex !== -1) {
      const event = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      separatorIndex = buffer.indexOf("\n\n");

      for (const line of event.split("\n")) {
        if (!line.startsWith("data:")) {
          continue;
        }
        const data = line.slice(5).trim();
        if (!data || data === "[DONE]") {
          continue;
        }
        try {
          const parsed = JSON.parse(data) as {
            error?: { message?: string };
            model?: string;
            choices?: { delta?: StreamDelta }[];
            usage?: {
              prompt_tokens?: number;
              completion_tokens?: number;
              total_tokens?: number;
            };
          };
          if (parsed.error?.message) {
            throw new Error(parsed.error.message);
          }
          if (parsed.usage) {
            usage = parsed.usage;
          }
          const delta = parsed.choices?.[0]?.delta;
          const deltaContent = delta?.content;
          const deltaThinking = delta?.reasoning_content || delta?.reasoning || delta?.thought;
          if (deltaThinking && enableThinking) {
            onDelta(deltaThinking, "thinking");
          } else if (deltaContent) {
            onDelta(enableThinking ? deltaContent : stripThinkingMarkupFromText(deltaContent), "content");
          }
        } catch (error) {
          if (error instanceof Error) {
            throw error;
          }
          // ignore malformed chunks
        }
      }
    }

    if (done) {
      break;
    }
  }

  // Process any remaining buffer content that lacked a trailing double-newline
  // (can happen when the TCP connection closes before the final \n\n is received).
  if (buffer.trim()) {
    for (const line of buffer.split("\n")) {
      if (!line.startsWith("data:")) {
        continue;
      }
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") {
        continue;
      }
      try {
        const parsed = JSON.parse(data) as {
          error?: { message?: string };
          model?: string;
          choices?: { delta?: StreamDelta }[];
          usage?: {
            prompt_tokens?: number;
            completion_tokens?: number;
            total_tokens?: number;
          };
        };
        if (parsed.error?.message) {
          throw new Error(parsed.error.message);
        }
        if (parsed.usage) {
          usage = parsed.usage;
        }
        const delta = parsed.choices?.[0]?.delta;
        const deltaContent = delta?.content;
        const deltaThinking = delta?.reasoning_content || delta?.reasoning || delta?.thought;
        if (deltaThinking && enableThinking) {
          onDelta(deltaThinking, "thinking");
        } else if (deltaContent) {
          onDelta(enableThinking ? deltaContent : stripThinkingMarkupFromText(deltaContent), "content");
        }
      } catch (error) {
        if (error instanceof Error) {
          throw error;
        }
        // ignore malformed chunks
      }
    }
  }

  const elapsedSeconds = Math.max((performance.now() - startedAt) / 1000, 0.001);
  const completionTokens = usage?.completion_tokens ?? null;

  return {
    model,
    elapsedSeconds,
    promptTokens: usage?.prompt_tokens ?? null,
    completionTokens,
    totalTokens: usage?.total_tokens ?? null,
    tokensPerSecond: completionTokens !== null ? completionTokens / elapsedSeconds : null,
  };
}

function buildUserMessageContent(inputText: string, attachments: Attachment[]): { displayContent: string; apiContent: ChatMessageContent } {
  if (attachments.length === 0) {
    return { displayContent: inputText, apiContent: inputText };
  }

  const displaySegments: string[] = [];
  const contentParts: ChatContentPart[] = [];
  const introText = inputText || "Analyze the attached file(s).";

  displaySegments.push(introText);
  contentParts.push({ type: "text", text: introText });

  for (const file of attachments) {
    if (file.content) {
      const displayAttachmentText = formatAttachmentLabel(file);
      const attachmentText = `${displayAttachmentText}\n\`\`\`\n${file.content}\n\`\`\``;
      displaySegments.push(displayAttachmentText);
      contentParts.push({ type: "text", text: attachmentText });
      continue;
    }

    if (file.type.startsWith("image/") && file.dataUrl) {
      displaySegments.push(`[Attached Image: ${file.name} (${formatAttachmentSize(file.size)})]`);
      contentParts.push({ type: "image_url", image_url: { url: file.dataUrl } });
      continue;
    }

    const fallbackText = formatAttachmentFallbackText(file);
    displaySegments.push(fallbackText);
    contentParts.push({ type: "text", text: fallbackText });
  }

  const containsImage = attachments.some((file) => file.kind === "image" && file.dataUrl);
  const containsHiddenAttachmentContent = attachments.some((file) => Boolean(file.content));
  return {
    displayContent: displaySegments.join("\n\n"),
    apiContent: containsImage || containsHiddenAttachmentContent ? contentParts : displaySegments.join("\n\n"),
  };
}

function formatSpeakerLabel(message: ChatMessage, username: string | null): string {
  if (message.role === "user") {
    return username || "User";
  }

  if (message.role === "assistant") {
    return message.modelName || message.stats?.model || "Assistant";
  }

  return message.role;
}

function formatInteger(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "n/a";
  }

  return new Intl.NumberFormat().format(value);
}

function formatRate(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "n/a";
  }

  return value >= 100 ? value.toFixed(0) : value.toFixed(1);
}

function formatDuration(value: number): string {
  if (Number.isNaN(value) || value < 0) {
    return "n/a";
  }

  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)}s`;
}

function formatThoughtLabel(value: number | null): string {
  if (value === null || Number.isNaN(value) || value < 0) {
    return "Thought";
  }

  const rounded = value >= 10 ? value.toFixed(1) : value.toFixed(2);
  return `Thought for ${rounded} ${Number(rounded) === 1 ? "second" : "seconds"}`;
}
