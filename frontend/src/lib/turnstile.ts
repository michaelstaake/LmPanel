import type { MutableRefObject } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (container: string | HTMLElement, config: Record<string, unknown>) => string;
      reset: (widgetId?: string) => void;
      getResponse: (widgetId?: string) => string;
      remove: (widgetId: string) => void;
    };
  }
}

export function turnstileRenderOptions(siteKey: string, tokenRef: MutableRefObject<string | null>) {
  return {
    sitekey: siteKey,
    theme: "light",
    size: "flexible",
    callback: (token: string) => {
      tokenRef.current = token;
    },
    "expired-callback": () => {
      tokenRef.current = null;
    },
    "error-callback": () => {
      tokenRef.current = null;
    },
  };
}

export function readTurnstileToken(widgetId: string | null, tokenRef: MutableRefObject<string | null>): string | undefined {
  if (!widgetId || !window.turnstile) {
    return undefined;
  }
  const token = tokenRef.current || window.turnstile.getResponse(widgetId);
  return token || undefined;
}

export function resetTurnstileWidget(widgetId: string | null, tokenRef: MutableRefObject<string | null>) {
  tokenRef.current = null;
  if (widgetId && window.turnstile) {
    window.turnstile.reset(widgetId);
  }
}
