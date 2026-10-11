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

  it("renders sourced summary sections and disclaimer", () => {
    render(<TaxSummaryMessage citations={citationsFixture} content={taxSummaryFixture} />);

    expect(screen.getByRole("heading", { name: "Tax information summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Income to review" })).toBeInTheDocument();
    expect(screen.getByText(/not personal tax or financial advice/i)).toBeInTheDocument();
  });
});
