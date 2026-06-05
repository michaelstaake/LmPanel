import { ReactNode, createContext, useContext } from "react";

export type MobileNavSection = {
  title?: string;
  content: ReactNode;
} | null;

type MobileNavContextValue = {
  closeMobileNav: () => void;
  setMobileNavSection: (section: MobileNavSection) => void;
};

const MobileNavContext = createContext<MobileNavContextValue | null>(null);

export function MobileNavProvider({ children, value }: { children: ReactNode; value: MobileNavContextValue }) {
  return <MobileNavContext.Provider value={value}>{children}</MobileNavContext.Provider>;
}

export function useMobileNav() {
  const context = useContext(MobileNavContext);
  if (!context) {
    throw new Error("useMobileNav must be used within MobileNavProvider");
  }
  return context;
}