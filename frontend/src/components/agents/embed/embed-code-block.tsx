"use client";

/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- Installation code is a named horizontal scroll region. */

import { Check, Copy, ExternalLink, Link2, LockKeyhole } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { getModePath, type EmbedFormValues } from "./embed-types";
import { QRCode } from "./qr-code";

interface EmbedCodeBlockProps {
  values: EmbedFormValues;
  baseUrl: string;
  publicId: string;
  canCopySnippets: boolean;
  blockedReason: string;
}

/**
 * Renders a single copy-to-clipboard code snippet block.
 */
function CodeSnippet({
  code,
  tabId,
  copiedTab,
  setCopiedTab,
}: {
  code: string;
  tabId: string;
  copiedTab: string | null;
  setCopiedTab: (id: string | null) => void;
}) {
  const handleCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopiedTab(tabId);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopiedTab(null), 2000);
  };

  return (
    <div className="relative">
      <pre
        tabIndex={0}
        role="region"
        aria-label={`${tabId.replaceAll("-", " ")} installation code`}
        className="overflow-x-auto rounded-lg bg-muted p-4 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {code}
      </pre>
      <Button
        size="icon"
        variant="ghost"
        className="absolute right-2 top-2 h-8 w-8"
        onClick={handleCopy}
        aria-label="Copy code"
      >
        {copiedTab === tabId ? (
          <Check className="h-4 w-4 text-success" />
        ) : (
          <Copy className="h-4 w-4" />
        )}
      </Button>
    </div>
  );
}

/**
 * The tabbed code-snippet panel + share-link block for the embed dialog.
 * All snippets are derived from `values` + `baseUrl` + `publicId`.
 */
