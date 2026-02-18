import { useState } from 'react'
import { toast } from 'sonner'
import {
  Megaphone, FileText, Palette, Calendar, BarChart3,
  Plus, CheckCircle, XCircle, Clock, Eye, TrendingUp,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import StatCard from '@/components/shared/stat-card'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import {
  useCampaigns, useMarketingContent, useBrandProfiles,
  useApprovalQueue, useMarketingAnalytics, useMarketingCalendar,
  useCreateCampaign, useUpdateCampaign,
  useCreateContent, useApproveContent, useRejectContent,
  useCreateBrandProfile, useDeleteBrandProfile,
} from '@/hooks/use-admin-api'
import type { MarketingCampaign, ContentItem, BrandProfile } from '@/types/api'
import { cn } from '@/lib/utils'

// ── Status helpers ──

const campaignStatusColor: Record<string, string> = {
  planning: 'bg-blue-500/15 text-blue-500 border-blue-500/20',
  active: 'bg-success/15 text-success border-success/20',
  paused: 'bg-warning/15 text-warning border-warning/20',
  completed: 'bg-muted text-muted-foreground border-border',
  cancelled: 'bg-destructive/15 text-destructive border-destructive/20',
}

const contentStatusColor: Record<string, string> = {
  draft: 'bg-muted text-muted-foreground border-border',
  review: 'bg-warning/15 text-warning border-warning/20',
  approved: 'bg-blue-500/15 text-blue-500 border-blue-500/20',
  scheduled: 'bg-purple-500/15 text-purple-500 border-purple-500/20',
  published: 'bg-success/15 text-success border-success/20',
  failed: 'bg-destructive/15 text-destructive border-destructive/20',
  archived: 'bg-muted text-muted-foreground border-border',
}

function MarketingBadge({ status, colors }: { status: string; colors: Record<string, string> }) {
  const style = colors[status] || 'bg-muted text-muted-foreground border-border'
  return (
    <Badge variant="outline" className={cn('font-mono text-[10px] font-semibold capitalize', style)}>
      {status}
    </Badge>
  )
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
    })
  } catch { return dateStr }
}

function formatCurrency(val: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val)
}

// ── Campaigns Tab ──

