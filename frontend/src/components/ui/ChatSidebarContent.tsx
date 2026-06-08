type ChatSidebarContentProps = {
  token: string;
  isLoadingChats: boolean;
  savedChats: { id: number; title: string }[];
  activeChatId: number | null;
  onNewChat: () => void;
  onOpenChat: (chatId: number) => Promise<void>;
  onDeleteChat: (chatId: number) => Promise<void>;
  onCollapse?: () => void;
  onAfterSelectChat?: () => void;
  className?: string;
  listClassName?: string;
};

export default function ChatSidebarContent({
  token,
  isLoadingChats,
  savedChats,
  activeChatId,
  onNewChat,
  onOpenChat,
  onDeleteChat,
  onCollapse,
  onAfterSelectChat,
  className = "mt-4 space-y-2 text-sm text-sand/70",
  listClassName = "max-h-[40vh] space-y-1 overflow-y-auto",
}: ChatSidebarContentProps) {
  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onNewChat}
          className="flex-1  bg-sand px-4 py-2 text-left text-sm font-semibold text-canvas transition hover:bg-sand/80"
        >
          <span className="inline-flex items-center gap-2">
            <i className="bi bi-pencil-square text-[16px] leading-none" aria-hidden="true" />
            <span>New Chat</span>
          </span>
        </button>
        {onCollapse ? (
          <button
            type="button"
            onClick={onCollapse}
            className="flex h-10 w-10 items-center justify-center  btn-icon text-sand/70 transition hover:border-white/20 hover:bg-white/10 hover:text-sand"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <i className="bi bi-layout-sidebar-inset-reverse text-[16px] leading-none" aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {token ? (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-sand/40">
            Chats {isLoadingChats ? "(loading...)" : `(${savedChats.length})`}
          </div>
          {savedChats.length === 0 && !isLoadingChats ? (
            <div className="surface-muted p-2 text-xs text-sand/50">
              No chats to display.
            </div>
          ) : null}
          <ul className={listClassName}>
            {savedChats.map((chat) => (
              <li key={chat.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => {
                    onAfterSelectChat?.();
                    void onOpenChat(chat.id);
                  }}
                  className={`flex-1 truncate border border-transparent px-2 py-1 text-left text-xs text-sand/80 hover:border-white/10 hover:bg-white/10 ${
                    activeChatId === chat.id ? "border-amber/40 bg-amber/15 text-sand" : ""
                  }`}
                  title={chat.title}
                >
                  {chat.title || `Chat ${chat.id}`}
                </button>
                <button
                  type="button"
                  onClick={() => void onDeleteChat(chat.id)}
                  className="px-2 py-1 text-xs text-sand/40 hover:bg-red-500/15 hover:text-red-300"
                  aria-label="Delete chat"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="surface-muted p-2 text-xs text-sand/60">
          Sign in via the <a className="font-semibold underline" href="/login">Login</a>{" "}
          page to save your chat history.
        </div>
      )}
    </div>
  );
}