import { PropsWithChildren, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

type ModalProps = PropsWithChildren<{
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  describedBy?: string;
  fullScreen?: boolean;
  overlayClassName?: string;
  layoutClassName?: string;
  panelClassName?: string;
}>;

function getFocusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden") && !element.getAttribute("aria-hidden"));
}

export default function Modal({
  open,
  onClose,
  labelledBy,
  describedBy,
  fullScreen = false,
  overlayClassName = "",
  layoutClassName = "",
  panelClassName = "",
  children,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const { body } = document;
    const previousOverflow = body.style.overflow;
    body.style.overflow = "hidden";

    const frameId = window.requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (!panel) {
        return;
      }

      const focusTargets = getFocusableElements(panel);
      const firstTarget = focusTargets[0] ?? panel;
      firstTarget.focus();
    });

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const panel = panelRef.current;
      if (!panel) {
        return;
      }

      const focusTargets = getFocusableElements(panel);
      if (focusTargets.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }

      const firstTarget = focusTargets[0];
      const lastTarget = focusTargets[focusTargets.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey && activeElement === firstTarget) {
        event.preventDefault();
        lastTarget.focus();
      } else if (!event.shiftKey && activeElement === lastTarget) {
        event.preventDefault();
        firstTarget.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      window.cancelAnimationFrame(frameId);
      document.removeEventListener("keydown", handleKeyDown);
      body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div
      className={`fixed inset-0 z-[100] overflow-y-auto bg-black/45 ${fullScreen ? "" : "p-4 backdrop-blur-sm sm:p-6"} ${overlayClassName}`.trim()}
      aria-hidden={false}
    >
      <div
        className={`flex min-h-full items-start justify-center ${fullScreen ? "" : "py-4 sm:items-center sm:py-8"} ${layoutClassName}`.trim()}
      >
        <div className="fixed inset-0" aria-hidden="true" onClick={onClose} />
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={labelledBy}
          aria-describedby={describedBy}
          tabIndex={-1}
          className={`relative z-[101] w-full overflow-y-auto outline-none overscroll-contain ${fullScreen ? "min-h-dvh max-h-none -none border-0 bg-[#fffdf7] shadow-none" : "max-h-[calc(100dvh-4rem)] -[28px] border border-black/10 bg-[#fffdf7] shadow-2xl sm:max-h-[min(calc(100dvh-7rem),860px)]"} ${panelClassName}`}
        >
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}