import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useToast } from "../../context/ToastContext";

const TOAST_STYLES = {
  success: {
    cardClassName: "border-emerald-500 bg-emerald-900 text-emerald-100",
  },
  error: {
    cardClassName: "border-rose-500 bg-rose-900 text-rose-100",
  },
  info: {
    cardClassName: "border-blue-500 bg-blue-900 text-blue-100",
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
    <div className="fixed inset-x-3 top-3 z-[120] flex flex-col gap-3 sm:left-auto sm:right-4 sm:w-full sm:max-w-md">
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
            className={`cursor-pointer border p-4 shadow-lg shadow-black/10 transition duration-200 animate-[toast-in_180ms_ease-out] ${hoveredToastId === toast.id ? "opacity-80" : "opacity-100"} ${style.cardClassName}`}
            onClick={() => dismissToast(toast.id)}
          >
            {toast.content ?? <p className="min-w-0 text-sm leading-6">{toast.message}</p>}
          </section>
        );
      })}
    </div>,
    document.body
  );
}