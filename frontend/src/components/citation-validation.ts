import type { components } from "../api/generated-types";

type Citation = components["schemas"]["Citation"];
type Checklist = components["schemas"]["DocumentChecklistContent"];
type Summary = components["schemas"]["TaxSummaryContent"];

export function hasValidChecklistCitations(content: Checklist, citations: readonly Citation[]): boolean {
  return content.items.every((item) => item.citation_ordinals.length > 0 && item.citation_ordinals.every((ordinal) =>
    citations.some((citation) => citation.ordinal === ordinal && citation.tax_year === content.tax_year && isHttps(citation.url)),
  ));
}

export function hasValidSummaryCitations(content: Summary, citations: readonly Citation[]): boolean {
  return content.sections.every((section) => section.citation_ordinals.every((ordinal) =>
    citations.some((citation) => citation.ordinal === ordinal && citation.tax_year === content.tax_year && isHttps(citation.url)),
  ));
}

function isHttps(url: string): boolean {
  try { return new URL(url).protocol === "https:"; } catch { return false; }
}
