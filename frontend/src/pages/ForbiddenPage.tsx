import { NavLink } from "react-router-dom";

export default function ForbiddenPage() {
  return (
    <section className=" border border-black/10 bg-white/80 p-10 shadow-sm text-center">
      <p className="font-display text-6xl font-semibold tracking-tight text-black/20 mb-4">403</p>
      <h2 className="text-xl font-semibold mb-2">Access denied</h2>
      <p className="text-sm text-black/50 mb-6">You don't have permission to view this page.</p>
      <NavLink to="/" className="inline-block  bg-ink px-4 py-2 text-sm text-white hover:bg-ink/80">
        Go home
      </NavLink>
    </section>
  );
}
