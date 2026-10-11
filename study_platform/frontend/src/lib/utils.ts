import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
export function milliseconds(value: number | null | undefined): string {
  if (value == null)
    return "—";
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ms`;
}
export function memory(value: number | null | undefined): string {
  return value == null ? "—" : `${(value / 1048576).toFixed(1)} MiB`;
}
export function artifactUrl(path: string): string {
  return `/api/artifacts/${path.split("/").map(encodeURIComponent).join("/")}`;
}
export function shortDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