function CampaignsTab() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const { data, isLoading } = useCampaigns(statusFilter || undefined)
  const [showCreate, setShowCreate] = useState(false)
  const [newCampaign, setNewCampaign] = useState({ name: '', campaign_type: 'multi_channel', budget_usd: '', strategy: '' })
  const createCampaign = useCreateCampaign()
  const updateCampaign = useUpdateCampaign()

  const campaigns = data?.campaigns || []

  const handleCreate = () => {
    if (!newCampaign.name) { toast.error('Campaign name is required'); return }
    createCampaign.mutate({
      name: newCampaign.name,
      campaign_type: newCampaign.campaign_type,
      budget_usd: parseFloat(newCampaign.budget_usd) || 0,
      strategy: newCampaign.strategy,
    }, {
      onSuccess: () => {
        toast.success('Campaign created')
        setShowCreate(false)
        setNewCampaign({ name: '', campaign_type: 'multi_channel', budget_usd: '', strategy: '' })
      },
      onError: (err) => toast.error(err.message),
    })
  }

  const handleStatusChange = (campaign: MarketingCampaign, newStatus: string) => {
    updateCampaign.mutate({ id: campaign.id, data: { status: newStatus } }, {
      onSuccess: () => toast.success(`Campaign ${newStatus}`),
      onError: (err) => toast.error(err.message),
    })
  }

  if (isLoading) return <CardSkeleton />

  const activeCampaigns = campaigns.filter(c => c.status === 'active').length
  const totalBudget = campaigns.reduce((sum, c) => sum + (c.budget_usd || 0), 0)
  const totalSpent = campaigns.reduce((sum, c) => sum + (c.spent_usd || 0), 0)

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Total Campaigns" value={campaigns.length} />
        <StatCard label="Active" value={activeCampaigns} sub="currently running" />
        <StatCard label="Total Budget" value={formatCurrency(totalBudget)} />
        <StatCard label="Total Spent" value={formatCurrency(totalSpent)} sub={totalBudget > 0 ? `${((totalSpent / totalBudget) * 100).toFixed(0)}% utilized` : ''} />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {['', 'planning', 'active', 'paused', 'completed'].map(s => (
            <Button
              key={s}
              variant={statusFilter === s ? 'default' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter(s)}
              className="text-xs"
            >
              {s || 'All'}
            </Button>
          ))}
        </div>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" /> New Campaign
        </Button>
      </div>

      {/* Campaign Cards */}
      {campaigns.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Megaphone className="mb-3 h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No campaigns yet</p>
            <Button size="sm" variant="outline" className="mt-3" onClick={() => setShowCreate(true)}>
              Create your first campaign
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {campaigns.map(campaign => (
            <CampaignCard
              key={campaign.id}
              campaign={campaign}
              onStatusChange={handleStatusChange}
            />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Campaign</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground">Name</label>
              <Input
                value={newCampaign.name}
                onChange={e => setNewCampaign(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Spring Coffee Launch"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Type</label>
              <Select
                value={newCampaign.campaign_type}
                onValueChange={v => setNewCampaign(prev => ({ ...prev, campaign_type: v }))}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="social">Social</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                  <SelectItem value="ads">Ads</SelectItem>
                  <SelectItem value="seo">SEO</SelectItem>
                  <SelectItem value="multi_channel">Multi-Channel</SelectItem>
                  <SelectItem value="promotion">Promotion</SelectItem>
                  <SelectItem value="launch">Launch</SelectItem>
                  <SelectItem value="seasonal">Seasonal</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Budget (USD)</label>
              <Input
                type="number"
                value={newCampaign.budget_usd}
                onChange={e => setNewCampaign(prev => ({ ...prev, budget_usd: e.target.value }))}
                placeholder="500.00"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Strategy</label>
              <Textarea
                value={newCampaign.strategy}
                onChange={e => setNewCampaign(prev => ({ ...prev, strategy: e.target.value }))}
                placeholder="Focus on Instagram and email..."
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={createCampaign.isPending}>
              {createCampaign.isPending ? 'Creating...' : 'Create Campaign'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function CampaignCard({
  campaign,
  onStatusChange,
}: {
  campaign: MarketingCampaign
  onStatusChange: (c: MarketingCampaign, s: string) => void
}) {
  const utilization = campaign.budget_usd > 0
    ? Math.min(100, (campaign.spent_usd / campaign.budget_usd) * 100)
    : 0

  return (
    <Card className="border-border">
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-sm font-semibold">{campaign.name}</h3>
              <MarketingBadge status={campaign.status} colors={campaignStatusColor} />
            </div>
            <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground">
              <span className="capitalize">{campaign.campaign_type.replace('_', ' ')}</span>
              {campaign.start_date && (
                <span>{formatDate(campaign.start_date)} — {formatDate(campaign.end_date)}</span>
              )}
            </div>
          </div>
        </div>

        {/* Budget bar */}
        {campaign.budget_usd > 0 && (
          <div className="mt-3">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>{formatCurrency(campaign.spent_usd)} spent</span>
              <span>{formatCurrency(campaign.budget_usd)} budget</span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  utilization >= 90 ? 'bg-destructive' : utilization >= 70 ? 'bg-warning' : 'bg-primary'
                )}
                style={{ width: `${utilization}%` }}
              />
            </div>
          </div>
        )}

        {campaign.strategy && (
          <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">{campaign.strategy}</p>
        )}

        {/* Actions */}
        <div className="mt-3 flex gap-1.5">
          {campaign.status === 'planning' && (
            <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => onStatusChange(campaign, 'active')}>
              <TrendingUp className="mr-1 h-3 w-3" /> Activate
            </Button>
          )}
          {campaign.status === 'active' && (
            <>
              <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => onStatusChange(campaign, 'paused')}>
                Pause
              </Button>
              <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => onStatusChange(campaign, 'completed')}>
                Complete
              </Button>
            </>
          )}
          {campaign.status === 'paused' && (
            <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => onStatusChange(campaign, 'active')}>
              Resume
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ── Content Tab ──

function ContentTab() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const { data, isLoading } = useMarketingContent(undefined, statusFilter || undefined)
  const { data: queueData } = useApprovalQueue()
  const approveContent = useApproveContent()
  const rejectContent = useRejectContent()
  const [showCreate, setShowCreate] = useState(false)
  const [newContent, setNewContent] = useState({ title: '', content_type: 'social_post', platform: 'instagram', body: '' })
  const createContent = useCreateContent()

  const items = data?.items || []
  const queueCount = queueData?.total || 0

  const handleApprove = (id: string) => {
    approveContent.mutate(id, {
      onSuccess: () => toast.success('Content approved'),
      onError: (err) => toast.error(err.message),
    })
  }

  const handleReject = (id: string) => {
    rejectContent.mutate(id, {
      onSuccess: () => toast.success('Content rejected — moved back to draft'),
      onError: (err) => toast.error(err.message),
    })
  }

  const handleCreate = () => {
    if (!newContent.title) { toast.error('Title is required'); return }
    createContent.mutate({
      title: newContent.title,
      content_type: newContent.content_type,
      platform: newContent.platform,
      body: newContent.body,
    }, {
      onSuccess: () => {
        toast.success('Content created as draft')
        setShowCreate(false)
        setNewContent({ title: '', content_type: 'social_post', platform: 'instagram', body: '' })
      },
      onError: (err) => toast.error(err.message),
    })
  }

  if (isLoading) return <CardSkeleton />

  const byStatus = items.reduce<Record<string, number>>((acc, i) => {
    acc[i.status] = (acc[i.status] || 0) + 1; return acc
  }, {})

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label="Total Items" value={items.length} />
        <StatCard label="Drafts" value={byStatus.draft || 0} />
        <StatCard label="In Review" value={queueCount} sub={queueCount > 0 ? 'awaiting approval' : ''} />
        <StatCard label="Scheduled" value={byStatus.scheduled || 0} />
        <StatCard label="Published" value={byStatus.published || 0} />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap gap-2">
          {['', 'draft', 'review', 'approved', 'scheduled', 'published', 'failed'].map(s => (
            <Button
              key={s}
              variant={statusFilter === s ? 'default' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter(s)}
              className="text-xs"
            >
              {s || 'All'}
            </Button>
          ))}
        </div>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" /> New Content
        </Button>
      </div>

      {/* Content list */}
      {items.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FileText className="mb-3 h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No content items</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map(item => (
            <ContentItemCard
              key={item.id}
              item={item}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Content</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground">Title</label>
              <Input
                value={newContent.title}
                onChange={e => setNewContent(prev => ({ ...prev, title: e.target.value }))}
                placeholder="Spring Coffee Launch Post"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">Type</label>
                <Select
                  value={newContent.content_type}
                  onValueChange={v => setNewContent(prev => ({ ...prev, content_type: v }))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="social_post">Social Post</SelectItem>
                    <SelectItem value="email">Email</SelectItem>
                    <SelectItem value="ad_copy">Ad Copy</SelectItem>
                    <SelectItem value="blog_post">Blog Post</SelectItem>
                    <SelectItem value="newsletter">Newsletter</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">Platform</label>
                <Select
                  value={newContent.platform}
                  onValueChange={v => setNewContent(prev => ({ ...prev, platform: v }))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="instagram">Instagram</SelectItem>
                    <SelectItem value="facebook">Facebook</SelectItem>
                    <SelectItem value="twitter">Twitter/X</SelectItem>
                    <SelectItem value="linkedin">LinkedIn</SelectItem>
                    <SelectItem value="email">Email</SelectItem>
                    <SelectItem value="tiktok">TikTok</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Body</label>
              <Textarea
                value={newContent.body}
                onChange={e => setNewContent(prev => ({ ...prev, body: e.target.value }))}
                placeholder="Write your content here..."
                rows={5}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={createContent.isPending}>
              {createContent.isPending ? 'Creating...' : 'Create Draft'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ContentItemCard({
  item,
  onApprove,
  onReject,
}: {
  item: ContentItem
  onApprove: (id: string) => void
  onReject: (id: string) => void
}) {
  const platformIcons: Record<string, string> = {
    instagram: 'IG', facebook: 'FB', twitter: 'X', linkedin: 'LI',
    email: 'EM', tiktok: 'TT',
  }

  return (
    <Card className="border-border">
      <CardContent className="flex items-center gap-4 p-3">
        {/* Platform badge */}
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-muted text-[10px] font-bold text-muted-foreground">
          {platformIcons[item.platform] || item.platform.slice(0, 2).toUpperCase()}
        </div>

        {/* Content info */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{item.title || 'Untitled'}</span>
            <MarketingBadge status={item.status} colors={contentStatusColor} />
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted-foreground">
            <span className="capitalize">{item.content_type.replace('_', ' ')}</span>
            <span className="capitalize">{item.platform}</span>
            {item.scheduled_at && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatDate(item.scheduled_at)}
              </span>
            )}
            {item.created_by && <span>by {item.created_by}</span>}
          </div>
          {item.body && (
            <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground/70">{item.body}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-shrink-0 gap-1.5">
          {item.status === 'review' && (
            <>
              <Button size="sm" variant="outline" className="h-7 text-[11px] text-success hover:text-success" onClick={() => onApprove(item.id)}>
                <CheckCircle className="mr-1 h-3 w-3" /> Approve
              </Button>
              <Button size="sm" variant="outline" className="h-7 text-[11px] text-destructive hover:text-destructive" onClick={() => onReject(item.id)}>
                <XCircle className="mr-1 h-3 w-3" /> Reject
              </Button>
            </>
          )}
          {item.status === 'published' && item.external_id && (
            <Button size="sm" variant="ghost" className="h-7 text-[11px]">
              <Eye className="mr-1 h-3 w-3" /> View
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ── Brand Profiles Tab ──

function BrandProfilesTab() {
  const { data, isLoading } = useBrandProfiles()
  const [showCreate, setShowCreate] = useState(false)
  const [newProfile, setNewProfile] = useState({ name: '', tone: '', preferred: '', banned: '' })
  const createProfile = useCreateBrandProfile()
  const deleteProfile = useDeleteBrandProfile()

  const profiles = data?.profiles || []

  const handleCreate = () => {
    if (!newProfile.name) { toast.error('Profile name is required'); return }
    createProfile.mutate({
      name: newProfile.name,
      tone: newProfile.tone,
      vocabulary_rules: {
        preferred: newProfile.preferred ? newProfile.preferred.split(',').map(s => s.trim()) : [],
        banned: newProfile.banned ? newProfile.banned.split(',').map(s => s.trim()) : [],
      },
      is_default: profiles.length === 0,
    }, {
      onSuccess: () => {
        toast.success('Brand profile created')
        setShowCreate(false)
        setNewProfile({ name: '', tone: '', preferred: '', banned: '' })
      },
      onError: (err) => toast.error(err.message),
    })
  }

  const handleDelete = (id: number) => {
    deleteProfile.mutate(id, {
      onSuccess: () => toast.success('Brand profile deleted'),
      onError: (err) => toast.error(err.message),
    })
  }

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Brand voice profiles guide AI content generation with consistent tone and vocabulary.
        </p>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" /> New Profile
        </Button>
      </div>

      {profiles.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Palette className="mb-3 h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No brand profiles</p>
            <Button size="sm" variant="outline" className="mt-3" onClick={() => setShowCreate(true)}>
              Create your first brand profile
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {profiles.map(profile => (
            <BrandProfileCard key={profile.id} profile={profile} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Brand Profile</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground">Name</label>
              <Input
                value={newProfile.name}
                onChange={e => setNewProfile(prev => ({ ...prev, name: e.target.value }))}
                placeholder="My Cafe Brand"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Tone</label>
              <Textarea
                value={newProfile.tone}
                onChange={e => setNewProfile(prev => ({ ...prev, tone: e.target.value }))}
                placeholder="Warm, friendly, knowledgeable about coffee..."
                rows={2}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Preferred Words (comma-separated)</label>
              <Input
                value={newProfile.preferred}
                onChange={e => setNewProfile(prev => ({ ...prev, preferred: e.target.value }))}
                placeholder="artisan, handcrafted, premium"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Banned Words (comma-separated)</label>
              <Input
                value={newProfile.banned}
                onChange={e => setNewProfile(prev => ({ ...prev, banned: e.target.value }))}
                placeholder="cheap, basic, ordinary"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={createProfile.isPending}>
              {createProfile.isPending ? 'Creating...' : 'Create Profile'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function BrandProfileCard({ profile, onDelete }: { profile: BrandProfile; onDelete: (id: number) => void }) {
  const preferred = profile.vocabulary_rules?.preferred || []
  const banned = profile.vocabulary_rules?.banned || []

  return (
    <Card className="border-border">
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold">{profile.name}</h3>
              {profile.is_default && (
                <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20 text-[10px]">Default</Badge>
              )}
            </div>
            {profile.tone && (
              <p className="mt-1 text-[11px] text-muted-foreground">{profile.tone}</p>
            )}
          </div>
          <Button size="sm" variant="ghost" className="h-7 text-[11px] text-destructive hover:text-destructive" onClick={() => onDelete(profile.id)}>
            Delete
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {preferred.map(word => (
            <Badge key={word} variant="outline" className="bg-success/10 text-success border-success/20 text-[10px]">
              +{word}
            </Badge>
          ))}
          {banned.map(word => (
            <Badge key={word} variant="outline" className="bg-destructive/10 text-destructive border-destructive/20 text-[10px]">
              -{word}
            </Badge>
          ))}
        </div>

        {Object.keys(profile.platform_guidelines || {}).length > 0 && (
          <div className="mt-2 text-[10px] text-muted-foreground">
            Platform guides: {Object.keys(profile.platform_guidelines).join(', ')}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Calendar Tab ──

function CalendarTab() {
  const { data, isLoading } = useMarketingCalendar()
  const events = data?.events || []

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Scheduled content and campaign milestones.
        </p>
      </div>

      {events.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Calendar className="mb-3 h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No upcoming events</p>
            <p className="mt-1 text-xs text-muted-foreground/60">Schedule content to see events here</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {events.map((event, idx) => (
            <Card key={event.id || idx} className="border-border">
              <CardContent className="flex items-center gap-4 p-3">
                <div className="flex h-10 w-10 flex-shrink-0 flex-col items-center justify-center rounded-md bg-primary/10">
                  <span className="text-[10px] font-bold text-primary">
                    {event.scheduled_at ? new Date(event.scheduled_at).toLocaleDateString('en-US', { month: 'short' }) : ''}
                  </span>
                  <span className="text-sm font-bold text-primary">
                    {event.scheduled_at ? new Date(event.scheduled_at).getDate() : ''}
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-medium">{event.title}</span>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <Badge variant="outline" className="text-[9px] capitalize">{event.event_type}</Badge>
                    {event.scheduled_at && (
                      <span>
                        {new Date(event.scheduled_at).toLocaleTimeString('en-US', {
                          hour: 'numeric', minute: '2-digit',
                        })}
                      </span>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Analytics Tab ──

function AnalyticsTab() {
  const [source, setSource] = useState<string>('')
  const [days, setDays] = useState(30)
  const { data, isLoading } = useMarketingAnalytics(source || undefined, days)

  if (isLoading) return <CardSkeleton />

  const metrics = data?.metrics || {}
  const hasMetrics = Object.keys(metrics).length > 0

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <div className="flex gap-2">
          {['', 'social', 'email', 'ads', 'seo'].map(s => (
            <Button
              key={s}
              variant={source === s ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSource(s)}
              className="text-xs"
            >
              {s || 'All Sources'}
            </Button>
          ))}
        </div>
        <Select value={String(days)} onValueChange={v => setDays(parseInt(v))}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="7">Last 7 days</SelectItem>
            <SelectItem value="14">Last 14 days</SelectItem>
            <SelectItem value="30">Last 30 days</SelectItem>
            <SelectItem value="90">Last 90 days</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {!hasMetrics ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <BarChart3 className="mb-3 h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No analytics data yet</p>
            <p className="mt-1 text-xs text-muted-foreground/60">
              Metrics will appear once content is published and tracked
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* Metric cards */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Object.entries(metrics).map(([key, value]) => (
              <StatCard
                key={key}
                label={key.replace(/_/g, ' ')}
                value={typeof value === 'number' ? value.toLocaleString() : String(value)}
              />
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Period Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                Showing {source || 'all sources'} for the last {days} days.
                {Object.keys(metrics).length} metrics tracked.
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

// ── Main Page ──

export default function MarketingPage() {
  const { data: campaignsData } = useCampaigns()
  const { data: contentData } = useMarketingContent()
  const { data: queueData } = useApprovalQueue()
  const { data: profilesData } = useBrandProfiles()

  const totalCampaigns = campaignsData?.total || 0
  const totalContent = contentData?.total || 0
  const pendingApproval = queueData?.total || 0
  const totalProfiles = profilesData?.total || 0

  return (
    <div className="space-y-6">
      {/* Overview Stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="Campaigns"
          value={totalCampaigns}
          sub="total campaigns"
        />
        <StatCard
          label="Content Items"
          value={totalContent}
          sub="across all campaigns"
        />
        <StatCard
          label="Pending Approval"
          value={
            <span className={pendingApproval > 0 ? 'text-warning' : ''}>
              {pendingApproval}
            </span>
          }
          sub={pendingApproval > 0 ? 'needs review' : 'queue clear'}
        />
        <StatCard
          label="Brand Profiles"
          value={totalProfiles}
          sub="voice profiles"
        />
      </div>

      {/* Tabs */}
      <Tabs defaultValue="campaigns" className="space-y-4">
        <TabsList>
          <TabsTrigger value="campaigns" className="gap-1.5">
            <Megaphone className="h-3.5 w-3.5" /> Campaigns
          </TabsTrigger>
          <TabsTrigger value="content" className="gap-1.5">
            <FileText className="h-3.5 w-3.5" /> Content
            {pendingApproval > 0 && (
              <Badge variant="destructive" className="ml-1 h-4 w-4 rounded-full p-0 text-[9px]">
                {pendingApproval}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="brand" className="gap-1.5">
            <Palette className="h-3.5 w-3.5" /> Brand
          </TabsTrigger>
          <TabsTrigger value="calendar" className="gap-1.5">
            <Calendar className="h-3.5 w-3.5" /> Calendar
          </TabsTrigger>
          <TabsTrigger value="analytics" className="gap-1.5">
            <BarChart3 className="h-3.5 w-3.5" /> Analytics
          </TabsTrigger>
        </TabsList>

        <TabsContent value="campaigns">
          <CampaignsTab />
        </TabsContent>

        <TabsContent value="content">
          <ContentTab />
        </TabsContent>

        <TabsContent value="brand">
          <BrandProfilesTab />
        </TabsContent>

        <TabsContent value="calendar">
          <CalendarTab />
        </TabsContent>

        <TabsContent value="analytics">
          <AnalyticsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
