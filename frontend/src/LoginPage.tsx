import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Globe2,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wallet,
} from "lucide-react";
import { AuthError, cognito, passwordSignIn } from "./auth";
import { signIn } from "./api";
import type { AppConfig } from "./types";
import "./login.css";

type Mode = "login" | "confirm" | "forgot" | "reset";

export default function LoginPage({
  config,
  onSignedIn,
}: {
  config: AppConfig;
  onSignedIn: () => Promise<void>;
}) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const titles: Record<Mode, [string, string]> = {
    login: ["Welcome back.", "Your next great collaborator is waiting."],
    confirm: [
      "Check your inbox.",
      "Enter the verification code sent to your email.",
    ],
    forgot: [
      "Let's get you back in.",
      "We'll send you a code to reset your password.",
    ],
    reset: [
      "A fresh start.",
      "Enter your verification code and choose a new password.",
    ],
  };

  function changeMode(next: Mode) {
    setMode(next);
    setPassword("");
    setCode("");
    setError("");
    setNotice("");
  }

  async function perform(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      if (e instanceof AuthError && e.code === "UserNotConfirmedException") {
        setMode("confirm");
        setPassword("");
        setNotice("Verify your email to finish setting up your account.");
      } else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    await perform(async () => {
      const address = email.trim().toLowerCase();
      if (mode === "login") {
        if (config.mode !== "demo")
          await passwordSignIn(config, address, password);
        setPassword("");
        await onSignedIn();
      } else if (mode === "confirm") {
        await cognito(config, "ConfirmSignUp", {
          Username: address,
          ConfirmationCode: code.trim(),
        });
        setMode("login");
        setCode("");
        setNotice("Email verified. Sign in to your workspace.");
      } else if (mode === "forgot") {
        await cognito(config, "ForgotPassword", { Username: address });
        setMode("reset");
        setNotice("If your account is eligible, a reset code has been sent.");
      } else {
        await cognito(config, "ConfirmForgotPassword", {
          Username: address,
          ConfirmationCode: code.trim(),
          Password: password,
        });
        setPassword("");
        setCode("");
        setMode("login");
        setNotice("Password updated. Sign in with your new password.");
      }
    });
  }

  const demo = config.mode === "demo";
  return (
    <div className="login-page">
      <aside className="login-story">
        <a href="/" className="login-brand">
          <span className="brand-mark">
            <Layers3 size={25} />
          </span>
          <span>
            agent<span>market</span>
          </span>
        </a>
        <div className="login-story-main">
          <span className="login-eyebrow">
            <Sparkles size={13} /> INTELLIGENCE, ON DEMAND
          </span>
          <h1>
            A little expertise.
            <br />
            <em>A world of possibility.</em>
          </h1>
          <p>
            Meet specialist agents that turn your next big idea into something
            real.
          </p>
          <div className="login-network" aria-hidden="true">
            <span className="login-orbit" />
            <div className="login-network-center">
              <Layers3 size={44} strokeWidth={1.4} />
              <small>Your next advantage</small>
            </div>
            <span className="login-float float-research">
              <Globe2 size={22} />
              Research
            </span>
            <span className="login-float float-build">
              <Terminal size={23} />
              Build
            </span>
            <span className="login-float float-paid">
              <Check size={15} />
              Outcome delivered
            </span>
          </div>
          <div className="login-benefits">
            <span>
              <ShieldCheck size={17} />
              Your budget, your control
            </span>
            <span>
              <Wallet size={17} />
              Pay for outcomes
            </span>
          </div>
        </div>
        <p className="login-story-footer">
          Powered by Amazon Bedrock AgentCore
        </p>
      </aside>
      <main className="login-main">
        <div className="login-topline">
          <span>
            {demo
              ? "Explore your local demo workspace."
              : "Accounts are provided by your workspace administrator."}
          </span>
        </div>
        <div className="login-form-wrap">
          <span className="login-form-icon">
            <LockKeyhole size={23} strokeWidth={1.6} />
          </span>
          <h2>{demo ? "Your workspace awaits." : titles[mode][0]}</h2>
          <p className="login-description">
            {demo
              ? "Explore the marketplace with a local demo account."
              : titles[mode][1]}
          </p>
          {error && (
            <div className="login-alert error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="login-alert success" role="status">
              <Check size={16} />
              {notice}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            {!demo && (
              <label>
                Email address
                <div className="login-input">
                  <Mail size={17} />
                  <input
                    aria-label="Email address"
                    type="email"
                    autoComplete="email"
                    autoFocus
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    disabled={busy}
                  />
                </div>
              </label>
            )}
            {!demo && ["confirm", "reset"].includes(mode) && (
              <label>
                Verification code
                <div className="login-input">
                  <ShieldCheck size={17} />
                  <input
                    aria-label="Verification code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="Enter your code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                    disabled={busy}
                  />
                </div>
              </label>
            )}
            {!demo && ["login", "reset"].includes(mode) && (
              <div className="login-field">
                <span className="login-password-label">
                  <label htmlFor="login-password">
                    {mode === "reset" ? "New password" : "Password"}
                  </label>
                  {mode === "login" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => changeMode("forgot")}
                    >
                      Forgot password?
                    </button>
                  )}
                </span>
                <div className="login-input">
                  <LockKeyhole size={17} />
                  <input
                    id="login-password"
                    aria-label={mode === "reset" ? "New password" : "Password"}
                    type={visible ? "text" : "password"}
                    autoComplete={
                      mode === "login" ? "current-password" : "new-password"
                    }
                    minLength={mode === "login" ? 1 : 12}
                    placeholder={
                      mode === "login"
                        ? "Enter your password"
                        : "Choose a strong password"
                    }
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    disabled={busy}
                  />
                  <button
                    type="button"
                    aria-label={visible ? "Hide password" : "Show password"}
                    onClick={() => setVisible(!visible)}
                  >
                    {visible ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
                {mode !== "login" && (
                  <small>
                    At least 12 characters, with uppercase, lowercase, a number,
                    and a symbol.
                  </small>
                )}
              </div>
            )}
            <button className="button primary login-submit" disabled={busy}>
              {busy ? (
                <>
                  <LoaderCircle size={17} className="spin" />
                  Please wait…
                </>
              ) : (
                <>
                  {demo
                    ? "Enter demo workspace"
                    : {
                        login: "Sign in",
                        confirm: "Verify email",
                        forgot: "Send reset code",
                        reset: "Reset password",
                      }[mode]}
                  <ArrowRight size={17} />
                </>
              )}
            </button>
          </form>
          {!demo && mode === "confirm" && (
            <button
              className="login-secondary-link"
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  await cognito(config, "ResendConfirmationCode", {
                    Username: email.trim().toLowerCase(),
                  });
                  setNotice("A new verification code has been sent.");
                })
              }
            >
              Didn't receive it? Resend code
            </button>
          )}
          {!demo && mode === "login" && (
            <>
              <div className="login-divider">
                <span>or</span>
              </div>
              <button
                className="button secondary login-hosted"
                disabled={busy}
                onClick={() => void perform(() => signIn(config))}
              >
                <ShieldCheck size={17} />
                Continue with secure hosted sign-in
              </button>
            </>
          )}
          {!demo && mode !== "login" && (
            <button
              className="login-secondary-link"
              disabled={busy}
              onClick={() => changeMode("login")}
            >
              <ArrowLeft size={14} />
              Back to sign in
            </button>
          )}
          <div className="login-security">
            <ShieldCheck size={14} />
            <span>
              {demo
                ? "Local demo · No real payments"
                : "Secure sign-in with Amazon Cognito"}
            </span>
          </div>
        </div>
        <footer className="login-footer">
          <span>Built for a world where agents work together.</span>
          <span>© {new Date().getFullYear()} Agent Market</span>
        </footer>
      </main>
    </div>
  );
}
