"use client";

import {
  ArrowLeft,
  MessageSquare,
  Mail,
  Phone,
  Layers,
  Save,
  Play,
  Clock,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import type { CampaignType } from "@/types";

const campaignTypes: { value: CampaignType; label: string; icon: LucideIcon; description: string }[] = [
  {
    value: "sms",
    label: "SMS",
    icon: MessageSquare,
    description: "Send text messages to your contacts",
  },
  {
    value: "email",
    label: "Email",
    icon: Mail,
    description: "Send email campaigns to your contacts",
  },
  {
    value: "voice",
    label: "Voice",
    icon: Phone,
    description: "AI-powered voice calls to contacts",
  },
  {
    value: "multi_channel",
    label: "Multi-Channel",
    icon: Layers,
    description: "Combine SMS, email, and voice",
  },
];

interface CampaignFormProps {
  campaignId?: string;
}

export function CampaignForm({ campaignId }: CampaignFormProps) {
  const router = useRouter();
  const isEditing = !!campaignId;

  const [campaignType, setCampaignType] = useState<CampaignType>("sms");
  const [enableSchedule, setEnableSchedule] = useState(false);

  const handleSave = () => {
    // Redirect to appropriate wizard based on campaign type
    if (campaignType === "sms") {
      router.push("/campaigns/sms/new");
    } else if (campaignType === "voice") {
      router.push("/campaigns/voice/new");
    } else if (campaignType === "email") {
      router.push("/campaigns/email/new");
    } else {
      // multi_channel is not yet available; return to the list.
      router.push("/campaigns");
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/campaigns" aria-label="Back to campaigns">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {isEditing ? "Edit Campaign" : "Create Campaign"}
          </h1>
          <p className="text-muted-foreground">
            {isEditing
              ? "Modify your campaign settings"
              : "Set up a new outreach campaign"}
          </p>
        </div>
      </div>

      {/* Campaign Type Selection */}
      <Card>
        <CardHeader>
          <CardTitle>Campaign Type</CardTitle>
          <CardDescription>
            Choose how you want to reach your contacts
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {campaignTypes.map((type) => {
              const Icon = type.icon;
              const isSelected = campaignType === type.value;

              return (
                <motion.button
                  key={type.value}
                  onClick={() => setCampaignType(type.value)}
                  className={`relative p-4 rounded-lg border-2 text-left transition-colors ${
                    isSelected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50"
                  }`}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                >
                  <Icon
                    className={`size-6 mb-2 ${
                      isSelected ? "text-primary" : "text-muted-foreground"
                    }`}
                  />
                  <div className="font-medium">{type.label}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {type.description}
                  </div>
                </motion.button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Basic Info */}
      <Card>
        <CardHeader>
          <CardTitle>Basic Information</CardTitle>
          <CardDescription>
            Name and describe your campaign
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Campaign Name</Label>
            <Input
              id="name"
              placeholder="e.g., Spring Property Showcase"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              placeholder="Describe the purpose of this campaign..."
              rows={3}
            />
          </div>
        </CardContent>
      </Card>

      {/* Message Templates */}
      <Card>
        <CardHeader>
          <CardTitle>Message Content</CardTitle>
          <CardDescription>
            Create your message templates. Use {"{{variable}}"} for personalization.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="sms" className="w-full">
            <TabsList className="mb-4">
              {(campaignType === "sms" || campaignType === "multi_channel") && (
                <TabsTrigger value="sms">
                  <MessageSquare className="size-4 mr-2" />
                  SMS
                </TabsTrigger>
              )}
              {(campaignType === "email" || campaignType === "multi_channel") && (
                <TabsTrigger value="email">
                  <Mail className="size-4 mr-2" />
                  Email
                </TabsTrigger>
              )}
              {(campaignType === "voice" || campaignType === "multi_channel") && (
                <TabsTrigger value="voice">
                  <Phone className="size-4 mr-2" />
                  Voice
                </TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="sms" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="sms-template">SMS Message</Label>
                <Textarea
                  id="sms-template"
                  placeholder="Hi {{first_name}}, check out our new listings!"
                  rows={4}
                />
                <p className="text-xs text-muted-foreground">
                  Available variables: {"{{first_name}}"}, {"{{last_name}}"}, {"{{company_name}}"}
                </p>
              </div>
            </TabsContent>

            <TabsContent value="email" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email-subject">Email Subject</Label>
                <Input
                  id="email-subject"
                  placeholder="Exclusive Offer for {{first_name}}"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email-template">Email Body</Label>
                <Textarea
                  id="email-template"
                  placeholder="<p>Dear {{first_name}},</p><p>We have exciting news...</p>"
                  rows={8}
                />
              </div>
            </TabsContent>

            <TabsContent value="voice" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="voice-agent">AI Agent</Label>
                <Select>
                  <SelectTrigger>
                    <SelectValue placeholder="Select an AI agent" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="agent-1">Sarah - Sales Agent</SelectItem>
                    <SelectItem value="agent-2">Mike - Support Agent</SelectItem>
                    <SelectItem value="agent-3">Emma - Scheduler</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="voice-script">Voice Script</Label>
                <Textarea
                  id="voice-script"
                  placeholder="Hello {{first_name}}, I'm calling from..."
                  rows={6}
                />
                <p className="text-xs text-muted-foreground">
                  This script guides the AI agent during the call
                </p>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Scheduling */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Scheduling</CardTitle>
              <CardDescription>
                Configure when to run this campaign
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Label htmlFor="enable-schedule">Enable Scheduling</Label>
              <Switch
                id="enable-schedule"
                checked={enableSchedule}
                onCheckedChange={setEnableSchedule}
              />
            </div>
          </div>
        </CardHeader>
        {enableSchedule && (
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="start-date">Start Date & Time</Label>
                <Input id="start-date" type="datetime-local" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="end-date">End Date & Time (Optional)</Label>
                <Input id="end-date" type="datetime-local" />
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      {/* Rate Limiting */}
      <Card>
        <CardHeader>
          <CardTitle>Rate Limiting</CardTitle>
          <CardDescription>
            Control the pace of your outreach
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="messages-per-hour">Messages per Hour</Label>
              <Input
                id="messages-per-hour"
                type="number"
                placeholder="200"
                defaultValue={200}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="max-retries">Max Retries</Label>
              <Input
                id="max-retries"
                type="number"
                placeholder="3"
                defaultValue={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="retry-delay">Retry Delay (minutes)</Label>
              <Input
                id="retry-delay"
                type="number"
                placeholder="60"
                defaultValue={60}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Actions */}
      <div className="flex items-center justify-end gap-4">
        <Button variant="outline" asChild>
          <Link href="/campaigns">Cancel</Link>
        </Button>
        <Button variant="outline" onClick={handleSave}>
          <Save className="mr-2 size-4" />
          Save as Draft
        </Button>
        {enableSchedule ? (
          <Button onClick={handleSave}>
            <Clock className="mr-2 size-4" />
            Schedule Campaign
          </Button>
        ) : (
          <Button onClick={handleSave}>
            <Play className="mr-2 size-4" />
            Start Campaign
          </Button>
        )}
      </div>
    </div>
  );
}
