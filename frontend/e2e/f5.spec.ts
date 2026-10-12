import { expect, test } from "@playwright/test";

import type { components } from "../src/api/generated-types";
import { checklistFixture, citationsFixture, completedQuestionnaireFixture } from "../src/test/fixtures/showcase";

const conversationId = "44444444-4444-4444-8444-444444444444";

test("declines the optional summary without rendering a tax summary", async ({ page }) => {
  let declined = false;
  let requestBody: components["schemas"]["CreateTaxSummaryRequest"] | null = null;
  const intake = { ...completedQuestionnaireFixture.tax_intake, status: "awaiting_summary_confirmation" as const, version: 5 };
  const questionnaire = structuredMessage("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "questionnaire", completedQuestionnaireFixture, []);
  const checklist = structuredMessage("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "document_checklist", checklistFixture, citationsFixture);
  const confirmation = structuredMessage("cccccccc-cccc-4ccc-8ccc-cccccccccccc", "summary_confirmation", checklistFixture.summary_confirmation, []);
  const closing = textMessage("dddddddd-dddd-4ddd-8ddd-dddddddddddd", "assistant", "No summary was created. Your checklist remains available.", "clarification");

  await installSessionRoutes(page, () => declined ? [questionnaire, checklist, confirmation, closing] : [questionnaire, checklist, confirmation]);
  await page.route(`**/api/v1/tax-intakes/${intake.id}`, async (route) => {
    await route.fulfill({ json: declined ? { ...intake, status: "summary_declined", version: 6 } : intake });
  });
  await page.route(`**/api/v1/tax-intakes/${intake.id}/summary`, async (route) => {
    requestBody = await route.request().postDataJSON() as components["schemas"]["CreateTaxSummaryRequest"];
    declined = true;
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: textStream(closing.id, closing.content, "clarification") });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "No, thanks" }).click();
  await expect(page.getByText(closing.content).last()).toBeVisible();
  expect(requestBody).toEqual(expect.objectContaining({ requested: false, version: 5 }));
  await expect(page.getByRole("heading", { name: "Tax information summary" })).toHaveCount(0);
});

