import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ReviewSummaryCardProps {
  name: string;
  description?: string;
  fromPhoneDisplay: string;
}

export function ReviewSummaryCard({
  name,
  description,
  fromPhoneDisplay,
}: ReviewSummaryCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Campaign Summary</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-sm text-muted-foreground">Name</p>
            <p className="font-medium">{name}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">From</p>
            <p className="font-medium">{fromPhoneDisplay}</p>
          </div>
        </div>
        {description && (
          <div>
            <p className="text-sm text-muted-foreground">Description</p>
            <p className="font-medium">{description}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
