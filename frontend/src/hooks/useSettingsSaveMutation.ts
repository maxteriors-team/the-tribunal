"use client";

import {
  useMutation,
  type UseMutationOptions,
  type UseMutationResult,
} from "@tanstack/react-query";
import { useRef } from "react";
import { toast } from "sonner";

import { getApiErrorMessage } from "@/lib/utils/errors";

type FeedbackMessage<TData, TVariables> = string | ((data: TData, variables: TVariables) => string);

type ErrorFeedbackMessage<TError, TVariables> =
  | string
  | ((error: TError, variables: TVariables) => string);

type SettingsSaveMutationOptions<
  TData = unknown,
  TError = Error,
  TVariables = void,
  TOnMutateResult = unknown,
> = Omit<
  UseMutationOptions<TData, TError, TVariables, TOnMutateResult>,
  "onError" | "onSuccess" | "throwOnError"
> & {
  successMessage: FeedbackMessage<TData, TVariables>;
  errorMessage: ErrorFeedbackMessage<TError, TVariables>;
  onSuccess?: UseMutationOptions<TData, TError, TVariables, TOnMutateResult>["onSuccess"];
  onError?: UseMutationOptions<TData, TError, TVariables, TOnMutateResult>["onError"];
};

const SETTINGS_FEEDBACK_TOAST_ID = "settings-save-feedback";
const RAW_TRANSPORT_MESSAGE =
  /^(?:request failed with status code \d{3}|network error|failed to fetch|internal server error)$/i;

function resolveSuccessMessage<TData, TVariables>(
  message: FeedbackMessage<TData, TVariables>,
  data: TData,
  variables: TVariables,
): string {
  return typeof message === "function" ? message(data, variables) : message;
}

function resolveErrorMessage<TError, TVariables>(
  message: ErrorFeedbackMessage<TError, TVariables>,
  error: TError,
  variables: TVariables,
): string {
  const fallback = typeof message === "function" ? message(error, variables) : message;
  const apiMessage = getApiErrorMessage(error, fallback).trim();
  return !apiMessage || RAW_TRANSPORT_MESSAGE.test(apiMessage) ? fallback : apiMessage;
}

function restoreInitiatingControl(control: HTMLElement | null): void {
  if (!control) return;

  requestAnimationFrame(() => {
    const focusWasLost =
      document.activeElement === document.body || document.activeElement === null;
    if (focusWasLost && control.isConnected && !control.matches(":disabled")) {
      control.focus({ preventScroll: true });
    }
  });
}

/**
 * Gives every Settings form save the same visible and screen-reader feedback
 * while keeping API failures local to the control that initiated them.
 */
export function useSettingsSaveMutation<
  TData = unknown,
  TError = Error,
  TVariables = void,
  TOnMutateResult = unknown,
>(
  options: SettingsSaveMutationOptions<TData, TError, TVariables, TOnMutateResult>,
): UseMutationResult<TData, TError, TVariables, TOnMutateResult> {
  const { successMessage, errorMessage, onSuccess, onError, ...mutationOptions } = options;
  const initiatingControlRef = useRef<HTMLElement | null>(null);

  const mutation = useMutation({
    ...mutationOptions,
    // The app normally escalates 5xx mutations to an error boundary. Settings
    // saves have an immediate, recoverable retry path, so keep the current tab
    // mounted and announce the failure instead.
    throwOnError: false,
    onSuccess: (data, variables, onMutateResult, context) => {
      onSuccess?.(data, variables, onMutateResult, context);
      toast.success("Changes saved", {
        id: SETTINGS_FEEDBACK_TOAST_ID,
        description: resolveSuccessMessage(successMessage, data, variables),
      });
      restoreInitiatingControl(initiatingControlRef.current);
    },
    onError: (error, variables, onMutateResult, context) => {
      onError?.(error, variables, onMutateResult, context);
      toast.error("Changes not saved", {
        id: SETTINGS_FEEDBACK_TOAST_ID,
        description: resolveErrorMessage(errorMessage, error, variables),
      });
      restoreInitiatingControl(initiatingControlRef.current);
    },
  });

  const rememberInitiatingControl = () => {
    initiatingControlRef.current =
      document.activeElement instanceof HTMLElement && document.activeElement !== document.body
        ? document.activeElement
        : null;
  };

  const mutate: typeof mutation.mutate = (variables, mutateOptions) => {
    rememberInitiatingControl();
    mutation.mutate(variables, mutateOptions);
  };
  const mutateAsync: typeof mutation.mutateAsync = (variables, mutateOptions) => {
    rememberInitiatingControl();
    return mutation.mutateAsync(variables, mutateOptions);
  };

  return { ...mutation, mutate, mutateAsync };
}
