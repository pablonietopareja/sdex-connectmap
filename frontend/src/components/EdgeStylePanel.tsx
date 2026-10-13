import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import type {
  EdgeRoute,
  EdgeVisualStyle,
  EdgeVisualStyleUpdate,
} from "../types";
import { Modal } from "./Modal";
import { Notice } from "./Notice";
import { Switch } from "./Switch";
import { hexToHsv, hsvToHex, normalizeHexColor } from "./edges/color";

type ColorTarget = "sheath" | "flow";
type PanelTab = ColorTarget | "route";

const DEFAULT_COLORS: Record<ColorTarget, string> = {
  sheath: "#5A7FAE",
  flow: "#4DA3FF",
};

const TARGET_COPY: Record<
  ColorTarget,
  { tab: string; heading: string; description: string }
> = {
  sheath: {
    tab: "Cable",
    heading: "Cable color",
    description: "Changes the cable's outer sheath.",
  },
  flow: {
    tab: "Data flow",
    heading: "Data flow color",
    description: "Changes the moving data segments inside the cable.",
  },
};

const TARGETS: ColorTarget[] = ["sheath", "flow"];
const TABS: PanelTab[] = ["sheath", "flow", "route"];

const PALETTE = [
  "#5A7FAE",
  "#4DA3FF",
  "#24518A",
  "#18885A",
  "#1A9A9A",
  "#7557C7",
  "#BD3E91",
  "#D66B2C",
  "#D4A017",
  "#C34B50",
  "#7A8591",
  "#FFFFFF",
  "#111820",
] as const;

interface EdgeStylePanelProps {
  edgeId: string | null;
  style: EdgeVisualStyle | null;
  route?: EdgeRoute | null;
  onClose: () => void;
  onApply: (
    edgeId: string,
    update: EdgeVisualStyleUpdate,
  ) => Promise<EdgeVisualStyle>;
  onReset: (edgeId: string) => Promise<void>;
  onResetRoute?: (edgeId: string) => Promise<void>;
  visualLink?: boolean;
  onDeleteVisualLink?: (edgeId: string) => Promise<void>;
}

function themeDefaultColors(): Record<ColorTarget, string> {
  if (typeof window === "undefined") return DEFAULT_COLORS;
  const computed = window.getComputedStyle(document.documentElement);
  return {
    sheath:
      normalizeHexColor(computed.getPropertyValue("--edge-blue")) ??
      DEFAULT_COLORS.sheath,
    flow:
      normalizeHexColor(computed.getPropertyValue("--edge-flow")) ??
      DEFAULT_COLORS.flow,
  };
}

