import { Component, lazy, Suspense } from "react";
import type { ReactNode } from "react";

import { Button } from "~/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "~/components/ui/empty";
import { Skeleton } from "~/components/ui/skeleton";

import { PageHeader } from "../app/PageHeader";

// The admin code is loaded when the route is opened, so visitors of the chat do not download it.
const AdminPage = lazy(() => import("./AdminPage").then((module) => ({ default: module.AdminPage })));

function AdminFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Admin" />
      {children}
    </div>
  );
}

function AdminLoading() {
  return (
    <AdminFrame>
      <div role="status" aria-label="Loading the admin page" className="mx-auto flex w-full max-w-md flex-col gap-3 p-6">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    </AdminFrame>
  );
}

/** The admin code is a separate file; this catches a failed download of it. */
class AdminLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <AdminFrame>
        <Empty>
          <EmptyHeader>
            <EmptyTitle className="text-base font-medium">The admin page did not load</EmptyTitle>
            <EmptyDescription>Check your connection and reload the page.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => window.location.reload()}>Reload</Button>
          </EmptyContent>
        </Empty>
      </AdminFrame>
    );
  }
}

export function AdminRoute() {
  return (
    <AdminLoadBoundary>
      <Suspense fallback={<AdminLoading />}>
        <AdminPage />
      </Suspense>
    </AdminLoadBoundary>
  );
}
