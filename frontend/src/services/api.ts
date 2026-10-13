import type {
  ApiErrorPayload,
  ConfigPayload,
  ConfigStatus,
  ConnectionSourceHandle,
  DeviceVisualRouting,
  EdgeVisualStyle,
  EdgeVisualStyleUpdate,
  EdgeRoute,
  EdgeRouteUpdate,
  LayoutUpdate,
  RackMembership,
  RackMembershipUpdate,
  SdexInterfaceName,
  Settings,
  TestConnectionResult,
  TopologyEvent,
  TopologySnapshot,
  VisualElement,
  VisualElementCreate,
  VisualElementUpdate,
  VisualLink,
  VisualLinkCreate,
  VisualLinkUpdate,
  VisualTopology,
} from "../types";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const parseErrorMessage = (payload: ApiErrorPayload, fallback: string): string => {
  const structuredDetails = payload.error?.details;
  if (Array.isArray(structuredDetails)) {
    const detailsMessage = structuredDetails
      .flatMap((entry) => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
        const message = entry.message ?? entry.msg;
        return typeof message === "string" ? [message] : [];
      })
      .join("; ");
    if (detailsMessage) return detailsMessage;
  }
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    const validationMessage = payload.detail
      .map((entry) => entry.message ?? entry.msg)
      .filter(Boolean)
      .join("; ");
    if (validationMessage) return validationMessage;
  }
  if (payload.error?.message) return payload.error.message;
  return payload.message ?? fallback;
};

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
      signal,
      credentials: "same-origin",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      "ConnectMap API is not reachable. Check that the service is running.",
      0,
      "network_error",
    );
  }

  if (!response.ok) {
    let payload: ApiErrorPayload = {};
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      // A sanitized status message is safer than reflecting an arbitrary body.
    }
    throw new ApiError(
      parseErrorMessage(payload, `Request failed (${response.status})`),
      response.status,
      payload.error?.code,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  getConfigStatus: (signal?: AbortSignal) =>
    request<ConfigStatus>("/api/config/status", {}, signal),

  testConfig: (payload: ConfigPayload, signal?: AbortSignal) =>
    request<TestConnectionResult>(
      "/api/config/test",
      { method: "POST", body: JSON.stringify(payload) },
      signal,
    ),

  saveConfig: (payload: ConfigPayload, signal?: AbortSignal) =>
    request<ConfigStatus>(
      "/api/config",
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  getTopology: (signal?: AbortSignal) =>
    request<TopologySnapshot>("/api/topology", {}, signal),

  refreshTopology: (signal?: AbortSignal) =>
    request<{
      accepted: boolean;
      in_progress: boolean;
      correlation_id?: string;
    }>("/api/topology/refresh", { method: "POST" }, signal),

  getSettings: (signal?: AbortSignal) =>
    request<Settings>("/api/settings", {}, signal),

  updateSettings: (payload: Partial<Settings>, signal?: AbortSignal) =>
    request<Settings>(
      "/api/settings",
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  saveLayout: (payload: LayoutUpdate, signal?: AbortSignal) =>
    request<{ ok: boolean }>(
      "/api/layout",
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  resetLayout: (signal?: AbortSignal) =>
    request<{ ok: boolean }>(
      "/api/layout/reset",
      { method: "POST" },
      signal,
    ),

  updateEdgeStyle: (
    edgeId: string,
    payload: EdgeVisualStyleUpdate,
    signal?: AbortSignal,
  ) =>
    request<EdgeVisualStyle>(
      `/api/edges/${encodeURIComponent(edgeId)}/style`,
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  resetEdgeStyle: (edgeId: string, signal?: AbortSignal) =>
    request<{ ok: boolean }>(
      `/api/edges/${encodeURIComponent(edgeId)}/style`,
      { method: "DELETE" },
      signal,
    ),

  getVisualTopology: (signal?: AbortSignal) =>
    request<VisualTopology>("/api/visual-topology", {}, signal),

  createVisualElement: (
    payload: VisualElementCreate,
    signal?: AbortSignal,
  ) =>
    request<VisualElement>(
      "/api/visual-elements",
      { method: "POST", body: JSON.stringify(payload) },
      signal,
    ),

  updateVisualElement: (
    elementId: string,
    payload: VisualElementUpdate,
    signal?: AbortSignal,
  ) =>
    request<VisualElement>(
      `/api/visual-elements/${encodeURIComponent(elementId)}`,
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  deleteVisualElement: (
    elementId: string,
    ejectMembers = false,
    leaveUnrouted = false,
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (ejectMembers) query.set("eject_members", "true");
    if (leaveUnrouted) query.set("leave_unrouted", "true");
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    return request<{
      ok: boolean;
      ejected_member_ids: string[];
      unrouted_connection_ids: string[];
    }>(
      `/api/visual-elements/${encodeURIComponent(elementId)}${suffix}`,
      { method: "DELETE" },
      signal,
    );
  },

  addRackMember: (
    rackId: string,
    payload: RackMembershipUpdate,
    signal?: AbortSignal,
  ) =>
    request<RackMembership>(
      `/api/racks/${encodeURIComponent(rackId)}/members`,
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  removeRackMember: (
    rackId: string,
    connectionId: string,
    signal?: AbortSignal,
  ) =>
    request<{ ok: boolean }>(
      `/api/racks/${encodeURIComponent(rackId)}/members/${encodeURIComponent(connectionId)}`,
      { method: "DELETE" },
      signal,
    ),

  createVisualLink: (payload: VisualLinkCreate, signal?: AbortSignal) =>
    request<VisualLink>(
      "/api/visual-links",
      { method: "POST", body: JSON.stringify(payload) },
      signal,
    ),

  updateVisualLink: (
    linkId: string,
    payload: VisualLinkUpdate,
    signal?: AbortSignal,
  ) =>
    request<VisualLink>(
      `/api/visual-links/${encodeURIComponent(linkId)}`,
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  deleteVisualLink: (linkId: string, signal?: AbortSignal) =>
    request<{ ok: boolean }>(
      `/api/visual-links/${encodeURIComponent(linkId)}`,
      { method: "DELETE" },
      signal,
    ),

  updateEdgeRoute: (
    edgeId: string,
    payload: EdgeRouteUpdate,
    signal?: AbortSignal,
  ) =>
    request<EdgeRoute | null>(
      `/api/edges/${encodeURIComponent(edgeId)}/route`,
      { method: "PUT", body: JSON.stringify(payload) },
      signal,
    ),

  resetEdgeRoute: (edgeId: string, signal?: AbortSignal) =>
    request<{ ok: boolean }>(
      `/api/edges/${encodeURIComponent(edgeId)}/route`,
      { method: "DELETE" },
      signal,
    ),

  updateInterfaceOverride: (
    connectionId: string,
    interfaceName: SdexInterfaceName,
    signal?: AbortSignal,
  ) =>
    request<{ ok: boolean }>(
      `/api/connections/${encodeURIComponent(connectionId)}/interface-override`,
      {
        method: "PUT",
        body: JSON.stringify({ interface_name: interfaceName }),
      },
      signal,
    ),

  resetInterfaceOverride: (connectionId: string, signal?: AbortSignal) =>
    request<{ ok: boolean }>(
      `/api/connections/${encodeURIComponent(connectionId)}/interface-override`,
      { method: "DELETE" },
      signal,
    ),

  updateConnectionVisualRouting: (
    connectionId: string,
    sourceHandle: ConnectionSourceHandle,
    signal?: AbortSignal,
  ) =>
    request<DeviceVisualRouting>(
      `/api/connections/${encodeURIComponent(connectionId)}/visual-routing`,
      {
        method: "PUT",
        body: JSON.stringify({ source_handle: sourceHandle }),
      },
      signal,
    ),

  resetConnectionVisualRouting: (
    connectionId: string,
    signal?: AbortSignal,
  ) =>
    request<{ ok: boolean }>(
      `/api/connections/${encodeURIComponent(connectionId)}/visual-routing`,
      { method: "DELETE" },
      signal,
    ),
};

export function subscribeToTopologyEvents(
  onEvent: (event: TopologyEvent) => void,
  onConnectionChange?: (connected: boolean) => void,
): () => void {
  if (typeof EventSource === "undefined") return () => undefined;

  const source = new EventSource("/api/events", { withCredentials: true });
  const consume = (message: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(message.data) as TopologyEvent);
    } catch {
      // Ignore malformed events; the next valid topology event will recover.
    }
  };
  const namedEvents = ["topology", "refresh", "status"] as const;

  source.onopen = () => onConnectionChange?.(true);
  source.onerror = () => onConnectionChange?.(false);
  source.onmessage = consume;
  namedEvents.forEach((name) => source.addEventListener(name, consume));

  return () => {
    namedEvents.forEach((name) => source.removeEventListener(name, consume));
    source.close();
  };
}
