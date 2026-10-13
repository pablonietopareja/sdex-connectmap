import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "../services/api";
import type {
  ConfigPayload,
  ConfigStatus,
  TestConnectionResult,
} from "../types";
import { Notice } from "./Notice";
import { ArrowRightIcon, CheckIcon, RefreshIcon } from "./icons";

interface ConnectionFormProps {
  mode: "onboarding" | "settings";
  initial?: ConfigStatus | null;
  onSave: (payload: ConfigPayload) => Promise<void>;
  onCancel?: () => void;
}

interface FormValues {
  baseUrl: string;
  username: string;
  password: string;
  verifyTls: boolean;
  timeoutSeconds: string;
}

interface FormErrors {
  baseUrl?: string;
  username?: string;
  password?: string;
  timeoutSeconds?: string;
}

export function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim();
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error("Enter a valid SDEX URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Only HTTP and HTTPS URLs are supported.");
  }
  if (!parsed.hostname || parsed.username || parsed.password) {
    throw new Error("Enter a host without embedded credentials.");
  }
  if (parsed.port && Number(parsed.port) < 1) {
    throw new Error("Use a port from 1 to 65535.");
  }
  if (parsed.search || parsed.hash) {
    throw new Error("Query strings and fragments are not allowed.");
  }
  const path = parsed.pathname.replace(/\/+$/, "");
  if (path && path !== "/") {
    throw new Error("Use the SDEX origin only, without a path.");
  }
  return `${parsed.protocol}//${parsed.host}`;
}

function validate(
  values: FormValues,
  requirePassword: boolean,
): { errors: FormErrors; payload?: ConfigPayload } {
  const errors: FormErrors = {};
  let baseUrl = "";
  try {
    baseUrl = normalizeBaseUrl(values.baseUrl);
  } catch (error) {
    errors.baseUrl =
      error instanceof Error ? error.message : "Enter a valid SDEX URL.";
  }
  if (!values.username.trim()) errors.username = "Username is required.";
  if (requirePassword && !values.password) {
    errors.password = "Password is required for the initial connection.";
  }
  const timeout = Number(values.timeoutSeconds);
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 120) {
    errors.timeoutSeconds = "Use a timeout from 1 to 120 seconds.";
  }
  if (Object.keys(errors).length > 0) return { errors };

  return {
    errors,
    payload: {
      base_url: baseUrl,
      username: values.username.trim(),
      ...(values.password ? { password: values.password } : {}),
      verify_tls: values.verifyTls,
      timeout_seconds: timeout,
    },
  };
}

