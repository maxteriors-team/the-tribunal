import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Tabs } from "@/components/ui/tabs";

import {
  groupSettingsTabs,
  settingsGroups,
  settingsTabs,
  SettingsTabNavigation,
} from "./settings-page";

function renderNavigation() {
  render(
    <Tabs defaultValue="profile">
      <SettingsTabNavigation activeTab="profile" groups={groupSettingsTabs(settingsTabs)} />
    </Tabs>,
  );
}

describe("SettingsTabNavigation", () => {
  it("keeps every tab label visible inside a named category", () => {
    renderNavigation();

    expect(screen.getByRole("tablist", { name: "Settings sections" })).toBeVisible();
    for (const group of settingsGroups) {
      const category = document.querySelector(`[data-settings-group="${group.value}"]`);
      expect(category).toBeVisible();
      expect(category?.querySelector("[data-settings-group-label]")).toHaveTextContent(group.label);
    }

    for (const tab of settingsTabs) {
      const trigger = screen.getByRole("tab", { name: tab.label });
      const groupLabel = settingsGroups.find((group) => group.value === tab.group)?.label;
      expect(trigger).toHaveTextContent(tab.label);
      expect(trigger).toHaveAccessibleDescription(groupLabel);
      expect(trigger.querySelector("span")).toBeVisible();
    }
  });

  it("moves focus and selection through the grouped tabs with arrow keys", async () => {
    const user = userEvent.setup();
    renderNavigation();

    const profileTab = screen.getByRole("tab", { name: "Profile" });
    await user.click(profileTab);
    expect(profileTab).toHaveFocus();

    await user.keyboard("{ArrowRight}");

    const notificationsTab = screen.getByRole("tab", { name: "Notifications" });
    expect(notificationsTab).toHaveFocus();
    expect(notificationsTab).toHaveAttribute("aria-selected", "true");
  });
});
