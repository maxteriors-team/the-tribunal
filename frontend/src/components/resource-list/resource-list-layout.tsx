import type { ReactNode } from "react";

interface ResourceListLayoutProps {
  header: ReactNode;
  stats?: ReactNode;
  filterBar?: ReactNode;
  children: ReactNode;
  emptyState?: ReactNode;
  pagination?: ReactNode;
  extras?: ReactNode;
  isEmpty?: boolean;
}

export function ResourceListLayout({
  header,
  stats,
  filterBar,
  children,
  emptyState,
  pagination,
  extras,
  isEmpty,
}: ResourceListLayoutProps) {
  return (
    <div className="space-y-6 p-4 sm:p-6">
      {header}
      {stats}
      {filterBar}
      {isEmpty ? emptyState : children}
      {pagination}
      {extras}
    </div>
  );
}
