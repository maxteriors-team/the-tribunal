import { apiGet, apiPost, apiPut } from "@/lib/api";
import type {
  PreBookingAudienceEnrollResponse,
  PreBookingAudienceParams,
  PreBookingAudiencePreview,
  PreBookingConfig,
  PreBookingConfigCreate,
  PreBookingConfigUpdate,
  PreBookingLaunchRequest,
  PreBookingReservation,
  PreBookingReserveRequest,
  PreBookingReserveResponse,
} from "@/types";

/**
 * Pre-booking rides on top of an existing campaign rather than beside it: the
 * campaign is created through `smsCampaignsApi.create` first, then the offer is
 * attached here. That two-call shape is why this module has no
 * `createApiClient` base — there is no standalone pre-booking resource to CRUD.
 */
const offerPath = (workspaceId: string, campaignId: string) =>
  `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/pre-booking`;

export interface EnrollAudienceParams extends PreBookingAudienceParams {
  /** Cap on how many contacts to enrol; omit to take the whole audience. */
  limit?: number;
}

export interface ListReservationsParams {
  status_filter?: string;
  limit?: number;
}

export const preBookingApi = {
  getOffer: async (
    workspaceId: string,
    campaignId: string
  ): Promise<PreBookingConfig> => {
    return apiGet<PreBookingConfig>(offerPath(workspaceId, campaignId));
  },

  createOffer: async (
    workspaceId: string,
    campaignId: string,
    data: PreBookingConfigCreate
  ): Promise<PreBookingConfig> => {
    return apiPost<PreBookingConfig>(offerPath(workspaceId, campaignId), data);
  },

  updateOffer: async (
    workspaceId: string,
    campaignId: string,
    data: PreBookingConfigUpdate
  ): Promise<PreBookingConfig> => {
    return apiPut<PreBookingConfig>(offerPath(workspaceId, campaignId), data);
  },

  /**
   * Hand the campaign to the pre-booking worker with a future launch date. The
   * whole point is building September's campaign for January's season, so the
   * campaign goes to `scheduled` rather than sending on the spot.
   */
  scheduleLaunch: async (
    workspaceId: string,
    campaignId: string,
    data: PreBookingLaunchRequest
  ): Promise<PreBookingConfig> => {
    return apiPost<PreBookingConfig>(
      `${offerPath(workspaceId, campaignId)}/launch`,
      data
    );
  },

  /**
   * Size the warm database *before* a campaign row exists — the number that
   * decides whether building the campaign is worth the afternoon. Workspace
   * scoped, so the wizard can call it live while the operator toggles sources.
   *
   * Every slice flag rides straight through as a query param, including
   * `include_prior_season_christmas` / `seasons_back`. Axios omits `undefined`
   * and `null`, so an unset flag or an unbounded `seasons_back` simply takes the
   * server default (`false`, and "every season on record").
   */
  previewWorkspaceAudience: async (
    workspaceId: string,
    params: PreBookingAudienceParams = {}
  ): Promise<PreBookingAudiencePreview> => {
    return apiGet<PreBookingAudiencePreview>(
      `/api/v1/workspaces/${workspaceId}/pre-booking/audience`,
      { params }
    );
  },

  /** Same slice flags as the preview, plus a cap on how many to enrol. */
  enrollAudience: async (
    workspaceId: string,
    campaignId: string,
    params: EnrollAudienceParams = {}
  ): Promise<PreBookingAudienceEnrollResponse> => {
    return apiPost<PreBookingAudienceEnrollResponse>(
      `${offerPath(workspaceId, campaignId)}/audience/enroll`,
      undefined,
      { params }
    );
  },

  listReservations: async (
    workspaceId: string,
    campaignId: string,
    params: ListReservationsParams = {}
  ): Promise<PreBookingReservation[]> => {
    return apiGet<PreBookingReservation[]>(
      `${offerPath(workspaceId, campaignId)}/reservations`,
      { params }
    );
  },

  reserveSlot: async (
    workspaceId: string,
    campaignId: string,
    data: PreBookingReserveRequest
  ): Promise<PreBookingReserveResponse> => {
    return apiPost<PreBookingReserveResponse>(
      `${offerPath(workspaceId, campaignId)}/reservations`,
      data
    );
  },
};
