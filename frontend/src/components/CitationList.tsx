import { ArrowUpRight } from "lucide-react";

import type { components } from "../api/generated-types";
import styles from "./messages.module.css";

type Citation = components["schemas"]["Citation"];

export function CitationList({ citations, ordinals }: { citations: readonly Citation[]; ordinals: readonly number[] }) {
  const visible = ordinals.flatMap((ordinal) => {
    const citation = citations.find((item) => item.ordinal === ordinal);
    return citation === undefined ? [] : [citation];
  });

  return (
    <ul aria-label="ATO sources" className={styles.citations}>
      {visible.map((citation) => (
        <li key={citation.ordinal}>
          <a href={citation.url} rel="noopener noreferrer" target="_blank">
            <span>{citation.ordinal}</span>{citation.title}<ArrowUpRight aria-hidden="true" size={13} />
          </a>
        </li>
      ))}
    </ul>
  );
}