export function EmbedCodeBlock({
  values,
  baseUrl,
  publicId,
  canCopySnippets,
  blockedReason,
}: EmbedCodeBlockProps) {
  const [copiedTab, setCopiedTab] = useState<string | null>(null);

  const modePath = useMemo(
    () => getModePath(values.display, values.mode),
    [values.display, values.mode],
  );

  const loaderSnippet = useMemo(
    () =>
      `<script src="${baseUrl}/widget/v1/loader.js" data-agent-id="${publicId}" defer></script>`,
    [baseUrl, publicId],
  );

  const scriptCode = useMemo(() => {
    const displayAttr = values.display !== "floating" ? ` display="${values.display}"` : "";
    return `<script src="${baseUrl}/widget/v1/widget.js" defer></script>\n<ai-agent agent-id="${publicId}" mode="${values.mode}"${displayAttr}></ai-agent>`;
  }, [baseUrl, publicId, values.mode, values.display]);

  const reactCode = useMemo(() => {
    const iframeModePath = modePath ? `/${modePath}` : "";
    return `export function AIAgent() {
  return (
    <iframe
      src="${baseUrl}/embed/${publicId}${iframeModePath}?theme=${values.theme}"
      width="100%"
      height="600"
      allow="microphone"
      style={{ border: 'none', borderRadius: '16px' }}
    />
  );
}`;
  }, [baseUrl, publicId, modePath, values.theme]);

  const iframeCode = useMemo(() => {
    const iframeModePath = modePath ? `/${modePath}` : "";
    const isFullpage = values.display === "fullpage";
    const width = isFullpage ? "100%" : "400";
    const height = isFullpage ? "100%" : "600";
    return `<iframe
  src="${baseUrl}/embed/${publicId}${iframeModePath}?theme=${values.theme}"
  width="${width}"
  height="${height}"
  allow="microphone"
  style="border: none; border-radius: 16px;"
></iframe>`;
  }, [baseUrl, publicId, modePath, values.theme, values.display]);

  const shareLink = `${baseUrl}/embed/${publicId}/fullpage?theme=${values.theme}`;

  if (!canCopySnippets) {
    return (
      <Alert className="border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
        <LockKeyhole className="h-4 w-4" />
        <AlertTitle>Installation code locked until your domain is saved</AlertTitle>
        <AlertDescription className="space-y-2">
          <p>{blockedReason}</p>
          <p>
            Add the domain where this widget will run, then save changes. Until the saved allowlist
            includes that domain, backend embed requests will be blocked.
          </p>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <Tabs defaultValue="quickstart" className="w-full">
        <TabsList className="flex w-full overflow-x-auto">
          <TabsTrigger value="quickstart" className="text-xs">
            Quick Start
          </TabsTrigger>
          <TabsTrigger value="htmljs" className="text-xs">
            HTML / JS
          </TabsTrigger>
          <TabsTrigger value="react" className="text-xs">
            React
          </TabsTrigger>
          <TabsTrigger value="wordpress" className="text-xs">
            WordPress
          </TabsTrigger>
          <TabsTrigger value="shopify" className="text-xs">
            Shopify
          </TabsTrigger>
          <TabsTrigger value="webflow" className="text-xs">
            Webflow
          </TabsTrigger>
          <TabsTrigger value="iframe" className="text-xs">
            iframe
          </TabsTrigger>
        </TabsList>

        <TabsContent value="quickstart" className="space-y-2">
          <CodeSnippet
            code={loaderSnippet}
            tabId="quickstart"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
          <p className="text-xs text-muted-foreground">
            Add this single line before {`</body>`}. That&apos;s it — settings are auto-loaded.
          </p>
        </TabsContent>

        <TabsContent value="htmljs" className="space-y-2">
          <CodeSnippet
            code={scriptCode}
            tabId="htmljs"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
          <p className="text-xs text-muted-foreground">
            Add this code before the closing {`</body>`} tag of your website.
          </p>
        </TabsContent>

        <TabsContent value="react" className="space-y-2">
          <CodeSnippet
            code={reactCode}
            tabId="react"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
          <p className="text-xs text-muted-foreground">
            Drop this component anywhere in your React app.
          </p>
        </TabsContent>

        <TabsContent value="wordpress" className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Go to <strong>Appearance → Widgets → Custom HTML</strong> (or your theme&apos;s footer).
            Paste this code:
          </p>
          <CodeSnippet
            code={loaderSnippet}
            tabId="wordpress"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
        </TabsContent>

        <TabsContent value="shopify" className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Go to <strong>Online Store → Themes → Edit Code → theme.liquid</strong>. Paste before{" "}
            {`</body>`}:
          </p>
          <CodeSnippet
            code={loaderSnippet}
            tabId="shopify"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
        </TabsContent>

        <TabsContent value="webflow" className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Go to <strong>Project Settings → Custom Code → Footer Code</strong>. Paste:
          </p>
          <CodeSnippet
            code={loaderSnippet}
            tabId="webflow"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
        </TabsContent>

        <TabsContent value="iframe" className="space-y-2">
          <CodeSnippet
            code={iframeCode}
            tabId="iframe"
            copiedTab={copiedTab}
            setCopiedTab={setCopiedTab}
          />
          <p className="text-xs text-muted-foreground">
            Use this iframe to embed the agent directly on your page.
          </p>
        </TabsContent>
      </Tabs>

      {publicId && (
        <div className="space-y-3 rounded-lg border p-4">
          <div className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-muted-foreground" />
            <Label htmlFor="agent-embed-share-link" className="text-sm font-medium">
              Share Link
            </Label>
          </div>
          <p className="text-xs text-muted-foreground">
            Share this direct link — no embedding required.
          </p>
          <div className="flex items-center gap-2">
            <Input
              id="agent-embed-share-link"
              readOnly
              value={shareLink}
              className="flex-1 font-mono text-xs"
            />
            <Button
              size="icon"
              variant="outline"
              onClick={() => {
                void navigator.clipboard.writeText(shareLink);
                setCopiedTab("sharelink");
                toast.success("Copied to clipboard");
                setTimeout(() => setCopiedTab(null), 2000);
              }}
              aria-label="Copy share link"
            >
              {copiedTab === "sharelink" ? (
                <Check className="h-4 w-4 text-success" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </Button>
            <Button size="icon" variant="outline" asChild>
              <a
                href={shareLink}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open share link in new tab"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            </Button>
          </div>
          <QRCode value={shareLink} />
        </div>
      )}
    </div>
  );
}
