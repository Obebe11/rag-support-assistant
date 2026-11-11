import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <section className="page-placeholder" aria-labelledby="not-found-title">
      <h1 id="not-found-title" className="page-placeholder__title">
        Page not found
      </h1>
      <p className="page-placeholder__text">
        This address does not exist. <Link to="/">Go to the chat</Link>.
      </p>
    </section>
  );
}
