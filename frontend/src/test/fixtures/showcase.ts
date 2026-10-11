import type { components } from "../../api/generated-types";

const intakeId = "33333333-3333-4333-8333-333333333333";
const conversationId = "44444444-4444-4444-8444-444444444444";

const questions = [
  {
    key: "first_tax_return",
    order: 1,
    prompt: "Is this your first Australian tax return?",
    question_type: "single",
    required: true,
    options: [
      { code: "yes", label: "Yes, this is my first return" },
      { code: "no", label: "No, I have lodged before" },
    ],
  },
  {
    key: "work_expenses",
    order: 2,
    prompt: "Which work-related expenses did you have?",
    question_type: "multiple",
    required: true,
    options: [
      { code: "working_from_home", label: "Working from home" },
      { code: "work_related_car", label: "Car and travel" },
      { code: "self_education", label: "Self-education" },
      { code: "none", label: "None of these" },
    ],
  },
  {
    key: "income_sources",
    order: 3,
    prompt: "Which income did you receive?",
    question_type: "multiple",
    required: true,
    options: [
      { code: "salary_wages", label: "Salary or wages" },
      { code: "residential_rental_property", label: "Residential rental property" },
      { code: "australian_bank_interest", label: "Australian bank interest" },
      { code: "none", label: "None of these" },
    ],
  },
] as const satisfies readonly components["schemas"]["TaxQuestion"][];

const baseIntake = {
  id: intakeId,
  conversation_id: conversationId,
  template_version: "limited-tax-2025-26-v1",
  tax_year: "2025-26",
  questions,
  version: 3,
  created_at: "2026-10-12T00:10:00Z",
  updated_at: "2026-10-12T00:14:00Z",
} as const;

export const questionnaireFixture = {
  type: "questionnaire",
  tax_intake: {
    ...baseIntake,
    status: "questionnaire_active",
    current_step: 2,
    answers: [
      {
        question_key: "first_tax_return",
        selected_options: ["no"],
        updated_at: "2026-10-12T00:12:00Z",
      },
      {
        question_key: "work_expenses",
        selected_options: ["working_from_home"],
        updated_at: "2026-10-12T00:14:00Z",
      },
    ],
  },
} satisfies components["schemas"]["QuestionnaireContent"];

export const completedQuestionnaireFixture = {
  type: "questionnaire",
  tax_intake: {
    ...baseIntake,
    status: "questionnaire_completed",
    current_step: 3,
    answers: [
      {
        question_key: "first_tax_return",
        selected_options: ["no"],
        updated_at: "2026-10-12T00:12:00Z",
      },
      {
        question_key: "work_expenses",
        selected_options: ["working_from_home"],
        updated_at: "2026-10-12T00:14:00Z",
      },
      {
        question_key: "income_sources",
        selected_options: ["salary_wages", "australian_bank_interest"],
        updated_at: "2026-10-12T00:16:00Z",
      },
    ],
    version: 4,
    updated_at: "2026-10-12T00:16:00Z",
    completed_at: "2026-10-12T00:16:00Z",
  },
} satisfies components["schemas"]["QuestionnaireContent"];

export const citationsFixture = [
  {
    ordinal: 1,
    claim_type: "salary_wages",
    title: "Income statement",
    url: "https://www.ato.gov.au/individuals-and-families/jobs-and-employment-types/income-from-more-than-one-job/income-statements",
    document_id: "ato-income-statement",
    content_hash: "fixture-income-statement",
    chunk_ids: ["income-statement-1"],
    tax_year: "2025-26",
    accessed_at: "2026-10-12",
  },
  {
    ordinal: 2,
    claim_type: "working_from_home",
    title: "Working from home expenses",
    url: "https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/deductions-you-can-claim/working-from-home-expenses",
    document_id: "ato-wfh-expenses",
    content_hash: "fixture-wfh-expenses",
    chunk_ids: ["wfh-1"],
    tax_year: "2025-26",
    accessed_at: "2026-10-12",
  },
  {
    ordinal: 3,
    claim_type: "australian_bank_interest",
    title: "Interest income",
    url: "https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/income-you-must-declare/investment-income/interest-income",
    document_id: "ato-interest-income",
    content_hash: "fixture-interest-income",
    chunk_ids: ["interest-1"],
    tax_year: "2025-26",
    accessed_at: "2026-10-12",
  },
] as const satisfies readonly components["schemas"]["Citation"][];

export const checklistFixture = {
  type: "document_checklist",
  tax_intake_id: intakeId,
  tax_year: "2025-26",
  items: [
    {
      id: "55555555-5555-4555-8555-555555555551",
      ordinal: 1,
      claim_type: "salary_wages",
      document_name: "Income statement",
      plain_language_explanation: "Shows the salary, tax withheld and employer details reported for you.",
      how_to_obtain: "Open myGov, go to ATO online services and check that the statement is tax ready.",
      applies_because: "You selected salary or wages as an income source.",
      citation_ordinals: [1],
    },
    {
      id: "55555555-5555-4555-8555-555555555552",
      ordinal: 2,
      claim_type: "working_from_home",
      document_name: "Working-from-home records",
      plain_language_explanation: "Supports the hours worked at home and the expenses included in your claim.",
      how_to_obtain: "Keep your hours diary plus invoices or bills used for your chosen calculation method.",
      applies_because: "You selected working from home in the guided questions.",
      citation_ordinals: [2],
    },
    {
      id: "55555555-5555-4555-8555-555555555553",
      ordinal: 3,
      claim_type: "australian_bank_interest",
      document_name: "Bank interest summary",
      plain_language_explanation: "Confirms the gross interest paid across your Australian bank accounts.",
      how_to_obtain: "Download the annual interest summary from each bank or compare it with ATO pre-fill.",
      applies_because: "You selected Australian bank interest as an income source.",
      citation_ordinals: [3],
    },
  ],
  summary_confirmation: {
    type: "summary_confirmation",
    tax_intake_id: intakeId,
    prompt: "Would you like a plain-language summary of your tax information?",
  },
} satisfies components["schemas"]["DocumentChecklistContent"];

export const taxSummaryFixture = {
  type: "tax_summary",
  tax_intake_id: intakeId,
  tax_year: "2025-26",
  sections: [
    {
      heading: "Income to review",
      plain_language_text: "Check your tax-ready income statement and confirm interest from every Australian bank account.",
      citation_ordinals: [1, 3],
    },
    {
      heading: "Deduction records",
      plain_language_text: "Keep a record of your working-from-home hours and the documents required by your calculation method.",
      citation_ordinals: [2],
    },
  ],
  disclaimer: "This is general information for organising records, not personal tax or financial advice.",
} satisfies components["schemas"]["TaxSummaryContent"];
