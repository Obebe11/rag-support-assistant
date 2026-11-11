import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

import { App } from "../App";

/** Render the whole app at `path` against the mock API, with a user to drive it. */
export function renderApp(path = "/") {
  // `applyAccept: false` lets a test pick a file the input's `accept` would filter out, as a drag and drop can.
  const user = userEvent.setup({ applyAccept: false });
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { user, ...view };
}
