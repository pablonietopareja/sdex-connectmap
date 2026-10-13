import type { ReactNode } from "react";
import { AlertIcon, CheckIcon, InfoIcon } from "./icons";

interface NoticeProps {
  tone?: "info" | "warning" | "danger" | "success";
  title?: string;
  children: ReactNode;
  className?: string;
}

export function Notice({
  tone = "info",
  title,
  children,
  className = "",
}: NoticeProps) {
  const Icon =
    tone === "success" ? CheckIcon : tone === "info" ? InfoIcon : AlertIcon;
  return (
    <div className={`notice notice-${tone} ${className}`} role="status">
      <Icon />
      <div>
        {title && <strong>{title}</strong>}
        <div>{children}</div>
      </div>
    </div>
  );
}
