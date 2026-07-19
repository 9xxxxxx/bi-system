import type { RichTextBlock, RichTextBlockType, RichTextMark } from "./types";

const blockTypes = new Set<RichTextBlockType>([
  "heading",
  "paragraph",
  "bullet",
]);
const marks = new Set<RichTextMark>(["bold", "italic"]);

export function normalizeRichTextBlocks(config: {
  blocks?: unknown;
  content?: unknown;
}): RichTextBlock[] {
  if (Array.isArray(config.blocks)) {
    return config.blocks.flatMap((candidate: unknown) => {
      if (typeof candidate !== "object" || candidate === null) return [];
      const block = candidate as Record<string, unknown>;
      const type = block.type;
      if (
        typeof type !== "string" ||
        !blockTypes.has(type as RichTextBlockType) ||
        typeof block.text !== "string"
      ) {
        return [];
      }
      return [
        {
          type: type as RichTextBlockType,
          text: block.text,
          marks: Array.isArray(block.marks)
            ? block.marks.filter(
                (mark): mark is RichTextMark =>
                  typeof mark === "string" && marks.has(mark as RichTextMark),
              )
            : [],
        },
      ];
    });
  }
  return typeof config.content === "string" && config.content
    ? [{ type: "paragraph", text: config.content, marks: [] }]
    : [];
}
