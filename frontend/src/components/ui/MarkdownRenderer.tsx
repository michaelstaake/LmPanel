import { useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

type MarkdownRendererProps = {
  content: string;
  className?: string;
};

export default function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  const [copyStates, setCopyStates] = useState<Record<number, "idle" | "copied">>({});
  const codeRefs = useRef<Map<number, HTMLPreElement>>(new Map());
  let blockCounter = 0;

  const handleCopy = (index: number) => {
    const preEl = codeRefs.current.get(index);
    if (!preEl) return;

    const codeEl = preEl.querySelector(".hljs");
    const text = codeEl?.textContent || "";

    void navigator.clipboard.writeText(text).then(() => {
      setCopyStates((prev) => ({ ...prev, [index]: "copied" }));
      setTimeout(() => {
        setCopyStates((prev) => ({ ...prev, [index]: "idle" }));
      }, 2000);
    });
  };

  const components: Components = {
    pre: (props) => {
      const { children, ...rest } = props;
      const index = blockCounter++;
      return (
        <pre
          ref={(el) => {
            if (el) codeRefs.current.set(index, el);
            else codeRefs.current.delete(index);
          }}
          className="my-3 w-full max-w-full overflow-hidden rounded-2xl border border-black/10 bg-ink text-sand shadow-sm first:mt-0 last:mb-0"
          {...rest}
        >
          <div className="max-h-[24rem] overflow-y-auto">
            <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-white/10 bg-ink/95 px-4 py-2 text-[11px] uppercase tracking-[0.18em] text-sand/55 backdrop-blur-sm">
              <span>code</span>
              <button
                type="button"
                onClick={() => handleCopy(index)}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-semibold tracking-[0.12em] text-sand/70 transition hover:bg-white/10 hover:text-sand"
                aria-label="Copy code"
                title="Copy code"
              >
                <i className="bi bi-clipboard text-[14px] leading-none" aria-hidden="true"></i>
                <span>{copyStates[index] === "copied" ? "Copied" : "Copy"}</span>
              </button>
            </div>
            <pre className="max-w-full overflow-x-auto px-4 py-4 text-[13px] leading-6 text-sand/95">
              {children}
            </pre>
          </div>
        </pre>
      );
    },
    code: (props) => {
      const { children, className, ...rest } = props;
      return (
        <code className={className} {...rest}>
          {children}
        </code>
      );
    },
  };

  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
