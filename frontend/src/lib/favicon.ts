import { apiGet } from "./api";
import type { StatusResponse } from "./records";

const COLORS = {
  ready: { color: "#2f8f4e", border: 4 },
  warning: { color: "#c98a13", border: 6 },
  error: { color: "#c63f3f", border: 6 },
} as const;

function encodeSvgString(str: string): string {
  return str
    .replace(/</g, "%3C")
    .replace(/>/g, "%3E")
    .replace(/&/g, "%26")
    .replace(/"/g, "%22")
    .replace(/'/g, "%27");
}

type StatusKey = keyof typeof COLORS;

export function createFaviconSvg(status: StatusKey): string {
  const { color, border } = COLORS[status];
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%23cccccc'/><rect y='28' width='32' height='${border}' fill='${color.replace("#", "%23")}'/><text x='16' y='23' text-anchor='middle' font-family='Arial,sans-serif' font-weight='bold' font-size='18' fill='%23111111'>Lm</text></svg>`;
  return `data:image/svg+xml,${encodeSvgString(svg)}`;
}

export async function getSystemStatus(): Promise<StatusKey> {
  try {
    const data = await apiGet<StatusResponse>("/api/status");
    const devices = data.devices || [];
    const activeModels = devices.reduce((sum, d) => sum + (d.models?.length || 0), 0);

    if (activeModels === 0) {
      return "error";
    }

    const maxMemoryUsage = devices.reduce((max, d) => {
      const usage = d.memory_total_mb > 0 ? (d.memory_used_mb / d.memory_total_mb) * 100 : 0;
      return Math.max(max, usage);
    }, 0);

    if (maxMemoryUsage > 90) {
      return "warning";
    }

    return "ready";
  } catch {
    return "error";
  }
}
