import { TERMS_AND_CONDITIONS_URL } from "@/lib/legal";

interface TermsAndConditionsLinkProps {
  className?: string;
}

export function TermsAndConditionsLink({ className }: TermsAndConditionsLinkProps) {
  return (
    <a
      href={TERMS_AND_CONDITIONS_URL}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
    >
      Terms and Conditions
    </a>
  );
}
