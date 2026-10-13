import { NetworkIcon } from "./icons";

export function LoadingScreen({ message = "Loading ConnectMap…" }: { message?: string }) {
  return (
    <main className="loading-screen">
      <div className="brand-mark large pulse">
        <NetworkIcon />
      </div>
      <strong>SDEX ConnectMap</strong>
      <span>{message}</span>
    </main>
  );
}

export function TopologyLoading() {
  return (
    <main className="topology-loading" aria-label="Loading topology">
      <div className="skeleton skeleton-topbar" />
      <div className="skeleton skeleton-node center" />
      <div className="skeleton skeleton-node one" />
      <div className="skeleton skeleton-node two" />
      <div className="skeleton skeleton-node three" />
    </main>
  );
}
