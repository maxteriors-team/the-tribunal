import type { WizardErrors } from "../wizard-types";

import type { BasicsFields, ScheduleFields } from "./form-types";

export function validateBasics(data: BasicsFields): WizardErrors {
  const errors: WizardErrors = {};
  if (!data.name.trim()) errors.name = "Campaign name is required";
  if (!data.from_phone_number)
    errors.from_phone_number = "Phone number is required";
  return errors;
}

export function validateSchedule(data: ScheduleFields): WizardErrors {
  return data.sending_days.length === 0
    ? { sending_days: "Select at least one day" }
    : {};
}

export function validateContacts(selectedCount: number): WizardErrors {
  return selectedCount === 0
    ? { contacts: "Select at least one contact" }
    : {};
}

export function validateAgent(data: {
  ai_enabled: boolean;
  agent_id?: string;
}): WizardErrors {
  if (data.ai_enabled && !data.agent_id) {
    return {
      agent_id:
        "Select an AI agent to handle responses, or turn off AI responses",
    };
  }
  return {};
}
