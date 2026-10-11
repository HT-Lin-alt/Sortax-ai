import { expect, test } from "@playwright/test";

import type { components } from "../src/api/generated-types";
import { checklistFixture, citationsFixture, questionnaireFixture } from "../src/test/fixtures/showcase";

test("renders the complete F1 fixture timeline", async ({ page }) => {
  await page.route("**/health/live", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });
  await page.goto("/?fixtures=1");

  await expect(page.getByRole("heading", { name: "Sortax" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A few details first" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Documents to gather" })).toBeAttached();
  await expect(page.getByRole("heading", { name: "Tax information summary" })).toBeAttached();
  await expect(page.getByLabel("Message Sortax")).toBeDisabled();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
});

for (const viewport of [
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 484, height: 1024 },
]) {
  test(`matches the ${String(viewport.width)}x${String(viewport.height)} visual baseline`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.route("**/health/live", async (route) => {
      await route.fulfill({ json: { status: "ok" } });
    });
    await page.goto("/?fixtures=1");
    await expect(page.getByRole("heading", { name: "Sortax" })).toBeVisible();
    await expect(page).toHaveScreenshot(`f1-${String(viewport.width)}x${String(viewport.height)}.png`, {
      animations: "disabled",
      caret: "hide",
      fullPage: true,
    });
  });
}

test("starts a conversation and completes ordinary streamed chat", async ({ page }) => {
  const conversationId = "44444444-4444-4444-8444-444444444444";
  let sent = false;
  const greeting = message("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", conversationId, "assistant", "Hi, I’m Sortax. How can I help today?");
  const user = message("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", conversationId, "user", "What records should I keep?");
  const answer = message("cccccccc-cccc-4ccc-8ccc-cccccccccccc", conversationId, "assistant", "Keep records that support the income and deductions in your return.");

  await page.route("**/health/live", async (route) => { await route.fulfill({ json: { status: "ok" } }); });
  await page.route("**/api/v1/dev/token", async (route) => {
    await route.fulfill({ status: 201, json: { access_token: "test-token", token_type: "bearer", expires_in: 3600 } });
  });
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ json: { user_id: "11111111-1111-4111-8111-111111111111", tenant_id: "22222222-2222-4222-8222-222222222222", role: "user" } });
  });
  await page.route("**/api/v1/conversations", async (route) => {
    await route.fulfill({ status: 201, json: { id: conversationId, title: "Tax organiser", status: "active", last_message_at: null, created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z", expires_at: "2026-11-12T00:00:00Z", version: 1 } });
  });
  await page.route(`**/api/v1/conversations/${conversationId}/start`, async (route) => {
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: streamFor("Hi, I’m Sortax. How can I help today?") });
  });
  await page.route(`**/api/v1/conversations/${conversationId}/messages*`, async (route) => {
    if (route.request().method() === "POST") {
      sent = true;
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: streamFor("Keep records that support the income and deductions in your return.") });
      return;
    }
    await route.fulfill({ json: { items: sent ? [greeting, user, answer] : [greeting], next_cursor: null } });
  });

  await page.goto("/");
  await expect(page.getByText("Hi, I’m Sortax. How can I help today?")).toBeVisible();
  const composer = page.getByLabel("Message Sortax");
  await expect(composer).toBeEnabled();
  await composer.fill("What records should I keep?");
  await composer.press("Enter");
  await expect(page.getByText("Keep records that support the income and deductions in your return.")).toBeVisible();
  await expect(page.getByLabel("Send message")).toBeDisabled();
});

