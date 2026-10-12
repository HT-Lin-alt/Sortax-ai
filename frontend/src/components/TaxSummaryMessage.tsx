import { BadgeCheck } from "lucide-react";

import type { components } from "../api/generated-types";
import { CitationList } from "./CitationList";
import { SafeMarkdown } from "./SafeMarkdown";
import { hasValidSummaryCitations } from "./citation-validation";
import styles from "./messages.module.css";

type TaxSummary = components["schemas"]["TaxSummaryContent"];
type Citation = components["schemas"]["Citation"];

export function TaxSummaryMessage({ content, citations }: { content: TaxSummary; citations: readonly Citation[] }) {
  if (!hasValidSummaryCitations(content, citations)) {
    return <article className={styles.featureCard} role="alert"><h2>Source information is incomplete</h2><p>This summary could not be verified.</p></article>;
  }
  return (
    <article className={styles.summaryCard}>
      <header>
        <span aria-hidden="true"><BadgeCheck size={22} /></span>
        <div><p className={styles.eyebrow}>Your {content.tax_year} overview</p><h2>Tax information summary</h2></div>
      </header>
      <div className={styles.summarySections}>
        {content.sections.map((section) => (
          <section key={section.heading}>
            <h3>{section.heading}</h3>
            <div className={styles.summaryMarkdown}><SafeMarkdown>{section.plain_language_text}</SafeMarkdown></div>
            <CitationList citations={citations} ordinals={section.citation_ordinals} />
          </section>
        ))}
      </div>
      <p className={styles.disclaimer}>{content.disclaimer}</p>
    </article>
  );
}
