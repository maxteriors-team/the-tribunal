"use client";

import { Upload } from "lucide-react";
import { useCallback, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface FileDropzoneProps {
  /**
   * Comma-separated list of file types accepted, e.g. `.csv` or
   * `.csv,text/csv` or `image/*`. Forwarded to the native `<input accept>`
   * attribute and used for client-side validation.
   *
   * @see https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/accept
   */
  accept: string;
  /** Called with a single file once the user has selected/dropped a valid one. */
  onFile: (file: File) => void;
  /** Main label shown in the dropzone (e.g. "Drop CSV here"). */
  placeholder: string;
  /** Optional secondary line. Defaults to "or click to browse". */
  subtext?: string;
  /** Optional custom icon. Defaults to the Upload icon. */
  icon?: ReactNode;
  /** Optional callback when a file is rejected by `accept` validation. */
  onReject?: (reason: string, file: File) => void;
  /** Disables the dropzone (no click, no drop). */
  disabled?: boolean;
  /** Accessible label for the button. Defaults to `placeholder`. */
  ariaLabel?: string;
  /** Extra classes appended to the outer element. */
  className?: string;
}

/**
 * Match a file against an HTML `accept` string. Supports:
 *  - extensions (".csv", ".png")
 *  - exact MIME types ("text/csv")
 *  - wildcard MIME ("image/*")
 *
 * Mirrors the browser's native file-input matching so behaviour stays
 * consistent whether the file is selected via the picker (already filtered)
 * or dragged in (unfiltered, must be checked by us).
 */
function isFileAccepted(file: File, accept: string): boolean {
  const tokens = accept
    .split(",")
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean);
  if (tokens.length === 0) return true;

  const fileName = file.name.toLowerCase();
  const fileType = file.type.toLowerCase();

  return tokens.some((token) => {
    if (token.startsWith(".")) {
      return fileName.endsWith(token);
    }
    if (token.endsWith("/*")) {
      const prefix = token.slice(0, -1); // keep trailing slash
      return fileType.startsWith(prefix);
    }
    return fileType === token;
  });
}

function describeAccept(accept: string): string {
  return accept
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .join(", ");
}

/**
 * Accessible CSV/file dropzone. Handles drag-over visual state, native file
 * picker via hidden `<input>`, `accept`-based validation with an inline
 * error message, and keyboard activation (Enter/Space) per WAI-ARIA button
 * pattern.
 */
export function FileDropzone({
  accept,
  onFile,
  placeholder,
  subtext = "or click to browse",
  icon,
  onReject,
  disabled = false,
  ariaLabel,
  className,
}: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openPicker = useCallback(() => {
    if (disabled) return;
    inputRef.current?.click();
  }, [disabled]);

  const handleFile = useCallback(
    (file: File) => {
      if (!isFileAccepted(file, accept)) {
        const reason = `Please select a ${describeAccept(accept)} file.`;
        setError(reason);
        onReject?.(reason, file);
        return;
      }
      setError(null);
      onFile(file);
    },
    [accept, onFile, onReject],
  );

  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setDragActive(true);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setDragActive(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (disabled) return;
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) handleFile(dropped);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) handleFile(selected);
    // Reset so selecting the same file twice still fires onChange.
    e.target.value = "";
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target !== inputRef.current) openPicker();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openPicker();
    }
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={ariaLabel ?? placeholder}
        aria-disabled={disabled || undefined}
        className={cn(
          "border-2 border-dashed rounded-lg p-8 flex flex-col items-center justify-center gap-3 text-center transition-colors outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          disabled ? "opacity-50 cursor-not-allowed border-border" : "cursor-pointer",
          !disabled && dragActive
            ? "border-primary bg-primary/5"
            : !disabled && !error
              ? "border-border hover:border-primary/50 hover:bg-muted/30"
              : null,
          error && !dragActive ? "border-destructive/50 bg-destructive/5" : null,
        )}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {icon ?? <Upload className="size-8 text-muted-foreground" />}
        <div>
          <p className="font-medium">{placeholder}</p>
          {subtext && <p className="text-sm text-muted-foreground mt-1">{subtext}</p>}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={handleInputChange}
          disabled={disabled}
          tabIndex={-1}
        />
      </div>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
