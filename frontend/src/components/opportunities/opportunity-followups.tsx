"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { OpportunityNoteKind, OpportunityTask } from "@/types";

interface OpportunityFollowupsProps {
  workspaceId: string;
  opportunityId: string;
  tasks: OpportunityTask[];
}

/**
 * Notes, tasks and updates filed against the *deal*.
 *
 * A contact can have several jobs running at once, so a follow-up parked on the
 * contact loses the one fact that makes it actionable -- which job it is about.
 * Everything here posts to the opportunity instead.
 */
export function OpportunityFollowups({
  workspaceId,
  opportunityId,
  tasks,
}: OpportunityFollowupsProps) {
  const queryClient = useQueryClient();

  const [noteBody, setNoteBody] = useState("");
  const [noteKind, setNoteKind] = useState<OpportunityNoteKind>("note");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDueAt, setTaskDueAt] = useState("");
  const [taskAssigneeId, setTaskAssigneeId] = useState<number | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.opportunities.detail(workspaceId, opportunityId),
    });
  };

  const noteMutation = useMutation({
    mutationFn: (input: { body: string; kind: OpportunityNoteKind }) =>
      opportunitiesApi.addNote(workspaceId, opportunityId, input),
    onSuccess: (_data, input) => {
      setNoteBody("");
      toast.success(input.kind === "update" ? "Update posted" : "Note added");
      refresh();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to save note")),
  });

  const createTaskMutation = useMutation({
    mutationFn: (input: {
      title: string;
      due_at?: string | null;
      assigned_user_id: number | null;
    }) => opportunitiesApi.createTask(workspaceId, opportunityId, input),
    onSuccess: () => {
      setTaskTitle("");
      setTaskDueAt("");
      setTaskAssigneeId(null);
      toast.success("Task added");
      refresh();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to add task")),
  });

  const toggleTaskMutation = useMutation({
    mutationFn: (input: { taskId: string; completed: boolean }) =>
      opportunitiesApi.updateTask(workspaceId, opportunityId, input.taskId, {
        completed: input.completed,
      }),
    onSuccess: () => refresh(),
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to update task")),
  });

  const assignTaskMutation = useMutation({
    mutationFn: (input: { taskId: string; assignedUserId: number | null }) =>
      opportunitiesApi.updateTask(workspaceId, opportunityId, input.taskId, {
        assigned_user_id: input.assignedUserId,
      }),
    onSuccess: () => {
      toast.success("Tagged user updated");
      refresh();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to update tagged user")),
  });

  const submitNote = () => {
    const body = noteBody.trim();
    if (!body || noteMutation.isPending) return;
    noteMutation.mutate({ body, kind: noteKind });
  };

  const submitTask = () => {
    const title = taskTitle.trim();
    if (!title || createTaskMutation.isPending) return;
    createTaskMutation.mutate({
      // The input is a local date; send it as an ISO instant so the API and the
      // list agree on the day.
      title,
      due_at: taskDueAt ? new Date(`${taskDueAt}T12:00:00`).toISOString() : null,
      assigned_user_id: taskAssigneeId,
    });
  };

  const openTasks = tasks.filter((task) => !task.completed_at);
  const doneTasks = tasks.filter((task) => task.completed_at);

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">Follow-ups</p>

      <Tabs defaultValue="note">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="note">Note or update</TabsTrigger>
          <TabsTrigger value="task">Task</TabsTrigger>
        </TabsList>

        <TabsContent value="note" className="space-y-2 pt-2">
          <Label htmlFor="opportunity-note-body" className="sr-only">
            Note about this deal
          </Label>
          <Textarea
            id="opportunity-note-body"
            value={noteBody}
            onChange={(event) => setNoteBody(event.target.value)}
            placeholder="What happened on this deal?"
            rows={3}
          />
          <div className="flex items-center justify-between gap-2">
            <div className="flex gap-1">
              {(["note", "update"] as const).map((kind) => (
                <Button
                  key={kind}
                  type="button"
                  size="sm"
                  variant={noteKind === kind ? "secondary" : "ghost"}
                  aria-pressed={noteKind === kind}
                  onClick={() => setNoteKind(kind)}
                >
                  {kind === "note" ? "Note" : "Update"}
                </Button>
              ))}
            </div>
            <Button
              type="button"
              size="sm"
              onClick={submitNote}
              disabled={!noteBody.trim() || noteMutation.isPending}
            >
              {noteMutation.isPending ? "Saving..." : "Add"}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="task" className="space-y-2 pt-2">
          <Label htmlFor="opportunity-task-title" className="sr-only">
            Task title
          </Label>
          <Input
            id="opportunity-task-title"
            value={taskTitle}
            onChange={(event) => setTaskTitle(event.target.value)}
            placeholder="e.g. Send the revised quote"
          />
          <TeamMemberPicker
            workspaceId={workspaceId}
            value={taskAssigneeId}
            onValueChange={setTaskAssigneeId}
            label="Tag a user"
            triggerId="opportunity-task-assignee"
            className="max-w-sm"
            disabled={createTaskMutation.isPending}
          />
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Label htmlFor="opportunity-task-due" className="text-xs text-muted-foreground">
                Due
              </Label>
              <Input
                id="opportunity-task-due"
                type="date"
                className="h-8 w-auto"
                value={taskDueAt}
                onChange={(event) => setTaskDueAt(event.target.value)}
              />
            </div>
            <Button
              type="button"
              size="sm"
              onClick={submitTask}
              disabled={!taskTitle.trim() || createTaskMutation.isPending}
            >
              {createTaskMutation.isPending ? "Adding..." : "Add task"}
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {tasks.length > 0 ? (
        <ul className="space-y-1.5">
          {[...openTasks, ...doneTasks].map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              workspaceId={workspaceId}
              disabled={toggleTaskMutation.isPending}
              assigning={
                assignTaskMutation.isPending && assignTaskMutation.variables?.taskId === task.id
              }
              onToggle={(completed) =>
                toggleTaskMutation.mutate({ taskId: task.id, completed })
              }
              onAssigneeChange={(assignedUserId) =>
                assignTaskMutation.mutate({ taskId: task.id, assignedUserId })
              }
            />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function TaskRow({
  task,
  workspaceId,
  disabled,
  assigning,
  onToggle,
  onAssigneeChange,
}: {
  task: OpportunityTask;
  workspaceId: string;
  disabled: boolean;
  assigning: boolean;
  onToggle: (completed: boolean) => void;
  onAssigneeChange: (assignedUserId: number | null) => void;
}) {
  const isDone = !!task.completed_at;
  // Overdue only matters while the task is open -- flagging a finished task red
  // just because it was closed late is noise on a board people scan fast.
  const isOverdue = !isDone && !!task.due_at && new Date(task.due_at) < new Date();

  return (
    <li className="flex items-start gap-2 rounded-md border p-2">
      <Checkbox
        id={`task-${task.id}`}
        checked={isDone}
        disabled={disabled}
        onCheckedChange={(next) => onToggle(next === true)}
        aria-label={isDone ? `Reopen ${task.title}` : `Complete ${task.title}`}
      />
      <div className="min-w-0 flex-1">
        <label
          htmlFor={`task-${task.id}`}
          className={`block cursor-pointer text-sm ${
            isDone ? "text-muted-foreground line-through" : ""
          }`}
        >
          {task.title}
        </label>
        {task.due_at ? (
          <p className={`text-xs ${isOverdue ? "text-destructive" : "text-muted-foreground"}`}>
            {isOverdue ? "Overdue " : "Due "}
            {formatDate(task.due_at)}
          </p>
        ) : null}
        <TeamMemberPicker
          workspaceId={workspaceId}
          value={task.assigned_user_id ?? null}
          onValueChange={onAssigneeChange}
          label="Tagged user"
          triggerId={`opportunity-task-${task.id}-assignee`}
          className="mt-2 max-w-xs"
          disabled={isDone || assigning}
        />
      </div>
    </li>
  );
}
