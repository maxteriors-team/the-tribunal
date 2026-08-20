"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2, GripVertical, Sparkles, Loader2 } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { leadMagnetsApi, GenerateQuizRequest } from "@/lib/api/lead-magnets";
import type { QuizContent, QuizQuestion, QuizOption, QuizResult } from "@/types";

interface QuizBuilderProps {
  workspaceId: string;
  value: QuizContent;
  onChange: (value: QuizContent) => void;
}

const createDefaultQuestion = (index: number): QuizQuestion => ({
  id: `q${index}`,
  text: "",
  type: "single_choice",
  options: [
    { id: `q${index}_a`, text: "", score: 10 },
    { id: `q${index}_b`, text: "", score: 5 },
    { id: `q${index}_c`, text: "", score: 0 },
  ],
});

const createDefaultResult = (id: string, minScore: number, maxScore: number): QuizResult => ({
  id,
  min_score: minScore,
  max_score: maxScore,
  title: "",
  description: "",
  cta_text: "",
});

export function QuizBuilder({ workspaceId, value, onChange }: QuizBuilderProps) {
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [aiInputs, setAiInputs] = useState<GenerateQuizRequest>({
    topic: "",
    target_audience: "",
    goal: "",
    num_questions: 5,
  });

  const generateMutation = useMutation({
    mutationFn: () => leadMagnetsApi.generateQuiz(workspaceId, aiInputs),
    onSuccess: (data) => {
      if (data.success) {
        onChange({
          title: data.title || value.title,
          description: data.description || value.description,
          questions: data.questions || [],
          results: data.results || [],
        });
        setAiDialogOpen(false);
      }
    },
  });

  const updateQuestion = (index: number, updates: Partial<QuizQuestion>) => {
    const newQuestions = [...value.questions];
    newQuestions[index] = { ...newQuestions[index], ...updates };
    onChange({ ...value, questions: newQuestions });
  };

  const updateOption = (
    questionIndex: number,
    optionIndex: number,
    updates: Partial<QuizOption>,
  ) => {
    const newQuestions = [...value.questions];
    const newOptions = [...newQuestions[questionIndex].options];
    newOptions[optionIndex] = { ...newOptions[optionIndex], ...updates };
    newQuestions[questionIndex] = { ...newQuestions[questionIndex], options: newOptions };
    onChange({ ...value, questions: newQuestions });
  };

  const addQuestion = () => {
    onChange({
      ...value,
      questions: [...value.questions, createDefaultQuestion(value.questions.length + 1)],
    });
  };

  const removeQuestion = (index: number) => {
    onChange({
      ...value,
      questions: value.questions.filter((_, i) => i !== index),
    });
  };

  const addOption = (questionIndex: number) => {
    const question = value.questions[questionIndex];
    const newOption: QuizOption = {
      id: `${question.id}_${String.fromCharCode(97 + question.options.length)}`,
      text: "",
      score: 0,
    };
    const newQuestions = [...value.questions];
    newQuestions[questionIndex] = {
      ...question,
      options: [...question.options, newOption],
    };
    onChange({ ...value, questions: newQuestions });
  };

  const removeOption = (questionIndex: number, optionIndex: number) => {
    const newQuestions = [...value.questions];
    newQuestions[questionIndex] = {
      ...newQuestions[questionIndex],
      options: newQuestions[questionIndex].options.filter((_, i) => i !== optionIndex),
    };
    onChange({ ...value, questions: newQuestions });
  };

  const updateResult = (index: number, updates: Partial<QuizResult>) => {
    const newResults = [...value.results];
    newResults[index] = { ...newResults[index], ...updates };
    onChange({ ...value, results: newResults });
  };

  const addResult = () => {
    const maxScore =
      value.results.length > 0 ? Math.max(...value.results.map((r) => r.max_score)) : 100;
    onChange({
      ...value,
      results: [
        ...value.results,
        createDefaultResult(`result${value.results.length + 1}`, 0, maxScore),
      ],
    });
  };

  const removeResult = (index: number) => {
    onChange({
      ...value,
      results: value.results.filter((_, i) => i !== index),
    });
  };

  return (
    <div className="space-y-6">
      {/* Header with AI Generation */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold">Quiz Builder</h3>
          <p className="text-sm text-muted-foreground">
            Create qualification questions with scoring
          </p>
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
              <DialogTitle>Generate Quiz with AI</DialogTitle>
              <DialogDescription>
                Describe your quiz and we&apos;ll generate questions and scoring
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>Topic</Label>
                <Input
                  placeholder="e.g., Marketing readiness assessment"
                  value={aiInputs.topic}
                  onChange={(e) => setAiInputs((p) => ({ ...p, topic: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label>Target Audience</Label>
                <Input
                  placeholder="e.g., Small business owners"
                  value={aiInputs.target_audience}
                  onChange={(e) => setAiInputs((p) => ({ ...p, target_audience: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label>Goal</Label>
                <Input
                  placeholder="e.g., Qualify leads for marketing services"
                  value={aiInputs.goal}
                  onChange={(e) => setAiInputs((p) => ({ ...p, goal: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label>Number of Questions</Label>
                <Select
                  value={String(aiInputs.num_questions)}
                  onValueChange={(v) => setAiInputs((p) => ({ ...p, num_questions: parseInt(v) }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n} questions
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex justify-end">
              <Button
                onClick={() => generateMutation.mutate()}
                disabled={
                  !aiInputs.topic ||
                  !aiInputs.target_audience ||
                  !aiInputs.goal ||
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
                    Generate Quiz
                  </>
                )}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Quiz Title and Description */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label>Quiz Title</Label>
          <Input
            placeholder="e.g., Marketing Readiness Score"
            value={value.title}
            onChange={(e) => onChange({ ...value, title: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>Description</Label>
          <Input
            placeholder="Brief description of the quiz"
            value={value.description || ""}
            onChange={(e) => onChange({ ...value, description: e.target.value })}
          />
        </div>
      </div>

      <Separator />

      {/* Questions */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Label className="text-base">Questions</Label>
          <Button variant="outline" size="sm" onClick={addQuestion}>
            <Plus className="size-4 mr-1" />
            Add Question
          </Button>
        </div>

        {value.questions.map((question, qIndex) => (
          <Card key={question.id}>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <GripVertical className="size-4 text-muted-foreground cursor-grab" />
                <CardTitle className="text-sm flex-1">Question {qIndex + 1}</CardTitle>
                <Select
                  value={question.type}
                  onValueChange={(v) => updateQuestion(qIndex, { type: v as QuizQuestion["type"] })}
                >
                  <SelectTrigger className="w-40" aria-label={`Question ${qIndex + 1} type`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="single_choice">Single Choice</SelectItem>
                    <SelectItem value="multiple_choice">Multiple Choice</SelectItem>
                    <SelectItem value="scale">Scale (1-10)</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive"
                  onClick={() => removeQuestion(qIndex)}
                  aria-label={`Remove question ${qIndex + 1}`}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                placeholder="Enter your question..."
                value={question.text}
                onChange={(e) => updateQuestion(qIndex, { text: e.target.value })}
              />

              {question.type !== "scale" && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm text-muted-foreground">Options</Label>
                    <Button variant="ghost" size="sm" onClick={() => addOption(qIndex)}>
                      <Plus className="size-3 mr-1" />
                      Add
                    </Button>
                  </div>
                  {question.options.map((option, oIndex) => (
                    <div key={option.id} className="flex items-center gap-2">
                      <Input
                        placeholder={`Option ${oIndex + 1}`}
                        value={option.text}
                        onChange={(e) => updateOption(qIndex, oIndex, { text: e.target.value })}
                        className="flex-1"
                      />
                      <Input
                        type="number"
                        placeholder="Score"
                        value={option.score}
                        onChange={(e) =>
                          updateOption(qIndex, oIndex, { score: parseInt(e.target.value) || 0 })
                        }
                        className="w-20"
                      />
                      {question.options.length > 2 && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-muted-foreground hover:text-destructive"
                          onClick={() => removeOption(qIndex, oIndex)}
                          aria-label={`Remove option ${oIndex + 1} from question ${qIndex + 1}`}
                        >
                          <Trash2 className="size-4" aria-hidden="true" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {question.type === "scale" && (
                <div className="space-y-2">
                  <Label className="text-sm text-muted-foreground">Score Weight</Label>
                  <Input
                    type="number"
                    placeholder="Weight multiplier (e.g., 5)"
                    value={question.weight || ""}
                    onChange={(e) =>
                      updateQuestion(qIndex, { weight: parseInt(e.target.value) || undefined })
                    }
                    className="w-32"
                  />
                  <p className="text-xs text-muted-foreground">
                    Final score = selected value (1-10) × weight
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        ))}

        {value.questions.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-8 text-center">
              <p className="text-muted-foreground mb-2">No questions yet</p>
              <Button variant="outline" size="sm" onClick={addQuestion}>
                <Plus className="size-4 mr-1" />
                Add Your First Question
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      <Separator />

      {/* Results */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Label className="text-base">Result Ranges</Label>
          <Button variant="outline" size="sm" onClick={addResult}>
            <Plus className="size-4 mr-1" />
            Add Result
          </Button>
        </div>

        {value.results.map((result, rIndex) => (
          <Card key={result.id}>
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-2 flex-1">
                  <Input
                    type="number"
                    placeholder="Min"
                    value={result.min_score}
                    onChange={(e) =>
                      updateResult(rIndex, { min_score: parseInt(e.target.value) || 0 })
                    }
                    className="w-20"
                  />
                  <span className="text-muted-foreground">to</span>
                  <Input
                    type="number"
                    placeholder="Max"
                    value={result.max_score}
                    onChange={(e) =>
                      updateResult(rIndex, { max_score: parseInt(e.target.value) || 0 })
                    }
                    className="w-20"
                  />
                  <span className="text-muted-foreground">points</span>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive"
                  onClick={() => removeResult(rIndex)}
                  aria-label={`Remove result range ${rIndex + 1}`}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </div>
              <Input
                placeholder="Result title (e.g., 'Ready to Scale!')"
                value={result.title}
                onChange={(e) => updateResult(rIndex, { title: e.target.value })}
              />
              <Textarea
                placeholder="Result description and next steps..."
                value={result.description}
                onChange={(e) => updateResult(rIndex, { description: e.target.value })}
                rows={2}
              />
              <Input
                placeholder="CTA button text (e.g., 'Book a Call')"
                value={result.cta_text || ""}
                onChange={(e) => updateResult(rIndex, { cta_text: e.target.value })}
              />
            </CardContent>
          </Card>
        ))}

        {value.results.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-8 text-center">
              <p className="text-muted-foreground mb-2">No result ranges defined</p>
              <Button variant="outline" size="sm" onClick={addResult}>
                <Plus className="size-4 mr-1" />
                Add Result Range
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
