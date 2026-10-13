import { useEffect, type DragEvent } from "react";
import type { VisualTool } from "./types";

export const VISUAL_ELEMENT_DRAG_TYPE = "application/x-connectmap-element";

const TOOLS: ReadonlyArray<{
  id: VisualTool;
  label: string;
  description: string;
}> = [
  {
    id: "rack",
    label: "Rack",
    description: "Group industrial connections in a slot matrix",
  },
  {
    id: "switch",
    label: "Switch",
    description: "Add a local cable aggregation element",
  },
];

export function readVisualToolDrag(dataTransfer: DataTransfer): VisualTool | null {
  const value = dataTransfer.getData(VISUAL_ELEMENT_DRAG_TYPE);
  return value === "rack" || value === "switch" ? value : null;
}

export interface EditorToolbarProps {
  visible: boolean;
  activeTool?: VisualTool | null;
  onCreate: (tool: VisualTool) => void;
  onToolDragStart?: (tool: VisualTool) => void;
  onToolDragEnd?: () => void;
  onCancel?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  historyBusy?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
}

export function EditorToolbar({
  visible,
  activeTool = null,
  onCreate,
  onToolDragStart,
  onToolDragEnd,
  onCancel,
  canUndo = false,
  canRedo = false,
  historyBusy = false,
  onUndo,
  onRedo,
}: EditorToolbarProps) {
  useEffect(() => {
    if (!visible || !activeTool || !onCancel) return undefined;
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onCancel();
    };
    document.addEventListener("keydown", cancelOnEscape);
    return () => document.removeEventListener("keydown", cancelOnEscape);
  }, [activeTool, onCancel, visible]);

  if (!visible) return null;

  const startDrag = (event: DragEvent<HTMLButtonElement>, tool: VisualTool) => {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(VISUAL_ELEMENT_DRAG_TYPE, tool);
    event.dataTransfer.setData("text/plain", tool);
    onToolDragStart?.(tool);
  };

  return (
    <nav
      className="editor-toolbar nodrag nopan"
      aria-label="Editor elements"
      data-testid="editor-toolbar"
    >
      <span className="editor-toolbar-title">Add element</span>
      {TOOLS.map((tool) => (
        <button
          className={`editor-tool${activeTool === tool.id ? " is-active" : ""}`}
          type="button"
          key={tool.id}
          draggable
          aria-label={`Add ${tool.label}`}
          aria-pressed={activeTool === tool.id}
          title={`${tool.description}. Drag to place or click to add at the visible center.`}
          data-tool={tool.id}
          onClick={() => onCreate(tool.id)}
          onDragStart={(event) => startDrag(event, tool.id)}
          onDragEnd={() => onToolDragEnd?.()}
        >
          <span className={`editor-tool-preview editor-tool-preview--${tool.id}`}>
            {tool.id === "rack" ? (
              <span className="rack-tool-grid" aria-hidden="true">
                <span />
                <span />
                <span className="rack-tool-empty">+</span>
              </span>
            ) : (
              <img src="/icons/Switch.svg" alt="" draggable={false} />
            )}
          </span>
          <span>{tool.label}</span>
        </button>
      ))}
      <div className="editor-history-controls" aria-label="Editor history">
        <button
          type="button"
          disabled={!canUndo || historyBusy}
          aria-label="Undo visual change"
          title="Undo (Ctrl+Z)"
          onClick={onUndo}
        >
          <span aria-hidden="true">↶</span>
        </button>
        <button
          type="button"
          disabled={!canRedo || historyBusy}
          aria-label="Redo visual change"
          title="Redo (Ctrl+Y or Ctrl+Shift+Z)"
          onClick={onRedo}
        >
          <span aria-hidden="true">↷</span>
        </button>
      </div>
    </nav>
  );
}
