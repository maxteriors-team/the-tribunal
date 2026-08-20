"use client";

import { Plus, Trash2, GripVertical, Star, MessageSquare, FileText } from "lucide-react";
import { motion, AnimatePresence, Reorder } from "motion/react";
import { useState } from "react";

import { LoadTemplateDialog } from "@/components/experiments/load-template-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { MessageTemplate } from "@/types";

export interface VariantFormData {
  id: string;
  name: string;
  message_template: string;
  is_control: boolean;
  sort_order: number;
}

interface VariantEditorProps {
  variants: VariantFormData[];
  onChange: (variants: VariantFormData[]) => void;
  error?: string;
}

const placeholders = [
  { label: "First Name", value: "{first_name}" },
  { label: "Last Name", value: "{last_name}" },
  { label: "Company", value: "{company_name}" },
];

export function VariantEditor({ variants, onChange, error }: VariantEditorProps) {
  const [activeVariantId, setActiveVariantId] = useState<string | null>(variants[0]?.id || null);
  const [loadTemplateOpen, setLoadTemplateOpen] = useState(false);

  const generateId = () => `temp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

  const addVariant = () => {
    const newVariant: VariantFormData = {
      id: generateId(),
      name: `Variant ${String.fromCharCode(65 + variants.length)}`,
      message_template: "",
      is_control: variants.length === 0,
      sort_order: variants.length,
    };
    onChange([...variants, newVariant]);
    setActiveVariantId(newVariant.id);
  };

  const updateVariant = (id: string, updates: Partial<VariantFormData>) => {
    onChange(variants.map((v) => (v.id === id ? { ...v, ...updates } : v)));
  };

  const removeVariant = (id: string) => {
    const newVariants = variants.filter((v) => v.id !== id);
    // If removed variant was control, make first variant control
    if (newVariants.length > 0) {
      const hadControl = newVariants.some((v) => v.is_control);
      if (!hadControl) {
        newVariants[0].is_control = true;
      }
    }
    onChange(newVariants);
    if (activeVariantId === id) {
      setActiveVariantId(newVariants[0]?.id || null);
    }
  };

  const setAsControl = (id: string) => {
    onChange(
      variants.map((v) => ({
        ...v,
        is_control: v.id === id,
      })),
    );
  };

  const handleReorder = (reorderedVariants: VariantFormData[]) => {
    onChange(
      reorderedVariants.map((v, index) => ({
        ...v,
        sort_order: index,
      })),
    );
  };

  const insertPlaceholder = (variantId: string, placeholder: string) => {
    const variant = variants.find((v) => v.id === variantId);
    if (variant) {
      updateVariant(variantId, {
        message_template: variant.message_template + placeholder,
      });
    }
  };

  const handleLoadTemplate = (template: MessageTemplate) => {
    if (activeVariantId) {
      updateVariant(activeVariantId, {
        message_template: template.message_template,
      });
    }
  };

  const activeVariant = variants.find((v) => v.id === activeVariantId);

  return (
    <div className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-12 gap-4">
        {/* Variant List */}
        <div className="col-span-4 space-y-2">
          <div className="flex items-center justify-between mb-2">
            <Label>Message Variants</Label>
            <Button type="button" variant="outline" size="sm" onClick={addVariant}>
              <Plus className="size-4 mr-1" />
              Add
            </Button>
          </div>

          <Reorder.Group axis="y" values={variants} onReorder={handleReorder} className="space-y-2">
            <AnimatePresence>
              {variants.map((variant) => (
                <Reorder.Item key={variant.id} value={variant} className="cursor-move">
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                  >
                    <Card
                      className={`cursor-pointer transition-colors ${
                        activeVariantId === variant.id
                          ? "border-primary ring-1 ring-primary"
                          : "hover:border-muted-foreground/50"
                      }`}
                      onClick={() => setActiveVariantId(variant.id)}
                    >
                      <CardContent className="p-3">
                        <div className="flex items-center gap-2">
                          <GripVertical className="size-4 text-muted-foreground flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-medium truncate">{variant.name}</span>
                              {variant.is_control && (
                                <Badge variant="secondary" className="text-xs flex-shrink-0">
                                  <Star className="size-3 mr-1" />
                                  Control
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground truncate mt-1">
                              {variant.message_template || "No message yet"}
                            </p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </motion.div>
                </Reorder.Item>
              ))}
            </AnimatePresence>
          </Reorder.Group>

          {variants.length === 0 && (
            <div className="text-center py-8 border-2 border-dashed rounded-lg">
              <MessageSquare className="size-8 mx-auto text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">Add at least 2 variants to test</p>
              <Button type="button" variant="link" size="sm" onClick={addVariant}>
                Add your first variant
              </Button>
            </div>
          )}
        </div>

        {/* Variant Editor */}
        <div className="col-span-8">
          {activeVariant ? (
            <Card>
              <CardContent className="p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium">Edit Variant</h4>
                  <div className="flex items-center gap-2">
                    {!activeVariant.is_control && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setAsControl(activeVariant.id)}
                      >
                        <Star className="size-4 mr-1" />
                        Set as Control
                      </Button>
                    )}
                    {variants.length > 1 && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => removeVariant(activeVariant.id)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="variant-name">Variant Name</Label>
                  <Input
                    id="variant-name"
                    value={activeVariant.name}
                    onChange={(e) => updateVariant(activeVariant.id, { name: e.target.value })}
                    placeholder="e.g., Friendly Tone"
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="variant-message">Message</Label>
                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-xs h-6 px-2"
                        onClick={() => setLoadTemplateOpen(true)}
                      >
                        <FileText className="size-3 mr-1" />
                        Load Template
                      </Button>
                      <span className="text-xs text-muted-foreground mx-2">Insert:</span>
                      {placeholders.map((p) => (
                        <Button
                          key={p.value}
                          type="button"
                          variant="outline"
                          size="sm"
                          className="text-xs h-6 px-2"
                          onClick={() => insertPlaceholder(activeVariant.id, p.value)}
                        >
                          {p.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                  <Textarea
                    id="variant-message"
                    value={activeVariant.message_template}
                    onChange={(e) =>
                      updateVariant(activeVariant.id, {
                        message_template: e.target.value,
                      })
                    }
                    placeholder="Hi {first_name}, ..."
                    rows={5}
                  />
                  <p className="text-xs text-muted-foreground">
                    {activeVariant.message_template.length}/160 characters (standard SMS)
                  </p>
                </div>

                <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                  <div>
                    <p className="font-medium text-sm">Control Variant</p>
                    <p className="text-xs text-muted-foreground">
                      Use this as the baseline for comparison
                    </p>
                  </div>
                  <Switch
                    aria-label={`Use ${activeVariant.name} as the control variant`}
                    checked={activeVariant.is_control}
                    onCheckedChange={() => setAsControl(activeVariant.id)}
                  />
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="flex items-center justify-center h-full border-2 border-dashed rounded-lg p-8">
              <div className="text-center">
                <MessageSquare className="size-8 mx-auto text-muted-foreground mb-2" />
                <p className="text-muted-foreground">Select a variant to edit</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {variants.length > 0 && variants.length < 2 && (
        <Alert>
          <AlertDescription>
            You need at least 2 variants to run an A/B test. Add another variant to continue.
          </AlertDescription>
        </Alert>
      )}

      <LoadTemplateDialog
        open={loadTemplateOpen}
        onOpenChange={setLoadTemplateOpen}
        onSelect={handleLoadTemplate}
      />
    </div>
  );
}
