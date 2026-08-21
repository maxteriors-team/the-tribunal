import api, { apiGet, apiPatch, apiPost } from "@/lib/api";
import type { components } from "@/lib/api/_generated";

export type AttendanceEntry = components["schemas"]["AttendanceEntryResponse"];
export type AttendanceReport = components["schemas"]["AttendanceReportResponse"];
export type AttendanceAdminReport = components["schemas"]["AttendanceAdminReportResponse"];
export type AttendanceAdminCreateRequest = components["schemas"]["AttendanceManualEntryRequest"];
export type AttendanceUpdateRequest = components["schemas"]["AttendanceEntryUpdateRequest"];
export type AttendanceVoidRequest = components["schemas"]["AttendanceVoidRequest"];
export type AttendanceExportRequest = components["schemas"]["AttendanceExportRequest"];
export type AttendancePauseRequest = components["schemas"]["AttendancePauseRequest"];
export type AttendanceStatus = AttendanceEntry["status"];
export type AttendanceSource = AttendanceEntry["source"];

export interface AttendanceRangeParams {
  date_from: string;
  date_to: string;
  user_id?: number;
}

export interface AttendanceClockRequest {
  request_id: string;
  note?: string;
}

function workspaceAttendanceUrl(workspaceId: string, suffix = ""): string {
  return `/api/v1/workspaces/${workspaceId}/attendance${suffix}`;
}

function safeDownloadFilename(header: string | undefined, fallback: string): string {
  const match = header?.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1]?.trim();
  return filename && /^[a-zA-Z0-9._-]+$/.test(filename) ? filename : fallback;
}

export const attendanceApi = {
  mine: (workspaceId: string, params: AttendanceRangeParams): Promise<AttendanceReport> =>
    apiGet(workspaceAttendanceUrl(workspaceId, "/me"), { params }),

  clockIn: (workspaceId: string, body: AttendanceClockRequest): Promise<AttendanceEntry> =>
    apiPost(workspaceAttendanceUrl(workspaceId, "/clock-in"), body),

  clockOut: (workspaceId: string, body: AttendanceClockRequest): Promise<AttendanceEntry> =>
    apiPost(workspaceAttendanceUrl(workspaceId, "/clock-out"), body),

  pause: (workspaceId: string, body: AttendancePauseRequest): Promise<AttendanceEntry> =>
    apiPost(workspaceAttendanceUrl(workspaceId, "/pause"), body),

  resume: (workspaceId: string, body: AttendancePauseRequest): Promise<AttendanceEntry> =>
    apiPost(workspaceAttendanceUrl(workspaceId, "/resume"), body),

  team: (workspaceId: string, params: AttendanceRangeParams): Promise<AttendanceAdminReport> =>
    apiGet(workspaceAttendanceUrl(workspaceId, "/entries"), { params }),

  createEntry: (
    workspaceId: string,
    body: AttendanceAdminCreateRequest,
  ): Promise<AttendanceEntry> => apiPost(workspaceAttendanceUrl(workspaceId, "/entries"), body),

  updateEntry: (
    workspaceId: string,
    entryId: string,
    body: AttendanceUpdateRequest,
  ): Promise<AttendanceEntry> =>
    apiPatch(workspaceAttendanceUrl(workspaceId, `/entries/${entryId}`), body),

  voidEntry: (
    workspaceId: string,
    entryId: string,
    body: AttendanceVoidRequest,
  ): Promise<AttendanceEntry> =>
    apiPost(workspaceAttendanceUrl(workspaceId, `/entries/${entryId}/void`), body),

  exportCsv: async (
    workspaceId: string,
    body: AttendanceExportRequest,
  ): Promise<{ blob: Blob; filename: string }> => {
    const response = await api.post<Blob>(workspaceAttendanceUrl(workspaceId, "/exports"), body, {
      responseType: "blob",
    });
    return {
      blob: response.data,
      filename: safeDownloadFilename(
        response.headers["content-disposition"],
        `tribunal-hours-${body.date_from}-${body.date_to}.csv`,
      ),
    };
  },
};
