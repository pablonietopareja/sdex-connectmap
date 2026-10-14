import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DetailsDrawer } from "./components/DetailsDrawer";
import { EdgeStylePanel } from "./components/EdgeStylePanel";
import { RackPropertiesPanel } from "./components/editor/RackPropertiesPanel";
import { SwitchPropertiesPanel } from "./components/editor/SwitchPropertiesPanel";
import type {
  RackElementView,
  SwitchElementView,
} from "./components/editor/types";
import { FatalError } from "./components/FatalError";
import { LoadingScreen, TopologyLoading } from "./components/LoadingScreen";
import { Onboarding } from "./components/Onboarding";
import { SettingsModal } from "./components/SettingsModal";
import { SummaryPanel } from "./components/SummaryPanel";
import { TopBar } from "./components/TopBar";
import { TopologyCanvas } from "./components/canvas/TopologyCanvas";
import { CloseIcon } from "./components/icons";
import { REFRESH_OPTIONS } from "./constants";
import { useTheme } from "./hooks/useTheme";
import { useEditorHistory } from "./hooks/useEditorHistory";
import { useTopologyEvents } from "./hooks/useTopologyEvents";
import { api, ApiError } from "./services/api";
import type {
  ConfigPayload,
  ConfigStatus,
  ConnectionSourceHandle,
  ConnectionNode,
  EdgeVisualStyle,
  EdgeVisualStyleUpdate,
  EdgeRoute,
  EdgeRouteUpdate,
  LayoutUpdate,
  ManualNetworkInterface,
  Settings,
  ThemePreference,
  TopologyEvent,
  TopologySnapshot,
  VisualElement,
  VisualElementCreate,
  VisualElementUpdate,
  VisualLink,
  VisualLinkCreate,
} from "./types";
import { withCompleteLayout } from "./utils";

const DEFAULT_SETTINGS: Settings = {
  refresh_interval_seconds: 300,
  allowed_refresh_intervals: REFRESH_OPTIONS.map((option) => option.value),
  show_not_enabled: false,
  theme: "system",
  network_interfaces: [],
};

function friendlyError(error: unknown, fallback: string): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : fallback;
}

function snapshotWithEdgeStyle(
  snapshot: TopologySnapshot,
  edgeId: string,
  style: EdgeVisualStyle | null,
): TopologySnapshot {
  const edgeStyles = { ...(snapshot.edge_styles ?? {}) };
  if (style) edgeStyles[edgeId] = style;
  else delete edgeStyles[edgeId];

  return {
    ...snapshot,
    edges: snapshot.edges?.map((edge) =>
      edge.id === edgeId ? { ...edge, style } : edge,
    ),
    edge_styles:
      Object.keys(edgeStyles).length > 0 ? edgeStyles : undefined,
  };
}

function snapshotWithEdgeRoute(
  snapshot: TopologySnapshot,
  edgeId: string,
  route: EdgeRoute | null,
): TopologySnapshot {
  const visualTopology = snapshot.visual_topology;
  const routes = { ...(visualTopology?.routes ?? {}) };
  if (route) routes[edgeId] = route;
  else delete routes[edgeId];
  return {
    ...snapshot,
    edges: snapshot.edges?.map((edge) =>
      edge.id === edgeId ? { ...edge, route } : edge,
    ),
    visual_topology: visualTopology
      ? { ...visualTopology, routes }
      : visualTopology,
  };
}

function snapshotWithLayout(
  snapshot: TopologySnapshot,
  update: LayoutUpdate,
): TopologySnapshot {
  const positions = { ...(snapshot.layout?.positions ?? {}) };
  for (const position of update.positions ?? []) {
    positions[position.node_id] = { x: position.x, y: position.y };
  }
  return {
    ...snapshot,
    layout: {
      ...snapshot.layout,
      positions,
      viewport: update.viewport ?? snapshot.layout?.viewport ?? null,
    },
  };
}

function visualElementBeforeUpdate(
  element: VisualElement,
  update: VisualElementUpdate,
): VisualElementUpdate {
  const before: VisualElementUpdate = {};
  if ("name" in update) before.name = element.name;
  if ("description" in update) before.description = element.description;
  if ("position" in update) before.position = { ...element.position };
  if ("external_interface" in update) {
    before.external_interface = element.external_interface;
  }
  if (element.type === "rack") {
    if ("rows" in update) before.rows = element.rows;
    if ("columns" in update) before.columns = element.columns;
    if ("collapsed" in update) before.collapsed = element.collapsed;
  }
  if (element.type === "switch" && "status_mode" in update) {
    before.status_mode = element.status_mode;
  }
  return before;
}

function edgeStyleUpdate(style: EdgeVisualStyle): EdgeVisualStyleUpdate {
  return {
    sheath_color: style.sheath_color,
    flow_color: style.flow_color,
    reverse_flow: style.reverse_flow === true,
  };
}

function edgeRouteUpdate(route: EdgeRoute): EdgeRouteUpdate {
  return {
    routing_mode: route.routing_mode,
    waypoints: route.waypoints.map((waypoint) => ({ ...waypoint })),
  };
}

