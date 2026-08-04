import { Suspense } from "react";

import { PageLoadingState } from "@/components/ui/page-state";

import { RegisterClient } from "./register-client";

export default function RegisterPage() {
  return (
    // Suspense: RegisterClient reads useSearchParams (?invite=...).
    <Suspense fallback={<PageLoadingState className="min-h-screen" />}>
      <RegisterClient />
    </Suspense>
  );
}
