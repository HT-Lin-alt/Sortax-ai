import { Check, FileText } from "lucide-react";

import type { components } from "../api/generated-types";
import { CitationList } from "./CitationList";
import { hasValidChecklistCitations } from "./citation-validation";
import styles from "./messages.module.css";

type Checklist = components["schemas"]["DocumentChecklistContent"];
type Citation = components["schemas"]["Citation"];

export function DocumentChecklistMessage({ content, citations }: { content: Checklist; citations: readonly Citation[] }) {
  if (!hasValidChecklistCitations(content, citations)) {
    return <article className={styles.featureCard} role="alert"><h2>Source information is incomplete</h2><p>This checklist could not be verified. Please generate it again.</p></article>;
  }
  return (
    <article className={styles.checklistCard}>
      <header className={styles.cardHeader}>
        <div><p className={styles.eyebrow}>Personalised checklist</p><h2>Documents to gather</h2></div>
        <span className={styles.documentCount}>{content.items.length}</span>
      </header>
      <p className={styles.cardIntro}>Based on your answers for the {content.tax_year} tax year.</p>
      <ol className={styles.checklist}>
        {content.items.map((item) => (
          <li key={item.id}>
            <div aria-hidden="true" className={styles.fileIcon}><FileText size={19} /></div>
            <div className={styles.checklistBody}>
              <div className={styles.checklistTitle}><h3>{item.document_name}</h3><span><Check size={13} />Relevant</span></div>
              <p>{item.plain_language_explanation}</p>
              <dl>
                <div><dt>How to get it</dt><dd>{item.how_to_obtain}</dd></div>
                <div><dt>Why it applies</dt><dd>{item.applies_because}</dd></div>
              </dl>
              <CitationList citations={citations} ordinals={item.citation_ordinals} />
            </div>
          </li>
        ))}
      </ol>
    </article>
  );
}