export default function App() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [snapshot, setSnapshot] = useState<TopologySnapshot | null>(null);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [initializing, setInitializing] = useState(true);
  const [topologyLoading, setTopologyLoading] = useState(false);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [notification, setNotification] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [editorEnabled, setEditorEnabled] = useState(false);
  const [selectedNode, setSelectedNode] = useState<ConnectionNode | null>(null);
  const [selectedVisualId, setSelectedVisualId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [interfaceOverrideBusy, setInterfaceOverrideBusy] = useState<
    string | null
  >(null);
  const [summaryCollapsed, setSummaryCollapsed] = useState(
    () => window.innerWidth < 900,
  );
  const { preference: theme, setPreference: setTheme } = useTheme();
  const refreshPollTimer = useRef<number | null>(null);
  const refreshPollGeneration = useRef(0);
  const topologyRequestGeneration = useRef(0);
  const historyError = useCallback((error: unknown) => {
    setNotification(
      friendlyError(error, "The visual editor operation could not be restored."),
    );
  }, []);
  const {
    execute: executeHistory,
    undo: undoHistory,
    redo: redoHistory,
    canUndo,
    canRedo,
    busy: historyBusy,
  } = useEditorHistory({
    enabled: editorEnabled,
    onError: historyError,
  });

  const loadTopology = useCallback(async (signal?: AbortSignal) => {
    const generation = ++topologyRequestGeneration.current;
    const next = await api.getTopology(signal);
    // An older refresh must not overwrite a snapshot loaded after a local edit.
    if (signal?.aborted || generation !== topologyRequestGeneration.current) {
      return null;
    }
    setSnapshot(next);
    setSelectedNode((selected) => {
      if (!selected) return null;
      return next.gateway.id === selected.id
        ? next.gateway
        : (next.nodes.find((node) => node.id === selected.id) ?? null);
    });
    setSelectedEdgeId((selected) => {
      if (!selected) return null;
      const exists =
        next.edges?.some((edge) => edge.id === selected) ??
        next.nodes.some((node) => `sdex-to-${node.id}` === selected);
      return exists ? selected : null;
    });
    setSelectedVisualId((selected) =>
      selected &&
      next.visual_topology?.elements.some((element) => element.id === selected)
        ? selected
        : null,
    );
    return next;
  }, []);

  const loadApplication = useCallback(async (signal?: AbortSignal) => {
    setInitializing(true);
    setFatalError(null);
    try {
      const status = await api.getConfigStatus(signal);
      setConfig(status);
      if (status.configured) {
        setTopologyLoading(true);
        const [nextSettings] = await Promise.all([
          api.getSettings(signal),
          loadTopology(signal),
        ]);
        setSettings(nextSettings);
        setTheme(nextSettings.theme);
      } else {
        setSnapshot(null);
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setFatalError(
          friendlyError(error, "ConnectMap could not load its configuration."),
        );
      }
    } finally {
      if (!signal?.aborted) {
        setInitializing(false);
        setTopologyLoading(false);
      }
    }
  }, [loadTopology, setTheme]);

  useEffect(() => {
    const controller = new AbortController();
    void loadApplication(controller.signal);
    return () => controller.abort();
  }, [loadApplication]);

  const cancelRefreshPolling = useCallback(() => {
    refreshPollGeneration.current += 1;
    if (refreshPollTimer.current !== null) {
      window.clearTimeout(refreshPollTimer.current);
      refreshPollTimer.current = null;
    }
  }, []);

  const startRefreshPolling = useCallback(() => {
    cancelRefreshPolling();
    const generation = refreshPollGeneration.current;
    let attempt = 0;

    const schedule = (delay: number) => {
      refreshPollTimer.current = window.setTimeout(() => {
        void poll();
      }, delay);
    };

    const poll = async () => {
      if (generation !== refreshPollGeneration.current) return;
      try {
        const next = await loadTopology();
        if (next && !next.refresh_in_progress) {
          cancelRefreshPolling();
          return;
        }
      } catch (error) {
        if (attempt >= 60) {
          setNotification(
            friendlyError(
              error,
              "Refresh status could not be confirmed. Live updates will continue.",
            ),
          );
        }
      }
      attempt += 1;
      if (attempt >= 60) {
        cancelRefreshPolling();
        setSnapshot((current) =>
          current ? { ...current, refresh_in_progress: false } : current,
        );
        setNotification(
          "Refresh status timed out. Live updates remain active and the current snapshot is preserved.",
        );
        return;
      }
      schedule(1_000);
    };

    schedule(700);
  }, [cancelRefreshPolling, loadTopology]);

  useEffect(() => cancelRefreshPolling, [cancelRefreshPolling]);

  const handleEvent = useCallback(
    (event: TopologyEvent) => {
      if (event.type === "refresh.started") {
        setSnapshot((current) =>
          current ? { ...current, refresh_in_progress: true } : current,
        );
      }
      if (
        event.type === "topology.updated" ||
        event.type === "refresh.failed"
      ) {
        void loadTopology()
          .then((next) => {
            if (next && !next.refresh_in_progress) cancelRefreshPolling();
          })
          .catch((error) =>
            setNotification(
              friendlyError(error, "The updated topology could not be loaded."),
            ),
          );
      }
    },
    [cancelRefreshPolling, loadTopology],
  );
  const eventsConnected = useTopologyEvents(handleEvent);

  const saveConfiguration = async (payload: ConfigPayload) => {
    const status = await api.saveConfig(payload);
    setConfig(status);
    setTopologyLoading(true);
    try {
      const [nextSettings] = await Promise.all([
        api.getSettings(),
        loadTopology(),
      ]);
      setSettings(nextSettings);
      setTheme(nextSettings.theme);
      setSettingsOpen(false);
    } finally {
      setTopologyLoading(false);
    }
  };

  const updateSetting = async <K extends keyof Settings>(
    key: K,
    value: Settings[K],
  ) => {
    const previous = settings;
    setSettings((current) => ({ ...current, [key]: value }));
    try {
      const saved = await api.updateSettings({ [key]: value });
      setSettings(saved);
    } catch (error) {
      setSettings(previous);
      setNotification(friendlyError(error, "The preference could not be saved."));
    }
  };

  const handleThemeChange = (next: ThemePreference) => {
    setTheme(next);
    void updateSetting("theme", next);
  };

  const handleRefresh = async () => {
    setSnapshot((current) =>
      current ? { ...current, refresh_in_progress: true } : current,
    );
    try {
      await api.refreshTopology();
      startRefreshPolling();
    } catch (error) {
      setSnapshot((current) =>
        current ? { ...current, refresh_in_progress: false } : current,
      );
      setNotification(friendlyError(error, "Refresh could not be started."));
    }
  };

  const saveLayoutDirect = useCallback(async (update: LayoutUpdate) => {
    try {
      await api.saveLayout(update);
      setSnapshot((current) =>
        current ? snapshotWithLayout(current, update) : current,
      );
    } catch (error) {
      const message = friendlyError(error, "The layout could not be saved.");
      setNotification(message);
      throw error;
    }
  }, []);

  const saveLayout = useCallback(
    async (update: LayoutUpdate) => {
      if (!editorEnabled || !snapshot || !update.positions?.length) {
        await saveLayoutDirect(update);
        return;
      }
      const complete = withCompleteLayout(snapshot).positions;
      const before = update.positions.map((position) => {
        const previous = complete[position.node_id] ?? { x: 0, y: 0 };
        return { node_id: position.node_id, x: previous.x, y: previous.y };
      });
      const after = update.positions.map((position) => ({ ...position }));
      const changed = before.some(
        (position, index) =>
          position.x !== after[index]?.x || position.y !== after[index]?.y,
      );
      if (!changed) return;
      const executed = await executeHistory({
        action: "Move topology node",
        affectedIds: after.map((position) => position.node_id),
        before,
        after,
        execute: () => saveLayoutDirect({ positions: after }),
        undo: () => saveLayoutDirect({ positions: before }),
        redo: () => saveLayoutDirect({ positions: after }),
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [editorEnabled, executeHistory, saveLayoutDirect, snapshot],
  );

  const resetLayout = useCallback(async () => {
    await api.resetLayout();
  }, []);

  const openNodeDetails = useCallback((node: ConnectionNode) => {
    setSelectedEdgeId(null);
    setSelectedVisualId(null);
    setSelectedNode(node);
  }, []);

  const openVisualDetails = useCallback((element: VisualElement) => {
    setSelectedEdgeId(null);
    setSelectedNode(null);
    setSelectedVisualId(element.id);
  }, []);

  const openEdgeStyle = useCallback((edgeId: string) => {
    setSelectedNode(null);
    setSelectedVisualId(null);
    setSelectedEdgeId(edgeId);
  }, []);

  const applyEdgeStyleDirect = useCallback(
    async (
      edgeId: string,
      update: EdgeVisualStyleUpdate,
    ): Promise<EdgeVisualStyle> => {
      try {
        const saved = await api.updateEdgeStyle(edgeId, update);
        setSnapshot((current) =>
          current ? snapshotWithEdgeStyle(current, edgeId, saved) : current,
        );
        return saved;
      } catch (error) {
        setNotification(
          friendlyError(error, "The cable style could not be saved."),
        );
        throw error;
      }
    },
    [],
  );

  const resetEdgeStyleDirect = useCallback(async (edgeId: string): Promise<void> => {
    try {
      await api.resetEdgeStyle(edgeId);
      setSnapshot((current) =>
        current ? snapshotWithEdgeStyle(current, edgeId, null) : current,
      );
    } catch (error) {
      setNotification(
        friendlyError(error, "The cable style could not be reset."),
      );
      throw error;
    }
  }, []);

  const applyEdgeStyle = useCallback(
    async (
      edgeId: string,
      update: EdgeVisualStyleUpdate,
    ): Promise<EdgeVisualStyle> => {
      const before =
        snapshot?.edges?.find((edge) => edge.id === edgeId)?.style ??
        snapshot?.edge_styles?.[edgeId] ??
        null;
      if (!editorEnabled) return applyEdgeStyleDirect(edgeId, update);
      let saved: EdgeVisualStyle | null = null;
      const executed = await executeHistory({
        action: "Change cable appearance",
        affectedIds: [edgeId],
        before,
        after: update,
        execute: async () => {
          saved = await applyEdgeStyleDirect(edgeId, update);
        },
        undo: async () => {
          if (before) {
            await applyEdgeStyleDirect(edgeId, edgeStyleUpdate(before));
          } else {
            await resetEdgeStyleDirect(edgeId);
          }
        },
        redo: async () => {
          await applyEdgeStyleDirect(edgeId, update);
        },
      });
      if (!executed || !saved) {
        throw new Error("Another visual editor operation is still running.");
      }
      return saved;
    },
    [
      applyEdgeStyleDirect,
      editorEnabled,
      executeHistory,
      resetEdgeStyleDirect,
      snapshot,
    ],
  );

  const resetEdgeStyle = useCallback(async (edgeId: string): Promise<void> => {
    const before =
      snapshot?.edges?.find((edge) => edge.id === edgeId)?.style ??
      snapshot?.edge_styles?.[edgeId] ??
      null;
    if (!before || !editorEnabled) {
      await resetEdgeStyleDirect(edgeId);
      return;
    }
    const executed = await executeHistory({
      action: "Reset cable appearance",
      affectedIds: [edgeId],
      before,
      after: null,
      execute: () => resetEdgeStyleDirect(edgeId),
      undo: async () => {
        await applyEdgeStyleDirect(edgeId, edgeStyleUpdate(before));
      },
      redo: () => resetEdgeStyleDirect(edgeId),
    });
    if (!executed) {
      throw new Error("Another visual editor operation is still running.");
    }
  }, [
    applyEdgeStyleDirect,
    editorEnabled,
    executeHistory,
    resetEdgeStyleDirect,
    snapshot,
  ]);

  const saveEdgeRouteDirect = useCallback(
    async (edgeId: string, update: EdgeRouteUpdate): Promise<EdgeRoute | void> => {
      try {
        const saved = await api.updateEdgeRoute(edgeId, update);
        setSnapshot((current) =>
          current ? snapshotWithEdgeRoute(current, edgeId, saved) : current,
        );
        return saved ?? undefined;
      } catch (error) {
        setNotification(
          friendlyError(error, "The cable route could not be saved."),
        );
        throw error;
      }
    },
    [],
  );

  const resetEdgeRouteDirect = useCallback(async (edgeId: string): Promise<void> => {
    try {
      await api.resetEdgeRoute(edgeId);
      setSnapshot((current) =>
        current ? snapshotWithEdgeRoute(current, edgeId, null) : current,
      );
    } catch (error) {
      setNotification(
        friendlyError(error, "The cable route could not be reset."),
      );
      throw error;
    }
  }, []);

  const saveEdgeRoute = useCallback(
    async (edgeId: string, update: EdgeRouteUpdate): Promise<EdgeRoute | void> => {
      const before =
        snapshot?.edges?.find((edge) => edge.id === edgeId)?.route ??
        snapshot?.visual_topology?.routes[edgeId] ??
        null;
      if (!editorEnabled) return saveEdgeRouteDirect(edgeId, update);
      let saved: EdgeRoute | void = undefined;
      const executed = await executeHistory({
        action: "Edit cable route",
        affectedIds: [edgeId],
        before,
        after: update,
        execute: async () => {
          saved = await saveEdgeRouteDirect(edgeId, update);
        },
        undo: async () => {
          if (before) {
            await saveEdgeRouteDirect(edgeId, edgeRouteUpdate(before));
          } else {
            await resetEdgeRouteDirect(edgeId);
          }
        },
        redo: async () => {
          await saveEdgeRouteDirect(edgeId, update);
        },
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
      return saved;
    },
    [
      editorEnabled,
      executeHistory,
      resetEdgeRouteDirect,
      saveEdgeRouteDirect,
      snapshot,
    ],
  );

  const resetEdgeRoute = useCallback(async (edgeId: string): Promise<void> => {
    const before =
      snapshot?.edges?.find((edge) => edge.id === edgeId)?.route ??
      snapshot?.visual_topology?.routes[edgeId] ??
      null;
    if (!before || !editorEnabled) {
      await resetEdgeRouteDirect(edgeId);
      return;
    }
    const executed = await executeHistory({
      action: "Reset cable route",
      affectedIds: [edgeId],
      before,
      after: null,
      execute: () => resetEdgeRouteDirect(edgeId),
      undo: async () => {
        await saveEdgeRouteDirect(edgeId, edgeRouteUpdate(before));
      },
      redo: () => resetEdgeRouteDirect(edgeId),
    });
    if (!executed) {
      throw new Error("Another visual editor operation is still running.");
    }
  }, [
    editorEnabled,
    executeHistory,
    resetEdgeRouteDirect,
    saveEdgeRouteDirect,
    snapshot,
  ]);

  const deleteVisualLinkDirect = useCallback(
    async (edgeId: string): Promise<void> => {
      try {
        await api.deleteVisualLink(edgeId);
        setSelectedEdgeId(null);
        await loadTopology();
      } catch (error) {
        setNotification(
          friendlyError(error, "The visual link could not be removed."),
        );
        throw error;
      }
    },
    [loadTopology],
  );

  const createVisualElementDirect = useCallback(
    async (payload: VisualElementCreate): Promise<VisualElement> => {
      try {
        const created = await api.createVisualElement(payload);
        await loadTopology();
        return created;
      } catch (error) {
        setNotification(
          friendlyError(error, "The topology element could not be created."),
        );
        throw error;
      }
    },
    [loadTopology],
  );

  const updateVisualElementDirect = useCallback(
    async (elementId: string, payload: VisualElementUpdate) => {
      try {
        const saved = await api.updateVisualElement(elementId, payload);
        await loadTopology();
        return saved;
      } catch (error) {
        setNotification(
          friendlyError(error, "The topology element could not be saved."),
        );
        throw error;
      }
    },
    [loadTopology],
  );

  const deleteVisualElementDirect = useCallback(
    async (
      elementId: string,
      options: { leaveUnrouted?: boolean } = {},
    ) => {
      try {
        const isRack = snapshot?.visual_topology?.elements.some(
          (element) => element.id === elementId && element.type === "rack",
        );
        await api.deleteVisualElement(
          elementId,
          isRack,
          options.leaveUnrouted ?? false,
        );
        setSelectedVisualId(null);
        await loadTopology();
      } catch (error) {
        setNotification(
          friendlyError(error, "The topology element could not be deleted."),
        );
        throw error;
      }
    },
    [loadTopology, snapshot],
  );

  const createVisualLinkDirect = useCallback(
    async (payload: VisualLinkCreate): Promise<VisualLink> => {
      try {
        const link = await api.createVisualLink(payload);
        await loadTopology();
        return link;
      } catch (error) {
        setNotification(
          friendlyError(error, "The visual connection could not be created."),
        );
        throw error;
      }
    },
    [loadTopology],
  );

  const createVisualElement = useCallback(
    async (payload: VisualElementCreate): Promise<VisualElement> => {
      if (!editorEnabled) {
        const created = await createVisualElementDirect(payload);
        openVisualDetails(created);
        return created;
      }
      let created: VisualElement | null = null;
      const executed = await executeHistory({
        action: `Create ${payload.type}`,
        execute: async () => {
          created = await createVisualElementDirect(payload);
          openVisualDetails(created);
        },
        undo: async () => {
          if (created) await deleteVisualElementDirect(created.id);
        },
        redo: async () => {
          if (!created) return;
          created = await createVisualElementDirect({
            ...payload,
            id: created.id,
          });
        },
      });
      if (!executed || !created) {
        throw new Error("Another visual editor operation is still running.");
      }
      return created;
    },
    [
      createVisualElementDirect,
      deleteVisualElementDirect,
      editorEnabled,
      executeHistory,
      openVisualDetails,
    ],
  );

  const updateVisualElement = useCallback(
    async (elementId: string, payload: VisualElementUpdate) => {
      const element = snapshot?.visual_topology?.elements.find(
        (candidate) => candidate.id === elementId,
      );
      if (!editorEnabled || !element) {
        return updateVisualElementDirect(elementId, payload);
      }
      const before = visualElementBeforeUpdate(element, payload);
      let saved: VisualElement | null = null;
      const movedOnly =
        Object.keys(payload).length === 1 && payload.position !== undefined;
      const executed = await executeHistory({
        action: movedOnly ? `Move ${element.type}` : `Edit ${element.type}`,
        affectedIds: [elementId],
        before,
        after: payload,
        execute: async () => {
          saved = await updateVisualElementDirect(elementId, payload);
        },
        undo: async () => {
          await updateVisualElementDirect(elementId, before);
        },
        redo: async () => {
          await updateVisualElementDirect(elementId, payload);
        },
      });
      if (!executed || !saved) {
        throw new Error("Another visual editor operation is still running.");
      }
      return saved;
    },
    [editorEnabled, executeHistory, snapshot, updateVisualElementDirect],
  );

  const deleteVisualElement = useCallback(
    async (
      elementId: string,
      options: { leaveUnrouted?: boolean } = {},
    ) => {
      const currentSnapshot = snapshot;
      const element = currentSnapshot?.visual_topology?.elements.find(
        (candidate) => candidate.id === elementId,
      );
      if (!editorEnabled || !currentSnapshot || !element) {
        await deleteVisualElementDirect(elementId, options);
        return;
      }
      const rackMemberships =
        currentSnapshot.visual_topology?.rack_memberships.filter(
          (membership) => membership.rack_id === elementId,
        ) ?? [];
      const links =
        currentSnapshot.visual_topology?.links.filter(
          (link) => link.source === elementId || link.target === elementId,
        ) ?? [];
      const linkState = links.map((link) => ({
        link,
        route: currentSnapshot.visual_topology?.routes[link.id] ?? null,
        style:
          currentSnapshot.edges?.find((edge) => edge.id === link.id)?.style ??
          currentSnapshot.edge_styles?.[link.id] ??
          null,
      }));
      const recreate = async () => {
        await createVisualElementDirect({
          id: element.id,
          type: element.type,
          position: { ...element.position },
          name: element.name,
          description: element.description,
          external_interface: element.external_interface,
          ...(element.type === "rack"
            ? { rows: element.rows, columns: element.columns }
            : { status_mode: element.status_mode }),
        });
        for (const membership of rackMemberships) {
          await api.addRackMember(element.id, {
            connection_id: membership.connection_id,
            row: membership.row,
            column: membership.column,
            allow_unresolved_interface:
              membership.unresolved_interface_confirmed ?? false,
          });
        }
        for (const state of linkState) {
          await api.createVisualLink({
            id: state.link.id,
            source: state.link.source,
            target: state.link.target,
            source_handle: state.link.source_handle,
            target_handle: state.link.target_handle,
            external_interface: state.link.external_interface,
            allow_unresolved_interface:
              state.link.unresolved_interface_confirmed ?? false,
          });
          if (state.route) {
            await api.updateEdgeRoute(state.link.id, edgeRouteUpdate(state.route));
          }
          if (state.style) {
            await api.updateEdgeStyle(state.link.id, edgeStyleUpdate(state.style));
          }
        }
        await loadTopology();
      };
      const executed = await executeHistory({
        action: `Delete ${element.type}`,
        affectedIds: [elementId, ...links.map((link) => link.id)],
        before: { element, rackMemberships, linkState },
        after: null,
        execute: () => deleteVisualElementDirect(elementId, options),
        undo: recreate,
        redo: () => deleteVisualElementDirect(elementId, options),
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [
      createVisualElementDirect,
      deleteVisualElementDirect,
      editorEnabled,
      executeHistory,
      loadTopology,
      snapshot,
    ],
  );

  const addRackMemberDirect = useCallback(
    async (
      rackId: string,
      connectionId: string,
      row: number,
      column: number,
      allowUnresolvedInterface = false,
    ) => {
      try {
        await api.addRackMember(rackId, {
          connection_id: connectionId,
          row,
          column,
          allow_unresolved_interface: allowUnresolvedInterface,
        });
        await loadTopology();
      } catch (error) {
        setNotification(
          friendlyError(error, "The device could not be placed in the rack."),
        );
        throw error;
      }
    },
    [loadTopology],
  );

  const removeRackMemberDirect = useCallback(
    async (rackId: string, connectionId: string) => {
      try {
        await api.removeRackMember(rackId, connectionId);
        await loadTopology();
      } catch (error) {
        setNotification(
          friendlyError(error, "The device could not be removed from the rack."),
        );
        throw error;
      }
    },
    [loadTopology],
  );

  const addRackMember = useCallback(
    async (
      rackId: string,
      connectionId: string,
      row: number,
      column: number,
      allowUnresolvedInterface = false,
    ) => {
      const previous = snapshot?.visual_topology?.rack_memberships.find(
        (membership) => membership.connection_id === connectionId,
      );
      if (!editorEnabled) {
        await addRackMemberDirect(
          rackId,
          connectionId,
          row,
          column,
          allowUnresolvedInterface,
        );
        return;
      }
      const executed = await executeHistory({
        action: "Place device in Rack",
        affectedIds: [rackId, connectionId],
        before: previous ?? null,
        after: { rackId, connectionId, row, column },
        execute: () =>
          addRackMemberDirect(
            rackId,
            connectionId,
            row,
            column,
            allowUnresolvedInterface,
          ),
        undo: async () => {
          await removeRackMemberDirect(rackId, connectionId);
          if (previous) {
            await addRackMemberDirect(
              previous.rack_id,
              connectionId,
              previous.row,
              previous.column,
              previous.unresolved_interface_confirmed ?? false,
            );
          }
        },
        redo: () =>
          addRackMemberDirect(
            rackId,
            connectionId,
            row,
            column,
            allowUnresolvedInterface,
          ),
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [
      addRackMemberDirect,
      editorEnabled,
      executeHistory,
      removeRackMemberDirect,
      snapshot,
    ],
  );

  const removeRackMember = useCallback(
    async (rackId: string, connectionId: string) => {
      const previous = snapshot?.visual_topology?.rack_memberships.find(
        (membership) =>
          membership.rack_id === rackId &&
          membership.connection_id === connectionId,
      );
      if (!editorEnabled || !previous) {
        await removeRackMemberDirect(rackId, connectionId);
        return;
      }
      const executed = await executeHistory({
        action: "Remove device from Rack",
        affectedIds: [rackId, connectionId],
        before: previous,
        after: null,
        execute: () => removeRackMemberDirect(rackId, connectionId),
        undo: () =>
          addRackMemberDirect(
            rackId,
            connectionId,
            previous.row,
            previous.column,
            previous.unresolved_interface_confirmed ?? false,
          ),
        redo: () => removeRackMemberDirect(rackId, connectionId),
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [
      addRackMemberDirect,
      editorEnabled,
      executeHistory,
      removeRackMemberDirect,
      snapshot,
    ],
  );

  const createVisualLink = useCallback(
    async (payload: VisualLinkCreate): Promise<VisualLink> => {
      if (!editorEnabled) return createVisualLinkDirect(payload);
      let created: VisualLink | null = null;
      const executed = await executeHistory({
        action: "Create visual link",
        execute: async () => {
          created = await createVisualLinkDirect(payload);
        },
        undo: async () => {
          if (created) await deleteVisualLinkDirect(created.id);
        },
        redo: async () => {
          if (!created) return;
          created = await createVisualLinkDirect({
            ...payload,
            id: created.id,
            source_handle: created.source_handle,
            target_handle: created.target_handle,
          });
        },
      });
      if (!executed || !created) {
        throw new Error("Another visual editor operation is still running.");
      }
      return created;
    },
    [
      createVisualLinkDirect,
      deleteVisualLinkDirect,
      editorEnabled,
      executeHistory,
    ],
  );

  const deleteVisualLink = useCallback(
    async (edgeId: string): Promise<void> => {
      const currentSnapshot = snapshot;
      const link = currentSnapshot?.visual_topology?.links.find(
        (candidate) => candidate.id === edgeId,
      );
      if (!editorEnabled || !currentSnapshot || !link) {
        await deleteVisualLinkDirect(edgeId);
        return;
      }
      const route = currentSnapshot.visual_topology?.routes[edgeId] ?? null;
      const style =
        currentSnapshot.edges?.find((edge) => edge.id === edgeId)?.style ??
        currentSnapshot.edge_styles?.[edgeId] ??
        null;
      const restore = async () => {
        await api.createVisualLink({
          id: link.id,
          source: link.source,
          target: link.target,
          source_handle: link.source_handle,
          target_handle: link.target_handle,
          external_interface: link.external_interface,
          allow_unresolved_interface:
            link.unresolved_interface_confirmed ?? false,
        });
        if (route) await api.updateEdgeRoute(edgeId, edgeRouteUpdate(route));
        if (style) await api.updateEdgeStyle(edgeId, edgeStyleUpdate(style));
        await loadTopology();
      };
      const executed = await executeHistory({
        action: "Delete visual link",
        affectedIds: [edgeId],
        before: { link, route, style },
        after: null,
        execute: () => deleteVisualLinkDirect(edgeId),
        undo: restore,
        redo: () => deleteVisualLinkDirect(edgeId),
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [
      deleteVisualLinkDirect,
      editorEnabled,
      executeHistory,
      loadTopology,
      snapshot,
    ],
  );

  const saveNetworkInterfaces = async (
    interfaces: ManualNetworkInterface[],
  ): Promise<void> => {
    try {
      const saved = await api.updateSettings({ network_interfaces: interfaces });
      setSettings(saved);
      await loadTopology();
    } catch (error) {
      setNotification(
        friendlyError(error, "The network interface fallback could not be saved."),
      );
      throw error;
    }
  };

  const updateInterfaceOverride = async (
    connectionId: string,
    interfaceName: "eth1" | "eth2" | null,
  ): Promise<void> => {
    setInterfaceOverrideBusy(connectionId);
    try {
      if (interfaceName) {
        await api.updateInterfaceOverride(connectionId, interfaceName);
      } else {
        await api.resetInterfaceOverride(connectionId);
      }
      await loadTopology();
    } catch (error) {
      setNotification(
        friendlyError(error, "The interface override could not be saved."),
      );
      throw error;
    } finally {
      setInterfaceOverrideBusy(null);
    }
  };

  const reanchorConnection = useCallback(
    async (
      connectionId: string,
      sourceHandle: ConnectionSourceHandle,
    ): Promise<void> => {
      const edgeId = `sdex-to-${connectionId}`;
      const edge = snapshot?.edges?.find((candidate) => candidate.id === edgeId);
      if (!edge) {
        throw new Error("The primary SDEX cable is no longer available.");
      }
      const previous =
        edge.source_handle === "top" ||
        edge.source_handle === "right" ||
        edge.source_handle === "bottom" ||
        edge.source_handle === "left"
          ? edge.source_handle
          : null;
      if (previous === sourceHandle) return;
      const apply = async (handle: ConnectionSourceHandle) => {
        await api.updateConnectionVisualRouting(connectionId, handle);
        await loadTopology();
      };
      const reset = async () => {
        await api.resetConnectionVisualRouting(connectionId);
        await loadTopology();
      };
      if (!editorEnabled) {
        await apply(sourceHandle);
        return;
      }
      const executed = await executeHistory({
        action: "Re-anchor primary SDEX cable",
        affectedIds: [connectionId, edgeId],
        before: previous,
        after: sourceHandle,
        execute: () => apply(sourceHandle),
        undo: () => (previous ? apply(previous) : reset()),
        redo: () => apply(sourceHandle),
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [editorEnabled, executeHistory, loadTopology, snapshot],
  );

  const selectedEdgeStyle = useMemo(() => {
    if (!snapshot || !selectedEdgeId) return null;
    return (
      snapshot.edges?.find((edge) => edge.id === selectedEdgeId)?.style ??
      snapshot.edge_styles?.[selectedEdgeId] ??
      null
    );
  }, [selectedEdgeId, snapshot]);

  const selectedEdgeRoute = useMemo(() => {
    if (!snapshot || !selectedEdgeId) return null;
    return (
      snapshot.edges?.find((edge) => edge.id === selectedEdgeId)?.route ??
      snapshot.visual_topology?.routes[selectedEdgeId] ??
      null
    );
  }, [selectedEdgeId, snapshot]);

  const selectedEdgeIsVisualLink = useMemo(
    () =>
      Boolean(
        selectedEdgeId &&
          snapshot?.visual_topology?.links.some(
            (link) => link.id === selectedEdgeId,
          ),
      ),
    [selectedEdgeId, snapshot?.visual_topology?.links],
  );

  const selectedVisualElement = useMemo(
    () =>
      snapshot?.visual_topology?.elements.find(
        (element) => element.id === selectedVisualId,
      ) ?? null,
    [selectedVisualId, snapshot],
  );

  const selectedRack = useMemo<RackElementView | null>(() => {
    if (selectedVisualElement?.type !== "rack" || !snapshot) return null;
    const rackMemberships =
      snapshot.visual_topology?.rack_memberships.filter(
        (membership) => membership.rack_id === selectedVisualElement.id,
      ) ?? [];
    return {
      ...selectedVisualElement,
      member_ids: rackMemberships.map((membership) => membership.connection_id),
      slot_assignments: rackMemberships.map((membership) => ({
        row: membership.row,
        column: membership.column,
        connection_id: membership.connection_id,
      })),
    };
  }, [selectedVisualElement, snapshot]);

  const selectedSwitch = useMemo<SwitchElementView | null>(
    () =>
      selectedVisualElement?.type === "switch"
        ? selectedVisualElement
        : null,
    [selectedVisualElement],
  );

  const memberNames = useMemo(() => {
    const result: Record<string, string> = {};
    for (const node of snapshot?.nodes ?? []) result[node.id] = node.display_name;
    for (const membership of snapshot?.visual_topology?.rack_memberships ?? []) {
      if (membership.connection) {
        result[membership.connection_id] = membership.connection.display_name;
      }
    }
    return result;
  }, [snapshot]);

  const ungroupRack = useCallback(
    async (rackId: string) => {
      const rackMemberships =
        snapshot?.visual_topology?.rack_memberships
          .filter((membership) => membership.rack_id === rackId) ?? [];
      const removeAll = async () => {
        try {
          for (const membership of rackMemberships) {
            await api.removeRackMember(rackId, membership.connection_id);
          }
          await loadTopology();
        } catch (error) {
          setNotification(
            friendlyError(error, "The Rack members could not be ungrouped."),
          );
          throw error;
        }
      };
      const restoreAll = async () => {
        for (const membership of rackMemberships) {
          await api.addRackMember(rackId, {
            connection_id: membership.connection_id,
            row: membership.row,
            column: membership.column,
            allow_unresolved_interface:
              membership.unresolved_interface_confirmed ?? false,
          });
        }
        await loadTopology();
      };
      if (!editorEnabled || rackMemberships.length === 0) {
        await removeAll();
        return;
      }
      const executed = await executeHistory({
        action: "Ungroup Rack members",
        affectedIds: [
          rackId,
          ...rackMemberships.map((membership) => membership.connection_id),
        ],
        before: rackMemberships,
        after: [],
        execute: removeAll,
        undo: restoreAll,
        redo: removeAll,
      });
      if (!executed) {
        throw new Error("Another visual editor operation is still running.");
      }
    },
    [editorEnabled, executeHistory, loadTopology, snapshot],
  );

  const visibleSummary = useMemo(() => {
    if (!snapshot) return null;
    return snapshot.summary;
  }, [snapshot]);

  if (initializing) return <LoadingScreen />;
  if (fatalError) {
    return <FatalError message={fatalError} onRetry={() => void loadApplication()} />;
  }
  if (!config?.configured) {
    return (
      <Onboarding
        status={config}
        onSave={saveConfiguration}
      />
    );
  }
  if (topologyLoading || !snapshot || !visibleSummary) return <TopologyLoading />;

  return (
    <div className="app-shell">
      <TopBar
        snapshot={snapshot}
        editorEnabled={editorEnabled}
        showNotEnabled={settings.show_not_enabled}
        refreshInterval={settings.refresh_interval_seconds}
        theme={theme}
        eventsConnected={eventsConnected}
        tlsWarning={config.tls_warning || !config.verify_tls}
        onEditorChange={setEditorEnabled}
        onShowNotEnabledChange={(enabled) =>
          void updateSetting("show_not_enabled", enabled)
        }
        onRefreshIntervalChange={(seconds) =>
          void updateSetting("refresh_interval_seconds", seconds)
        }
        onThemeChange={handleThemeChange}
        onRefresh={() => void handleRefresh()}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main className="workspace">
        <TopologyCanvas
          snapshot={snapshot}
          editorEnabled={editorEnabled}
          showNotEnabled={settings.show_not_enabled}
          onSelectNode={openNodeDetails}
          onSelectVisual={openVisualDetails}
          onConfigureEdge={openEdgeStyle}
          onSaveLayout={saveLayout}
          onResetLayout={resetLayout}
          onCreateVisualElement={createVisualElement}
          onUpdateVisualElement={updateVisualElement}
          onDeleteVisualElement={deleteVisualElement}
          onAddRackMember={addRackMember}
          onRemoveRackMember={removeRackMember}
          onCreateVisualLink={createVisualLink}
          onReanchorConnection={reanchorConnection}
          onSaveEdgeRoute={saveEdgeRoute}
          onResetEdgeRoute={resetEdgeRoute}
          onNotify={setNotification}
          canUndo={canUndo}
          canRedo={canRedo}
          historyBusy={historyBusy}
          onUndo={() => void undoHistory()}
          onRedo={() => void redoHistory()}
        />
        <SummaryPanel
          summary={visibleSummary}
          collapsed={summaryCollapsed}
          onToggle={() => setSummaryCollapsed((current) => !current)}
        />
        <DetailsDrawer
          node={selectedNode}
          networkInterfaces={snapshot.network_interfaces ?? []}
          onInterfaceOverride={updateInterfaceOverride}
          interfaceOverrideBusy={interfaceOverrideBusy === selectedNode?.id}
          onClose={() => setSelectedNode(null)}
        />
        <RackPropertiesPanel
          rack={selectedRack}
          memberNames={memberNames}
          onClose={() => setSelectedVisualId(null)}
          onSave={async (rackId, update, options) => {
            await updateVisualElement(rackId, {
              ...update,
              overflow_policy: options.expelOverflow ? "eject" : "reject",
            });
          }}
          onUngroupAll={ungroupRack}
          onDelete={deleteVisualElement}
        />
        <SwitchPropertiesPanel
          visualSwitch={selectedSwitch}
          onClose={() => setSelectedVisualId(null)}
          onSave={async (switchId, update) => {
            await updateVisualElement(switchId, update);
          }}
          onDelete={deleteVisualElement}
        />
        <EdgeStylePanel
          edgeId={selectedEdgeId}
          style={selectedEdgeStyle}
          route={selectedEdgeRoute}
          visualLink={selectedEdgeIsVisualLink}
          onClose={() => setSelectedEdgeId(null)}
          onApply={applyEdgeStyle}
          onReset={resetEdgeStyle}
          onResetRoute={resetEdgeRoute}
          onDeleteVisualLink={deleteVisualLink}
        />
      </main>

      {notification && (
        <div className="toast" role="alert">
          <span>{notification}</span>
          <button
            className="icon-button"
            type="button"
            aria-label="Dismiss notification"
            onClick={() => setNotification(null)}
          >
            <CloseIcon />
          </button>
        </div>
      )}

      <SettingsModal
        open={settingsOpen}
        status={config}
        settings={settings}
        onClose={() => setSettingsOpen(false)}
        onSave={saveConfiguration}
        onSaveNetworkInterfaces={saveNetworkInterfaces}
      />
    </div>
  );
}
