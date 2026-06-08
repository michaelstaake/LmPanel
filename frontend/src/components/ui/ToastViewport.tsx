import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useToast } from "../../context/ToastContext";

const TOAST_STYLES = {
  success: {
    cardClassName: "border-emerald-500/40 bg-emerald-500/15 text-emerald-200",
  },
  error: {
    cardClassName: "border-rose-500/40 bg-rose-500/15 text-rose-200",
  },
  info: {
    cardClassName: "border-blue-500/40 bg-blue-500/15 text-blue-200",
  },
} as const;

export default function ToastViewport() {
  const { dismissToast, toasts } = useToast();
  const [isMounted, setIsMounted] = useState(false);
  const [hoveredToastId, setHoveredToastId] = useState<string | null>(null);
  const toastRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    toastRefs.current = Object.fromEntries(
      toasts.map((toast) => [toast.id, toastRefs.current[toast.id] ?? null])
    );
  }, [toasts]);

  useEffect(() => {
    if (!isMounted || toasts.length === 0) {
      setHoveredToastId(null);
      return;
    }

    const handlePointerMove = (event: PointerEvent) => {
      const nextHoveredToastId = toasts.find((toast) => {
        const element = toastRefs.current[toast.id];

        if (!element) {
          return false;
        }

        const rect = element.getBoundingClientRect();

        return (
          event.clientX >= rect.left &&
          event.clientX <= rect.right &&
          event.clientY >= rect.top &&
          event.clientY <= rect.bottom
        );
      })?.id ?? null;

      setHoveredToastId((currentHoveredToastId) =>
        currentHoveredToastId === nextHoveredToastId ? currentHoveredToastId : nextHoveredToastId
      );
    };

    const handlePointerLeave = () => {
      setHoveredToastId(null);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointercancel", handlePointerLeave);
    window.addEventListener("blur", handlePointerLeave);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointercancel", handlePointerLeave);
      window.removeEventListener("blur", handlePointerLeave);
    };
  }, [isMounted, toasts]);

  if (!isMounted || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div className="pointer-events-none fixed inset-x-3 top-3 z-[120] flex flex-col gap-3 sm:left-auto sm:right-4 sm:w-full sm:max-w-md">
      {toasts.map((toast) => {
        const style = TOAST_STYLES[toast.kind];

        return (
          <section
            key={toast.id}
            ref={(element) => {
              toastRefs.current[toast.id] = element;
            }}
            role={toast.kind === "error" ? "alert" : "status"}
            aria-live={toast.kind === "error" ? "assertive" : "polite"}
            className={`pointer-events-none  border p-4 shadow-lg shadow-black/10 backdrop-blur transition duration-200 animate-[toast-in_180ms_ease-out] ${hoveredToastId === toast.id ? "opacity-55" : "opacity-85"} ${style.cardClassName}`}
          >
            {toast.content ?? <p className="min-w-0 text-sm leading-6">{toast.message}</p>}
          </section>
        );
      })}
    </div>,
    document.body
  );
}