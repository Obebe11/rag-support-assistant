import { Button } from "~/components/ui/button";
import { StatusBanner } from "~/components/StatusBanner";

import { useHealth } from "../hooks/useHealth";

/**
 * "Server unavailable" and "database unavailable" notices. By default the
 * banner floats over the top spacer of the content area, so it neither pushes
 * the page down nor covers a message.
 */
export function HealthBanner(props: { placement?: "overlay" | "inline" }) {
  const { state, reload } = useHealth();
  const retry = (
    <Button variant="outline" size="xs" className="shrink-0" onClick={reload}>
      Try again
    </Button>
  );

  if (state.status === "error") {
    return (
      <StatusBanner
        variant="error"
        title="Cannot reach the server"
        message="The assistant is unavailable right now."
        action={retry}
        placement={props.placement}
      />
    );
  }
  if (state.status === "ready" && state.health.database !== "ok") {
    return (
      <StatusBanner
        variant="error"
        title="Database unavailable"
        message="The assistant cannot answer right now."
        action={retry}
        placement={props.placement}
      />
    );
  }
  return null;
}
