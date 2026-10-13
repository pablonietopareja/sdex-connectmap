import { memo, useEffect } from "react";
import {
  Handle,
  Position,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import type {
  SwitchHandleView,
  SwitchNodeViewData,
} from "../editor/types";
import { StatusBadge } from "../StatusBadge";

export const SWITCH_ICON = "/icons/Switch.svg";

export type SwitchFlowNode = Node<SwitchNodeViewData, "switch">;

function handlesForSide(
  handles: readonly SwitchHandleView[],
  side: SwitchHandleView["side"],
): readonly SwitchHandleView[] {
  return handles.filter((handle) => handle.side === side);
}

function SwitchNodeCardComponent({
  id,
  data,
  selected,
}: NodeProps<SwitchFlowNode>) {
  const updateNodeInternals = useUpdateNodeInternals();
  const leftHandles = handlesForSide(data.handles, "left");
  const rightHandles = handlesForSide(data.handles, "right");
  const visualLinkCount = data.handles.filter(
    (handle) => handle.id !== "left:new" && handle.id !== "right:new",
  ).length;
  const handleSignature = data.handles
    .map((handle) => `${handle.id}:${handle.side}:${handle.type}`)
    .join("|");

  useEffect(() => {
    updateNodeInternals(id);
  }, [handleSignature, id, updateNodeInternals]);

  const renderHandles = (
    handles: readonly SwitchHandleView[],
    side: SwitchHandleView["side"],
  ) =>
    handles.map((handle, index) => (
      <Handle
        id={handle.id}
        key={handle.id}
        type={handle.type}
        position={side === "left" ? Position.Left : Position.Right}
        aria-label={handle.label ?? `Switch ${side} connection ${index + 1}`}
        style={{ top: `${((index + 1) / (handles.length + 1)) * 100}%` }}
      />
    ));

  const visualSwitch = data.visualSwitch;
  const aggregate = visualSwitch.aggregate;
  const aggregateStatus = aggregate?.status ?? "unknown";
  return (
    <article
      className={`switch-node-card node-status-${aggregateStatus}${selected ? " selected" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${visualSwitch.name}, ConnectMap topology switch. Double-click for properties`}
      data-testid="switch-node"
      onDoubleClick={(event) => {
        event.stopPropagation();
        data.onOpen(visualSwitch);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        data.onOpen(visualSwitch);
      }}
    >
      {renderHandles(leftHandles, "left")}
      {renderHandles(rightHandles, "right")}
      <div className="switch-node-accent" aria-hidden="true" />
      <header className="switch-node-header">
        <span>ConnectMap topology element</span>
        <strong title={visualSwitch.name}>{visualSwitch.name}</strong>
      </header>
      <div className="switch-node-main">
        <div className="switch-node-icon-shell">
          <img src={SWITCH_ICON} alt="" draggable={false} />
        </div>
        <div className="switch-node-copy">
          <strong>Visual cable aggregator</strong>
          <span title={visualSwitch.description ?? undefined}>
            {visualSwitch.description || "No device telemetry is asserted."}
          </span>
          <small>
            Interface: {visualSwitch.effective_external_interface ?? "Not selected"}
            {visualSwitch.interface_conflict ? " (conflict)" : ""}
          </small>
        </div>
      </div>
      <footer className="switch-node-footer">
        <StatusBadge status={aggregateStatus} compact />
        {aggregate && (
          <span
            className="switch-aggregate-counts"
            title="Connected / disconnected / unknown / disabled"
          >
            {aggregate.connected} / {aggregate.disconnected} / {aggregate.unknown} / {aggregate.disabled}
          </span>
        )}
        <small>
          {visualLinkCount} visual {visualLinkCount === 1 ? "link" : "links"}
        </small>
      </footer>
    </article>
  );
}

export const SwitchNodeCard = memo(SwitchNodeCardComponent);