test("restores and completes the three-step tax questionnaire", async ({ page }) => {
  const conversationId = "44444444-4444-4444-8444-444444444444";
  let intake: components["schemas"]["TaxIntake"] = {
    ...questionnaireFixture.tax_intake,
    status: "questionnaire_active",
    current_step: 1,
    answers: [],
    version: 1,
  };
  let checklistReady = false;
  const questionnaireMessage = structuredMessage(
    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    conversationId,
    "questionnaire",
    { type: "questionnaire", tax_intake: intake },
    [],
  );
  const checklistMessage = structuredMessage(
    "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    conversationId,
    "document_checklist",
    checklistFixture,
    citationsFixture,
  );

  await page.addInitScript((id) => { localStorage.setItem("sortax.recentConversationId", id); }, conversationId);
  await page.route("**/health/live", async (route) => { await route.fulfill({ json: { status: "ok" } }); });
  await page.route("**/api/v1/dev/token", async (route) => {
    await route.fulfill({ status: 201, json: { access_token: "test-token", token_type: "bearer", expires_in: 3600 } });
  });
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ json: { user_id: "11111111-1111-4111-8111-111111111111", tenant_id: "22222222-2222-4222-8222-222222222222", role: "user" } });
  });
  await page.route(`**/api/v1/conversations/${conversationId}/messages*`, async (route) => {
    await route.fulfill({ json: { items: checklistReady ? [questionnaireMessage, checklistMessage] : [questionnaireMessage], next_cursor: null } });
  });
  await page.route(`**/api/v1/tax-intakes/${intake.id}`, async (route) => {
    await route.fulfill({ json: intake });
  });
  await page.route(`**/api/v1/tax-intakes/${intake.id}/answers/*`, async (route) => {
    const questionKey = route.request().url().split("/").at(-1);
    const body = await route.request().postDataJSON() as { selected_options: string[]; version: number };
    if (questionKey === "first_tax_return") {
      expect(body).toEqual({ selected_options: ["no"], version: 1 });
      intake = withAnswer(intake, "first_tax_return", ["no"], 2, 2);
      await route.fulfill({
        status: 409,
        json: { error: { code: "invalid_workflow_state", message: "The questionnaire changed.", request_id: "conflict-1", retryable: false, details: {} } },
      });
      return;
    }
    if (questionKey === "work_expenses") {
      expect(body).toEqual({ selected_options: ["working_from_home"], version: 2 });
      intake = withAnswer(intake, "work_expenses", ["working_from_home"], 3, 3);
      await route.fulfill({ json: intake });
      return;
    }
    expect(body).toEqual({ selected_options: ["salary_wages", "australian_bank_interest"], version: 3 });
    intake = withAnswer(intake, "income_sources", ["salary_wages", "australian_bank_interest"], 3, 4);
    await route.fulfill({ json: intake });
  });
  await page.route(`**/api/v1/tax-intakes/${intake.id}/complete`, async (route) => {
    expect(await route.request().postDataJSON()).toEqual(expect.objectContaining({ version: 4 }));
    checklistReady = true;
    intake = { ...intake, status: "checklist_ready", version: 5, completed_at: "2026-10-12T01:00:00Z" };
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: checklistStream() });
  });

  await page.goto("/");
  await expect(page.getByText("Is this your first Australian tax return?")).toBeVisible();
  await page.getByRole("radio", { name: "No, I have lodged before" }).click();
  await page.getByRole("button", { name: /continue/i }).click();
  await expect(page.getByText("Which work-related expenses did you have?")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Which work-related expenses did you have?")).toBeVisible();
  await page.getByRole("checkbox", { name: "Working from home" }).click();
  await page.getByRole("button", { name: /continue/i }).click();
  await expect(page.getByText("Which income did you receive?")).toBeVisible();
  await page.getByRole("checkbox", { name: "Salary or wages" }).click();
  await page.getByRole("checkbox", { name: "Australian bank interest" }).click();
  await page.getByRole("button", { name: /find my documents/i }).click();

  await expect(page.getByRole("heading", { name: "Documents to gather" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your answers" })).toBeAttached();
});

function streamFor(text: string): string {
  return [
    `event: generation.started\nid: 1\ndata: {"generation_id":"99999999-9999-4999-8999-999999999999","message_id":"88888888-8888-4888-8888-888888888888"}\n\n`,
    `event: message.delta\nid: 2\ndata: ${JSON.stringify({ generation_id: "99999999-9999-4999-8999-999999999999", message_id: "88888888-8888-4888-8888-888888888888", seq: 1, delta: text })}\n\n`,
    `event: message.completed\nid: 3\ndata: {"generation_id":"99999999-9999-4999-8999-999999999999","message_id":"88888888-8888-4888-8888-888888888888","content_type":"text","structured_content":null,"completion_kind":"general_chat","grounded":false,"citations":[]}\n\n`,
  ].join("");
}

function message(id: string, conversationId: string, role: "assistant" | "user", content: string) {
  return { id, conversation_id: conversationId, role, content, content_type: "text", structured_content: null, status: "completed", grounded: false, citation_count: 0, citations: [], created_at: "2026-10-12T00:00:00Z", completed_at: "2026-10-12T00:00:01Z" };
}

function structuredMessage(
  id: string,
  conversationId: string,
  contentType: components["schemas"]["MessageContentType"],
  structuredContent: components["schemas"]["Message"]["structured_content"],
  citations: readonly components["schemas"]["Citation"][],
) {
  return {
    id,
    conversation_id: conversationId,
    role: "assistant" as const,
    content: "",
    content_type: contentType,
    structured_content: structuredContent,
    status: "completed" as const,
    grounded: citations.length > 0,
    citation_count: citations.length,
    citations,
    created_at: "2026-10-12T00:00:00Z",
    completed_at: "2026-10-12T00:00:01Z",
  };
}

function withAnswer(
  intake: components["schemas"]["TaxIntake"],
  questionKey: string,
  selectedOptions: readonly string[],
  currentStep: number,
  version: number,
): components["schemas"]["TaxIntake"] {
  return {
    ...intake,
    current_step: currentStep,
    version,
    updated_at: "2026-10-12T00:30:00Z",
    answers: [
      ...intake.answers.filter((answer) => answer.question_key !== questionKey),
      { question_key: questionKey, selected_options: selectedOptions, updated_at: "2026-10-12T00:30:00Z" },
    ],
  };
}

function checklistStream(): string {
  return [
    `event: generation.started\nid: 1\ndata: {"generation_id":"77777777-7777-4777-8777-777777777777","message_id":"eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}\n\n`,
    `event: retrieval.started\nid: 2\ndata: {"retrieval_run_id":"66666666-6666-4666-8666-666666666666","claim_types":["salary_wages","working_from_home","australian_bank_interest"],"tax_year":"2025-26"}\n\n`,
    `event: retrieval.completed\nid: 3\ndata: {"retrieval_run_id":"66666666-6666-4666-8666-666666666666","status":"completed","collection_name":"ato_knowledge_demo","retrieval_config_version":"demo-v1","candidate_count":6,"selected_count":3}\n\n`,
    `event: message.completed\nid: 4\ndata: ${JSON.stringify({ generation_id: "77777777-7777-4777-8777-777777777777", message_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", content_type: "document_checklist", structured_content: checklistFixture, completion_kind: "document_checklist", grounded: true, citations: citationsFixture })}\n\n`,
  ].join("");
}
