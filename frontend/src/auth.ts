import type { AppConfig } from "./types";

type CognitoResult = {
  AuthenticationResult?: { AccessToken: string };
  ChallengeName?: string;
  CodeDeliveryDetails?: { Destination?: string };
};

export class AuthError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function cognito(
  config: AppConfig,
  operation: string,
  body: Record<string, unknown>,
): Promise<CognitoResult> {
  const response = await fetch(
    `https://cognito-idp.${config.cognito_region}.amazonaws.com/`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${operation}`,
      },
      body: JSON.stringify({ ClientId: config.cognito_client_id, ...body }),
    },
  );
  const result = await response.json();
  if (!response.ok) {
    const code = String(result.__type || "AuthenticationError")
      .split("#")
      .pop()!;
    const messages: Record<string, string> = {
      NotAuthorizedException:
        operation === "InitiateAuth"
          ? "The email or password is incorrect."
          : "This request could not be completed for this account. Try signing in or resetting your password.",
      UserNotFoundException: "The email or password is incorrect.",
      UsernameExistsException:
        "An account with this email already exists. Sign in instead.",
      CodeMismatchException:
        "That verification code is incorrect. Please try again.",
      ExpiredCodeException: "This code has expired. Request a new code.",
      LimitExceededException:
        "Too many attempts. Please wait a few minutes and try again.",
      TooManyRequestsException:
        "Too many attempts. Please wait a few minutes and try again.",
      InvalidPasswordException:
        "Use at least 12 characters, including uppercase, lowercase, a number, and a symbol.",
    };
    throw new AuthError(
      code,
      messages[code] || result.message || "Could not complete this request.",
    );
  }
  return result;
}

export async function passwordSignIn(
  config: AppConfig,
  email: string,
  password: string,
) {
  const result = await cognito(config, "InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  if (!result.AuthenticationResult?.AccessToken) {
    throw new AuthError(
      result.ChallengeName || "AuthenticationError",
      result.ChallengeName === "NEW_PASSWORD_REQUIRED"
        ? "Set your password using “Forgot password?” before signing in."
        : "This account requires an additional sign-in step. Use secure hosted sign-in.",
    );
  }
  sessionStorage.setItem(
    "access_token",
    result.AuthenticationResult.AccessToken,
  );
}
