import { AlertIcon, RefreshIcon } from "./icons";

export function FatalError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <main className="fatal-screen">
      <div className="fatal-icon">
        <AlertIcon />
      </div>
      <p className="eyebrow">ConnectMap API</p>
      <h1>Unable to load the application</h1>
      <p>{message}</p>
      <button className="button button-primary" type="button" onClick={onRetry}>
        <RefreshIcon />
        Try again
      </button>
    </main>
  );
}