function styleColors(
  style: EdgeVisualStyle | null,
  defaults: Record<ColorTarget, string>,
): Record<ColorTarget, string> {
  return {
    sheath: normalizeHexColor(style?.sheath_color ?? "") ?? defaults.sheath,
    flow: normalizeHexColor(style?.flow_color ?? "") ?? defaults.flow,
  };
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function EdgeStylePanel({
  edgeId,
  style,
  route = null,
  onClose,
  onApply,
  onReset,
  onResetRoute,
  visualLink = false,
  onDeleteVisualLink,
}: EdgeStylePanelProps) {
  const baseId = useId();
  const instructionsId = `${baseId}-picker-instructions`;
  const [activeTab, setActiveTab] = useState<PanelTab>("sheath");
  const activeTarget: ColorTarget = activeTab === "route" ? "sheath" : activeTab;
  const defaultColors = useMemo(themeDefaultColors, [edgeId]);
  const savedColors = useMemo(
    () => styleColors(style, defaultColors),
    [defaultColors, style],
  );
  const savedReverseFlow = style?.reverse_flow ?? false;
  const [draft, setDraft] =
    useState<Record<ColorTarget, string>>(savedColors);
  const [inputs, setInputs] =
    useState<Record<ColorTarget, string>>(savedColors);
  const [reverseFlow, setReverseFlow] = useState(savedReverseFlow);
  const [busy, setBusy] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [confirmLinkDelete, setConfirmLinkDelete] = useState(false);
  const pointerId = useRef<number | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    setDraft(savedColors);
    setInputs(savedColors);
    setReverseFlow(savedReverseFlow);
  }, [edgeId, savedColors, savedReverseFlow]);

  useEffect(() => {
    setActiveTab("sheath");
    setOperationError(null);
    setAnnouncement("");
    setConfirmLinkDelete(false);
  }, [edgeId]);

  const invalidTargets = TARGETS.filter(
    (target) => normalizeHexColor(inputs[target]) === null,
  );
  const changed = TARGETS.some(
    (target) => draft[target] !== savedColors[target],
  ) || reverseFlow !== savedReverseFlow;
  const hsv = hexToHsv(draft[activeTarget]);

  const setColor = (target: ColorTarget, value: string) => {
    const normalized = normalizeHexColor(value);
    if (!normalized) return;
    setDraft((current) => ({ ...current, [target]: normalized }));
    setInputs((current) => ({ ...current, [target]: normalized }));
    setOperationError(null);
    setAnnouncement("");
  };

  const setHsv = (next: {
    hue?: number;
    saturation?: number;
    value?: number;
  }) => {
    setColor(
      activeTarget,
      hsvToHex({
        hue: next.hue ?? hsv.hue,
        saturation: next.saturation ?? hsv.saturation,
        value: next.value ?? hsv.value,
      }),
    );
  };

  const updateFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const saturation =
      ((event.clientX - bounds.left) / bounds.width) * 100;
    const value = 100 - ((event.clientY - bounds.top) / bounds.height) * 100;
    setHsv({ saturation, value });
  };

  const handlePickerKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 10 : 2;
    let next: { saturation?: number; value?: number } | null = null;
    if (event.key === "ArrowLeft") {
      next = { saturation: hsv.saturation - step };
    } else if (event.key === "ArrowRight") {
      next = { saturation: hsv.saturation + step };
    } else if (event.key === "ArrowUp") {
      next = { value: hsv.value + step };
    } else if (event.key === "ArrowDown") {
      next = { value: hsv.value - step };
    } else if (event.key === "Home") {
      next = { saturation: 0 };
    } else if (event.key === "End") {
      next = { saturation: 100 };
    } else if (event.key === "PageUp") {
      next = { value: hsv.value + 10 };
    } else if (event.key === "PageDown") {
      next = { value: hsv.value - 10 };
    }
    if (!next) return;
    event.preventDefault();
    setHsv(next);
  };

  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % TABS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + TABS.length) % TABS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = TABS.length - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const target = TABS[nextIndex];
    if (!target) return;
    setActiveTab(target);
    tabRefs.current[nextIndex]?.focus();
  };

  const apply = async () => {
    if (!edgeId || invalidTargets.length > 0 || !changed) return;
    const sheathColor = normalizeHexColor(inputs.sheath);
    const flowColor = normalizeHexColor(inputs.flow);
    if (!sheathColor || !flowColor) return;

    setBusy(true);
    setOperationError(null);
    setAnnouncement("");
    try {
      await onApply(edgeId, {
        sheath_color: sheathColor,
        flow_color: flowColor,
        reverse_flow: reverseFlow,
      });
      setAnnouncement("Cable style saved.");
    } catch (error) {
      setOperationError(
        errorMessage(error, "The cable style could not be saved."),
      );
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!edgeId) return;
    if (!style) {
      setDraft(defaultColors);
      setInputs(defaultColors);
      setReverseFlow(false);
      setOperationError(null);
      setAnnouncement("Unsaved changes reset to the theme defaults.");
      return;
    }
    setBusy(true);
    setOperationError(null);
    setAnnouncement("");
    try {
      await onReset(edgeId);
      setAnnouncement("Cable style reset to the theme defaults.");
    } catch (error) {
      setOperationError(
        errorMessage(error, "The cable style could not be reset."),
      );
    } finally {
      setBusy(false);
    }
  };

  const resetRoute = async () => {
    if (!edgeId || !onResetRoute || !route) return;
    setBusy(true);
    setOperationError(null);
    setAnnouncement("");
    try {
      await onResetRoute(edgeId);
      setAnnouncement("Cable route reset to automatic routing.");
    } catch (error) {
      setOperationError(
        errorMessage(error, "The cable route could not be reset."),
      );
    } finally {
      setBusy(false);
    }
  };

  const deleteVisualLink = async () => {
    if (!edgeId || !visualLink || !onDeleteVisualLink) return;
    setBusy(true);
    setOperationError(null);
    setAnnouncement("");
    try {
      await onDeleteVisualLink(edgeId);
      setConfirmLinkDelete(false);
    } catch (error) {
      setOperationError(
        errorMessage(error, "The visual link could not be removed."),
      );
    } finally {
      setBusy(false);
    }
  };

  const copy = TARGET_COPY[activeTarget];
  const invalid = normalizeHexColor(inputs[activeTarget]) === null;
  const panelId = `${baseId}-${activeTarget}-panel`;
  const tabId = `${baseId}-${activeTarget}-tab`;
  const pickerStyle: CSSProperties = {
    backgroundColor: `hsl(${hsv.hue} 100% 50%)`,
    backgroundImage:
      "linear-gradient(to top, #000000, transparent), linear-gradient(to right, #FFFFFF, transparent)",
  };
  const markerStyle: CSSProperties = {
    left: `${hsv.saturation}%`,
    top: `${100 - hsv.value}%`,
    backgroundColor: draft[activeTarget],
  };

  return (
    <Modal
      open={edgeId !== null}
      title="Cable appearance"
      eyebrow={edgeId ?? undefined}
      size="small"
      onClose={onClose}
    >
      <form
        className="edge-style-panel"
        onSubmit={(event) => {
          event.preventDefault();
          void apply();
        }}
      >
        <div className="edge-style-tabs" role="tablist" aria-label="Cable color">
          {TABS.map((target, index) => (
            <button
              key={target}
              ref={(element) => {
                tabRefs.current[index] = element;
              }}
              id={`${baseId}-${target}-tab`}
              className="edge-style-tab"
              type="button"
              role="tab"
              aria-selected={activeTab === target}
              aria-controls={`${baseId}-${target}-panel`}
              tabIndex={activeTab === target ? 0 : -1}
              onClick={() => setActiveTab(target)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
            >
              {target === "route" ? "Route" : TARGET_COPY[target].tab}
            </button>
          ))}
        </div>

        {activeTab !== "route" ? <section
          id={panelId}
          className="edge-style-tab-panel"
          role="tabpanel"
          aria-labelledby={tabId}
          tabIndex={0}
        >
          <header className="edge-style-panel-heading">
            <div>
              <h3>{copy.heading}</h3>
              <p>{copy.description}</p>
            </div>
            {activeTarget === "flow" && (
              <div className="edge-flow-direction-control">
                <Switch
                  checked={reverseFlow}
                  onChange={(checked) => {
                    setReverseFlow(checked);
                    setOperationError(null);
                    setAnnouncement("");
                  }}
                  label="Reverse Flow"
                />
              </div>
            )}
          </header>

          <fieldset className="edge-color-palette">
            <legend>Standard colors</legend>
            <div>
              {PALETTE.map((color) => (
                <button
                  key={color}
                  className="edge-color-swatch"
                  type="button"
                  aria-label={`Set ${copy.heading.toLowerCase()} to ${color}`}
                  aria-pressed={draft[activeTarget] === color}
                  title={color}
                  style={{ backgroundColor: color }}
                  onClick={() => setColor(activeTarget, color)}
                />
              ))}
            </div>
          </fieldset>

          <div className="edge-color-picker">
            <p id={instructionsId} className="sr-only">
              Use left and right arrows to change saturation. Use up and down
              arrows to change brightness. Hold Shift for larger steps.
            </p>
            <div
              className="edge-color-saturation-value"
              role="slider"
              tabIndex={0}
              aria-label={`${copy.heading} saturation and brightness`}
              aria-describedby={instructionsId}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={hsv.value}
              aria-valuetext={`Saturation ${hsv.saturation}%, brightness ${hsv.value}%`}
              style={pickerStyle}
              onKeyDown={handlePickerKeyDown}
              onPointerDown={(event) => {
                event.preventDefault();
                pointerId.current = event.pointerId;
                event.currentTarget.setPointerCapture?.(event.pointerId);
                updateFromPointer(event);
              }}
              onPointerMove={(event) => {
                if (pointerId.current === event.pointerId) {
                  updateFromPointer(event);
                }
              }}
              onPointerUp={(event) => {
                if (pointerId.current !== event.pointerId) return;
                pointerId.current = null;
                event.currentTarget.releasePointerCapture?.(event.pointerId);
              }}
              onPointerCancel={() => {
                pointerId.current = null;
              }}
            >
              <span
                className="edge-color-picker-marker"
                style={markerStyle}
                aria-hidden="true"
              />
            </div>

            <label className="edge-hue-control">
              <span>Hue</span>
              <input
                type="range"
                min={0}
                max={359}
                step={1}
                value={hsv.hue}
                aria-label={`${copy.heading} hue`}
                onChange={(event) =>
                  setHsv({ hue: Number(event.currentTarget.value) })
                }
              />
            </label>
          </div>

          <label className="edge-hex-control">
            <span>Hex color</span>
            <span>
              <span
                className="edge-color-preview"
                style={{ backgroundColor: draft[activeTarget] }}
                aria-hidden="true"
              />
              <input
                value={inputs[activeTarget]}
                inputMode="text"
                autoCapitalize="characters"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={invalid}
                aria-describedby={invalid ? `${baseId}-hex-error` : undefined}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  setInputs((current) => ({
                    ...current,
                    [activeTarget]: value,
                  }));
                  const normalized = normalizeHexColor(value);
                  if (normalized) {
                    setDraft((current) => ({
                      ...current,
                      [activeTarget]: normalized,
                    }));
                  }
                  setOperationError(null);
                  setAnnouncement("");
                }}
                onBlur={() => {
                  const normalized = normalizeHexColor(inputs[activeTarget]);
                  if (normalized) setColor(activeTarget, normalized);
                }}
              />
            </span>
          </label>
          {invalid && (
            <p id={`${baseId}-hex-error`} className="field-error" role="alert">
              Enter a six-digit hexadecimal color, for example #4DA3FF.
            </p>
          )}
        </section> : (
          <section
            id={`${baseId}-route-panel`}
            className="edge-style-tab-panel edge-route-panel"
            role="tabpanel"
            aria-labelledby={`${baseId}-route-tab`}
            tabIndex={0}
          >
            <header>
              <h3>Cable route</h3>
              <p>
                {"Select this cable in Editor mode, then Ctrl+click its trace to add a 90\u00b0 bend or click and drag a waypoint for a free bend."}
              </p>
            </header>
            <dl className="edge-route-summary">
              <div>
                <dt>Routing</dt>
                <dd>{route?.routing_mode ?? "auto"}</dd>
              </div>
              <div>
                <dt>Waypoints</dt>
                <dd>{route?.waypoints.length ?? 0}</dd>
              </div>
            </dl>
            <button
              className="button button-ghost"
              type="button"
              disabled={busy || !route || !onResetRoute}
              onClick={() => void resetRoute()}
            >
              Reset route
            </button>
            {visualLink && onDeleteVisualLink && (
              <>
                <button
                  className="button button-danger"
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmLinkDelete(true)}
                >
                  Remove visual link
                </button>
                {confirmLinkDelete && (
                  <Notice tone="danger" title="Remove this visual link?">
                    <p>
                      Only ConnectMap presentation metadata is removed. A real
                      device source returns to its direct SDEX path; a Rack or
                      Switch can then be connected to another uplink.
                    </p>
                    <div className="inline-confirm-actions">
                      <button
                        className="button button-ghost"
                        type="button"
                        disabled={busy}
                        onClick={() => setConfirmLinkDelete(false)}
                      >
                        Cancel
                      </button>
                      <button
                        className="button button-danger"
                        type="button"
                        disabled={busy}
                        onClick={() => void deleteVisualLink()}
                      >
                        Confirm remove link
                      </button>
                    </div>
                  </Notice>
                )}
              </>
            )}
          </section>
        )}

        {operationError && (
          <p className="field-error" role="alert">
            {operationError}
          </p>
        )}
        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        {activeTab !== "route" && <footer className="form-actions">
          <button
            className="button button-ghost"
            type="button"
            disabled={
              busy ||
              (!style && !changed && invalidTargets.length === 0)
            }
            onClick={() => void reset()}
          >
            Reset to default
          </button>
          <button
            className="button button-primary"
            type="submit"
            disabled={busy || invalidTargets.length > 0 || !changed}
          >
            {busy ? "Saving…" : "Apply"}
          </button>
        </footer>}
      </form>
    </Modal>
  );
}
