import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createEditorHistoryStore } from "../editor/history";
import {
  getEditorHistoryShortcut,
  isHistoryShortcutBlocked,
  useEditorHistory,
} from "./useEditorHistory";

function HistoryHarness({
  store,
  enabled = true,
  onError,
}: {
  store: ReturnType<typeof createEditorHistoryStore>;
  enabled?: boolean;
  onError?: (error: unknown) => void;
}) {
  const history = useEditorHistory({ store, enabled, onError });
  return (
    <output data-testid="history-state">
      {history.undoDepth}:{history.redoDepth}:{String(history.busy)}
    </output>
  );
}

async function dispatchShortcut(
  target: EventTarget,
  init: KeyboardEventInit,
): Promise<KeyboardEvent> {
  const event = new KeyboardEvent("keydown", {
    bubbles: true,
    cancelable: true,
    ...init,
  });
  await act(async () => {
    target.dispatchEvent(event);
    await Promise.resolve();
  });
  return event;
}

describe("useEditorHistory keyboard shortcuts", () => {
  it("uses Ctrl+Z for undo and prevents the browser action", async () => {
    const store = createEditorHistoryStore();
    const undo = vi.fn();
    store.record({ action: "move-node", undo, redo: vi.fn() });
    render(<HistoryHarness store={store} />);

    const event = await dispatchShortcut(document, { key: "z", ctrlKey: true });
    await waitFor(() => expect(undo).toHaveBeenCalledOnce());
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByTestId("history-state")).toHaveTextContent("0:1:false");
  });

  it("uses Ctrl+Y for redo", async () => {
    const store = createEditorHistoryStore();
    const redo = vi.fn();
    store.record({ action: "move-node", undo: vi.fn(), redo });
    await store.undo();
    render(<HistoryHarness store={store} />);

    const event = await dispatchShortcut(document, { key: "y", ctrlKey: true });
    await waitFor(() => expect(redo).toHaveBeenCalledOnce());
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByTestId("history-state")).toHaveTextContent("1:0:false");
  });

  it("uses Ctrl+Shift+Z for redo", async () => {
    const store = createEditorHistoryStore();
    const redo = vi.fn();
    store.record({ action: "waypoint", undo: vi.fn(), redo });
    await store.undo();
    render(<HistoryHarness store={store} />);

    await dispatchShortcut(document, {
      key: "Z",
      ctrlKey: true,
      shiftKey: true,
    });
    await waitFor(() => expect(redo).toHaveBeenCalledOnce());
  });

  it("does not consume a shortcut when the requested stack is empty", async () => {
    const store = createEditorHistoryStore();
    render(<HistoryHarness store={store} />);

    const event = await dispatchShortcut(document, { key: "z", ctrlKey: true });
    expect(event.defaultPrevented).toBe(false);
    expect(store.getSnapshot().undoDepth).toBe(0);
  });

  it("does not attach keyboard handling when disabled", async () => {
    const store = createEditorHistoryStore();
    const undo = vi.fn();
    store.record({ action: "move", undo, redo: vi.fn() });
    render(<HistoryHarness store={store} enabled={false} />);

    const event = await dispatchShortcut(document, { key: "z", ctrlKey: true });
    expect(event.defaultPrevented).toBe(false);
    expect(undo).not.toHaveBeenCalled();
  });

  it("removes the listener when the hook unmounts", async () => {
    const store = createEditorHistoryStore();
    const undo = vi.fn();
    store.record({ action: "move", undo, redo: vi.fn() });
    const view = render(<HistoryHarness store={store} />);
    view.unmount();

    await dispatchShortcut(document, { key: "z", ctrlKey: true });
    expect(undo).not.toHaveBeenCalled();
  });

  it("reports an asynchronous undo failure without consuming its entry", async () => {
    const store = createEditorHistoryStore();
    const onError = vi.fn();
    const error = new Error("rollback rejected");
    store.record({
      action: "reanchor",
      undo: () => Promise.reject(error),
      redo: vi.fn(),
    });
    render(<HistoryHarness store={store} onError={onError} />);

    await dispatchShortcut(document, { key: "z", ctrlKey: true });
    await waitFor(() => expect(onError).toHaveBeenCalledWith(error));
    expect(store.getSnapshot()).toMatchObject({ undoDepth: 1, redoDepth: 0 });
  });

  it("preserves native undo in input, color, textarea and select controls", async () => {
    const store = createEditorHistoryStore();
    const undo = vi.fn();
    store.record({ action: "move", undo, redo: vi.fn() });
    render(
      <>
        <HistoryHarness store={store} />
        <input aria-label="Text" />
        <input aria-label="Color" type="color" />
        <textarea aria-label="Notes" />
        <select aria-label="Interface" defaultValue="eth1">
          <option value="eth1">eth1</option>
        </select>
      </>,
    );

    for (const label of ["Text", "Color", "Notes", "Interface"]) {
      const control = screen.getByLabelText(label);
      control.focus();
      const event = await dispatchShortcut(control, { key: "z", ctrlKey: true });
      expect(event.defaultPrevented).toBe(false);
    }
    expect(undo).not.toHaveBeenCalled();
    expect(store.getSnapshot().undoDepth).toBe(1);
  });

  it("preserves native undo in nested contenteditable and role textbox fields", async () => {
    const store = createEditorHistoryStore();
    const undo = vi.fn();
    store.record({ action: "rename", undo, redo: vi.fn() });
    render(
      <>
        <HistoryHarness store={store} />
        <div contentEditable suppressContentEditableWarning tabIndex={0}>
          <span data-testid="editable-child">Rack name</span>
        </div>
        <div role="textbox" tabIndex={0} data-testid="role-textbox" />
      </>,
    );

    const child = screen.getByTestId("editable-child");
    child.parentElement?.focus();
    await dispatchShortcut(child, { key: "z", ctrlKey: true });
    const textbox = screen.getByTestId("role-textbox");
    textbox.focus();
    await dispatchShortcut(textbox, { key: "z", ctrlKey: true });

    expect(undo).not.toHaveBeenCalled();
  });

  it("does not mistake contenteditable=false for an editable field", () => {
    const element = document.createElement("div");
    element.setAttribute("contenteditable", "false");
    expect(isHistoryShortcutBlocked(element, null)).toBe(false);
  });

  it("ignores Meta, Alt and unrelated shortcuts", () => {
    expect(
      getEditorHistoryShortcut({
        key: "z",
        ctrlKey: false,
        metaKey: true,
        altKey: false,
        shiftKey: false,
      }),
    ).toBeNull();
    expect(
      getEditorHistoryShortcut({
        key: "z",
        ctrlKey: true,
        metaKey: false,
        altKey: true,
        shiftKey: false,
      }),
    ).toBeNull();
    expect(
      getEditorHistoryShortcut({
        key: "x",
        ctrlKey: true,
        metaKey: false,
        altKey: false,
        shiftKey: false,
      }),
    ).toBeNull();
  });

  it("updates the hook when history is recorded outside React", async () => {
    const store = createEditorHistoryStore();
    render(<HistoryHarness store={store} />);
    act(() => {
      store.record({ action: "create-rack", undo: vi.fn(), redo: vi.fn() });
    });

    await waitFor(() =>
      expect(screen.getByTestId("history-state")).toHaveTextContent("1:0:false"),
    );
  });
});
