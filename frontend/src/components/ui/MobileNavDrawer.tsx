import { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import Modal from "./Modal";

export type MobileNavItem = {
  to: string;
  label: string;
  iconClassName: string;
  end?: boolean;
};

type MobileNavDrawerProps = {
  open: boolean;
  onClose: () => void;
  sitename: string;
  navItems: MobileNavItem[];
  extraSection?: {
    title?: string;
    content: ReactNode;
  } | null;
};

export default function MobileNavDrawer({
  open,
  onClose,
  sitename,
  navItems,
  extraSection,
}: MobileNavDrawerProps) {
  return (
    <div className="xl:hidden">
      <Modal
        open={open}
        onClose={onClose}
        labelledBy="mobile-nav-title"
        fullScreen
        overlayClassName="bg-[#fffdf7] p-0 backdrop-blur-none sm:p-0"
        layoutClassName="items-stretch justify-stretch py-0 sm:items-stretch sm:justify-stretch sm:py-0"
        panelClassName="flex min-h-full w-full max-w-none flex-col rounded-none border-0 bg-[#fffdf7] shadow-none"
      >
        <div className="flex items-center justify-between border-b border-black/10 px-5 py-4">
          <h2 id="mobile-nav-title" className="font-display text-2xl font-semibold tracking-tight text-ink">{sitename}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center rounded-2xl border border-black/10 bg-white text-black/65 transition hover:border-black/20 hover:bg-black/5 hover:text-black"
            aria-label="Close navigation menu"
          >
            <i className="bi bi-x-lg text-[18px] leading-none" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          <nav className="space-y-2" aria-label="Primary navigation">
            {navItems.map((item) => (
              <NavLink
                key={`${item.to}-${item.label}`}
                to={item.to}
                end={item.end}
                onClick={onClose}
                className={({ isActive }) => `flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition ${isActive ? "bg-ink text-white" : "bg-black/5 text-ink hover:bg-black/10"}`}
              >
                <i className={`${item.iconClassName} text-[16px] leading-none`} aria-hidden="true" />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          {extraSection ? (
            <section className="mt-6 border-t border-black/10 pt-5" aria-labelledby={extraSection.title ? "mobile-nav-extra-section" : undefined}>
              {extraSection.title ? (
                <h3 id="mobile-nav-extra-section" className="mb-3 text-xs font-semibold uppercase tracking-[0.24em] text-black/45">
                  {extraSection.title}
                </h3>
              ) : null}
              {extraSection.content}
            </section>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}