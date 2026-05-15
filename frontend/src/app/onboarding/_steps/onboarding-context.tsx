"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/**
 * Extras the onboarding flow tracks outside the form:
 *  - uploaded CSV file + parsed row count (File can't go in form values)
 *  - verified-connection metadata returned by the API
 *  - count of contacts pulled from Follow Up Boss
 *  - leads-step validation error (since "have leads" isn't a form field)
 */
interface OnboardingExtras {
  csvFile: File | null;
  csvRowCount: number | null;
  setCsvFile: (file: File | null, rows: number | null) => void;

  fubConnected: boolean;
  fubName: string | null;
  markFubConnected: (name: string | null) => void;

  fubImportCount: number | null;
  setFubImportCount: (n: number | null) => void;

  calcomConnected: boolean;
  calcomUsername: string | null;
  markCalcomConnected: (username: string | null) => void;

  leadsError: string | null;
  setLeadsError: (msg: string | null) => void;
}

const OnboardingExtrasContext = createContext<OnboardingExtras | null>(null);

export function OnboardingExtrasProvider({ children }: { children: ReactNode }) {
  const [csvFile, setCsvFileState] = useState<File | null>(null);
  const [csvRowCount, setCsvRowCount] = useState<number | null>(null);

  const [fubConnected, setFubConnected] = useState(false);
  const [fubName, setFubName] = useState<string | null>(null);
  const [fubImportCount, setFubImportCount] = useState<number | null>(null);

  const [calcomConnected, setCalcomConnected] = useState(false);
  const [calcomUsername, setCalcomUsername] = useState<string | null>(null);

  const [leadsError, setLeadsError] = useState<string | null>(null);

  const setCsvFile = useCallback((file: File | null, rows: number | null) => {
    setCsvFileState(file);
    setCsvRowCount(rows);
    if (file) setLeadsError(null);
  }, []);

  const markFubConnected = useCallback((name: string | null) => {
    setFubConnected(true);
    setFubName(name);
  }, []);

  const markCalcomConnected = useCallback((username: string | null) => {
    setCalcomConnected(true);
    setCalcomUsername(username);
  }, []);

  const value = useMemo<OnboardingExtras>(
    () => ({
      csvFile,
      csvRowCount,
      setCsvFile,
      fubConnected,
      fubName,
      markFubConnected,
      fubImportCount,
      setFubImportCount,
      calcomConnected,
      calcomUsername,
      markCalcomConnected,
      leadsError,
      setLeadsError,
    }),
    [
      csvFile,
      csvRowCount,
      setCsvFile,
      fubConnected,
      fubName,
      markFubConnected,
      fubImportCount,
      calcomConnected,
      calcomUsername,
      markCalcomConnected,
      leadsError,
    ]
  );

  return (
    <OnboardingExtrasContext.Provider value={value}>
      {children}
    </OnboardingExtrasContext.Provider>
  );
}

export function useOnboardingExtras(): OnboardingExtras {
  const ctx = useContext(OnboardingExtrasContext);
  if (!ctx) {
    throw new Error(
      "useOnboardingExtras must be used inside <OnboardingExtrasProvider>"
    );
  }
  return ctx;
}
