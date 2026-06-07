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
  className = "mt-4 space-y-2 text-sm text-black/70",
  listClassName = "max-h-[40vh] space-y-1 overflow-y-auto",
}: ChatSidebarContentProps) {
  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onNewChat}
          className="flex-1  bg-ink px-4 py-2 text-left text-sm font-semibold text-white transition hover:bg-black"
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
            className="flex h-10 w-10 items-center justify-center  border border-black/10 bg-white text-black/60 transition hover:border-black/20 hover:bg-black/5 hover:text-black"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <i className="bi bi-layout-sidebar-inset-reverse text-[16px] leading-none" aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {token ? (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-black/40">
            Chats {isLoadingChats ? "(loading...)" : `(${savedChats.length})`}
          </div>
          {savedChats.length === 0 && !isLoadingChats ? (
            <div className=" bg-black/5 p-2 text-xs text-black/50">
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
                  className={`flex-1 truncate  px-2 py-1 text-left text-xs hover:bg-black/5 ${
                    activeChatId === chat.id ? "bg-amber/30" : ""
                  }`}
                  title={chat.title}
                >
                  {chat.title || `Chat ${chat.id}`}
                </button>
                <button
                  type="button"
                  onClick={() => void onDeleteChat(chat.id)}
                  className=" px-2 py-1 text-xs text-black/40 hover:bg-red-50 hover:text-red-700"
                  aria-label="Delete chat"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className=" bg-black/5 p-2 text-xs text-black/60">
          Sign in via the <a className="font-semibold underline" href="/login">Login</a>{" "}
          page to save your chat history.
        </div>
      )}
    </div>
  );
}