test("regenerates an allowed assistant message and refreshes history", async ({ page }) => {
  const original = textMessage("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "assistant", "Original answer", "general_chat");
  const retried = { ...textMessage("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "assistant", "Regenerated answer", "general_chat"), retry_of_message_id: original.id };
  let retryCompleted = false;
  let releaseRetry: () => void = () => undefined;
  const retryGate = new Promise<void>((resolve) => { releaseRetry = resolve; });

  await installSessionRoutes(page, () => retryCompleted ? [original, retried] : [original]);
  await page.route(`**/api/v1/messages/${original.id}/retry`, async (route) => {
    await retryGate;
    retryCompleted = true;
    await route.fulfill({
      status: 202,
      json: { id: "99999999-9999-4999-8999-999999999999", conversation_id: conversationId, assistant_message_id: retried.id, status: "completed" },
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(page.getByLabel("Finding relevant ATO guidance")).toBeVisible();
  releaseRetry();
  await expect(page.getByText("Regenerated answer")).toBeVisible();
  await expect(page.getByLabel("Finding relevant ATO guidance")).toHaveCount(0);
});

test("stays within the mobile startup and bundle budgets", async ({ page }) => {
  await page.route("**/health/live", async (route) => { await route.fulfill({ json: { status: "ok" } }); });
  await page.goto("/?fixtures=1");
  await expect(page.getByRole("heading", { name: "Sortax" })).toBeVisible();
  await page.locator('[aria-label="ATO sources"] a').last().evaluate((link) => {
    link.append(" A very long citation title that must stay inside the summary card without widening or clipping the conversation timeline");
  });

  const metrics = await page.evaluate(() => {
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming;
    const resources = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
    const paints = performance.getEntriesByType("paint");
    return {
      domContentLoadedMs: navigation.domContentLoadedEventEnd - navigation.startTime,
      firstContentfulPaintMs: paints.find((entry) => entry.name === "first-contentful-paint")?.startTime ?? 0,
      scriptBytes: resources.filter((entry) => entry.initiatorType === "script").reduce((total, entry) => total + entry.encodedBodySize, 0),
      styleBytes: resources.filter((entry) => entry.initiatorType === "link" && entry.name.endsWith(".css")).reduce((total, entry) => total + entry.encodedBodySize, 0),
      domNodes: document.getElementsByTagName("*").length,
      hasHorizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
      bodyHeight: document.body.getBoundingClientRect().height,
      viewportHeight: window.innerHeight,
      timelineScrolls: (() => {
        const timeline = document.querySelector<HTMLElement>('[aria-label="Conversation preview"]');
        return timeline !== null && timeline.scrollHeight > timeline.clientHeight;
      })(),
      contentEscapesTimeline: (() => {
        const timeline = document.querySelector<HTMLElement>('[aria-label="Conversation preview"]');
        if (timeline === null) return true;
        const bounds = timeline.getBoundingClientRect();
        return Array.from(timeline.querySelectorAll<HTMLElement>("*")).some((element) => {
          if (element.closest('[aria-hidden="true"]') !== null) return false;
          const rect = element.getBoundingClientRect();
          return rect.left < bounds.left - 1 || rect.right > bounds.right + 1;
        });
      })(),
      summaryClipsVertically: (() => {
        const heading = Array.from(document.querySelectorAll("h2")).find((element) => element.textContent === "Tax information summary");
        const card = heading?.closest("article");
        return card === null || card === undefined || card.scrollHeight > card.clientHeight + 1;
      })(),
    };
  });

  expect(metrics.domContentLoadedMs).toBeLessThan(3_000);
  expect(metrics.firstContentfulPaintMs).toBeLessThan(3_000);
  expect(metrics.scriptBytes).toBeLessThan(300_000);
  expect(metrics.styleBytes).toBeLessThan(30_000);
  expect(metrics.domNodes).toBeLessThan(400);
  expect(metrics.hasHorizontalOverflow).toBe(false);
  expect(metrics.bodyHeight).toBe(metrics.viewportHeight);
  expect(metrics.timelineScrolls).toBe(true);
  expect(metrics.contentEscapesTimeline).toBe(false);
  expect(metrics.summaryClipsVertically).toBe(false);
});

async function installSessionRoutes(
  page: import("@playwright/test").Page,
  messages: () => readonly object[],
) {
  await page.addInitScript((id) => { localStorage.setItem("sortax.recentConversationId", id); }, conversationId);
  await page.route("**/health/live", async (route) => { await route.fulfill({ json: { status: "ok" } }); });
  await page.route("**/api/v1/dev/token", async (route) => {
    await route.fulfill({ status: 201, json: { access_token: "test-token", token_type: "bearer", expires_in: 3600 } });
  });
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ json: { user_id: "11111111-1111-4111-8111-111111111111", tenant_id: "22222222-2222-4222-8222-222222222222", role: "user" } });
  });
  await page.route(`**/api/v1/conversations/${conversationId}/messages*`, async (route) => {
    await route.fulfill({ json: { items: messages(), next_cursor: null } });
  });
}

function textMessage(id: string, role: "assistant" | "user", content: string, completionKind?: "clarification" | "general_chat") {
  return {
    id, conversation_id: conversationId, role, content, content_type: "text" as const, structured_content: null,
    status: "completed" as const, completion_kind: completionKind, grounded: false, citation_count: 0, citations: [],
    created_at: "2026-10-12T00:00:00Z", completed_at: "2026-10-12T00:00:01Z",
  };
}

function structuredMessage(
  id: string,
  contentType: components["schemas"]["MessageContentType"],
  structuredContent: components["schemas"]["Message"]["structured_content"],
  citations: readonly components["schemas"]["Citation"][],
) {
  return {
    ...textMessage(id, "assistant", ""), content_type: contentType, structured_content: structuredContent,
    completion_kind: contentType, grounded: citations.length > 0, citation_count: citations.length, citations,
  };
}

function textStream(messageId: string, content: string, completionKind: "clarification" | "general_chat"): string {
  const generationId = "99999999-9999-4999-8999-999999999999";
  return [
    `event: generation.started\nid: 1\ndata: ${JSON.stringify({ generation_id: generationId, message_id: messageId })}\n\n`,
    `event: message.delta\nid: 2\ndata: ${JSON.stringify({ generation_id: generationId, message_id: messageId, seq: 1, delta: content })}\n\n`,
    `event: message.completed\nid: 3\ndata: ${JSON.stringify({ generation_id: generationId, message_id: messageId, content_type: "text", structured_content: null, completion_kind: completionKind, grounded: false, citations: [] })}\n\n`,
  ].join("");
}
