import type { LucideIcon } from "lucide-react";
import { ExternalLink } from "lucide-react";

interface InstructionStepProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  link?: string;
  linkLabel?: string;
}

export function InstructionStep({
  icon: Icon,
  title,
  description,
  link,
  linkLabel,
}: InstructionStepProps) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50">
      <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10 text-primary shrink-0">
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <p className="font-medium text-sm">{title}</p>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
        {link && (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 mt-1 text-xs text-primary hover:underline"
          >
            {linkLabel ?? "Open"} <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>
    </div>
  );
}
