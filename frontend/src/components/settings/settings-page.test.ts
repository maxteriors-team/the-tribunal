import { describe, expect, it } from "vitest";

import { can } from "@/lib/permissions";

import { canSeeSettingsTab, settingsTabs } from "./settings-page";

const SELF_TABS = ["profile", "notifications", "calendar"];
const MANAGER_TABS = [
  "profile",
  "tags",
  "notifications",
  "proposals",
  "pricing",
  "attach-rules",
  "pipeline",
  "speed-to-lead",
  "estimate-followup",
  "quote-revival",
  "neighbors",
  "calendar",
  "billing",
  "locations",
  "lead-sources",
];
const SALES_TABS = [
  "profile",
  "notifications",
  "speed-to-lead",
  "estimate-followup",
  "quote-revival",
  "neighbors",
  "calendar",
];

const EXPECTED_TABS_BY_ROLE: Record<string, string[]> = {
  owner: settingsTabs.map((tab) => tab.value),
  admin: settingsTabs.map((tab) => tab.value),
  manager: MANAGER_TABS,
  dispatcher: MANAGER_TABS,
  sales_rep: SALES_TABS,
  member: SELF_TABS,
  lead_technician: SELF_TABS,
  technician: SELF_TABS,
};

describe("Settings tab capability matrix", () => {
  it.each(Object.entries(EXPECTED_TABS_BY_ROLE))(
    "%s mounts exactly its authorized tabs",
    (role, expectedTabs) => {
      const visibleTabs = settingsTabs
        .filter((tab) => canSeeSettingsTab(tab, (capability) => can(role, capability)))
        .map((tab) => tab.value);

      expect(visibleTabs).toEqual(expectedTabs);
    },
  );

  it("keeps personal tabs capability-free and workspace tabs explicit", () => {
    for (const tab of settingsTabs) {
      if (SELF_TABS.includes(tab.value)) {
        expect(tab.requires, tab.value).toBeUndefined();
      } else {
        expect(tab.requires, tab.value).toBeDefined();
      }
    }
  });
});
