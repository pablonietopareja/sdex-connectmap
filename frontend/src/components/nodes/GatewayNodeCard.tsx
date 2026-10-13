import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { nodeIcon } from "../../utils";
import type { GatewayFlowNode } from "../canvas/types";
import { LockIcon } from "../icons";
import { StatusBadge } from "../StatusBadge";

function GatewayNodeCardComponent({ data, selected }: NodeProps<GatewayFlowNode>) {
  const gateway = data.connection;
  const interfaceByName = new Map(
    (data.networkInterfaces ?? []).map((networkInterface) => [
      networkInterface.name,
      networkInterface,
    ] as const),
  );
  const interfaceLabels = (["eth1", "eth2"] as const).map((name) => {
    const networkInterface = interfaceByName.get(name);
    const address = networkInterface?.addresses[0];
    return {
      name,
      value: address
        ? `${address.address}${
            address.prefix_length === null ? "" : `/${address.prefix_length}`
          }`
        : "Not reported",
    };
  });

  return (
    <article
      className={[
        "gateway-node-card",
        `node-status-${gateway.status}`,
        gateway.stale ? "node-stale" : "",
        selected ? "selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      role="button"
      tabIndex={0}
      aria-label={`SDEX gateway, ${gateway.status}, locked position. Double-click for details`}
      data-testid="gateway-node"
      onDoubleClick={(event) => {
        event.stopPropagation();
        data.onOpen(gateway);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          data.onOpen(gateway);
        }
      }}
    >
      <Handle
        id="sdex-eth1"
        type="target"
        position={Position.Top}
        aria-label="SDEX eth1 target"
      />
      <Handle
        id="sdex-eth2"
        type="target"
        position={Position.Bottom}
        aria-label="SDEX eth2 target"
      />
      {interfaceLabels.map(({ name, value }) => (
        <span
          className={`gateway-interface-label gateway-interface-label--${
            name === "eth1" ? "top" : "bottom"
          }`}
          data-interface={name}
          key={name}
        >
          <strong>{name}</strong>
          <small title={value}>{value}</small>
        </span>
      ))}
      <div className="gateway-ring" aria-hidden="true" />
      <div className="gateway-node-surface">
        <header className="gateway-header">
          <strong>SDEX Suite</strong>
        </header>
        <div className="gateway-main">
          <div className="gateway-icon-shell">
            <img src={nodeIcon(gateway)} alt="" draggable={false} />
          </div>
        </div>
        <footer className="gateway-footer">
          <div className="gateway-status-area">
            <StatusBadge status={gateway.status} compact />
            <span className="locked-label">
              <LockIcon />
              Locked
            </span>
          </div>
        </footer>
      </div>
    </article>
  );
}

export const GatewayNodeCard = memo(GatewayNodeCardComponent);
