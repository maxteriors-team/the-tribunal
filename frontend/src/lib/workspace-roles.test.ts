import { describe, expect, it } from "vitest";

import * as workspaceRoles from "./workspace-roles";

type RoleAssignmentPolicy = (
  actorRole: string,
  targetRole: workspaceRoles.AssignableRole,
) => boolean;

function getRoleAssignmentPolicy(): RoleAssignmentPolicy {
  const policy: unknown = Reflect.get(workspaceRoles, "canAssignWorkspaceRole");
  expect(policy, "workspace-roles must export canAssignWorkspaceRole").toBeTypeOf("function");
  return policy as RoleAssignmentPolicy;
}

const OTHER_ACTOR_ROLES = [
  "manager",
  "dispatcher",
  "sales_rep",
  "lead_technician",
  "technician",
  "member",
  "unknown",
] as const;

describe("canAssignWorkspaceRole", () => {
  it("allows owners to assign every assignable role", () => {
    const canAssignWorkspaceRole = getRoleAssignmentPolicy();

    expect(
      workspaceRoles.ASSIGNABLE_ROLES.filter((role) =>
        canAssignWorkspaceRole("owner", role),
      ),
    ).toEqual(workspaceRoles.ASSIGNABLE_ROLES);
  });

  it("allows admins to assign every non-admin role and not admin", () => {
    const canAssignWorkspaceRole = getRoleAssignmentPolicy();

    expect(
      workspaceRoles.ASSIGNABLE_ROLES.filter((role) =>
        canAssignWorkspaceRole("admin", role),
      ),
    ).toEqual(workspaceRoles.ASSIGNABLE_ROLES.filter((role) => role !== "admin"));
  });

  it("allows no other actor role to assign a workspace role", () => {
    const canAssignWorkspaceRole = getRoleAssignmentPolicy();

    for (const actorRole of OTHER_ACTOR_ROLES) {
      expect(
        workspaceRoles.ASSIGNABLE_ROLES.filter((role) =>
          canAssignWorkspaceRole(actorRole, role),
        ),
        actorRole,
      ).toEqual([]);
    }
  });
});
