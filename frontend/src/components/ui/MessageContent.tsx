import CodeBlock from "./CodeBlock";
import { parseMessageSegments } from "../../lib/codeBlockParser";

type MessageContentProps = {
  content: string;
  showStreamingCursor?: boolean;
};

export default function MessageContent({ content, showStreamingCursor = false }: MessageContentProps) {
  const segments = parseMessageSegments(content);

  return (
    <>
      {segments.map((segment, index) =>
        segment.type === "code" ? (
          <CodeBlock key={`code-${index}`} code={segment.content} language={segment.language} />
        ) : (
          <span key={`text-${index}`} className="whitespace-pre-wrap">
            {segment.content}
          </span>
        )
      )}
      {showStreamingCursor ? (
        <span className="ml-1 inline-block h-5 w-2 animate-pulse rounded-full bg-amber align-middle" />
      ) : null}
    </>
  );
}