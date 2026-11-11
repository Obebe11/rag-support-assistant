import { Link } from "react-router";

import { Button } from "~/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "~/components/ui/empty";

import { PageHeader } from "../app/PageHeader";

export function NotFoundPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Page not found" />
      <Empty>
        <EmptyHeader>
          <EmptyTitle className="text-base font-medium">This page does not exist</EmptyTitle>
          <EmptyDescription>The address may be mistyped, or the page was moved.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button render={<Link to="/" />}>Go to the chat</Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}
