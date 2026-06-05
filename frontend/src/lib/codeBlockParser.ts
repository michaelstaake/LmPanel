export type MessageSegment =
  | {
      type: "text";
      content: string;
    }
  | {
      type: "code";
      content: string;
      language: string | null;
    };

export function parseMessageSegments(content: string): MessageSegment[] {
  if (!content.includes("```")) {
    return [{ type: "text", content }];
  }

  const fencePattern = /```([^\n`]*)\n([\s\S]*?)```/g;
  const segments: MessageSegment[] = [];
  let lastIndex = 0;

  for (const match of content.matchAll(fencePattern)) {
    const matchIndex = match.index ?? 0;
    const [fullMatch, rawLanguage, codeContent] = match;

    if (matchIndex > lastIndex) {
      segments.push({
        type: "text",
        content: content.slice(lastIndex, matchIndex),
      });
    }

    segments.push({
      type: "code",
      content: codeContent.replace(/\n$/, ""),
      language: rawLanguage.trim() || null,
    });

    lastIndex = matchIndex + fullMatch.length;
  }

  if (lastIndex < content.length) {
    segments.push({
      type: "text",
      content: content.slice(lastIndex),
    });
  }

  return segments.length > 0 ? segments : [{ type: "text", content }];
}