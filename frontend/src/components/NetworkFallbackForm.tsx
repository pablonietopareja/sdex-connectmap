import { useEffect, useState, type FormEvent } from "react";
import type { ManualNetworkInterface } from "../types";
import { Notice } from "./Notice";

interface InterfaceValues {
  address: string;
  prefix: string;
}

const EMPTY_VALUES: Record<"eth1" | "eth2", InterfaceValues> = {
  eth1: { address: "", prefix: "" },
  eth2: { address: "", prefix: "" },
};

function fromInterfaces(
  interfaces: ManualNetworkInterface[],
): Record<"eth1" | "eth2", InterfaceValues> {
  const values = structuredClone(EMPTY_VALUES);
  for (const networkInterface of interfaces) {
    const first = networkInterface.addresses[0];
    if (first) {
      values[networkInterface.name] = {
        address: first.address,
        prefix: String(first.prefix_length),
      };
    }
  }
  return values;
}

export function NetworkFallbackForm({
  interfaces,
  onSave,
}: {
  interfaces: ManualNetworkInterface[];
  onSave: (interfaces: ManualNetworkInterface[]) => Promise<void>;
}) {
  const [values, setValues] = useState(() => fromInterfaces(interfaces));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => setValues(fromInterfaces(interfaces)), [interfaces]);

  const update = (
    name: "eth1" | "eth2",
    field: keyof InterfaceValues,
    value: string,
  ) => {
    setValues((current) => ({
      ...current,
      [name]: { ...current[name], [field]: value },
    }));
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const next: ManualNetworkInterface[] = [];
    for (const name of ["eth1", "eth2"] as const) {
      const address = values[name].address.trim();
      const prefixText = values[name].prefix.trim();
      if (!address && !prefixText) continue;
      const prefix = Number(prefixText);
      if (!address || !Number.isInteger(prefix) || prefix < 0 || prefix > 128) {
        setError(
          `${name} needs a literal IP address and a prefix from 0 to 128.`,
        );
        return;
      }
      next.push({
        name,
        addresses: [{ address, prefix_length: prefix }],
      });
    }

    setSaving(true);
    setError(null);
    try {
      await onSave(next);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The network fallback could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="network-fallback-form" onSubmit={(event) => void submit(event)}>
      <header>
        <p className="eyebrow">Network fallback</p>
        <h3>Explicit eth1 and eth2 networks</h3>
        <p>
          Use this only when the SDEX network response does not include a usable
          prefix. Blank fields remove the manual fallback; no prefix is assumed.
        </p>
      </header>
      <div className="network-fallback-grid">
        {(["eth1", "eth2"] as const).map((name) => (
          <fieldset key={name}>
            <legend>{name}</legend>
            <label className="form-field">
              <span>IP address</span>
              <input
                value={values[name].address}
                placeholder={name === "eth1" ? "192.168.10.1" : "192.168.20.1"}
                spellCheck={false}
                autoComplete="off"
                onChange={(event) => update(name, "address", event.target.value)}
              />
            </label>
            <label className="form-field">
              <span>Prefix length</span>
              <input
                type="number"
                min="0"
                max="128"
                inputMode="numeric"
                value={values[name].prefix}
                placeholder="24"
                onChange={(event) => update(name, "prefix", event.target.value)}
              />
            </label>
          </fieldset>
        ))}
      </div>
      {error && (
        <Notice tone="danger" title="Invalid network fallback">
          {error}
        </Notice>
      )}
      <footer className="form-actions">
        <button className="button button-secondary" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save network fallback"}
        </button>
      </footer>
    </form>
  );
}
