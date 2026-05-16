import type { ContactStatus, CampaignStatus, MessageTestStatus, OpportunityStatus } from "@/types";

export const contactStatusColors: Record<ContactStatus, string> = {
  new: "bg-blue-500/10 text-blue-500",
  contacted: "bg-yellow-500/10 text-yellow-500",
  qualified: "bg-green-500/10 text-green-500",
  converted: "bg-purple-500/10 text-purple-500",
  lost: "bg-red-500/10 text-red-500",
};

export const contactStatusDotColors: Record<ContactStatus, string> = {
  new: "bg-blue-500",
  contacted: "bg-yellow-500",
  qualified: "bg-green-500",
  converted: "bg-purple-500",
  lost: "bg-red-500",
};

export const contactStatusLabels: Record<ContactStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  converted: "Converted",
  lost: "Lost",
};

export const campaignStatusColors: Record<CampaignStatus, string> = {
  draft: "bg-gray-500/10 text-gray-500 border-gray-500/20",
  scheduled: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  running: "bg-green-500/10 text-green-500 border-green-500/20",
  paused: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
  completed: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  cancelled: "bg-red-500/10 text-red-500 border-red-500/20",
};

export const messageTestStatusColors: Record<MessageTestStatus, string> = {
  draft: "bg-gray-500/10 text-gray-500 border-gray-500/20",
  running: "bg-green-500/10 text-green-500 border-green-500/20",
  paused: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
  completed: "bg-purple-500/10 text-purple-500 border-purple-500/20",
};

export const appointmentStatusColors: Record<string, string> = {
  scheduled: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  completed: "bg-green-500/10 text-green-500 border-green-500/20",
  cancelled: "bg-red-500/10 text-red-500 border-red-500/20",
  no_show: "bg-gray-500/10 text-gray-500 border-gray-500/20",
};

export const opportunityStatusColors: Record<OpportunityStatus, string> = {
  open: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  won: "bg-green-500/10 text-green-600 border-green-500/20",
  lost: "bg-red-500/10 text-red-600 border-red-500/20",
  abandoned: "bg-gray-500/10 text-gray-600 border-gray-500/20",
};

export const callStatusColors: Record<string, string> = {
  completed: "bg-green-500/10 text-green-500 border-green-500/20",
  in_progress: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  initiated: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  ringing: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
  no_answer: "bg-gray-500/10 text-gray-500 border-gray-500/20",
  busy: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  failed: "bg-red-500/10 text-red-500 border-red-500/20",
};
