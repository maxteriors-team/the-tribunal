"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Phone,
  Mail,
  Calendar,
  Webhook,
  Key,
  Loader2,
  Send as SendIcon,
  Users,
} from "lucide-react";
import { useState } from "react";

import { IntegrationConfigDialog } from "@/components/settings/integration-config-dialog";
import { OpenAIChatGPTCard } from "@/components/settings/openai-chatgpt-card";
import { PhoneNumbersTable } from "@/components/settings/phone-numbers-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  integrationsApi,
  type IntegrationWithMaskedCredentials,
} from "@/lib/api/integrations";
import { settingsApi } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";

type IntegrationType =
  | "calcom"
  | "telnyx"
  | "openai"
  | "resend"
  | "lob"
  | "followupboss";

function getIntegrationIcon(type: string) {
  switch (type) {
    case "calcom":
      return Calendar;
    case "telnyx":
      return Phone;
    case "resend":
      return Mail;
    case "lob":
      return SendIcon;
    case "followupboss":
      return Users;
    default:
      return Webhook;
  }
}

function getIntegrationColor(type: string) {
  switch (type) {
    case "calcom":
      return "text-primary bg-primary/10";
    case "telnyx":
      return "text-destructive bg-destructive/10";
    case "resend":
      return "text-black bg-neutral-100";
    case "lob":
      return "text-amber-600 bg-amber-100";
    case "followupboss":
      return "text-blue-600 bg-blue-100";
    default:
      return "text-primary bg-primary/10";
  }
}

export function IntegrationsSettingsTab() {
  const workspaceId = useWorkspaceId();
  const [integrationDialogOpen, setIntegrationDialogOpen] = useState(false);
  const [selectedIntegration, setSelectedIntegration] =
    useState<IntegrationType | null>(null);

  // Fetch integrations (status display)
  const { data: integrationsData, isPending: integrationsLoading } = useQuery({
    queryKey: queryKeys.settings.integrations(workspaceId ?? ""),
    queryFn: () => settingsApi.getIntegrations(workspaceId!),
    enabled: !!workspaceId,
  });

  // Fetch configured integrations (with credentials)
  const { data: configuredIntegrations } = useQuery({
    queryKey: queryKeys.integrations.all(workspaceId ?? ""),
    queryFn: () => integrationsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  // Helper to find existing integration by type
  const getExistingIntegration = (
    type: IntegrationType
  ): IntegrationWithMaskedCredentials | null => {
    return (
      configuredIntegrations?.find((i) => i.integration_type === type) ?? null
    );
  };

  // Handler to open integration config dialog
  const handleConfigureIntegration = (type: IntegrationType) => {
    setSelectedIntegration(type);
    setIntegrationDialogOpen(true);
  };

  return (
    <div className="space-y-6">
      {/* Phone Numbers Section */}
      <PhoneNumbersTable variant="section" />

      <OpenAIChatGPTCard />

      <div className="grid gap-4 md:grid-cols-2">
        {integrationsLoading ? (
          <div className="col-span-2 flex items-center justify-center py-12">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          integrationsData?.integrations.map((integration) => {
            const Icon = getIntegrationIcon(integration.integration_type);
            const colorClass = getIntegrationColor(integration.integration_type);

            return (
              <Card key={integration.integration_type}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex size-10 items-center justify-center rounded-lg ${colorClass}`}
                      >
                        <Icon className="size-5" />
                      </div>
                      <div>
                        <CardTitle className="text-base">
                          {integration.display_name}
                        </CardTitle>
                        <CardDescription>
                          {integration.description}
                        </CardDescription>
                      </div>
                    </div>
                    {integration.is_connected ? (
                      <Badge className="bg-success/10 text-success border-success/20">
                        Connected
                      </Badge>
                    ) : (
                      <Badge variant="outline">Not Connected</Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">
                    {integration.is_connected
                      ? `${integration.display_name} is connected and ready to use.`
                      : `Connect ${integration.display_name} to enable this integration.`}
                  </p>
                </CardContent>
                <CardFooter>
                  {integration.is_connected ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        handleConfigureIntegration(
                          integration.integration_type as IntegrationType
                        )
                      }
                    >
                      Configure
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() =>
                        handleConfigureIntegration(
                          integration.integration_type as IntegrationType
                        )
                      }
                    >
                      Connect
                    </Button>
                  )}
                </CardFooter>
              </Card>
            );
          })
        )}
      </div>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="size-5" />
            API Keys
          </CardTitle>
          <CardDescription>
            Manage API keys for programmatic access
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between p-3 rounded-lg border">
            <div>
              <p className="font-medium">Production Key</p>
              <p className="text-sm text-muted-foreground font-mono">
                sk_live_****************************1234
              </p>
            </div>
            <Button variant="outline" size="sm">
              Reveal
            </Button>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg border">
            <div>
              <p className="font-medium">Test Key</p>
              <p className="text-sm text-muted-foreground font-mono">
                sk_test_****************************5678
              </p>
            </div>
            <Button variant="outline" size="sm">
              Reveal
            </Button>
          </div>
        </CardContent>
        <CardFooter>
          <Button variant="outline">Generate New Key</Button>
        </CardFooter>
      </Card>

      {/* Integration Config Dialog */}
      {selectedIntegration && (
        <IntegrationConfigDialog
          open={integrationDialogOpen}
          onOpenChange={setIntegrationDialogOpen}
          integrationType={selectedIntegration}
          existingIntegration={getExistingIntegration(selectedIntegration)}
        />
      )}
    </div>
  );
}
