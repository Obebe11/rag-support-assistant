import type { ReactNode } from "react";

import {
  WorkspaceBreadcrumb,
  WorkspaceBreadcrumbItem,
  WorkspaceBreadcrumbSeparator,
} from "~/components/WorkspaceBreadcrumb";
import { WorkspacePageHeader } from "~/components/WorkspacePageHeader";
import { cn } from "~/lib/utils";

import { ModeBadge } from "./ModeBadge";

/** The 52px top bar: where you are on the left, page actions and the mode badge on the right. */
export function PageHeader(props: {
  title: string;
  actions?: ReactNode;
  /** Leave room for the panel toggle that floats over the right end of the bar. */
  reserveToggleSpace?: boolean;
}) {
  return (
    <WorkspacePageHeader className="relative bg-background">
      <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
        <WorkspaceBreadcrumb ariaLabel="Breadcrumb" className="flex-1">
          <WorkspaceBreadcrumbItem className="hidden sm:flex">Northline</WorkspaceBreadcrumbItem>
          <WorkspaceBreadcrumbSeparator className="hidden sm:flex" />
          <WorkspaceBreadcrumbItem current>
            <h1 className="min-w-0 truncate">{props.title}</h1>
          </WorkspaceBreadcrumbItem>
        </WorkspaceBreadcrumb>
        <div
          className={cn(
            "flex shrink-0 items-center justify-end gap-2",
            props.reserveToggleSpace && "pr-10",
          )}
        >
          {props.actions}
          <ModeBadge />
        </div>
      </div>
    </WorkspacePageHeader>
  );
}
