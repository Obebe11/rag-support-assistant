import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

import { App } from "../App";

/** Render the whole app at `path` against the mock API, with a user to drive it. */
export function renderApp(path = "/") {
  const user = userEvent.setup();
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { user, ...view };
}
