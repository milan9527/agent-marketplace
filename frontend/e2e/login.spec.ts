import { expect, test } from "@playwright/test";

const config = {
  mode: "aws",
  network: "Base Sepolia",
  cognito_region: "us-east-1",
  cognito_client_id: "test-client",
  cognito_domain: "https://login.example.test",
  runtime: "Amazon Bedrock AgentCore",
  payments: "AgentCore Payments",
  chain_sync: false,
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/config", (route) => route.fulfill({ json: config }));
});

test("dedicated login rejects invalid credentials and opens the workspace after sign-in", async ({
  page,
}, info) => {
  let attempts = 0;
  await page.route(
    "https://cognito-idp.us-east-1.amazonaws.com/**",
    (route) => {
      expect(route.request().headers()["x-amz-target"]).toContain(
        "InitiateAuth",
      );
      const request = route.request().postDataJSON();
      expect(request.AuthFlow).toBe("USER_PASSWORD_AUTH");
      expect(request.AuthParameters.USERNAME).toBe("builder@example.test");
      attempts++;
      return route.fulfill(
        attempts === 1
          ? { status: 400, json: { __type: "NotAuthorizedException" } }
          : {
              json: {
                AuthenticationResult: { AccessToken: "test-access-token" },
              },
            },
      );
    },
  );
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Create.*account/i }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Accounts are provided by your workspace administrator."),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: `test-results/login-${info.project.name}.png`,
    fullPage: true,
  });
  await page.getByLabel("Email address").fill("builder@example.test");
  await page
    .getByLabel("Password", { exact: true })
    .fill("IncorrectPassword!123");
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "The email or password is incorrect.",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Discover your next advantage." }),
  ).toBeVisible();
  expect(attempts).toBe(2);
});

test("existing accounts can reset their password without self-registration", async ({
  page,
}) => {
  const operations: string[] = [];
  await page.route(
    "https://cognito-idp.us-east-1.amazonaws.com/**",
    (route) => {
      const operation = route
        .request()
        .headers()
        ["x-amz-target"].split(".")
        .pop()!;
      operations.push(operation);
      return route.fulfill({ json: {} });
    },
  );
  await page.goto("/login");
  await page.getByLabel("Email address").fill("builder@example.test");
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByRole("button", { name: "Send reset code" }).click();
  await page.getByLabel("Verification code").fill("654321");
  await page.getByLabel("New password").fill("NewStrongPassword!456");
  await page
    .getByRole("button", { name: "Reset password", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Password updated. Sign in with your new password.",
  );
  expect(operations).toEqual(["ForgotPassword", "ConfirmForgotPassword"]);
});

test("an existing unconfirmed account can finish email verification", async ({
  page,
}) => {
  const operations: string[] = [];
  await page.route(
    "https://cognito-idp.us-east-1.amazonaws.com/**",
    (route) => {
      const operation = route
        .request()
        .headers()
        ["x-amz-target"].split(".")
        .pop()!;
      operations.push(operation);
      return route.fulfill(
        operation === "InitiateAuth"
          ? { status: 400, json: { __type: "UserNotConfirmedException" } }
          : { json: {} },
      );
    },
  );
  await page.goto("/login");
  await page.getByLabel("Email address").fill("existing-builder@example.test");
  await page.getByLabel("Password", { exact: true }).fill("StrongPassword!123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Check your inbox." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Didn't receive it? Resend code" })
    .click();
  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Verify email", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  expect(operations).toEqual([
    "InitiateAuth",
    "ResendConfirmationCode",
    "ConfirmSignUp",
  ]);
});
