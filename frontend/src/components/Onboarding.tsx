import type { ConfigPayload, ConfigStatus } from "../types";
import { ConnectionForm } from "./ConnectionForm";

interface OnboardingProps {
  status?: ConfigStatus | null;
  onSave: (payload: ConfigPayload) => Promise<void>;
}

export function Onboarding({ status, onSave }: OnboardingProps) {
  return (
    <main className="onboarding-shell">
      <section className="onboarding-card">
        <header className="onboarding-heading">
          <div className="brand-mark large">
            <img
              src="/icons/SDEX_ConnectMap_logo.svg"
              alt=""
              draggable={false}
            />
          </div>
          <p className="eyebrow">SDEX ConnectMap</p>
          <h1>Connect your SDEX Suite</h1>
          <p>
            Add a read-only SDEX profile to discover and visualize your industrial
            connections. Credentials stay on the ConnectMap server.
          </p>
        </header>
        <div className="step-indicator" aria-label="Setup progress">
          <span className="active">1</span>
          <span />
          <span>2</span>
          <p>Connection</p>
          <p>Topology</p>
        </div>
        <ConnectionForm mode="onboarding" initial={status} onSave={onSave} />
      </section>
      <aside className="onboarding-aside" aria-hidden="true">
        <div className="preview-grid">
          <div className="preview-node preview-node-sdex">
            <img src="/icons/SDEX.svg" alt="" />
          </div>
          <span className="preview-line line-a" />
          <span className="preview-line line-b" />
          <span className="preview-line line-c" />
          <div className="preview-node node-a">
            <img src="/icons/S7_2.svg" alt="" />
          </div>
          <div className="preview-node node-b">
            <img src="/icons/OPC_UA_Server.svg" alt="" />
          </div>
          <div className="preview-node node-c">
            <img src="/icons/MQTT.svg" alt="" />
          </div>
        </div>
        <div className="onboarding-aside-copy">
          <strong>A live map of every configured connection</strong>
          <span>
            Read-only discovery, persistent layout, and clear operational status.
          </span>
        </div>
      </aside>
    </main>
  );
}
