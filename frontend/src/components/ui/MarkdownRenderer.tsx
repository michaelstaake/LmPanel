import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

type MarkdownRendererProps = {
  content: string;
  className?: string;
};

const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [...(defaultSchema.attributes?.code ?? []), "className", "class"],
    span: [...(defaultSchema.attributes?.span ?? []), "className", "class"],
  },
};

function isSafeHref(href: string): boolean {
  const trimmed = href.trim();
  if (!trimmed || trimmed.startsWith("#")) {
    return true;
  }
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) {
    return true;
  }

  try {
    const url = new URL(trimmed);
    return url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:";
  } catch {
    return false;
  }
}

export default function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  const [copyStates, setCopyStates] = useState<Record<number, "idle" | "copied">>({});
  const codeRefs = useRef<Map<number, HTMLPreElement>>(new Map());
  const copyTimeoutsRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  let blockCounter = 0;

  useEffect(() => {
    const timeouts = copyTimeoutsRef.current;
    return () => {
      timeouts.forEach((timeoutId) => clearTimeout(timeoutId));
      timeouts.clear();
    };
  }, []);

  const handleCopy = (index: number) => {
    const preEl = codeRefs.current.get(index);
    if (!preEl) return;

    const codeEl = preEl.querySelector(".hljs");
    const text = codeEl?.textContent || "";

    void navigator.clipboard.writeText(text).then(() => {
      setCopyStates((prev) => ({ ...prev, [index]: "copied" }));
      const existingTimeout = copyTimeoutsRef.current.get(index);
      if (existingTimeout) {
        clearTimeout(existingTimeout);
      }
      const timeoutId = setTimeout(() => {
        setCopyStates((prev) => ({ ...prev, [index]: "idle" }));
        copyTimeoutsRef.current.delete(index);
      }, 2000);
      copyTimeoutsRef.current.set(index, timeoutId);
    });
  };

  const components: Components = {
    a: ({ href, children, ...rest }) => {
      if (!href || !isSafeHref(href)) {
        return <span>{children}</span>;
      }
      return (
        <a href={href} rel="noopener noreferrer" target="_blank" {...rest}>
          {children}
        </a>
      );
    },
    pre: (props) => {
      const { children, ...rest } = props;
      const index = blockCounter++;
      return (
        <pre
          ref={(el) => {
            if (el) codeRefs.current.set(index, el);
            else codeRefs.current.delete(index);
          }}
          className="my-3 w-full max-w-full overflow-hidden  border border-white/10 bg-ink text-sand shadow-sm first:mt-0 last:mb-0"
          {...rest}
        >
          <div className="max-h-[24rem] overflow-y-auto">
            <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-white/10 bg-ink/95 px-4 py-2 text-[11px] uppercase tracking-[0.18em] text-sand/55 backdrop-blur-sm">
              <span>code</span>
              <button
                type="button"
                onClick={() => handleCopy(index)}
                className="inline-flex items-center gap-1  px-2 py-1 text-[10px] font-semibold tracking-[0.12em] text-sand/70 transition hover:bg-white/10 hover:text-sand"
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
      const { children, className: codeClassName, ...rest } = props;
      return (
        <code className={codeClassName} {...rest}>
          {children}
        </code>
      );
    },
  };

  return (
    <div className={`markdown-content${className ? ` ${className}` : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight, [rehypeSanitize, sanitizeSchema]]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
