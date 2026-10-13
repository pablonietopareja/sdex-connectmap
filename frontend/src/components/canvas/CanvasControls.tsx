import {
  FitIcon,
  FocusIcon,
  LayoutIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "../icons";

interface CanvasControlsProps {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onResetView: () => void;
  onResetLayout: () => void;
}

export function CanvasControls({
  onZoomIn,
  onZoomOut,
  onFit,
  onResetView,
  onResetLayout,
}: CanvasControlsProps) {
  return (
    <nav className="canvas-controls nodrag nopan" aria-label="Canvas controls">
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={onZoomIn}>
        <ZoomInIcon />
      </button>
      <button
        type="button"
        title="Zoom out"
        aria-label="Zoom out"
        onClick={onZoomOut}
      >
        <ZoomOutIcon />
      </button>
      <span className="control-separator" />
      <button
        type="button"
        title="Fit topology"
        aria-label="Fit topology"
        onClick={onFit}
      >
        <FitIcon />
      </button>
      <button
        type="button"
        title="Center SDEX"
        aria-label="Reset view and center SDEX"
        onClick={onResetView}
      >
        <FocusIcon />
      </button>
      <span className="control-separator" />
      <button
        type="button"
        title="Reset node layout"
        aria-label="Reset node layout"
        onClick={onResetLayout}
      >
        <LayoutIcon />
      </button>
    </nav>
  );
}
