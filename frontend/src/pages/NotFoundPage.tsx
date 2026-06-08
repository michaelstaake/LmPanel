import { NavLink } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <section className="surface p-10 text-center">
      <p className="font-display text-6xl font-semibold tracking-tight text-sand/20 mb-4">404</p>
      <h2 className="text-xl font-semibold mb-2">Page not found</h2>
      <p className="text-sm text-sand/50 mb-6">The page you're looking for doesn't exist or has been moved.</p>
      <NavLink to="/" className="inline-block  bg-sand px-4 py-2 text-sm text-canvas hover:bg-sand/80">
        Go home
      </NavLink>
    </section>
  );
}
