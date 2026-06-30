"use client";

import { useMemo } from "react";

import { can as roleCan, roleTier, type Capability, type Tier } from "@/lib/permissions";
import { useWorkspace } from "@/providers/workspace-provider";

interface Capabilities {
  /** The caller's resolved access tier in the current workspace. */
  tier: Tier;
  /** True when the current role is granted `capability`. */
  can: (capability: Capability) => boolean;
}

/**
 * Capability check for the active workspace, derived from the caller's
 * membership role (`useWorkspace().currentWorkspace?.role`). Mirrors the backend
 * gate in `app/api/deps.py`; used to show/hide nav, buttons, and route content.
 */
export function useCapabilities(): Capabilities {
  const { currentWorkspace } = useWorkspace();
  const role = currentWorkspace?.role;

  return useMemo(
    () => ({
      tier: roleTier(role),
      can: (capability: Capability) => roleCan(role, capability),
    }),
    [role]
  );
}
