import { expect, test } from "@playwright/test";

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
