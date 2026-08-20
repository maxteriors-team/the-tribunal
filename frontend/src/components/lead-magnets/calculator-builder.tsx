"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2, Sparkles, Loader2, HelpCircle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { leadMagnetsApi, GenerateCalculatorRequest } from "@/lib/api/lead-magnets";
import type {
  CalculatorContent,
  CalculatorInput,
  CalculatorOutput,
  CalculatorSelectOption,
} from "@/types";

interface CalculatorBuilderProps {
  workspaceId: string;
  value: CalculatorContent;
  onChange: (value: CalculatorContent) => void;
}

const createDefaultInput = (index: number): CalculatorInput => ({
  id: `input${index}`,
  label: "",
  type: "number",
  placeholder: "",
  required: true,
});

const createDefaultOutput = (index: number): CalculatorOutput => ({
  id: `output${index}`,
  label: "",
  formula: "",
  format: "currency",
  highlight: index === 0,
});

export function CalculatorBuilder({ workspaceId, value, onChange }: CalculatorBuilderProps) {
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [aiInputs, setAiInputs] = useState<GenerateCalculatorRequest>({
    calculator_type: "",
    industry: "",
    target_audience: "",
    value_proposition: "",
  });

  const generateMutation = useMutation({
    mutationFn: () => leadMagnetsApi.generateCalculator(workspaceId, aiInputs),
    onSuccess: (data) => {
      if (data.success) {
        onChange({
          title: data.title || value.title,
          description: data.description || value.description,
          inputs: data.inputs || [],
          calculations: data.calculations || [],
          outputs: data.outputs || [],
          cta: data.cta || value.cta,
        });
        setAiDialogOpen(false);
      }
    },
  });

  const updateInput = (index: number, updates: Partial<CalculatorInput>) => {
    const newInputs = [...value.inputs];
    newInputs[index] = { ...newInputs[index], ...updates };
    onChange({ ...value, inputs: newInputs });
  };

  const addInput = () => {
    onChange({
      ...value,
      inputs: [...value.inputs, createDefaultInput(value.inputs.length + 1)],
    });
  };

  const removeInput = (index: number) => {
    onChange({
      ...value,
      inputs: value.inputs.filter((_, i) => i !== index),
    });
  };

  const updateInputOption = (
    inputIndex: number,
    optionIndex: number,
    updates: Partial<CalculatorSelectOption>,
  ) => {
    const newInputs = [...value.inputs];
    const input = newInputs[inputIndex];
    if (input.options) {
      const newOptions = [...input.options];
      newOptions[optionIndex] = { ...newOptions[optionIndex], ...updates };
      newInputs[inputIndex] = { ...input, options: newOptions };
      onChange({ ...value, inputs: newInputs });
    }
  };

  const addInputOption = (inputIndex: number) => {
    const newInputs = [...value.inputs];
    const input = newInputs[inputIndex];
    const newOption: CalculatorSelectOption = {
      value: `option${(input.options?.length || 0) + 1}`,
      label: "",
      multiplier: 1,
    };
    newInputs[inputIndex] = {
      ...input,
      options: [...(input.options || []), newOption],
    };
    onChange({ ...value, inputs: newInputs });
  };

  const removeInputOption = (inputIndex: number, optionIndex: number) => {
    const newInputs = [...value.inputs];
    const input = newInputs[inputIndex];
    if (input.options) {
      newInputs[inputIndex] = {
        ...input,
        options: input.options.filter((_, i) => i !== optionIndex),
      };
      onChange({ ...value, inputs: newInputs });
    }
  };

  const updateOutput = (index: number, updates: Partial<CalculatorOutput>) => {
    const newOutputs = [...value.outputs];
    newOutputs[index] = { ...newOutputs[index], ...updates };
    onChange({ ...value, outputs: newOutputs });
  };

  const addOutput = () => {
    onChange({
      ...value,
      outputs: [...value.outputs, createDefaultOutput(value.outputs.length + 1)],
    });
  };

  const removeOutput = (index: number) => {
    onChange({
      ...value,
      outputs: value.outputs.filter((_, i) => i !== index),
    });
  };

  return (
    <TooltipProvider>
      <div className="space-y-6">
        {/* Header with AI Generation */}
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold">Calculator Builder</h3>
            <p className="text-sm text-muted-foreground">Build an ROI or value calculator</p>
          </div>
          <Dialog open={aiDialogOpen} onOpenChange={setAiDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-2">
                <Sparkles className="size-4" />
                Generate with AI
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Generate Calculator with AI</DialogTitle>
                <DialogDescription>
                  Describe your calculator and we&apos;ll generate the fields and formulas
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label>Calculator Type</Label>
                  <Input
                    placeholder="e.g., ROI Calculator, Savings Calculator"
                    value={aiInputs.calculator_type}
                    onChange={(e) =>
                      setAiInputs((p) => ({ ...p, calculator_type: e.target.value }))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>Industry</Label>
                  <Input
                    placeholder="e.g., Marketing, SaaS, E-commerce"
                    value={aiInputs.industry}
                    onChange={(e) => setAiInputs((p) => ({ ...p, industry: e.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Target Audience</Label>
                  <Input
                    placeholder="e.g., Small business owners"
                    value={aiInputs.target_audience}
                    onChange={(e) =>
                      setAiInputs((p) => ({ ...p, target_audience: e.target.value }))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>Value Proposition</Label>
                  <Textarea
                    placeholder="What value are you demonstrating?"
                    value={aiInputs.value_proposition}
                    onChange={(e) =>
                      setAiInputs((p) => ({ ...p, value_proposition: e.target.value }))
                    }
                    rows={2}
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <Button
                  onClick={() => generateMutation.mutate()}
                  disabled={
                    !aiInputs.calculator_type ||
                    !aiInputs.industry ||
                    !aiInputs.target_audience ||
                    !aiInputs.value_proposition ||
                    generateMutation.isPending
                  }
                >
                  {generateMutation.isPending ? (
                    <>
                      <Loader2 className="size-4 mr-2 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Sparkles className="size-4 mr-2" />
                      Generate Calculator
                    </>
                  )}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>

        {/* Calculator Title and Description */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>Calculator Title</Label>
            <Input
              placeholder="e.g., ROI Calculator"
              value={value.title}
              onChange={(e) => onChange({ ...value, title: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label>Description</Label>
            <Input
              placeholder="Brief description"
              value={value.description || ""}
              onChange={(e) => onChange({ ...value, description: e.target.value })}
            />
          </div>
        </div>

        <Separator />

        {/* Input Fields */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Label className="text-base">Input Fields</Label>
            <Button variant="outline" size="sm" onClick={addInput}>
              <Plus className="size-4 mr-1" />
              Add Input
            </Button>
          </div>

          {value.inputs.map((input, iIndex) => (
            <Card key={input.id}>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-sm flex-1">
                    {input.label || `Input ${iIndex + 1}`}
                  </CardTitle>
                  <Select
                    value={input.type}
                    onValueChange={(v) => {
                      const updates: Partial<CalculatorInput> = {
                        type: v as CalculatorInput["type"],
                      };
                      if (v === "select" && !input.options) {
                        updates.options = [{ value: "option1", label: "Option 1", multiplier: 1 }];
                      }
                      updateInput(iIndex, updates);
                    }}
                  >
                    <SelectTrigger
                      className="w-32"
                      aria-label={`${input.label || `Input ${iIndex + 1}`} type`}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="number">Number</SelectItem>
                      <SelectItem value="currency">Currency</SelectItem>
                      <SelectItem value="percentage">Percentage</SelectItem>
                      <SelectItem value="select">Dropdown</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive"
                    onClick={() => removeInput(iIndex)}
                    aria-label={`Remove ${input.label || `input ${iIndex + 1}`}`}
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label className="text-sm">Label</Label>
                    <Input
                      placeholder="Field label"
                      value={input.label}
                      onChange={(e) => updateInput(iIndex, { label: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm">Variable ID</Label>
                    <Input
                      placeholder="e.g., monthly_revenue"
                      value={input.id}
                      onChange={(e) =>
                        updateInput(iIndex, { id: e.target.value.replace(/\s/g, "_") })
                      }
                    />
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="space-y-2">
                    <Label className="text-sm">Placeholder</Label>
                    <Input
                      placeholder="e.g., 10000"
                      value={input.placeholder || ""}
                      onChange={(e) => updateInput(iIndex, { placeholder: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm">Prefix</Label>
                    <Input
                      placeholder="e.g., $"
                      value={input.prefix || ""}
                      onChange={(e) => updateInput(iIndex, { prefix: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm">Suffix</Label>
                    <Input
                      placeholder="e.g., %"
                      value={input.suffix || ""}
                      onChange={(e) => updateInput(iIndex, { suffix: e.target.value })}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label className="text-sm">Help Text</Label>
                  <Input
                    placeholder="Explanation of what to enter"
                    value={input.help_text || ""}
                    onChange={(e) => updateInput(iIndex, { help_text: e.target.value })}
                  />
                </div>

                {input.type === "select" && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm">Options</Label>
                      <Button variant="ghost" size="sm" onClick={() => addInputOption(iIndex)}>
                        <Plus className="size-3 mr-1" />
                        Add
                      </Button>
                    </div>
                    {input.options?.map((option, oIndex) => (
                      <div key={oIndex} className="flex items-center gap-2">
                        <Input
                          placeholder="Label"
                          value={option.label}
                          onChange={(e) =>
                            updateInputOption(iIndex, oIndex, { label: e.target.value })
                          }
                          className="flex-1"
                        />
                        <Input
                          placeholder="Value"
                          value={option.value}
                          onChange={(e) =>
                            updateInputOption(iIndex, oIndex, { value: e.target.value })
                          }
                          className="w-24"
                        />
                        <Input
                          type="number"
                          step="0.1"
                          placeholder="×"
                          value={option.multiplier ?? ""}
                          onChange={(e) =>
                            updateInputOption(iIndex, oIndex, {
                              multiplier: parseFloat(e.target.value),
                            })
                          }
                          className="w-16"
                        />
                        {(input.options?.length || 0) > 1 && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => removeInputOption(iIndex, oIndex)}
                            aria-label={`Remove option ${oIndex + 1} from ${input.label || `input ${iIndex + 1}`}`}
                          >
                            <Trash2 className="size-4" aria-hidden="true" />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <Switch
                    checked={input.required}
                    onCheckedChange={(checked) => updateInput(iIndex, { required: checked })}
                  />
                  <Label className="text-sm">Required</Label>
                </div>
              </CardContent>
            </Card>
          ))}

          {value.inputs.length === 0 && (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center justify-center py-8 text-center">
                <p className="text-muted-foreground mb-2">No input fields yet</p>
                <Button variant="outline" size="sm" onClick={addInput}>
                  <Plus className="size-4 mr-1" />
                  Add Input Field
                </Button>
              </CardContent>
            </Card>
          )}
        </div>

        <Separator />

        {/* Output Fields */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Label className="text-base">Output Results</Label>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="size-4 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p>Use input IDs in formulas. Example: input1 * (input2 / 100) * 12</p>
                </TooltipContent>
              </Tooltip>
            </div>
            <Button variant="outline" size="sm" onClick={addOutput}>
              <Plus className="size-4 mr-1" />
              Add Output
            </Button>
          </div>

          {value.outputs.map((output, oIndex) => (
            <Card key={output.id} className={output.highlight ? "ring-2 ring-primary" : ""}>
              <CardContent className="pt-4 space-y-3">
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="Result label"
                    value={output.label}
                    onChange={(e) => updateOutput(oIndex, { label: e.target.value })}
                    className="flex-1"
                  />
                  <Select
                    value={output.format}
                    onValueChange={(v) =>
                      updateOutput(oIndex, { format: v as CalculatorOutput["format"] })
                    }
                  >
                    <SelectTrigger
                      className="w-28"
                      aria-label={`${output.label || `Result ${oIndex + 1}`} format`}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="currency">Currency</SelectItem>
                      <SelectItem value="percentage">Percentage</SelectItem>
                      <SelectItem value="number">Number</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive"
                    onClick={() => removeOutput(oIndex)}
                    aria-label={`Remove ${output.label || `result ${oIndex + 1}`}`}
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                </div>

                <div className="space-y-2">
                  <Label className="text-sm">Formula</Label>
                  <Input
                    placeholder="e.g., input1 * (input2 / 100) * 12"
                    value={output.formula}
                    onChange={(e) => updateOutput(oIndex, { formula: e.target.value })}
                    className="font-mono text-sm"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-sm">Description</Label>
                  <Input
                    placeholder="What this result means"
                    value={output.description || ""}
                    onChange={(e) => updateOutput(oIndex, { description: e.target.value })}
                  />
                </div>

                <div className="flex items-center gap-2">
                  <Switch
                    checked={output.highlight}
                    onCheckedChange={(checked) => updateOutput(oIndex, { highlight: checked })}
                  />
                  <Label className="text-sm">Highlight as primary result</Label>
                </div>
              </CardContent>
            </Card>
          ))}

          {value.outputs.length === 0 && (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center justify-center py-8 text-center">
                <p className="text-muted-foreground mb-2">No output results yet</p>
                <Button variant="outline" size="sm" onClick={addOutput}>
                  <Plus className="size-4 mr-1" />
                  Add Output Result
                </Button>
              </CardContent>
            </Card>
          )}
        </div>

        <Separator />

        {/* CTA */}
        <div className="space-y-4">
          <Label className="text-base">Call to Action</Label>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label className="text-sm">Button Text</Label>
              <Input
                placeholder="e.g., Get Your Free Consultation"
                value={value.cta?.text || ""}
                onChange={(e) =>
                  onChange({ ...value, cta: { ...value.cta, text: e.target.value } })
                }
              />
            </div>
            <div className="space-y-2">
              <Label className="text-sm">Supporting Text</Label>
              <Input
                placeholder="e.g., Talk to an expert about your results"
                value={value.cta?.description || ""}
                onChange={(e) =>
                  onChange({
                    ...value,
                    cta: { text: value.cta?.text || "", description: e.target.value },
                  })
                }
              />
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
