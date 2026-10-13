import { useEffect, useRef, useState } from "react";
import { subscribeToTopologyEvents } from "../services/api";
import type { TopologyEvent } from "../types";

export function useTopologyEvents(onEvent: (event: TopologyEvent) => void) {
  const callback = useRef(onEvent);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    callback.current = onEvent;
  }, [onEvent]);

  useEffect(
    () =>
      subscribeToTopologyEvents(
        (event) => callback.current(event),
        setConnected,
      ),
    [],
  );

  return connected;
}
