import { NavLink, Outlet } from "react-router";

import { ModeBanner } from "../components/ModeBanner";
import "./AppShell.css";

/** Page frame shared by every route: header, mode banner, content, footer. */
export function AppShell() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <div className="app-header__inner">
          <NavLink to="/" className="app-brand" aria-label="Northline Support home">
            <span className="app-brand__mark" aria-hidden="true">
              N
            </span>
            <span className="app-brand__name">Northline</span>
            <span className="app-brand__product">Support</span>
          </NavLink>
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/" end className="app-nav__link">
              Chat
            </NavLink>
            <NavLink to="/admin" className="app-nav__link">
              Admin
            </NavLink>
          </nav>
        </div>
      </header>
      <ModeBanner />
      <main id="main" className="app-main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="app-footer">
        <p className="app-footer__inner">
          Handoff AI demo. Northline Office Equipment is a fictional company.
        </p>
      </footer>
    </>
  );
}
