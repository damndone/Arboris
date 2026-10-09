import { apiUrl, readResponse } from "../api";
import type { RequestOf, Schema } from "../apiTypes";
export type Operation = Schema<"OperationCatalogEntry">;
export type Target = NonNullable<Schema<"ManualOperationRequest">["target"]>;
export type Outcome = Schema<"ManualOperationResponse">;
export type Draft = Schema<"ManualReportDraft">;
export type Report = Schema<"ManualReportRecord">;
export function manualUrl(root: string, path: string, query: Record<string, string> = {}) {
    return apiUrl(`${path}?${new URLSearchParams({ project_root: root, ...query })}`);
}
async function request<T>(root: string, path: string, body?: unknown, query?: Record<string, string>): Promise<T> {
    return readResponse<T>(await fetch(manualUrl(root, path, query), body === undefined ? undefined : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }));
}
export const catalog = (root: string, target?: Target) => request<Schema<"OperationCatalog">>(root, "/operations", undefined, target ? { target: JSON.stringify(target) } : undefined);
export const execute = (root: string, body: RequestOf<"/operations/run", "post">) => request<Outcome>(root, "/operations/run", body);
const reportPath = (run: string) => `/runs/${encodeURIComponent(run)}/manual-reports`;
export const reportDraft = (root: string, run: string) => request<Draft>(root, `${reportPath(run)}/draft`);
export const reportHistory = (root: string, run: string) => request<Schema<"ManualReportHistory">>(root, reportPath(run));
export const saveReport = (root: string, run: string, body: Schema<"ManualReportRequest">) => request<Schema<"ManualReportSaved">>(root, reportPath(run), body);
export const reportExportUrl = (root: string, run: string, id: string, format: string) => manualUrl(root, `${reportPath(run)}/${encodeURIComponent(id)}/export`, { format });
