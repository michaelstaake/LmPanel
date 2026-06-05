import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

export type ToastKind = "success" | "error" | "info";

export type Toast = {
  id: string;
  kind: ToastKind;
  message: string;
  content?: ReactNode;
  duration: number;
};

type ShowToastOptions = {
  id?: string;
  duration?: number;
  content?: ReactNode;
};

type ToastContextValue = {
  toasts: Toast[];
  showToast: (kind: ToastKind, message: string, options?: ShowToastOptions) => string;
  showSuccess: (message: string, options?: ShowToastOptions) => string;
  showError: (message: string, options?: ShowToastOptions) => string;
  showInfo: (message: string, options?: ShowToastOptions) => string;
  dismissToast: (id: string) => void;
};

const TOAST_DURATION_MS: Record<ToastKind, number> = {
  success: 7000,
  error: 14000,
  info: 0,
};

const MAX_VISIBLE_TOASTS = 4;

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timersRef = useRef(new Map<string, number>());

  const dismissToast = useCallback((id: string) => {
    const timerId = timersRef.current.get(id);
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      timersRef.current.delete(id);
    }

    setToasts((currentToasts) => currentToasts.filter((toast) => toast.id !== id));
  }, []);

  const scheduleDismiss = useCallback((id: string, duration: number) => {
    const existingTimerId = timersRef.current.get(id);
    if (existingTimerId !== undefined) {
      window.clearTimeout(existingTimerId);
    }

    if (duration === 0) return;

    const timerId = window.setTimeout(() => {
      timersRef.current.delete(id);
      setToasts((currentToasts) => currentToasts.filter((toast) => toast.id !== id));
    }, duration);

    timersRef.current.set(id, timerId);
  }, []);

  const showToast = useCallback((kind: ToastKind, message: string, options?: ShowToastOptions) => {
    const id = options?.id ?? crypto.randomUUID();
    const duration = options?.duration ?? TOAST_DURATION_MS[kind];

    setToasts((currentToasts) => {
      const nextToast: Toast = { id, kind, message, content: options?.content, duration };
      const filteredToasts = currentToasts.filter((toast) => toast.id !== id);
      return [...filteredToasts, nextToast].slice(-MAX_VISIBLE_TOASTS);
    });

    scheduleDismiss(id, duration);
    return id;
  }, [scheduleDismiss]);

  const showSuccess = useCallback((message: string, options?: ShowToastOptions) => showToast("success", message, options), [showToast]);
  const showError = useCallback((message: string, options?: ShowToastOptions) => showToast("error", message, options), [showToast]);
  const showInfo = useCallback((message: string, options?: ShowToastOptions) => showToast("info", message, options), [showToast]);

  useEffect(() => () => {
    for (const timerId of timersRef.current.values()) {
      window.clearTimeout(timerId);
    }
    timersRef.current.clear();
  }, []);

  const value = useMemo<ToastContextValue>(() => ({
    toasts,
    showToast,
    showSuccess,
    showError,
    showInfo,
    dismissToast,
  }), [dismissToast, showError, showInfo, showSuccess, showToast, toasts]);

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}