function SystemResult({ result }: { result: TestConnectionResult }) {
  const system = result.system;
  const rows: Array<[string, string | undefined | null]> = [
    ["Product", system.product_type],
    ["API version", system.api_version],
    ["Status", system.status],
    ["FQDN", system.fqdn],
  ];
  return (
    <div className="connection-result" data-testid="connection-result">
      <div className="connection-result-heading">
        <span className="result-check">
          <CheckIcon />
        </span>
        <div>
          <strong>Connection successful</strong>
          <span>SDEX accepted the credentials and returned system data.</span>
        </div>
      </div>
      <dl className="connection-result-grid">
        {rows
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
    </div>
  );
}

function resultFingerprint(payload: ConfigPayload): string {
  return JSON.stringify(payload);
}

export function ConnectionForm({
  mode,
  initial,
  onSave,
  onCancel,
}: ConnectionFormProps) {
  const [values, setValues] = useState<FormValues>({
    baseUrl: initial?.base_url ?? "",
    username: initial?.username ?? "",
    password: "",
    verifyTls: initial?.verify_tls ?? true,
    timeoutSeconds: String(initial?.timeout_seconds ?? 15),
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);
  const [testedFingerprint, setTestedFingerprint] = useState<string | null>(null);

  useEffect(() => {
    if (!initial) return;
    setValues({
      baseUrl: initial.base_url ?? "",
      username: initial.username ?? "",
      password: "",
      verifyTls: initial.verify_tls,
      timeoutSeconds: String(initial.timeout_seconds),
    });
  }, [initial]);

  const requirePassword = mode === "onboarding" && !initial?.password_configured;
  const currentValidation = useMemo(
    () => validate(values, requirePassword),
    [requirePassword, values],
  );
  const hasChangedAfterTest =
    testedFingerprint !== null &&
    currentValidation.payload !== undefined &&
    resultFingerprint(currentValidation.payload) !== testedFingerprint;

  const setField = <K extends keyof FormValues>(
    field: K,
    value: FormValues[K],
  ) => {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
    setRequestError(null);
  };

  const getPayload = (): ConfigPayload | null => {
    const result = validate(values, requirePassword);
    setErrors(result.errors);
    return result.payload ?? null;
  };

  const handleTest = async () => {
    const payload = getPayload();
    if (!payload) return;
    setTesting(true);
    setRequestError(null);
    setTestResult(null);
    try {
      const result = await api.testConfig(payload);
      setTestResult(result);
      setTestedFingerprint(resultFingerprint(payload));
    } catch (error) {
      setRequestError(
        error instanceof ApiError
          ? error.message
          : "The connection test could not be completed.",
      );
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const payload = getPayload();
    if (!payload) return;
    setSaving(true);
    setRequestError(null);
    try {
      await onSave(payload);
    } catch (error) {
      setRequestError(
        error instanceof Error
          ? error.message
          : "The configuration could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="connection-form" onSubmit={(event) => void handleSubmit(event)}>
      {initial?.source === "environment" && (
        <Notice tone="info">
          This profile was initialized from environment variables. Saving creates
          a persistent profile that takes precedence.
        </Notice>
      )}

      <div className="form-grid">
        <label className={`form-field span-2${errors.baseUrl ? " has-error" : ""}`}>
          <span>SDEX Base URL</span>
          <input
            name="baseUrl"
            type="url"
            inputMode="url"
            autoComplete="url"
            placeholder="https://sdex-suite:443"
            value={values.baseUrl}
            onChange={(event) => setField("baseUrl", event.target.value)}
            aria-describedby="base-url-help"
            aria-invalid={Boolean(errors.baseUrl)}
          />
          <small id="base-url-help">
            Use the shared Docker DNS name or the reachable edgeNode address, for
            example <code>https://&lt;IP-edgeNode&gt;:1443</code>.
          </small>
          {errors.baseUrl && <span className="field-error">{errors.baseUrl}</span>}
        </label>

        <label className={`form-field${errors.username ? " has-error" : ""}`}>
          <span>Username</span>
          <input
            name="username"
            autoComplete="username"
            value={values.username}
            onChange={(event) => setField("username", event.target.value)}
            aria-invalid={Boolean(errors.username)}
          />
          {errors.username && <span className="field-error">{errors.username}</span>}
        </label>

        <label className={`form-field${errors.password ? " has-error" : ""}`}>
          <span>{mode === "settings" ? "Replace password" : "Password"}</span>
          <input
            name="password"
            type="password"
            autoComplete={mode === "onboarding" ? "current-password" : "new-password"}
            placeholder={
              mode === "settings" && initial?.password_configured
                ? "••••••••  (leave blank to keep)"
                : ""
            }
            value={values.password}
            onChange={(event) => setField("password", event.target.value)}
            aria-invalid={Boolean(errors.password)}
          />
          {errors.password && <span className="field-error">{errors.password}</span>}
        </label>

        <label
          className={`form-field timeout-field${
            errors.timeoutSeconds ? " has-error" : ""
          }`}
        >
          <span>Request timeout</span>
          <div className="input-suffix">
            <input
              name="timeout"
              type="number"
              min="1"
              max="120"
              step="1"
              inputMode="numeric"
              value={values.timeoutSeconds}
              onChange={(event) => setField("timeoutSeconds", event.target.value)}
              aria-invalid={Boolean(errors.timeoutSeconds)}
            />
            <span>seconds</span>
          </div>
          {errors.timeoutSeconds && (
            <span className="field-error">{errors.timeoutSeconds}</span>
          )}
        </label>

        <label className="tls-field">
          <span className="switch-copy">
            <span className="switch-label">Verify TLS certificate</span>
            <span className="switch-description">
              Recommended for production deployments.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={values.verifyTls}
            onChange={(event) => setField("verifyTls", event.target.checked)}
          />
          <span className="switch-track" aria-hidden="true">
            <span className="switch-thumb" />
          </span>
        </label>
      </div>

      {!values.verifyTls && (
        <Notice tone="warning" title="TLS verification is disabled">
          The SDEX certificate will not be authenticated. Use this only on a
          trusted industrial network.
        </Notice>
      )}

      <p className="least-privilege-note">
        Use a dedicated SDEX account with only the read permissions required for
        system and connection discovery.
      </p>

      {requestError && (
        <Notice tone="danger" title="Unable to continue">
          {requestError}
        </Notice>
      )}
      {testResult && !hasChangedAfterTest && <SystemResult result={testResult} />}
      {testResult && hasChangedAfterTest && (
        <Notice tone="info">Values changed. Run the connection test again.</Notice>
      )}

      <footer className="form-actions">
        {onCancel && (
          <button className="button button-ghost" type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button
          className="button button-secondary"
          type="button"
          disabled={testing || saving}
          onClick={() => void handleTest()}
        >
          <RefreshIcon className={testing ? "spin" : ""} />
          {testing ? "Testing…" : "Test connection"}
        </button>
        <button
          className="button button-primary"
          type="submit"
          disabled={saving || testing}
        >
          {saving
            ? "Saving…"
            : mode === "onboarding"
              ? "Save and continue"
              : "Save changes"}
          {!saving && <ArrowRightIcon />}
        </button>
      </footer>
    </form>
  );
}
