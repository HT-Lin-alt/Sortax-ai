import type { ReactNode } from "react";

interface SafeMarkdownProps {
  readonly children: string;
}

export function SafeMarkdown({ children }: SafeMarkdownProps) {
  const lines = normalize(children).split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading !== null) {
      const content = renderInline(heading[2] ?? "", `heading-${String(index)}`);
      blocks.push(heading[1]?.length === 1
        ? <h2 key={`block-${String(blocks.length)}`}>{content}</h2>
        : <h3 key={`block-${String(blocks.length)}`}>{content}</h3>);
      index += 1;
      continue;
    }

    const unordered = collectList(lines, index, /^\s*[-+*]\s+(.+)$/);
    if (unordered !== null) {
      blocks.push(<ul key={`block-${String(blocks.length)}`}>{unordered.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `ul-${String(index)}-${String(itemIndex)}`)}</li>)}</ul>);
      index = unordered.nextIndex;
      continue;
    }

    const ordered = collectList(lines, index, /^\s*\d+[.)]\s+(.+)$/);
    if (ordered !== null) {
      blocks.push(<ol key={`block-${String(blocks.length)}`}>{ordered.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `ol-${String(index)}-${String(itemIndex)}`)}</li>)}</ol>);
      index = ordered.nextIndex;
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const candidate = lines[index] ?? "";
      if (candidate.trim() === "" || isBlockStart(candidate)) break;
      paragraphLines.push(candidate);
      index += 1;
    }
    blocks.push(
      <p key={`block-${String(blocks.length)}`}>
        {paragraphLines.map((paragraphLine, lineIndex) => (
          <span key={lineIndex}>{lineIndex === 0 ? null : <br />}{renderInline(paragraphLine, `p-${String(index)}-${String(lineIndex)}`)}</span>
        ))}
      </p>,
    );
  }

  return <>{blocks}</>;
}

function normalize(value: string): string {
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/\\([\\`*_[\]()>#+.!-])/g, "$1")
    .replace(/\*{3,}/g, "**")
    .replace(/\s+(?=\*\*[A-Z][^*\n]{2,80}\*\*)/g, "\n\n")
    .replace(/[ \t]+\*[ \t]+(?=\S)/g, "\n- ")
    .replace(/^\s*\*\s*$/gm, "");
}

function isBlockStart(line: string): boolean {
  return /^(#{1,6})\s+/.test(line) || /^\s*[-+*]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line);
}

function collectList(lines: readonly string[], startIndex: number, pattern: RegExp) {
  const items: string[] = [];
  let nextIndex = startIndex;
  while (nextIndex < lines.length) {
    const match = pattern.exec(lines[nextIndex] ?? "");
    if (match === null) break;
    items.push(match[1] ?? "");
    nextIndex += 1;
  }
  return items.length === 0 ? null : { items, nextIndex };
}

function renderInline(value: string, keyPrefix: string): ReactNode[] {
  const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https:\/\/[^)\s]+\))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match = pattern.exec(value);
  while (match !== null) {
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`${keyPrefix}-${String(match.index)}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(<code key={`${keyPrefix}-${String(match.index)}`}>{token.slice(1, -1)}</code>);
    } else {
      const link = /^\[([^\]]+)\]\((https:\/\/[^)]+)\)$/.exec(token);
      if (link !== null) nodes.push(<a href={link[2]} key={`${keyPrefix}-${String(match.index)}`} rel="noopener noreferrer" target="_blank">{link[1]}</a>);
    }
    cursor = match.index + token.length;
    match = pattern.exec(value);
  }
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}
