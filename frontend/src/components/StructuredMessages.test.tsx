import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  checklistFixture,
  citationsFixture,
  completedQuestionnaireFixture,
  questionnaireFixture,
  taxSummaryFixture,
} from "../test/fixtures/showcase";
import { DocumentChecklistMessage } from "./DocumentChecklistMessage";
import { QuestionnaireMessage } from "./QuestionnaireMessage";
import { QuestionList } from "./QuestionList";
import { SummaryConfirmationMessage } from "./SummaryConfirmationMessage";
import { TaxSummaryMessage } from "./TaxSummaryMessage";

describe("structured message previews", () => {
  it("renders the current questionnaire step and selected option", () => {
    render(<QuestionnaireMessage content={questionnaireFixture} />);

    expect(screen.getByRole("heading", { name: "A few details first" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
    expect(screen.getByRole("checkbox", { name: "Working from home" })).toBeChecked();
  });

  it("keeps None mutually exclusive and saves the selected answer", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(questionnaireFixture.tax_intake);
    render(<QuestionnaireMessage content={questionnaireFixture} onSave={onSave} />);

    await user.click(screen.getByRole("checkbox", { name: "None of these" }));
    expect(screen.getByRole("checkbox", { name: "Working from home" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Car and travel" }));
    expect(screen.getByRole("checkbox", { name: "None of these" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(onSave).toHaveBeenCalledWith("work_expenses", ["work_related_car"]);
  });

  it("renders a compact completed question list", () => {
    render(<QuestionList content={completedQuestionnaireFixture} />);

    expect(screen.getByRole("heading", { name: "Your answers" })).toBeInTheDocument();
    expect(screen.getByText("Salary or wages, Australian bank interest")).toBeInTheDocument();
  });

  it("renders every checklist item with an HTTPS ATO citation", () => {
    render(<DocumentChecklistMessage citations={citationsFixture} content={checklistFixture} />);

    const items = screen.getAllByRole("listitem").filter((item) => within(item).queryByRole("heading") !== null);
    expect(items).toHaveLength(3);
    for (const item of items) {
      const source = within(item).getByRole("link");
      expect(source).toHaveAttribute("href", expect.stringMatching(/^https:\/\/www\.ato\.gov\.au\//));
      expect(source).toHaveAttribute("rel", "noopener noreferrer");
    }
  });

  it("fails closed when a checklist item has no valid citation", () => {
    const invalidChecklist = {
      ...checklistFixture,
      items: checklistFixture.items.map((item, index) => index === 0 ? { ...item, citation_ordinals: [] } : item),
    };
    render(<DocumentChecklistMessage citations={citationsFixture} content={invalidChecklist} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/source information is incomplete/i);
    expect(screen.queryByRole("heading", { name: "Documents to gather" })).not.toBeInTheDocument();
  });

  it("submits one explicit summary decision and disables both actions while busy", async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<SummaryConfirmationMessage content={checklistFixture.summary_confirmation} onDecision={onDecision} />);

    await user.click(screen.getByRole("button", { name: "Yes, create summary" }));
    expect(onDecision).toHaveBeenCalledWith(true);
    rerender(<SummaryConfirmationMessage busy content={checklistFixture.summary_confirmation} onDecision={onDecision} />);
    expect(screen.getByRole("button", { name: "No, thanks" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Yes, create summary" })).toBeDisabled();
  });

  it("submits an explicit summary decline", async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn().mockResolvedValue(undefined);
    render(<SummaryConfirmationMessage content={checklistFixture.summary_confirmation} onDecision={onDecision} />);

    await user.click(screen.getByRole("button", { name: "No, thanks" }));
    expect(onDecision).toHaveBeenCalledOnce();
    expect(onDecision).toHaveBeenCalledWith(false);
  });

  it("renders sourced summary sections and disclaimer", () => {
    render(<TaxSummaryMessage citations={citationsFixture} content={taxSummaryFixture} />);

    expect(screen.getByRole("heading", { name: "Tax information summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Income to review" })).toBeInTheDocument();
    expect(screen.getByText(/not personal tax or financial advice/i)).toBeInTheDocument();
  });

  it("renders markdown headings and inline bullet lists inside tax summary sections", () => {
    const markdownSummary = {
      ...taxSummaryFixture,
      sections: [
        {
          heading: "Overview",
          plain_language_text: "**Known Facts** * First tax return. * Salary and wages. **Document Requirements**\n*\nKeep your records.",
          citation_ordinals: [1],
        },
      ],
    };
    render(<TaxSummaryMessage citations={citationsFixture} content={markdownSummary} />);

    expect(screen.getByText("Known Facts")).toHaveProperty("tagName", "STRONG");
    expect(screen.getByText("Document Requirements")).toHaveProperty("tagName", "STRONG");
    const markdownList = screen.getByText("First tax return.").closest("ul");
    expect(markdownList).not.toBeNull();
    expect(within(markdownList as HTMLElement).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByText(/\*\*Known Facts\*\*/)).not.toBeInTheDocument();
    expect(screen.queryByText("*")).not.toBeInTheDocument();
  });
});
