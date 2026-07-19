import type { RichTextBlock, RichTextComponentConfig } from "./types";
import { normalizeRichTextBlocks } from "./richTextModel";

function MarkedText({ block }: { block: RichTextBlock }) {
  let content: React.ReactNode = block.text;
  if (block.marks.includes("bold")) content = <strong>{content}</strong>;
  if (block.marks.includes("italic")) content = <em>{content}</em>;
  return content;
}

export function RichTextBlocks({
  config,
}: {
  config: RichTextComponentConfig;
}) {
  const blocks = normalizeRichTextBlocks(config);
  if (blocks.length === 0)
    return <p className="dashboard-rich-text">暂无文本内容</p>;
  return (
    <div className="dashboard-rich-text">
      {blocks.map((block, index) => {
        const content = <MarkedText block={block} />;
        if (block.type === "heading")
          return <h3 key={`${index}:heading`}>{content}</h3>;
        if (block.type === "bullet")
          return (
            <ul key={`${index}:bullet`}>
              <li>{content}</li>
            </ul>
          );
        return <p key={`${index}:paragraph`}>{content}</p>;
      })}
    </div>
  );
}
