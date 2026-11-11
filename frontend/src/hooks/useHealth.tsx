import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, unwrap } from "../api/client";
import type { HealthResponse } from "../api/client";

export type HealthState =
  | { status: "loading" }
  | { status: "ready"; health: HealthResponse }
  | { status: "error" };

interface HealthContextValue {
  state: HealthState;
  reload: () => void;
}

const HealthContext = createContext<HealthContextValue | null>(null);

/** Loads `/api/health` once and shares it with the whole app. */
export function HealthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<HealthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    unwrap(api.GET("/api/health")).then(
      (health) => {
        if (active) setState({ status: "ready", health });
      },
      () => {
        if (active) setState({ status: "error" });
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((current) => current + 1);
  }, []);

  const value = useMemo(() => ({ state, reload }), [state, reload]);
  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth(): HealthContextValue {
  const value = useContext(HealthContext);
  if (value === null) {
    throw new Error("useHealth must be used inside <HealthProvider>.");
  }
  return value;
}
