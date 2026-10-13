import type { JsonValue } from "./topology";

export type ConfigSource = "database" | "environment" | "mock" | "none";

export interface ConfigStatus {
  configured: boolean;
  source: ConfigSource;
  base_url?: string | null;
  username?: string | null;
  verify_tls: boolean;
  timeout_seconds: number;
  password_configured: boolean;
  mock_mode: boolean;
  tls_warning: boolean;
}

export interface ConfigPayload {
  base_url: string;
  username: string;
  password?: string;
  verify_tls: boolean;
  timeout_seconds: number;
}

export interface SystemInfo {
  product_type?: string | null;
  api_version?: string | null;
  status?: string | null;
  fqdn?: string | null;
  hostname?: string | null;
  http_api?: string | boolean | null;
  os?: string | null;
  arch?: string | null;
  demo?: boolean | null;
  all_connected?: boolean | null;
}

export interface TestConnectionResult {
  ok: boolean;
  system: SystemInfo;
}

export type ThemePreference = "light" | "dark" | "system";

export interface ManualNetworkAddress {
  address: string;
  prefix_length: number;
}

export interface ManualNetworkInterface {
  name: "eth1" | "eth2";
  addresses: ManualNetworkAddress[];
}

export interface Settings {
  refresh_interval_seconds: number;
  allowed_refresh_intervals: number[];
  show_not_enabled: boolean;
  theme: ThemePreference;
  network_interfaces: ManualNetworkInterface[];
}

export interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    details?: JsonValue;
  };
  detail?: string | { msg?: string; message?: string }[];
  message?: string;
}

export interface TopologyEvent {
  type: string;
  correlation_id?: string;
  message?: string;
  [key: string]: unknown;
}
