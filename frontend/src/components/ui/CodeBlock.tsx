import { useState } from "react";

type CodeBlockProps = {
  code: string;
  language?: string | null;
};

export default function CodeBlock({ code, language }: CodeBlockProps) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");

  async function handleCopy() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = code;
        textarea.setAttribute("readonly", "true");
        textarea.style.position = "absolute";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }

      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("error");
      window.setTimeout(() => setCopyState("idle"), 2000);
    }
  }

  return (
    <div className="my-3 w-full max-w-full overflow-hidden  border border-black/10 bg-ink text-sand shadow-sm first:mt-0 last:mb-0">
      <div className="max-h-[24rem] overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-white/10 bg-ink/95 px-4 py-2 text-[11px] uppercase tracking-[0.18em] text-sand/55 backdrop-blur-sm">
          <span>{language || "code"}</span>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="inline-flex items-center gap-1  px-2 py-1 text-[10px] font-semibold tracking-[0.12em] text-sand/70 transition hover:bg-white/10 hover:text-sand"
            aria-label="Copy code"
            title="Copy code"
          >
            <i className="bi bi-clipboard text-[14px] leading-none" aria-hidden="true" />
            <span>{copyState === "copied" ? "Copied" : copyState === "error" ? "Retry" : "Copy"}</span>
          </button>
        </div>
        <pre className="max-w-full overflow-x-auto px-4 py-4 text-[13px] leading-6 text-sand/95">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}