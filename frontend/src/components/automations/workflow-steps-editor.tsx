"use client";

import {
  GitBranch,
  Mail,
  Megaphone,
  MessageSquare,
  Phone,
  Plus,
  Rocket,
  Settings2,
  Tag,
  Timer,
  Trash2,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import {
  GOTO_END,
  GOTO_NEXT_VALUE,
  WAIT_UNITS,
  WAIT_UNIT_LABELS,
  applyBranchConfig,
  applyWaitConfig,
  branchTargetSelectValue,
  isDanglingTarget,
  isTagAction,
  isWaitAction,
  parseBranchConfig,
  parseWaitConfig,
  setBranchTarget,
  stepSelectValue,
  type WaitUnit,
} from "@/components/automations/workflow-steps";
import { ContactFilterBuilder } from "@/components/filters/contact-filter-builder";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { DripCampaign } from "@/lib/api/drip-campaigns";
import type {
  AutomationAction,
  AutomationActionType,
  AutomationGotoTarget,
  Pipeline,
} from "@/types";

/** Label + icon for every action type, shared with the automation cards. */
export const actionTypeConfig: Record<AutomationActionType, { label: string; icon: LucideIcon }> = {
  send_sms: { label: "Send SMS", icon: MessageSquare },
  send_email: { label: "Send Email", icon: Mail },
  make_call: { label: "Make Call", icon: Phone },
  enroll_campaign: { label: "Enroll in Campaign", icon: Megaphone },
  start_drip_campaign: { label: "Start Drip Campaign", icon: Rocket },
  apply_tag: { label: "Apply Tag", icon: Tag },
  add_tag: { label: "Add Tag", icon: Tag },
  move_to_stage: { label: "Create or Move Deal", icon: TrendingUp },
  wait: { label: "Wait", icon: Timer },
  delay: { label: "Delay", icon: Timer },
  branch: { label: "Branch", icon: GitBranch },
  update_status: { label: "Update Status", icon: Settings2 },
};

/** Action types offered in the builder dropdown. */
export const ACTION_OPTIONS: AutomationActionType[] = [
  "send_sms",
  "send_email",
  "make_call",
  "enroll_campaign",
  "start_drip_campaign",
  "apply_tag",
  "move_to_stage",
  "wait",
  "branch",
];

/** Metadata for an action type, falling back to whatever the API stored. */
export function actionMeta(type: AutomationActionType): { label: string; icon: LucideIcon } {
  return actionTypeConfig[type] ?? { label: type, icon: Settings2 };
}

interface WorkflowStepsEditorProps {
  workspaceId: string;
  steps: AutomationAction[];
  onStepsChange: (steps: AutomationAction[]) => void;
  pipelines: Pipeline[];
  dripCampaigns: DripCampaign[];
}

/**
 * The step list of an automation: a flat, ordered sequence the backend walks
 * top to bottom. Control flow is expressed with `wait` and `branch` steps
 * rather than nesting, which is why a branch names its targets instead of
 * containing them.
 */
export function WorkflowStepsEditor({
  workspaceId,
  steps,
  onStepsChange,
  pipelines,
  dripCampaigns,
}: WorkflowStepsEditorProps) {
  const updateStep = (index: number, update: (step: AutomationAction) => AutomationAction) => {
    onStepsChange(steps.map((step, i) => (i === index ? update(step) : step)));
  };

  const setConfig = (index: number, config: Record<string, unknown>) => {
    updateStep(index, (step) => ({ ...step, config }));
  };

  const setConfigValue = (index: number, key: string, value: unknown) => {
    updateStep(index, (step) => ({ ...step, config: { ...step.config, [key]: value } }));
  };

  // Switching type drops the old config — a tag name means nothing to a branch —
  // but keeps the step's id, which another branch may already point at.
  const setType = (index: number, type: AutomationActionType) => {
    updateStep(index, (step) => (step.type === type ? step : { ...step, type, config: {} }));
  };

  const addStep = () => onStepsChange([...steps, { type: "send_sms", config: {} }]);

  const removeStep = (index: number) => onStepsChange(steps.filter((_, i) => i !== index));

  const targetOptions = (branchIndex: number) =>
    steps
      .map((step, index) => ({ index, label: `Step ${index + 1} · ${actionMeta(step.type).label}` }))
      .filter((option) => option.index !== branchIndex);

  const renderGotoSelect = (
    branchIndex: number,
    side: "thenGoto" | "elseGoto",
    label: string,
    target: AutomationGotoTarget
  ) => (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Select
        value={branchTargetSelectValue(steps, target)}
        onValueChange={(v) => onStepsChange(setBranchTarget(steps, branchIndex, side, v))}
      >
        <SelectTrigger>
          <SelectValue placeholder="Pick a step" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={GOTO_NEXT_VALUE}>Continue to next step</SelectItem>
          <SelectItem value={GOTO_END}>End workflow</SelectItem>
          {targetOptions(branchIndex).length > 0 && (
            <SelectGroup>
              <SelectLabel>Jump to</SelectLabel>
              {targetOptions(branchIndex).map((option) => (
                <SelectItem key={option.index} value={stepSelectValue(option.index)}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
        </SelectContent>
      </Select>
      {isDanglingTarget(steps, target) && (
        <p className="text-xs text-destructive">
          That step was removed. The run would stop here — pick a new target.
        </p>
      )}
    </div>
  );

  return (
    <div className="space-y-2">
      <Label>Steps</Label>
      <p className="text-xs text-muted-foreground">
        Steps run top to bottom. A wait pauses the run and it resumes later; a branch asks a
        question about the contact and sends the run wherever you point it.
      </p>
      <div className="space-y-3">
        {steps.map((step, index) => {
          const waitInputs = parseWaitConfig(step.config);
          const branchInputs = parseBranchConfig(step.config);
          return (
            <div key={index} className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-muted-foreground">Step {index + 1}</span>
                <Select
                  value={step.type}
                  onValueChange={(v) => setType(index, v as AutomationActionType)}
                >
                  <SelectTrigger className="flex-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ACTION_OPTIONS.map((value) => {
                      const Icon = actionMeta(value).icon;
                      return (
                        <SelectItem key={value} value={value}>
                          <div className="flex items-center gap-2">
                            <Icon className="size-4 text-muted-foreground" />
                            {actionMeta(value).label}
                          </div>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 shrink-0"
                  aria-label={`Remove step ${index + 1}`}
                  onClick={() => removeStep(index)}
                  disabled={steps.length === 1}
                >
                  <Trash2 className="size-4 text-muted-foreground" />
                </Button>
              </div>

              {isTagAction(step.type) && (
                <div className="space-y-2">
                  <Label htmlFor={`auto-step-${index}-tag`}>Tag to apply</Label>
                  <Input
                    id={`auto-step-${index}-tag`}
                    placeholder="e.g. Perm Lighting"
                    value={typeof step.config.tag === "string" ? step.config.tag : ""}
                    onChange={(e) => setConfigValue(index, "tag", e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Created in this workspace if it doesn&apos;t exist yet, then added to the
                    contact.
                  </p>
                </div>
              )}

              {step.type === "move_to_stage" && (
                <div className="space-y-2">
                  <Label>Put deal in stage</Label>
                  {pipelines.length > 0 ? (
                    <Select
                      value={typeof step.config.stage_id === "string" ? step.config.stage_id : ""}
                      onValueChange={(v) => {
                        const owner = pipelines.find((p) => p.stages?.some((s) => s.id === v));
                        setConfig(index, {
                          ...step.config,
                          stage_id: v,
                          pipeline_id: owner?.id ?? "",
                        });
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a stage" />
                      </SelectTrigger>
                      <SelectContent>
                        {pipelines.map((pipeline) => (
                          <SelectGroup key={pipeline.id}>
                            <SelectLabel>{pipeline.name}</SelectLabel>
                            {[...pipeline.stages]
                              .sort((a, b) => a.order - b.order)
                              .map((stage) => (
                                <SelectItem key={stage.id} value={stage.id}>
                                  {stage.name}
                                </SelectItem>
                              ))}
                          </SelectGroup>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No pipelines yet — create one in Opportunities first.
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Creates an open deal in this pipeline when the contact has none; otherwise moves
                    the existing open deal to this stage.
                  </p>
                </div>
              )}

              {step.type === "start_drip_campaign" && (
                <div className="space-y-2">
                  <Label>Drip campaign to start</Label>
                  {dripCampaigns.length > 0 ? (
                    <Select
                      value={
                        typeof step.config.drip_campaign_id === "string"
                          ? step.config.drip_campaign_id
                          : ""
                      }
                      onValueChange={(v) => setConfigValue(index, "drip_campaign_id", v)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a drip campaign" />
                      </SelectTrigger>
                      <SelectContent>
                        {dripCampaigns.map((campaign) => (
                          <SelectItem key={campaign.id} value={campaign.id}>
                            {campaign.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No drip campaigns yet — create a reactivation sequence first.
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Switches the sequence on so its enrolled past customers start receiving it. When
                    the trigger has a contact, that contact is enrolled too.
                  </p>
                </div>
              )}

              {isWaitAction(step.type) && (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-2">
                      <Label htmlFor={`auto-step-${index}-wait`}>Wait</Label>
                      <Input
                        id={`auto-step-${index}-wait`}
                        type="number"
                        min={0}
                        step={1}
                        value={waitInputs.amount || ""}
                        onChange={(e) =>
                          setConfig(
                            index,
                            applyWaitConfig(step.config, {
                              ...waitInputs,
                              amount: Number.parseFloat(e.target.value) || 0,
                            })
                          )
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Unit</Label>
                      <Select
                        value={waitInputs.unit}
                        onValueChange={(v) =>
                          setConfig(
                            index,
                            applyWaitConfig(step.config, { ...waitInputs, unit: v as WaitUnit })
                          )
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {WAIT_UNITS.map((unit) => (
                            <SelectItem key={unit} value={unit}>
                              {WAIT_UNIT_LABELS[unit]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    The run pauses here and picks up at the next step once the wait is over.
                  </p>
                </div>
              )}

              {step.type === "branch" && (
                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label>Conditions</Label>
                    {workspaceId ? (
                      <ContactFilterBuilder
                        compact
                        workspaceId={workspaceId}
                        filters={branchInputs.filters}
                        onFiltersChange={(filters) =>
                          setConfig(index, applyBranchConfig(step.config, { ...branchInputs, filters }))
                        }
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Pick a workspace to build branch conditions.
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Same rules as the contacts list and saved segments, re-checked against the
                      contact when the run reaches this step. No conditions means every contact
                      takes the yes path.
                    </p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {renderGotoSelect(index, "thenGoto", "If yes, go to", branchInputs.thenGoto)}
                    {renderGotoSelect(index, "elseGoto", "If no, go to", branchInputs.elseGoto)}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <Button variant="outline" size="sm" onClick={addStep} className="gap-2">
        <Plus className="size-4" />
        Add step
      </Button>
    </div>
  );
}
