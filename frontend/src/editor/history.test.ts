import { describe, expect, it, vi } from "vitest";
import {
  createEditorHistoryStore,
  createSnapshotHistoryCommand,
  DEFAULT_EDITOR_HISTORY_LIMIT,
  type EditorHistoryCommand,
} from "./history";

function command(
  action: string,
  undo: () => void | Promise<void> = vi.fn(),
  redo: () => void | Promise<void> = vi.fn(),
): EditorHistoryCommand {
  return { action, affectedIds: [action], undo, redo };
}

function deferred(): {
  promise: Promise<void>;
  resolve: () => void;
  reject: (error: unknown) => void;
} {
  let resolvePromise: (() => void) | undefined;
  let rejectPromise: ((error: unknown) => void) | undefined;
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return {
    promise,
    resolve: () => resolvePromise?.(),
    reject: (error) => rejectPromise?.(error),
  };
}

describe("EditorHistoryStore", () => {
  it("records exactly one entry per visual operation", () => {
    const store = createEditorHistoryStore();

    expect(
      store.record(
        command("move-node", vi.fn(), vi.fn()),
      ),
    ).toBe(true);
    expect(store.getSnapshot()).toMatchObject({
      canUndo: true,
      undoDepth: 1,
      redoDepth: 0,
      lastAction: "move-node",
    });
  });

  it("caps the browser-session history at 100 entries by default", async () => {
    const store = createEditorHistoryStore();
    expect(store.maxEntries).toBe(DEFAULT_EDITOR_HISTORY_LIMIT);
    const undone: number[] = [];
    for (let index = 0; index < 105; index += 1) {
      store.record(
        command(`move-${index}`, () => {
          undone.push(index);
        }),
      );
    }

    expect(store.getSnapshot().undoDepth).toBe(100);
    for (let index = 0; index < 100; index += 1) await store.undo();
    expect(undone).toHaveLength(100);
    expect(undone.at(-1)).toBe(5);
    expect(await store.undo()).toBe(false);
  });

  it("supports a smaller configured limit and validates it", async () => {
    expect(() => createEditorHistoryStore(0)).toThrow(/positive integer/i);
    expect(() => createEditorHistoryStore(1.5)).toThrow(/positive integer/i);
    const store = createEditorHistoryStore(2);
    const undoFirst = vi.fn();
    store.record(command("first", undoFirst));
    store.record(command("second"));
    store.record(command("third"));

    await store.undo();
    await store.undo();
    expect(undoFirst).not.toHaveBeenCalled();
  });

  it("restores partial immutable snapshots with asynchronous apply", async () => {
    type Position = Readonly<{ id: string; x: number; y: number }>;
    const before: Position = { id: "plc-a", x: 10, y: 20 };
    const after: Position = { id: "plc-a", x: 90, y: 110 };
    let current = after;
    const apply = vi.fn((next: Position) => {
      current = next;
      return Promise.resolve();
    });
    const store = createEditorHistoryStore();
    store.record(
      createSnapshotHistoryCommand({
        action: "move-node",
        affectedIds: ["plc-a"],
        before,
        after,
        apply,
      }),
    );

    expect(await store.undo()).toBe(true);
    expect(current).toBe(before);
    expect(await store.redo()).toBe(true);
    expect(current).toBe(after);
    expect(apply).toHaveBeenCalledTimes(2);
  });

  it("executes a new async command before recording it", async () => {
    const events: string[] = [];
    const store = createEditorHistoryStore();

    expect(
      await store.execute({
        action: "create-switch",
        affectedIds: ["switch-a"],
        execute: () => {
          events.push("execute");
          return Promise.resolve();
        },
        undo: () => {
          events.push("undo");
        },
        redo: () => {
          events.push("redo");
        },
      }),
    ).toBe(true);
    expect(events).toEqual(["execute"]);
    expect(store.getSnapshot().undoDepth).toBe(1);
    await store.undo();
    await store.redo();
    expect(events).toEqual(["execute", "undo", "redo"]);
  });

  it("does not record a command whose initial async effect fails", async () => {
    const store = createEditorHistoryStore();
    await expect(
      store.execute({
        action: "create-rack",
        execute: () => Promise.reject(new Error("API failed")),
        undo: vi.fn(),
        redo: vi.fn(),
      }),
    ).rejects.toThrow("API failed");

    expect(store.getSnapshot()).toMatchObject({
      busy: false,
      undoDepth: 0,
      redoDepth: 0,
    });
  });

  it("keeps the undo entry available when undo fails", async () => {
    const store = createEditorHistoryStore();
    store.record(
      command("delete-waypoint", () => Promise.reject(new Error("rollback failed"))),
    );

    await expect(store.undo()).rejects.toThrow("rollback failed");
    expect(store.getSnapshot()).toMatchObject({
      busy: false,
      canUndo: true,
      undoDepth: 1,
      redoDepth: 0,
    });
  });

  it("keeps the redo entry available when redo fails", async () => {
    const store = createEditorHistoryStore();
    store.record(
      command("cable-color", vi.fn(), () => Promise.reject(new Error("redo failed"))),
    );
    await store.undo();

    await expect(store.redo()).rejects.toThrow("redo failed");
    expect(store.getSnapshot()).toMatchObject({
      busy: false,
      undoDepth: 0,
      canRedo: true,
      redoDepth: 1,
    });
  });

  it("clears redo after a new visual action", async () => {
    const store = createEditorHistoryStore();
    store.record(command("move-a"));
    await store.undo();
    expect(store.getSnapshot().canRedo).toBe(true);

    store.record(command("move-b"));
    expect(store.getSnapshot()).toMatchObject({
      undoDepth: 1,
      redoDepth: 0,
      canRedo: false,
      lastAction: "move-b",
    });
  });

  it("serializes operations by rejecting another command while busy", async () => {
    const pendingEffect = deferred();
    const store = createEditorHistoryStore();
    const pending = store.execute({
      action: "resize-rack",
      execute: () => pendingEffect.promise,
      undo: vi.fn(),
      redo: vi.fn(),
    });

    expect(store.getSnapshot()).toMatchObject({ busy: true, canUndo: false });
    expect(store.record(command("move-switch"))).toBe(false);
    expect(await store.undo()).toBe(false);
    pendingEffect.resolve();
    await expect(pending).resolves.toBe(true);
    expect(store.getSnapshot()).toMatchObject({ busy: false, undoDepth: 1 });
  });

  it("cannot resurrect an async command after a safe clear", async () => {
    const pendingEffect = deferred();
    const store = createEditorHistoryStore();
    const pending = store.execute({
      action: "create-visual-link",
      execute: () => pendingEffect.promise,
      undo: vi.fn(),
      redo: vi.fn(),
    });

    store.clear("topology-reloaded");
    expect(store.getSnapshot()).toMatchObject({
      busy: true,
      undoDepth: 0,
      redoDepth: 0,
      invalidationReason: "topology-reloaded",
    });
    pendingEffect.resolve();

    await expect(pending).resolves.toBe(false);
    expect(store.getSnapshot()).toMatchObject({
      busy: false,
      undoDepth: 0,
      redoDepth: 0,
      invalidationReason: "topology-reloaded",
    });
  });

  it("invalidates pending undo without moving it to redo", async () => {
    const pendingUndo = deferred();
    const store = createEditorHistoryStore();
    store.record(command("reanchor", () => pendingUndo.promise));
    const undoing = store.undo();

    store.invalidate("API conflict");
    pendingUndo.resolve();
    await expect(undoing).resolves.toBe(false);
    expect(store.getSnapshot()).toMatchObject({
      undoDepth: 0,
      redoDepth: 0,
      invalidationReason: "API conflict",
    });
  });

  it("notifies subscribers and allows clean unsubscription", () => {
    const store = createEditorHistoryStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.record(command("rename-rack"));
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    store.clear();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("rejects blank action labels", () => {
    const store = createEditorHistoryStore();
    expect(() => store.record(command("   "))).toThrow(/non-empty action/i);
  });
});
