import { describe, expect, it } from "vitest";

import { can } from "@/lib/permissions";

import { canSeeSettingsTab, groupSettingsTabs, settingsTabs } from "./settings-page";

const SELF_TABS = ["profile", "notifications", "calendar"];
const MANAGER_TABS = [
  "profile",
  "notifications",
  "calendar",
  "tags",
  "proposals",
  "pricing",
  "locations",
  "lead-sources",
  "attach-rules",
  "pipeline",
  "speed-to-lead",
  "estimate-followup",
  "quote-revival",
  "neighbors",
  "billing",
];
const SALES_TABS = [
  "profile",
  "notifications",
  "calendar",
  "speed-to-lead",
  "estimate-followup",
  "quote-revival",
  "neighbors",
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

  it("groups every visible label into a stable Settings category", () => {
    const groups = groupSettingsTabs(settingsTabs);

    expect(groups.map((group) => group.label)).toEqual([
      "Personal",
      "CRM",
      "Automation",
      "Integrations",
      "Workspace",
    ]);
    expect(groups.flatMap((group) => group.tabs.map((tab) => tab.value))).toEqual(
      settingsTabs.map((tab) => tab.value),
    );
    expect(groups.flatMap((group) => group.tabs)).toHaveLength(20);
  });
});
