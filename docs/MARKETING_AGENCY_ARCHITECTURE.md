# Nexus AI Marketing Agency — Deep Research & Architecture

## Full-Service AI Marketing Automation System

**Status:** Deep Research Complete (Feb 18, 2026)
**Target:** Feature Stream 3 of 3
**Narrative:** "Agency-in-a-Box" — Every marketing capability, one AI platform

> **Research Note:** This document was compiled primarily from training knowledge
> through early 2025. Items marked with `[VERIFY-2026]` should be confirmed against
> current API documentation, as pricing, rate limits, and feature availability may
> have changed. A follow-up session with web access enabled is recommended for
> spot-checking these items.

---

## Table of Contents

1. [Social Media APIs](#1-social-media-apis)
2. [Email Marketing APIs](#2-email-marketing-apis)
3. [Advertising Platform APIs](#3-advertising-platform-apis)
4. [SEO Tools & APIs](#4-seo-tools--apis)
5. [AI Marketing Agent Platforms (Competitors)](#5-ai-marketing-agent-platforms-competitors)
6. [Content Generation Best Practices](#6-content-generation-best-practices)
7. [Marketing Analytics & Attribution](#7-marketing-analytics--attribution)
8. [Recommended Architecture for Nexus](#8-recommended-architecture-for-nexus)
9. [Plugin Design](#9-plugin-design)
10. [Implementation Roadmap](#10-implementation-roadmap)

---

## 1. Social Media APIs

### 1.1 Twitter/X API

**Current State (as of 2025):**
Twitter/X has undergone massive API changes under Elon Musk's ownership. The API was
completely restructured in 2023-2024 with aggressive pricing tiers.

**Tiers & Pricing:**

| Tier | Price | Tweet Cap | Read Cap | Key Features |
|------|-------|-----------|----------|--------------|
| Free | $0/mo | 1,500 tweets/mo (app-level) | None (write-only) | Post tweets only, 1 App, no read |
| Basic | $100/mo | 3,000 tweets/mo (app-level) | 10,000 reads/mo | Login with X, 2 Apps |
| Pro | $5,000/mo | 300,000 tweets/mo | 1,000,000 reads/mo | Full search, filtered stream, 3 Apps |
| Enterprise | $42,000+/mo | Custom | Custom | Full firehose, compliance, ads API |

`[VERIFY-2026]` — X has changed pricing multiple times. Verify current tiers.

**API Capabilities (v2):**
- **POST tweets**: Yes, all paid tiers. Supports text, media, polls, threads, quote tweets
- **DELETE tweets**: Yes
- **Read tweets**: Basic+ only. Free tier is write-only
- **Search tweets**: Pro+ (full-archive search requires Pro or Enterprise)
- **User lookup**: Basic+
- **Followers/following**: Basic+
- **Likes, retweets, bookmarks**: Basic+
- **Direct messages**: Pro+
- **Spaces**: Enterprise
- **Analytics**: Pro+ (tweet engagement metrics, impression counts)
- **Media upload**: All tiers via chunked upload endpoint
- **Scheduling**: NOT native API — must implement client-side scheduling

**Rate Limits (v2):**
- POST tweet: 200 requests per 15 min per user (OAuth 2.0)
- GET tweet: 300 requests per 15 min per user
- Search: 300 requests per 15 min (Pro), 60 per 15 min (Basic)
- User lookup: 300 per 15 min

**Python Libraries:**
- `tweepy` (v4.x): Most mature, supports v2 API, OAuth 2.0 PKCE, async support
- `python-twitter-v2`: Lighter wrapper, type-hinted
- `twikit`: Unofficial scraping library (violates ToS, not recommended)
- **Recommendation:** `tweepy>=4.14.0` — best maintained, full v2 coverage

**What CAN Be Automated:**
- Posting tweets, threads, media
- Reading mentions and replies (Basic+)
- Engagement analytics (Pro+)
- Following/unfollowing (with rate limits)
- Searching for brand mentions

**What CANNOT Be Automated via API:**
- Twitter/X Ads management (separate Ads API, Enterprise only, `[VERIFY-2026]`)
- Twitter Spaces (hosting/management)
- Community management
- Profile customization beyond bio/avatar

**Authentication:**
- OAuth 2.0 with PKCE (user-level, recommended)
- OAuth 1.0a (app-level, legacy)
- Bearer token (app-only read access on Basic+)

**Cost Assessment for Nexus:**
- **Minimum viable**: Basic ($100/mo) for post+read
- **Full agency**: Pro ($5,000/mo) for analytics+search+DMs
- **Ads**: Enterprise ($42,000+/mo) — prohibitively expensive for most users
- **Recommendation**: Support Basic tier as default, Pro as premium feature

---

### 1.2 LinkedIn API

**API Programs:**
LinkedIn has a complex API access structure with different "products" requiring
separate application approval.

**API Products:**

| Product | Access Level | Approval | Key Capabilities |
|---------|-------------|----------|-----------------|
| Sign In with LinkedIn | Open | Auto-approved | OAuth login, basic profile |
| Share on LinkedIn | Open | Auto-approved | Post to authenticated user's feed |
| Community Management | Restricted | Application required | Company page posting, comments, reactions |
| Marketing Developer Platform | Restricted | Partner application | Campaign Manager API, ad management |
| Advertising API | Restricted | LinkedIn partner | Full ads management |
| LinkedIn Pages API | Restricted | Application required | Company page management, analytics |

**Posting Capabilities:**

*Personal Profile Posting:*
- **Share on LinkedIn** product: Post text, articles, images, videos
- **Posts API** (`/rest/posts`): Create, read, delete posts
- Supports: Text, images (up to 9), videos, articles, documents, carousels
- Rate limit: ~100 API calls per day per member for posting `[VERIFY-2026]`
- Character limit: 3,000 for organic posts

*Company Page Posting:*
- Requires **Community Management** product (restricted access)
- Same content types as personal posting
- Can post as organization (not as individual)
- Analytics: Follower stats, post engagement, page views
- Rate limit: 100 posts per day per organization `[VERIFY-2026]`

**Analytics Available via API:**
- Page follower demographics
- Post-level engagement (likes, comments, shares, impressions, clicks)
- Organization follower statistics
- Share statistics
- Visitor analytics (page views, unique visitors)

**Python Libraries:**
- `linkedin-api`: Unofficial, reverse-engineered (violates ToS)
- `python-linkedin-v2`: Minimal wrapper, not well maintained
- **Recommendation**: Direct `httpx` calls to LinkedIn REST API v2 — no good official
  Python SDK exists. Build a thin wrapper class.

**Authentication:**
- OAuth 2.0 three-legged (Authorization Code flow)
- Access tokens expire in 60 days (refresh tokens available)
- Scopes: `r_liteprofile`, `w_member_social`, `r_organization_social`, `w_organization_social`,
  `r_organization_admin`, `rw_organization_admin`

**What CAN Be Automated:**
- Personal feed posting (text, images, videos, carousels)
- Company page posting (with Community Management access)
- Reading post analytics and engagement
- Comment management on own posts
- Follower analytics

**What CANNOT Be Automated (or requires special access):**
- InMail sending (Sales Navigator API, separate product)
- LinkedIn Ads (Marketing Developer Platform, partner-only)
- Group management
- LinkedIn Events
- LinkedIn newsletters (manual only as of early 2025)
- Hashtag analytics (limited)

**Cost Assessment:**
- API access itself is free (no per-request charges)
- Restricted products require business justification + review (weeks to months)
- Ads API requires LinkedIn Marketing Partner status
- **Key blocker**: Community Management approval can take 2-8 weeks

---

### 1.3 Instagram Graph API (via Meta)

**Prerequisites:**
- Facebook Business account linked to Instagram Professional account
- Meta App with Instagram Graph API product added
- Facebook Page connected to Instagram account
- App Review for certain permissions

**Content Publishing API:**

| Content Type | Supported | Notes |
|-------------|-----------|-------|
| Single Image | Yes | JPEG, max 8MB |
| Carousel (multi-image) | Yes | 2-10 images |
| Reels (short video) | Yes | 3-90 sec, max 1GB, 9:16 aspect |
| Stories | **No** | Stories cannot be published via API |
| IGTV | Deprecated | Merged into Reels |
| Live | **No** | Cannot start/manage live via API |

**Publishing Flow (2-step):**
1. **Create container**: `POST /{ig-user-id}/media` with image_url/video_url + caption
2. **Publish container**: `POST /{ig-user-id}/media_publish` with creation_id

For videos/reels, there's an async upload step between 1 and 2 (poll status).

**Rate Limits:**
- Content Publishing: 25 posts per 24-hour period per Instagram account `[VERIFY-2026]`
- API calls: 200 calls per hour per user (Instagram Graph API)
- Varies by endpoint — some are 50/hour

**Analytics Available:**
- **Account-level**: Followers count, media count, profile views, reach, impressions
- **Media-level**: Likes, comments, saves, shares, reach, impressions, engagement, video views
- **Stories insights**: Available for existing stories (but can't publish stories)
- **Audience demographics**: Age, gender, location (min 100 followers)
- **Online followers**: When your followers are most active (hourly breakdown)

**Hashtag Search:**
- Up to 30 unique hashtags per 7-day period
- Top/recent media for a hashtag
- Rate limited heavily

**Python Libraries:**
- `facebook-sdk`: Official Meta SDK, Python 3 compatible
- `instagrapi`: Unofficial private API (higher risk, more features, but ToS violation)
- `instagram-private-api`: Another unofficial option
- **Recommendation**: `facebook-sdk` for Graph API (official, safe), with `httpx` for
  any endpoints not covered

**Authentication:**
- OAuth 2.0 via Facebook Login
- Page Access Tokens (long-lived, 60 days, can be made permanent)
- System User tokens for server-to-server (Business Manager)

**What CAN Be Automated:**
- Publishing images, carousels, reels
- Reading comments and replies
- Replying to comments
- Getting post/account analytics
- Hashtag research (limited)
- Tagging users and locations

**What CANNOT Be Automated:**
- Stories publishing (the most significant gap)
- Direct messages (limited API, `[VERIFY-2026]` — Meta has been expanding DM API)
- Live video
- Shopping/product tagging
- Profile editing
- Following/unfollowing

**Cost Assessment:**
- API access is free
- Requires Meta Business verification (government ID, business docs)
- App Review process for advanced permissions (1-5 business days)
- **No direct API costs**, but Meta Business Suite is required infrastructure

---

### 1.4 Facebook Graph API (Pages)

**Facebook Pages API is the most mature and feature-rich social API available.**

**Capabilities:**

| Feature | API Support | Endpoint |
|---------|------------|----------|
| Post to Page | Yes | `POST /{page-id}/feed` |
| Photo posts | Yes | `POST /{page-id}/photos` |
| Video posts | Yes | `POST /{page-id}/videos` |
| Reel posts | Yes | `POST /{page-id}/video_reels` |
| Stories | Limited | Business accounts only `[VERIFY-2026]` |
| Scheduled posts | Yes | `scheduled_publish_time` parameter |
| Page insights | Yes | `GET /{page-id}/insights` |
| Post insights | Yes | `GET /{post-id}/insights` |
| Comments | Yes | Read, reply, delete, hide |
| Messages (Messenger) | Yes | Send/receive via Messenger Platform |
| Events | Yes | Create, update, read |
| Reactions | Read only | Cannot programmatically react |

**Rate Limits:**
- Standard: 200 calls per hour per user per app
- Pages: 4800 calls per 24 hours per page (pooled across apps)
- Posting: No explicit limit but best practice is <25/day per page
- Batch API: Up to 50 requests per batch call

**Page Insights Available:**
- `page_impressions`, `page_engaged_users`, `page_post_engagements`
- `page_fans` (total likes), `page_fan_adds`, `page_fan_removes`
- `page_views_total`, `page_video_views`
- Demographic breakdowns (age, gender, country, city)
- Post-level: reach, impressions, engagement, clicks, reactions by type

**Python Libraries:**
- `facebook-sdk` (official): Pages, posting, insights
- `facebook-business` (Meta Business SDK): Ads, marketing, business management
- **Recommendation**: `facebook-sdk` for organic, `facebook-business` for ads

**Authentication:**
- Page Access Token (recommended for page management)
- System User Token (recommended for server-to-server in Business Manager)
- Long-lived tokens: 60 days, extendable to "never expire" for System Users

---

### 1.5 TikTok API

**TikTok has the most restrictive API access of all major social platforms.**

**API Products:**

| Product | Access | Capabilities |
|---------|--------|-------------|
| Login Kit | Open | OAuth login |
| Content Posting API | Restricted | Post videos to TikTok |
| Research API | Academic/Business | Read public content for research |
| Commercial Content API | Restricted | Branded content |
| TikTok for Business API | Partner only | Ads, analytics, audience |

**Content Posting API:**
- **Status**: Restricted access — requires application and review
- Posts videos only (TikTok is video-first)
- Two flows: "Direct Post" (immediate) and "Upload to Inbox" (user approves in app)
- Supported: Video upload, caption, privacy settings, allow comments/duets/stitch
- NOT supported: Photo posts, slideshows `[VERIFY-2026]` (TikTok added photos in 2024)
- Video requirements: MP4/WebM, 287.6MB max, 1-10 min duration
- Rate limit: Unclear publicly — approval-based quotas `[VERIFY-2026]`

**Analytics:**
- TikTok Creator Tools API: Video views, likes, comments, shares, profile views
- Limited to own account data
- Requires separate permission scope
- 30-day data retention on most metrics

**Python Libraries:**
- `TikTokApi`: Unofficial, reverse-engineered (uses Playwright/browser automation)
  - High maintenance burden, breaks frequently when TikTok changes
  - **Not recommended for production**
- `tiktok-business-api-python`: Official Business SDK `[VERIFY-2026]`
- **Recommendation**: Direct API calls via `httpx` — no mature official Python SDK

**What CAN Be Automated:**
- Video upload and posting (with Content Posting API access)
- Reading own video analytics
- Account-level metrics

**What CANNOT Be Automated:**
- Responding to comments (no write API for comments as of early 2025)
- Direct messages
- Going live
- Duets/stitches
- Hashtag challenge creation
- Sound/music selection (copyright restrictions)

**Cost Assessment:**
- API access is free (when approved)
- Getting approved is the main challenge — TikTok is very selective
- Business API (ads) requires TikTok Marketing Partner status
- **Recommendation**: Treat TikTok as "phase 2" — harder to integrate, less API maturity

---

### 1.6 Social Media Management Middleware

**The middleware approach is strongly recommended as it dramatically simplifies
multi-platform posting and provides unified analytics.**

#### Buffer

**API Capabilities:**
- POST to: Twitter/X, LinkedIn, Instagram, Facebook, TikTok, Mastodon, Pinterest,
  Google Business, YouTube, Threads `[VERIFY-2026]`
- Schedule posts with date/time
- Queue management (shuffle, re-order)
- Analytics: Post-level engagement, best time to post, audience growth
- Content library / media management
- Link shortening + tracking

**API Details:**
- REST API, well-documented
- OAuth 2.0 authentication
- Rate limit: ~100 requests per 10 minutes per token
- Free tier: 3 social channels, 10 posts per channel in queue
- Essentials: $6/mo per channel, unlimited posts
- Team: $12/mo per channel

**Python SDK:** None official. Use `httpx` with their REST API.

**Limitations:**
- No Instagram Stories or Reels scheduling `[VERIFY-2026]`
- No TikTok direct posting (sends to draft/notification)
- Analytics depth varies by platform
- No ad management

#### Hootsuite

**API Capabilities:**
- POST to: All major platforms
- Schedule, publish, bulk upload
- Social listening / monitoring (Hootsuite Insights, powered by Brandwatch)
- Analytics + custom reports
- Team collaboration / approval workflows
- Content calendar

**API Details:**
- REST API v2
- OAuth 2.0
- Requires Professional plan ($99/mo) or higher for API access
- Rate limit: 150 requests per minute
- Webhook support for incoming messages

**Python SDK:** None official. REST API via `httpx`.

**Limitations:**
- API documentation is mediocre compared to Buffer
- Expensive for API access ($99/mo minimum)
- Social listening requires Hootsuite Insights add-on (expensive)

#### Ayrshare

**Specifically built as an API-first social media management platform.**
**This is the strongest middleware candidate for Nexus.**

**API Capabilities:**
- POST to: Twitter/X, LinkedIn, Instagram, Facebook, TikTok, YouTube, Pinterest,
  Reddit, Telegram, Google Business Profile
- Schedule posts
- Media upload (images, video)
- Analytics aggregation across platforms
- Comment management
- Auto-hashtag generation
- RSS feed auto-posting
- Webhooks for engagement events

**API Details:**
- REST API, excellent documentation
- API-key authentication (simpler than OAuth)
- Rate limit: Depends on plan
- Free tier: 1 profile per network, 50 posts/mo
- Premium: $99/mo, 5 profiles per network, unlimited posts
- Business: $249/mo, webhooks, advanced analytics, priority support

**Python SDK:** `social-post-api` (official)
```python
from ayrshare import SocialPost
social = SocialPost(api_key="YOUR_KEY")
social.post({
    "post": "Today is a great day!",
    "platforms": ["twitter", "facebook", "linkedin", "instagram"],
    "media_urls": ["https://example.com/image.jpg"],
    "scheduled_date": "2026-03-01T10:00:00Z"
})
```

**Why Ayrshare for Nexus:**
- API-first (not a UI tool with API bolted on)
- Unified posting + analytics across all platforms
- Handles OAuth token management internally (you connect accounts via their dashboard)
- Comment/engagement management via API
- Webhook support for real-time engagement monitoring
- RSS auto-posting for blog distribution
- Significantly simpler than managing 5+ platform-specific APIs

#### Later (formerly Later.com, Mavrck merger)

- Focused on visual content planning (Instagram-first)
- API available on Business+ plans
- Less API-friendly than Buffer/Ayrshare
- **Not recommended as middleware** for a developer-focused platform

#### Sprout Social

- Enterprise-grade social management
- Excellent analytics and reporting
- API available but primarily for their partner ecosystem
- **Very expensive** ($249/seat/mo starting)
- Not suitable as middleware — better as a competitor reference

### 1.7 Social Media API Summary & Recommendation

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED ARCHITECTURE                         │
│                                                                     │
│  PRIMARY: Ayrshare API (middleware)                                 │
│  ├── Single API for Twitter/X, LinkedIn, Instagram, Facebook,       │
│  │   TikTok, YouTube, Pinterest, Reddit                            │
│  ├── Unified analytics                                              │
│  ├── Comment/engagement management                                  │
│  └── $99/mo for full capability                                     │
│                                                                     │
│  DIRECT API (for features Ayrshare doesn't cover):                  │
│  ├── Twitter/X API (Basic $100/mo) — DMs, advanced search          │
│  ├── LinkedIn API — Community Management for deep page analytics   │
│  ├── Meta Graph API — Messenger integration, detailed insights     │
│  └── TikTok — Phase 2 when API matures                            │
│                                                                     │
│  FALLBACK: Buffer API ($6-12/channel/mo)                           │
│  └── Simpler, cheaper alternative to Ayrshare                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Python Dependencies to Add:**
```
tweepy>=4.14.0          # Twitter/X direct API
facebook-sdk>=3.1.0     # Meta (Facebook + Instagram) Graph API
social-post-api>=1.0.0  # Ayrshare unified posting [VERIFY-2026]
httpx>=0.27.0           # Already in requirements — for LinkedIn + TikTok direct
```

---

## 2. Email Marketing APIs

### 2.1 Mailchimp (Intuit)

**The most widely used email marketing platform. Excellent API.**

**API Capabilities:**
- **Campaigns**: Create, schedule, send, pause, cancel, replicate
- **Templates**: Create from HTML, list, update, delete
- **Lists/Audiences**: Create, manage subscribers, segments, tags
- **Automations**: Create automation workflows (welcome series, abandoned cart, etc.)
- **A/B Testing**: Subject line, content, send time
- **Analytics**: Opens, clicks, bounces, unsubscribes, revenue tracking
- **Transactional email**: Via Mandrill (separate product, included in Standard+)
- **Content optimization**: Subject line helper, send time optimization
- **Webhooks**: Subscribe/unsubscribe events, campaign events
- **Batch operations**: Bulk subscribe, bulk tag, etc.
- **Landing pages**: Create, publish (limited API)
- **E-commerce**: Revenue attribution, product recommendations

**API Details:**
- REST API v3.0, JSON, well-documented
- OAuth 2.0 or API key authentication
- Rate limit: 10 concurrent connections, max 500 requests per minute `[VERIFY-2026]`
- No per-request charges — pricing based on contact count

**Pricing (for 500 contacts):**
| Plan | Price | Emails/mo | Features |
|------|-------|-----------|----------|
| Free | $0 | 500 | 1 audience, basic templates, limited analytics |
| Essentials | $13/mo | 5,000 | A/B testing, custom templates, 24/7 support |
| Standard | $20/mo | 6,000 | Automations, retargeting, advanced analytics |
| Premium | $350/mo | 150,000 | Multivariate testing, advanced segmentation |

**Python Library:**
- `mailchimp-marketing` (official): `pip install mailchimp-marketing`
- `mailchimp-transactional` (official, for Mandrill): `pip install mailchimp-transactional`

```python
import mailchimp_marketing as MailchimpMarketing
client = MailchimpMarketing.Client()
client.set_config({"api_key": "YOUR_KEY", "server": "us1"})

# Create campaign
campaign = client.campaigns.create({
    "type": "regular",
    "recipients": {"list_id": "abc123"},
    "settings": {
        "subject_line": "Your Subject",
        "from_name": "Your Brand",
        "reply_to": "you@example.com"
    }
})

# Set content
client.campaigns.set_content(campaign["id"], {
    "html": "<html>Your email content</html>"
})

# Schedule
client.campaigns.schedule(campaign["id"], {
    "schedule_time": "2026-03-01T10:00:00+00:00"
})
```

**What CAN Be Automated:**
- Full campaign lifecycle (create, content, schedule, send, analyze)
- Subscriber management (add, remove, tag, segment)
- Automation workflows (create, activate, pause)
- A/B testing setup and analysis
- Template management
- Analytics retrieval

**What CANNOT Be Automated:**
- Drag-and-drop email design (must provide HTML)
- Compliance/legal review of content
- Domain authentication setup (one-time manual)
- Landing page visual design

**Verdict:** Strongest all-around email marketing API. **Recommended as primary.**

---

### 2.2 SendGrid (Twilio)

**Best for high-volume transactional + marketing email.**

**API Capabilities:**
- **Marketing Campaigns**: Create, schedule, send
- **Contacts/Lists**: Manage contacts, segments, custom fields
- **Templates**: Dynamic templates with Handlebars syntax
- **Automations**: Welcome series, re-engagement (Marketing Campaigns)
- **Transactional email**: The strongest transactional email API available
- **Email validation**: Check email deliverability before sending
- **Webhooks**: Delivery, open, click, bounce, spam report events
- **Suppressions**: Manage bounces, blocks, spam reports, unsubscribes
- **IP management**: Dedicated IPs, IP pools, warmup
- **Stats**: Aggregate and per-email statistics

**API Details:**
- REST API v3, well-documented
- API key authentication
- Rate limit: Varies by plan. Free: 100 emails/day. Pro: thousands/sec
- Separate endpoints for Marketing and Mail Send (transactional)

**Pricing:**
| Plan | Price | Emails/mo | Key Features |
|------|-------|-----------|-------------|
| Free | $0 | 100/day | Single sender, basic API |
| Essentials | $19.95/mo | 50,000 | No daily limit, A/B testing |
| Pro | $89.95/mo | 100,000 | Dynamic templates, automations, dedicated IP |
| Premier | Custom | Custom | Sub-user management, priority support |

**Python Library:**
- `sendgrid` (official): `pip install sendgrid`
- Extremely well-maintained, type-hinted

```python
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

message = Mail(
    from_email="you@example.com",
    to_emails="recipient@example.com",
    subject="Campaign Subject",
    html_content="<p>Your content</p>"
)
sg = SendGridAPIClient(api_key="YOUR_KEY")
response = sg.send(message)
```

**Best For:** High deliverability requirements, transactional + marketing combo,
developer-focused workflows.

---

### 2.3 Resend

**Modern, developer-first email API. The "Stripe of email."**

**API Capabilities:**
- **Send email**: HTML, plain text, React Email templates
- **Batch sending**: Up to 100 emails per batch request
- **Domains**: Add, verify, manage sending domains
- **API keys**: Create, revoke, manage
- **Webhooks**: Delivery, open, click, bounce events
- **Audiences**: Contact list management (added 2024)
- **Broadcasts**: Marketing email campaigns (added 2024) `[VERIFY-2026]`

**API Details:**
- REST API, extremely clean design
- API key authentication
- Rate limit: 2 requests/sec (Free), 10/sec (Pro), custom (Enterprise)
- Built on AWS SES infrastructure

**Pricing:**
| Plan | Price | Emails/mo | Contacts |
|------|-------|-----------|----------|
| Free | $0 | 100/day (3,000/mo) | 0 (no audience) |
| Pro | $20/mo | 50,000 | 10,000 contacts |
| Enterprise | Custom | Custom | Custom |

**Python Library:**
- `resend` (official): `pip install resend`

```python
import resend
resend.api_key = "re_YOUR_KEY"
resend.Emails.send({
    "from": "you@yourdomain.com",
    "to": ["recipient@example.com"],
    "subject": "Hello",
    "html": "<p>Content</p>"
})
```

**Strengths:** Cleanest API, best DX, React Email templates
**Weaknesses:** Younger product, less marketing automation features than Mailchimp/SendGrid,
Audiences/Broadcasts features still maturing `[VERIFY-2026]`

**Best For:** Developer-first teams who want simplicity + transactional email.

---

### 2.4 ConvertKit (now Kit)

**Creator-focused email marketing. Strong automation builder.**

**API Capabilities:**
- **Subscribers**: Add, tag, list, segment, custom fields
- **Broadcasts**: Create, schedule, send one-off emails
- **Sequences**: Create automated email sequences
- **Forms**: List, manage forms
- **Tags**: Create, apply, remove tags
- **Automations**: Trigger, read (limited write API)
- **Purchases**: Track purchases for e-commerce automation

**API Details:**
- REST API v3 + v4 (v4 in beta as of 2024) `[VERIFY-2026]`
- API secret or OAuth 2.0
- Rate limit: 120 requests per minute

**Pricing:**
| Plan | Price | Subscribers |
|------|-------|------------|
| Free | $0 | 10,000 | (limited features, no automations)
| Creator | $29/mo | 1,000 | Full automations, integrations
| Creator Pro | $59/mo | 1,000 | Priority support, referral system

**Python Library:** No official SDK. Use `httpx`.

**Strengths:** Best automation builder for creators, excellent deliverability
**Weaknesses:** Limited API write capabilities for automations, no A/B on campaigns (only sequences)

---

### 2.5 Brevo (formerly Sendinblue)

**All-in-one marketing platform: email + SMS + WhatsApp + chat.**

**API Capabilities:**
- **Email campaigns**: Create, schedule, send
- **Transactional email**: High-volume sending
- **SMS campaigns**: Send marketing + transactional SMS
- **WhatsApp campaigns**: Template-based messaging `[VERIFY-2026]`
- **Contacts**: CRUD, lists, segments, attributes
- **Automations**: Full workflow API (triggers, conditions, actions)
- **Templates**: Create, update, delete
- **Webhooks**: All email events + SMS events
- **Conversations**: Live chat API
- **CRM**: Deal pipeline management via API

**API Details:**
- REST API v3, well-documented
- API key authentication
- Rate limit: Depends on plan (free: limited, Enterprise: high)

**Pricing:**
| Plan | Price | Emails/mo | Features |
|------|-------|-----------|---------|
| Free | $0 | 300/day | API access, transactional |
| Starter | $25/mo | 20,000 | No daily limit, basic reporting |
| Business | $65/mo | 20,000 | Marketing automation, A/B, landing pages |
| Enterprise | Custom | Custom | Dedicated IP, priority support |

**Python Library:**
- `sib-api-v3-sdk` (official Brevo SDK): `pip install sib-api-v3-sdk`

**Strengths:** Multi-channel (email + SMS + WhatsApp), competitive pricing, full automation API
**Weaknesses:** Less polished than Mailchimp, documentation quality varies

### 2.6 Email Marketing API Summary & Recommendation

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED ARCHITECTURE                         │
│                                                                     │
│  PRIMARY: Mailchimp API (marketing campaigns)                       │
│  ├── Best automation builder                                        │
│  ├── Deepest analytics                                              │
│  ├── A/B testing built-in                                          │
│  ├── Most users already have Mailchimp accounts                    │
│  └── Official Python SDK                                           │
│                                                                     │
│  SECONDARY: SendGrid (transactional email)                          │
│  ├── Confirmation emails, password resets                          │
│  ├── High-volume sending                                           │
│  └── Excellent deliverability                                       │
│                                                                     │
│  ALTERNATIVE: Resend (for developer-focused users)                  │
│  └── Simpler API, React Email templates, growing features          │
│                                                                     │
│  MULTI-CHANNEL: Brevo (email + SMS + WhatsApp)                     │
│  └── When users need SMS/WhatsApp alongside email                  │
│                                                                     │
│  APPROACH: Abstract email provider behind interface                 │
│  └── EmailProvider protocol → Mailchimp/SendGrid/Resend adapters   │
└─────────────────────────────────────────────────────────────────────┘
```

**Python Dependencies:**
```
mailchimp-marketing>=3.0.0    # Mailchimp campaigns
sendgrid>=6.11.0              # SendGrid transactional
resend>=0.7.0                 # Resend (optional)
sib-api-v3-sdk>=7.6.0        # Brevo (optional)
```

---

## 3. Advertising Platform APIs

### 3.1 Google Ads API

**The most complex advertising API, but also the most powerful.**

**API Capabilities:**
- **Campaigns**: Create, update, pause, remove (Search, Display, Video, Shopping, App, Performance Max)
- **Ad Groups**: Create, manage targeting settings
- **Ads**: Create text ads, responsive search ads, responsive display ads, video ads
- **Keywords**: Add, remove, set bids, get search volume
- **Bidding**: Manual CPC, Target CPA, Target ROAS, Maximize Conversions
- **Budgets**: Set daily/campaign budgets
- **Targeting**: Demographics, interests, placements, topics, remarketing lists
- **Reporting**: Campaign/ad group/ad/keyword performance metrics
- **Conversions**: Create conversion actions, import offline conversions
- **Audiences**: Create, manage remarketing lists
- **Assets**: Manage ad extensions (sitelinks, callouts, snippets)
- **Recommendations**: Get and apply Google's optimization suggestions
- **Change history**: Audit trail of all account changes
- **Forecasting**: Keyword planner functionality via API

**API Details:**
- gRPC + REST API (v16 as of early 2025) `[VERIFY-2026]`
- OAuth 2.0 + developer token (requires Google Ads Manager account)
- Rate limit: 15,000 operations per minute per developer token (standard access)
- **Requires approval**: Must apply for basic or standard access developer token
- Test accounts available for development

**Pricing:**
- API access is free
- You pay for ad spend (Google Ads charges for clicks/impressions)
- Developer token requires basic verification (3-5 business days) or standard access (manual review)

**Python Library:**
- `google-ads` (official): `pip install google-ads`
- Mature, actively maintained, type-hinted, supports both gRPC and REST

```python
from google.ads.googleads.client import GoogleAdsClient

client = GoogleAdsClient.load_from_storage("google-ads.yaml")
ga_service = client.get_service("GoogleAdsService")

# Query campaign performance
query = """
    SELECT campaign.name, metrics.impressions, metrics.clicks,
           metrics.cost_micros, metrics.conversions
    FROM campaign
    WHERE segments.date DURING LAST_30_DAYS
    ORDER BY metrics.cost_micros DESC
"""
response = ga_service.search(customer_id="123-456-7890", query=query)
```

**GAQL (Google Ads Query Language):**
- SQL-like query language for reporting
- Extremely powerful — can query any combination of resources, metrics, segments
- Supports filtering, ordering, limiting
- This is the primary way to extract data

**What CAN Be Automated:**
- Full campaign lifecycle (create, manage, optimize, pause, delete)
- Keyword research and bid management
- Ad creation and testing
- Budget management and allocation
- Performance reporting (down to keyword level)
- Conversion tracking setup
- Audience management
- Applying recommendations

**What CANNOT Be Automated:**
- Initial account setup and billing configuration
- Policy review / ad approval (Google reviews)
- Google Merchant Center feed management (separate API)
- Physical location verification (Google Business)

---

### 3.2 Meta Marketing API (Facebook + Instagram Ads)

**Second-largest digital ad platform. Single API for Facebook + Instagram ads.**

**API Capabilities:**
- **Campaigns**: Create, update, read, delete (Awareness, Traffic, Engagement, Leads, Sales)
- **Ad Sets**: Targeting, placements, budgets, scheduling
- **Ads**: Creative management, preview, A/B testing
- **Creatives**: Image, video, carousel, collection, instant experience
- **Targeting**: Demographics, interests, behaviors, custom audiences, lookalike audiences
- **Custom Audiences**: Upload customer lists, website visitors (pixel), app activity
- **Lookalike Audiences**: Find similar users to existing customers
- **Pixel/CAPI**: Conversions API (server-side tracking, replacing pixel where possible)
- **Reporting**: Campaign/ad set/ad level metrics, breakdowns by age/gender/placement/device
- **Budget optimization**: Campaign Budget Optimization (CBO), ad set budgets
- **Rules**: Automated rules (pause if CPA > $X, increase budget if ROAS > Y)
- **Lead forms**: Create and manage lead gen forms
- **Product catalog**: For dynamic product ads (e-commerce)
- **Batch API**: Up to 50 requests per batch

**API Details:**
- REST API (Graph API v18+ as of early 2025) `[VERIFY-2026]`
- OAuth 2.0, Marketing API access requires Business verification
- Rate limit: Variable, based on BUC (Business Use Cases) scoring system
  - Typical: 200 calls per hour per ad account for reading, 500 per day for creation
  - Higher limits for marketing API partners
- **Versioning**: Graph API versions deprecated every 2 years

**Pricing:**
- API access is free
- Ad spend charged by Meta (CPM/CPC/CPA bidding)
- Business verification required (government ID, business docs, 1-5 days)

**Python Library:**
- `facebook-business` (official Meta Business SDK): `pip install facebook-business`

```python
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adaccount import AdAccount

FacebookAdsApi.init(app_id, app_secret, access_token)
account = AdAccount('act_123456')

# Create campaign
campaign = account.create_campaign(params={
    'name': 'My Campaign',
    'objective': 'OUTCOME_TRAFFIC',
    'status': 'PAUSED',
    'special_ad_categories': [],
})

# Get campaign insights
insights = campaign.get_insights(params={
    'date_preset': 'last_30d',
    'fields': ['impressions', 'clicks', 'spend', 'cpc', 'ctr'],
})
```

**Conversions API (CAPI):**
- Server-side event tracking (bypasses browser ad blockers)
- Replaces/supplements Facebook Pixel
- Events: Purchase, AddToCart, Lead, ViewContent, etc.
- Deduplication with browser pixel events via `event_id`
- **Strongly recommended** for accurate attribution

**What CAN Be Automated:**
- Full ad lifecycle (create, target, bid, budget, analyze, pause)
- Audience creation (custom, lookalike)
- Creative management
- Conversion tracking (CAPI)
- Automated rules
- Lead form creation
- Product catalog management

**What CANNOT Be Automated:**
- Account creation and initial setup
- Business verification
- Ad creative policy review (Meta reviews all ads)
- Community Standards compliance

---

### 3.3 LinkedIn Marketing API (Ads)

**Primarily B2B advertising. Most expensive CPC but highest-quality B2B leads.**

**API Capabilities:**
- **Campaigns**: Create, manage (Sponsored Content, Message Ads, Dynamic Ads, Text Ads)
- **Campaign Groups**: Organize campaigns
- **Creatives**: Single image, carousel, video, document, conversation ads
- **Targeting**: Job title, company, industry, seniority, skills, groups, ABM (account lists)
- **Audiences**: Matched audiences (website retargeting, contact targeting, lookalike)
- **Conversions**: Insight Tag + CAPI equivalent
- **Reporting**: Campaign analytics, demographic breakdowns
- **Lead Gen Forms**: Create and manage LinkedIn lead forms
- **Budget**: Daily/lifetime budgets, CPC/CPM/CPS bidding

**API Details:**
- REST API (LinkedIn Marketing API)
- OAuth 2.0
- **Requires LinkedIn Marketing Developer Platform access** (restricted, partner application)
- Rate limit: 100 requests per day for most endpoints `[VERIFY-2026]`

**Pricing:**
- API access is free (with Marketing Developer Platform approval)
- Ad spend: LinkedIn CPCs typically $5-12 (significantly higher than Google/Meta)
- Minimum daily budget: $10/day

**Python Library:**
- No official Python SDK for Marketing API
- Use `httpx` with LinkedIn REST endpoints

**What CAN Be Automated:**
- Campaign creation and management
- Audience building (matched audiences)
- Creative upload
- Budget management
- Performance reporting

**What CANNOT Be Automated:**
- Account creation
- Marketing Developer Platform access (manual application)
- Lead Gen Form responses (read-only, cannot modify forms in production)
- InMail content (template-based, requires approval)

**Key Challenge:**
LinkedIn Marketing API access is the most difficult to obtain. Requires:
1. LinkedIn Page with advertising history
2. Application to Marketing Developer Platform
3. Review process (4-8 weeks)
4. Annual recertification

---

### 3.4 Unified Ad Management Platforms

#### AdRoll
- Retargeting + prospecting across web, social, email
- API available for campaign management
- Integrates with Facebook, Google Display, email
- **Good for retargeting automation, but limited for search ads**

#### Smartly.io (now Smartly)
- Creative automation + media buying for social ads
- API for campaign management across Meta, TikTok, Snapchat, Pinterest
- Enterprise pricing ($10,000+/mo) `[VERIFY-2026]`
- **Too expensive for integration — but reference for features**

#### Marin Software
- Cross-channel bid management (Google, Bing, Meta, Amazon)
- API available
- Enterprise focused
- **Declining relevance** — most agencies use native APIs

#### Adalysis (Google Ads specific)
- Google Ads optimization and auditing
- No public API — UI-only tool
- **Reference for optimization features to build**

### 3.5 Advertising API Summary & Recommendation

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED ARCHITECTURE                         │
│                                                                     │
│  TIER 1 (Build first):                                             │
│  ├── Google Ads API — Search + Display + YouTube                   │
│  │   ├── Official SDK: google-ads                                  │
│  │   ├── GAQL for reporting                                        │
│  │   └── Developer token required (3-5 day approval)               │
│  ├── Meta Marketing API — Facebook + Instagram Ads                 │
│  │   ├── Official SDK: facebook-business                           │
│  │   ├── CAPI for server-side conversion tracking                  │
│  │   └── Business verification required                            │
│  │                                                                  │
│  TIER 2 (Phase 2):                                                 │
│  ├── LinkedIn Marketing API — B2B Advertising                      │
│  │   ├── Marketing Developer Platform access (4-8 week approval)   │
│  │   └── Custom httpx wrapper                                      │
│  ├── TikTok Ads API — Video advertising                           │
│  │   └── Marketing Partner access required                         │
│  │                                                                  │
│  APPROACH: Unified AdPlatform protocol                             │
│  └── AdProvider interface → Google/Meta/LinkedIn adapters          │
└─────────────────────────────────────────────────────────────────────┘
```

**Python Dependencies:**
```
google-ads>=24.0.0          # Google Ads API [VERIFY-2026 for latest version]
facebook-business>=19.0.0   # Meta Marketing API [VERIFY-2026]
```

---

## 4. SEO Tools & APIs

### 4.1 Ahrefs API

**One of the two dominant SEO platforms (alongside SEMrush).**

**API Capabilities:**
- **Site Explorer**: Backlink profile, referring domains, organic keywords, traffic estimates
- **Keywords Explorer**: Search volume, keyword difficulty, CPC, SERP analysis
- **Content Explorer**: Find popular content by topic/keyword
- **Site Audit**: Crawl issues, technical SEO problems
- **Rank Tracker**: Position tracking for keywords
- **Batch Analysis**: Bulk URL/domain metrics

**API Details:**
- REST API v3
- API token authentication
- Rate limit: Depends on plan (Lite: 500 rows/request, Standard: 3,000, Advanced: 5,000)
- Credits-based system: Each API call consumes credits (monthly allocation)
- `[VERIFY-2026]` — Ahrefs has been expanding API access, may have changed credit model

**Pricing:**
| Plan | Price | API Credits |
|------|-------|------------|
| Lite | $99/mo | Limited API access |
| Standard | $199/mo | Standard API access |
| Advanced | $399/mo | Full API access |
| Enterprise | $999/mo | Maximum API access |

API access level and credits vary significantly by plan.

**Python Library:**
- No official SDK
- Use `httpx` with Ahrefs REST API
- Community library: `python-ahrefs` (unmaintained)

**Key Endpoints for Marketing Agency:**
- `GET /v3/site-explorer/overview` — Domain metrics (DR, organic traffic, backlinks)
- `GET /v3/site-explorer/all-backlinks` — Full backlink list
- `GET /v3/keywords-explorer/overview` — Keyword metrics
- `GET /v3/site-explorer/organic-keywords` — Keywords a domain ranks for
- `GET /v3/site-explorer/organic-competitors` — Competitor analysis

---

### 4.2 SEMrush API

**Most comprehensive SEO + marketing intelligence platform.**

**API Capabilities:**
- **Domain Analytics**: Organic search, paid search, backlinks, display advertising
- **Keyword Analytics**: Search volume, difficulty, CPC, related keywords, questions
- **URL Analysis**: Specific page metrics
- **Traffic Analytics**: Website traffic estimates (competitive intelligence)
- **Content Marketing**: Topic research, SEO writing assistant API
- **Backlink Analytics**: Full backlink database
- **Position Tracking**: SERP monitoring
- **Site Audit**: Crawl health, issues, recommendations

**API Details:**
- REST API
- API key authentication
- Rate limit: 10 requests per second `[VERIFY-2026]`
- Row limits per request depend on plan
- Units-based system: Each API call consumes units (monthly allocation)

**Pricing (API):**
| Plan | Price | API Units/mo |
|------|-------|-------------|
| Pro | $129.95/mo | 10,000 |
| Guru | $249.95/mo | 50,000 |
| Business | $499.95/mo | 200,000 |

**Python Library:**
- No official SDK
- Use `httpx` with SEMrush API endpoints
- API response format: semicolon-separated values (not JSON!) — requires custom parsing

**Key Endpoints:**
- `domain_organic` — Organic keywords for a domain
- `domain_organic_unique` — Unique keywords data
- `phrase_all` — Keyword overview (volume, difficulty, CPC)
- `phrase_related` — Related keywords
- `phrase_questions` — Question-format keywords
- `backlinks_overview` — Domain backlink summary
- `url_organic` — Organic keywords for a specific URL

**Gotcha:** SEMrush API returns data in a proprietary semicolon-separated format, not JSON.
Requires custom parsing logic.

---

### 4.3 Google Search Console API

**Free, first-party data directly from Google. Essential for any SEO workflow.**

**API Capabilities:**
- **Search Analytics**: Clicks, impressions, CTR, position by query/page/country/device/date
- **URL Inspection**: Check indexing status, crawl info, Rich Results status
- **Sitemaps**: Submit, list, delete sitemaps
- **Index Coverage**: Indexing status of pages (via BigQuery export)

**API Details:**
- REST API (part of Google API ecosystem)
- OAuth 2.0 (Google service account or user consent)
- Rate limit: Varies. Search Analytics: 200 requests per minute
- Data availability: 3-day delay (not real-time)
- Data retention: 16 months of search performance data

**Pricing:** Completely free.

**Python Library:**
- `google-api-python-client` (official): `pip install google-api-python-client google-auth`
- Alternatively, `searchconsole` community library: `pip install searchconsole`

```python
from googleapiclient.discovery import build
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    'service-account.json',
    scopes=['https://www.googleapis.com/auth/webmasters.readonly']
)
service = build('searchconsole', 'v1', credentials=credentials)

# Query search analytics
response = service.searchanalytics().query(
    siteUrl='https://example.com',
    body={
        'startDate': '2026-01-01',
        'endDate': '2026-02-01',
        'dimensions': ['query', 'page'],
        'rowLimit': 1000
    }
).execute()
```

**What CAN Be Automated:**
- Search performance reporting (queries, pages, countries, devices)
- URL indexing status checks
- Sitemap submission
- Bulk URL inspection (limited rate)

**What CANNOT Be Automated:**
- Requesting re-indexing (manual via URL Inspection UI or API, but limited quotas)
- Disavow file upload (manual only)
- Property verification (one-time manual)

---

### 4.4 Moz API

**Domain authority pioneer, strong link intelligence.**

**API Capabilities:**
- **Link Explorer**: Backlinks, linking domains, anchor text
- **URL Metrics**: Domain Authority (DA), Page Authority (PA), spam score
- **Keyword Explorer**: Search volume, difficulty, organic CTR
- **SERP Analysis**: Top-ranking pages for keywords
- **On-page Optimization**: Page-level recommendations

**API Details:**
- REST API v2
- OAuth 2.0 + API ID/secret
- Rate limit: 10 requests per second (Pro), 30/sec (Enterprise)
- Credits-based: Monthly allocation based on plan

**Pricing:**
| Plan | Price | API Rows/mo |
|------|-------|------------|
| Standard | $99/mo | 5,000 |
| Medium | $179/mo | 20,000 |
| Large | $299/mo | 100,000 |
| Premium | $599/mo | 500,000 |

**Python Library:**
- No official SDK
- Use `httpx` — Moz API is straightforward REST

**Verdict:** Moz is losing market share to Ahrefs/SEMrush. Include as optional,
not primary.

---

### 4.5 SurferSEO / Clearscope (Content Optimization)

**These tools analyze top-ranking pages and provide content recommendations.**

#### SurferSEO
- **Content Editor**: NLP-based content scoring and recommendations
- **API**: `[VERIFY-2026]` — As of early 2025, SurferSEO had a limited API
  (audit, SERP analyzer). Content Editor API was in beta/limited access.
- **What's useful**: Content score, word count targets, NLP terms to include,
  competitor content structure analysis
- **Pricing**: $89/mo (Essential), $179/mo (Scale)
- **Python access**: Likely custom API or scraping needed

#### Clearscope
- **Content optimization**: Similar to Surfer, NLP-based content grading
- **API**: Limited/no public API as of early 2025 `[VERIFY-2026]`
- **Pricing**: $170/mo+
- **Not recommended for API integration** — designed for manual use

#### Alternative: Build In-House Content Optimization
Given that SurferSEO and Clearscope have limited APIs, the recommended approach is
to build content optimization into Nexus natively:

1. Use Google Search Console API to find target keywords
2. Use Ahrefs/SEMrush for keyword difficulty and search volume
3. Use Google Custom Search API (already in Nexus) to analyze top-10 SERP results
4. Use `web_fetch` to extract content from top-ranking pages
5. Use LLM (via Nexus agent) to analyze competitor content and generate optimization recommendations
6. Score content against competitor benchmarks using NLP (TF-IDF or BM25)

This approach gives Nexus a **competitive advantage** — built-in content optimization
without requiring expensive third-party subscriptions.

---

### 4.6 SEO API Summary & Recommendation

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED ARCHITECTURE                         │
│                                                                     │
│  ESSENTIAL (Free, first-party):                                     │
│  ├── Google Search Console API — Organic performance data          │
│  └── Google PageSpeed Insights API — Core Web Vitals (free)        │
│                                                                     │
│  PRIMARY SEO DATA (choose one):                                     │
│  ├── Ahrefs API — Best backlink data, cleaner API                  │
│  └── SEMrush API — More features, harder to parse (CSV format)     │
│                                                                     │
│  BUILT-IN (Nexus-native, no external dependency):                  │
│  ├── Content optimization engine (LLM-powered SERP analysis)       │
│  ├── On-page SEO checker (meta tags, headings, content structure)  │
│  ├── Keyword clustering (semantic grouping via embeddings)          │
│  └── Technical SEO audit (sitemap parsing, robots.txt, redirects) │
│                                                                     │
│  APPROACH: SEOProvider protocol + native engine                    │
│  └── AhrefsAdapter / SEMrushAdapter + built-in SEO analysis       │
└─────────────────────────────────────────────────────────────────────┘
```

**Python Dependencies:**
```
google-api-python-client>=2.0.0   # Google Search Console + PageSpeed
google-auth>=2.0.0                # Google auth for Search Console
```

---

## 5. AI Marketing Agent Platforms (Competitors)

### 5.1 Jasper AI

**The market leader in AI content creation for marketing (founded as Jarvis.ai).**

**What They Offer:**
- Long-form content generation (blog posts, articles)
- Marketing copy (ad copy, email subject lines, landing pages)
- Brand Voice feature: Custom brand voice profiles that constrain AI output
- Template library: 50+ marketing-specific templates
- Campaign assistant: Multi-channel content from a single brief
- SEO mode: Integration with SurferSEO for keyword-optimized content
- Jasper Art: AI image generation (DALL-E based)
- Jasper Chat: Conversational AI for marketing tasks
- Team collaboration: Content workflows, brand guidelines, approval chains

**API/Integration:**
- **Jasper API**: `[VERIFY-2026]` — Jasper introduced API access in 2024 for
  enterprise customers. Programmatic content generation.
- API is primarily for enterprise tier ($custom pricing)
- Features: Generate content, use templates programmatically, maintain brand voice
- **Not suitable as a building block** — it's a competitor, not a tool to integrate

**Pricing:**
- Creator: $49/mo per seat (limited features)
- Pro: $69/mo per seat (all templates, brand voice)
- Business: Custom (API access, advanced features, SSO)

**Key Learnings for Nexus:**
- Brand Voice is the killer feature — users need consistent AI-generated content
- Template library with marketing-specific prompts is essential
- SEO integration is table stakes
- Image generation alongside copy is expected
- Approval workflows matter for team use

---

### 5.2 Copy.ai

**Second-largest AI marketing copy platform.**

**What They Offer:**
- Marketing copy generation (short-form focused)
- Workflows: Multi-step AI automation (e.g., "research topic -> write blog -> generate social posts")
- 90+ templates for marketing copy types
- Brand voice profiles
- Chat-based interface
- API access on Enterprise plan

**API:**
- `[VERIFY-2026]` — Copy.ai has a workflow API for Enterprise tier
- Allows triggering workflows programmatically
- Can integrate into existing tools via webhooks

**Pricing:**
- Free: 2,000 words/mo
- Pro: $49/mo (unlimited words)
- Team: $249/mo (5 seats)
- Enterprise: Custom (API, SSO, dedicated support)

**Key Learnings for Nexus:**
- Multi-step workflows (not just single-prompt generation) are the direction
- "Research -> Generate -> Refine" pipelines map perfectly to Nexus sub-agents

---

### 5.3 HubSpot AI (Marketing Hub)

**Enterprise marketing automation with AI layered on top.**

**What They Offer:**
- AI content assistant: Blog posts, emails, social posts, landing pages
- AI chatbot builder
- Email marketing with AI subject line optimization
- Social media scheduling + AI caption generation
- SEO recommendations
- Ads management (Google, Facebook, LinkedIn)
- CRM integration (contacts, deals, pipeline)
- Attribution reporting
- Marketing automation workflows

**API:**
- HubSpot API is excellent — one of the best marketing APIs available
- REST API v3, OAuth 2.0
- Rate limit: 100 calls per 10 seconds (Free/Starter), 150/10s (Pro), 200/10s (Enterprise)
- Covers: CRM, marketing, sales, service, CMS, automation

**Python Library:**
- `hubspot-api-client` (official): `pip install hubspot-api-client`

**Pricing:**
- Free: CRM + limited marketing
- Starter: $20/mo (1,000 contacts)
- Professional: $890/mo (2,000 contacts, full automation)
- Enterprise: $3,600/mo (10,000 contacts, advanced)

**Key Insight:** HubSpot is not a competitor to integrate but rather a **competitive
reference** for features. Their pricing model shows the market values:
- CRM + marketing integration
- Multi-channel campaign management
- Attribution and ROI tracking
- Workflow automation

---

### 5.4 Salesforce Marketing Cloud (Einstein AI)

**Enterprise-grade, primarily for large organizations.**

**What They Offer:**
- Email Studio: Advanced email marketing
- Social Studio: Social media management
- Advertising Studio: Ad management
- Journey Builder: Complex automation workflows
- Einstein AI: Predictive analytics, content recommendations, send time optimization
- Einstein Content Selection: AI picks best email content per recipient

**API:**
- SOAP + REST API (complex, enterprise-oriented)
- `FuelSDK` for Python (official but not well maintained)
- **Not recommended for integration** — too complex, enterprise-only pricing

**Pricing:** $1,250/mo+ (starting)

---

### 5.5 Open-Source AI Marketing Agents

#### AutoGPT / BabyAGI / CrewAI
- General-purpose AI agent frameworks
- Can be configured for marketing tasks
- **CrewAI** has marketing-specific templates (SEO crew, content crew)
- Useful as architecture reference but not direct competition

#### Mautic (Open-Source Marketing Automation)
- PHP-based, self-hosted marketing automation
- Email campaigns, landing pages, lead scoring, segments
- REST API: Full campaign and contact management
- **Potential integration**: Nexus could manage Mautic via its API
- `[VERIFY-2026]` — Mautic 5.x may have updated API
- No AI features — but provides the automation infrastructure

#### n8n (Workflow Automation)
- Open-source, self-hostable Zapier alternative
- Has nodes for: Mailchimp, HubSpot, Google Ads, Facebook, Twitter, LinkedIn
- AI agent nodes (LangChain integration)
- **Architectural reference**: Shows how to build platform integrations modularly
- Could be a complementary tool (Nexus for AI, n8n for automation plumbing)

#### Flowise / Langflow
- Visual LLM workflow builders
- Can create marketing content pipelines
- **Reference for visual workflow design**, not direct competition

### 5.6 Competitor Analysis Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                COMPETITIVE LANDSCAPE & POSITIONING                   │
│                                                                     │
│  CONTENT GENERATION:                                                │
│  ├── Jasper ($49-69/seat/mo) — Brand voice, templates, SEO         │
│  ├── Copy.ai ($49/mo) — Workflows, short-form copy                │
│  └── Nexus advantage: Open-source, local LLM, multi-model          │
│                                                                     │
│  MARKETING AUTOMATION:                                              │
│  ├── HubSpot ($890+/mo) — CRM + full automation                   │
│  ├── Salesforce MC ($1,250+/mo) — Enterprise only                  │
│  ├── Mautic (free, self-hosted) — PHP, no AI                      │
│  └── Nexus advantage: AI-native, agent-based, affordable           │
│                                                                     │
│  NEXUS UNIQUE VALUE:                                                │
│  ├── 1. Self-hosted, data stays local                              │
│  ├── 2. Multi-model (Ollama local + Claude cloud + Claude Code)    │
│  ├── 3. Sub-agent orchestration (parallel research + generation)   │
│  ├── 4. Plugin architecture (extend with any integration)          │
│  ├── 5. Full agency workflow (not just content generation)         │
│  └── 6. Open-core with marketplace (vs. closed SaaS)              │
│                                                                     │
│  WHAT TO STEAL FROM COMPETITORS:                                    │
│  ├── Jasper: Brand Voice profiles, template library, SEO scoring  │
│  ├── Copy.ai: Multi-step workflows, research→generate pipelines   │
│  ├── HubSpot: CRM integration, attribution, workflow automation   │
│  └── Mautic: Self-hosted marketing automation API design          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. Content Generation Best Practices

### 6.1 Brand Voice Consistency

**This is the #1 most requested feature in AI content generation tools.**

**Architecture for Brand Voice System:**

```
BrandVoiceProfile:
  ├── brand_name: str
  ├── industry: str
  ├── tone_attributes: list[str]  # ["professional", "friendly", "authoritative"]
  ├── avoid_attributes: list[str]  # ["casual", "salesy", "jargon-heavy"]
  ├── vocabulary:
  │   ├── preferred_terms: dict[str, str]  # {"customer" -> "client"}
  │   ├── banned_terms: list[str]  # ["synergy", "paradigm shift"]
  │   └── brand_terms: list[str]  # Product names, branded phrases
  ├── writing_rules: list[str]
  │   # ["Always use active voice", "Keep sentences under 25 words"]
  ├── example_content: list[str]  # 3-5 samples of ideal brand writing
  ├── target_audience: str  # Description of who the content is for
  ├── competitor_differentiation: str  # How to differentiate from competitors
  └── platform_guidelines: dict[str, str]
      # {"twitter": "Casual, emoji OK, max 280 chars",
      #  "linkedin": "Professional, no emoji, thought leadership"}
```

**Implementation Strategy:**
1. Store brand profiles in PostgreSQL (JSON column in a `brand_profiles` table)
2. Inject brand voice as system prompt prefix for all content generation
3. Post-generation brand voice checker (LLM evaluates alignment, scores 1-10)
4. Brand voice learning: Analyze user's existing content to auto-generate profile
5. Per-platform voice variations (Twitter casual vs. LinkedIn professional)

**System Prompt Template for Content Generation:**
```
You are a content writer for {brand_name}. Follow these brand guidelines strictly:

TONE: {tone_attributes}
AVOID: {avoid_attributes}
VOCABULARY: Always use "{preferred_term}" instead of "{generic_term}"
NEVER USE: {banned_terms}
RULES: {writing_rules}

TARGET AUDIENCE: {target_audience}

Here are examples of our brand's ideal writing style:
{example_content}

Now generate {content_type} about {topic} for {platform}.
```

---

### 6.2 Content Approval Workflows

**Essential for team/agency use. Content should never auto-publish without human review.**

**Recommended Workflow States:**

```
DRAFT → REVIEW → APPROVED → SCHEDULED → PUBLISHED → ARCHIVED
  │        │         │
  └─ REVISION ←─┘    └─ ON_HOLD (paused before publish)
```

**Implementation in Nexus:**
- Map to existing WorkRegistry/KanBan system
- Add `content_items` table: id, type, platform, content, brand_id, status, reviewer_id,
  scheduled_at, published_at, published_url, metadata (JSONB)
- WebSocket notifications for review requests
- Telegram integration: "New blog post ready for review. Approve/Reject?"
- Bulk approval for social media batches

**Approval Triggers:**
- All long-form content (blog, whitepaper): Always require review
- Social media posts: Configurable (auto-approve if brand voice score > 8/10)
- Ad copy: Always require review (money at stake)
- Email campaigns: Require review (reputation at stake)

---

### 6.3 Plagiarism & Originality Checking

**Options:**

1. **Copyscape API** ($0.03-0.05 per search)
   - Industry standard for plagiarism detection
   - API: `GET https://www.copyscape.com/api/?...`
   - Returns matching URLs with percentage overlap
   - Python: Direct HTTP via `httpx`

2. **Grammarly Business** (no public API for plagiarism)
   - Great product but no programmatic access

3. **Originality.ai** (AI content detection + plagiarism)
   - Detects AI-generated content + checks for plagiarism
   - API: REST, $0.01 per 100 words
   - Useful for: Checking if AI content is "too AI-detectable"
   - `[VERIFY-2026]` — AI detection tools evolve rapidly

4. **Built-in Approach (Recommended):**
   - Use Google Custom Search API (already in Nexus) to search key phrases
   - Extract top results and compare with cosine similarity
   - Flag content that closely matches existing web content
   - LLM-based originality scoring: "Rate this content 1-10 for originality and explain"
   - Saves external API costs, leverages existing Nexus infrastructure

---

### 6.4 Image Generation Integration

**Image generation is increasingly expected alongside text content.**

#### DALL-E (OpenAI)
- **API**: REST, well-documented
- **Python**: `openai` library (`pip install openai`)
- **Pricing**: DALL-E 3: $0.040 per image (1024x1024), $0.080 (1024x1792)
- **Features**: Text-to-image, inpainting, variations
- **Quality**: Good for marketing (stock photo replacement)
- **Limitations**: Sometimes struggles with text in images, brand-specific elements

```python
from openai import OpenAI
client = OpenAI(api_key="YOUR_KEY")
response = client.images.generate(
    model="dall-e-3",
    prompt="Professional product photo of...",
    size="1024x1024",
    n=1,
)
image_url = response.data[0].url
```

#### Stable Diffusion (via API or local)
- **API providers**: Stability AI API, Replicate, Together AI
- **Local**: Can run on Mac Studio M4 Max via `diffusers` library
  - Models: SDXL, SD 3.x, Flux (via compatible forks)
  - Requires ~8-12GB VRAM for SDXL
- **Python**: `diffusers` library (`pip install diffusers`)
- **Pricing**: Free (local), $0.002-0.02 per image (API)
- **Advantage**: Self-hosted = unlimited, privacy-preserving

```python
# Local generation on Mac Studio
from diffusers import StableDiffusionXLPipeline
import torch

pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16
)
pipe = pipe.to("mps")  # Apple Silicon
image = pipe("Marketing banner for tech company, modern, clean").images[0]
```

#### Flux
- Latest generation open-source image model (Black Forest Labs)
- `[VERIFY-2026]` — Flux was rapidly evolving in late 2024/early 2025
- Available via: Replicate API, Together AI, local (requires significant compute)
- Excellent for photorealistic marketing imagery
- **Recommendation**: Monitor Flux evolution, integrate via Replicate/Together API

#### Midjourney
- **No public API** as of early 2025 `[VERIFY-2026]`
- Discord bot interface only
- Unofficial API wrappers exist but violate ToS
- **Not recommended for programmatic integration** until official API launches
- Can support via "prompt generation" — Nexus generates optimized Midjourney prompts
  that users paste into Discord

**Image Generation Recommendation:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  PRIMARY: DALL-E 3 API (best quality for marketing, simple API)    │
│  LOCAL: Stable Diffusion XL on Mac Studio M4 Max (free, private)  │
│  FUTURE: Flux via Replicate/Together (best open-source quality)   │
│  PROMPT-ONLY: Midjourney prompt generator (no API available)       │
│                                                                     │
│  APPROACH: ImageProvider protocol                                   │
│  └── DallEAdapter / StableDiffusionLocal / FluxAdapter             │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 6.5 Video Script Generation

**For TikTok/YouTube/Reels content:**

**Script Format for Short-form Video:**
```
VideoScript:
  ├── hook (0-3 sec): Attention-grabbing opening
  ├── problem (3-8 sec): Identify the pain point
  ├── solution (8-25 sec): Present the solution/content
  ├── proof (25-40 sec): Evidence, testimonial, demonstration
  ├── cta (40-60 sec): Call to action
  ├── caption: Platform-optimized text
  ├── hashtags: Relevant hashtags (researched)
  ├── music_suggestion: Trending audio recommendation
  └── visual_notes: Shot-by-shot visual direction
```

**Implementation:** LLM-powered with platform-specific prompts. Include trending
format awareness (e.g., "Get Ready With Me", "Day in the Life", etc.).

---

## 7. Marketing Analytics & Attribution

### 7.1 Google Analytics 4 (GA4) API

**Essential for website analytics. GA4 replaced Universal Analytics in 2023.**

**API Capabilities (GA4 Data API):**
- **Run Reports**: Custom reports with dimensions, metrics, date ranges, filters
- **Batch Reports**: Multiple reports in one request
- **Real-time Reports**: Current active users, events
- **Audience Export**: Export audience lists
- **Funnel Reports**: Visualize user journeys
- **Available Metrics**: Sessions, users, events, conversions, revenue, engagement
- **Available Dimensions**: Source, medium, campaign, page, country, device, etc.

**API Details:**
- REST API (`google.analytics.data` v1beta → v1)
- OAuth 2.0 or service account
- Rate limit: Core reporting: 10 requests per second per project, 10,000 per day
- Data freshness: 24-48 hours (standard), 4 hours (real-time)

**Python Library:**
- `google-analytics-data` (official): `pip install google-analytics-data`

```python
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension

client = BetaAnalyticsDataClient()
request = RunReportRequest(
    property=f"properties/{GA4_PROPERTY_ID}",
    dimensions=[
        Dimension(name="sessionSourceMedium"),
        Dimension(name="sessionCampaignName"),
    ],
    metrics=[
        Metric(name="sessions"),
        Metric(name="conversions"),
        Metric(name="totalRevenue"),
    ],
    date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
)
response = client.run_report(request)
```

**Pricing:** Free (GA4 is free for up to 10M events/mo; GA360 for enterprise).

---

### 7.2 UTM Parameter Management

**Critical for attribution. Every marketing link needs UTMs.**

**UTM Parameters:**
- `utm_source`: Where traffic comes from (google, facebook, newsletter)
- `utm_medium`: Marketing medium (cpc, email, social, organic)
- `utm_campaign`: Campaign name (spring_sale_2026)
- `utm_content`: Differentiates similar content (cta_button_red, banner_v2)
- `utm_term`: Paid search keywords

**Implementation for Nexus:**
```python
class UTMBuilder:
    def build_url(self, base_url: str, source: str, medium: str,
                  campaign: str, content: str = "", term: str = "") -> str:
        """Build UTM-tagged URL with validation and tracking."""
        params = {
            "utm_source": source,
            "utm_medium": medium,
            "utm_campaign": self._slugify(campaign),
        }
        if content: params["utm_content"] = content
        if term: params["utm_term"] = term
        # Store in DB for tracking and deduplication
        # Generate short URL via Bitly/Rebrandly API (optional)
        return f"{base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
```

**Auto-UTM for All Marketing Content:**
Every piece of content generated by Nexus should automatically have UTM parameters:
- Blog posts shared on social: `utm_source=twitter&utm_medium=social&utm_campaign={campaign_name}`
- Email links: `utm_source=mailchimp&utm_medium=email&utm_campaign={campaign_name}`
- Ad landing pages: `utm_source=google&utm_medium=cpc&utm_campaign={campaign_name}`

---

### 7.3 Multi-Touch Attribution Models

**Attribution answers: "Which marketing channel gets credit for the conversion?"**

**Models to Implement:**

1. **Last-Click** (simplest, default in GA4):
   - 100% credit to last touchpoint before conversion
   - Easy to implement, but undervalues awareness channels

2. **First-Click**:
   - 100% credit to first touchpoint
   - Good for understanding discovery channels

3. **Linear**:
   - Equal credit to all touchpoints
   - Fair but may over-credit irrelevant touches

4. **Time-Decay**:
   - More credit to touchpoints closer to conversion
   - Exponential decay function
   - Good balance for most businesses

5. **Position-Based (U-Shaped)**:
   - 40% to first touch, 40% to last touch, 20% split among middle
   - Popular compromise model

6. **Data-Driven** (requires significant data volume):
   - ML model learns from conversion paths
   - Requires 300+ conversions per month minimum
   - Google's DDA model uses Shapley values
   - **Implementation**: Nexus can build this with enough conversion data

**Data Sources for Attribution:**
- Google Analytics 4 (web sessions, conversions)
- UTM parameters on all marketing links
- CRM data (if integrated — e.g., HubSpot)
- Ad platform conversion data (Google Ads, Meta Ads)
- Email engagement data (Mailchimp opens/clicks)

**Implementation Approach:**
```python
class AttributionEngine:
    """Multi-touch attribution calculator."""

    def attribute(self, conversion_path: list[TouchPoint],
                  model: str = "time_decay") -> dict[str, float]:
        """
        Convert a list of touchpoints into channel-level credit allocation.

        Returns: {"google_cpc": 0.45, "email": 0.30, "organic": 0.25}
        """
        if model == "last_click":
            return self._last_click(conversion_path)
        elif model == "first_click":
            return self._first_click(conversion_path)
        elif model == "linear":
            return self._linear(conversion_path)
        elif model == "time_decay":
            return self._time_decay(conversion_path, half_life_days=7)
        elif model == "position_based":
            return self._position_based(conversion_path)
        elif model == "data_driven":
            return self._data_driven(conversion_path)
```

---

### 7.4 Marketing Dashboard & Reporting

**Unified view across all channels. The "single pane of glass" for marketing.**

**Metrics to Aggregate:**

| Category | Metrics | Source |
|----------|---------|--------|
| Website | Sessions, users, bounce rate, conversion rate | GA4 |
| SEO | Organic traffic, keyword rankings, backlinks | GSC + Ahrefs/SEMrush |
| Social | Followers, engagement rate, reach, impressions | Platform APIs / Ayrshare |
| Email | Open rate, click rate, unsubscribe rate, revenue | Mailchimp / SendGrid |
| Paid (Google) | Impressions, clicks, CTR, CPC, conversions, ROAS | Google Ads API |
| Paid (Meta) | Impressions, reach, clicks, CPC, conversions, ROAS | Meta Marketing API |
| Content | Posts published, content score, engagement per post | Internal tracking |
| Attribution | Revenue by channel, conversion paths, LTV by channel | Attribution engine |

**Automated Report Generation:**
- Weekly marketing summary (auto-generated, sent via email or Telegram)
- Monthly performance report (PDF/Markdown, with charts)
- Real-time alerts: "Ad spend exceeded budget by 20%", "Email bounce rate spike"
- Trend analysis: "Organic traffic up 15% MoM", "Twitter engagement declining"

**Implementation:** Store all metrics in a `marketing_metrics` table (time-series),
build aggregation queries, use LLM to generate natural-language insights.

---

## 8. Recommended Architecture for Nexus

### 8.1 Plugin Structure

The marketing agency capability should be split across **4 Nexus plugins** plus
a **marketing core module**:

```
backend/
├── core/
│   ├── marketing/
│   │   ├── __init__.py
│   │   ├── brand_voice.py          # Brand voice profiles + content scoring
│   │   ├── content_engine.py       # Content generation orchestration
│   │   ├── content_types.py        # Templates for blog, social, email, ad copy
│   │   ├── seo_engine.py           # Built-in SEO analysis + optimization
│   │   ├── utm_builder.py          # UTM parameter management
│   │   ├── attribution.py          # Multi-touch attribution models
│   │   ├── campaign_planner.py     # Campaign planning + calendar
│   │   └── approval_workflow.py    # Content approval state machine
│   │
├── plugins/
│   ├── social_media_plugin.py      # Social posting, scheduling, analytics
│   ├── email_marketing_plugin.py   # Email campaigns, sequences, analytics
│   ├── ads_plugin.py               # Google Ads + Meta Ads management
│   └── seo_plugin.py               # External SEO tools (Ahrefs/SEMrush/GSC)
```

### 8.2 Database Schema Additions

```sql
-- Brand voice profiles
CREATE TABLE brand_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,  -- tenant isolation
    name VARCHAR(255) NOT NULL,
    industry VARCHAR(100),
    tone_attributes JSONB DEFAULT '[]',
    avoid_attributes JSONB DEFAULT '[]',
    vocabulary JSONB DEFAULT '{}',
    writing_rules JSONB DEFAULT '[]',
    example_content JSONB DEFAULT '[]',
    target_audience TEXT,
    platform_guidelines JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Marketing content items (unified across all channels)
CREATE TABLE content_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,
    brand_id UUID REFERENCES brand_profiles(id),
    campaign_id UUID REFERENCES campaigns(id),
    content_type VARCHAR(50) NOT NULL,  -- blog, social_post, email, ad_copy, landing_page
    platform VARCHAR(50),  -- twitter, linkedin, instagram, facebook, tiktok, email, google_ads, meta_ads
    title VARCHAR(500),
    body TEXT NOT NULL,
    media_urls JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',  -- hashtags, utm_params, targeting, etc.
    brand_voice_score FLOAT,
    seo_score FLOAT,
    status VARCHAR(20) DEFAULT 'draft',  -- draft, review, approved, scheduled, published, archived
    reviewer_id UUID,
    reviewed_at TIMESTAMP,
    scheduled_at TIMESTAMP,
    published_at TIMESTAMP,
    published_url VARCHAR(1000),
    external_id VARCHAR(255),  -- ID from external platform (tweet ID, post ID, etc.)
    engagement JSONB DEFAULT '{}',  -- likes, shares, comments, views, clicks
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Marketing campaigns
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,
    brand_id UUID REFERENCES brand_profiles(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    goal VARCHAR(100),  -- awareness, engagement, traffic, leads, sales
    channels JSONB DEFAULT '[]',  -- ["twitter", "linkedin", "email", "google_ads"]
    target_audience JSONB DEFAULT '{}',
    budget JSONB DEFAULT '{}',  -- {"total": 5000, "google_ads": 2000, "meta_ads": 2000, "content": 1000}
    schedule JSONB DEFAULT '{}',  -- {"start": "2026-03-01", "end": "2026-03-31"}
    kpis JSONB DEFAULT '{}',  -- {"target_leads": 500, "target_roas": 3.0}
    status VARCHAR(20) DEFAULT 'planning',  -- planning, active, paused, completed
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Marketing calendar
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,
    campaign_id UUID REFERENCES campaigns(id),
    content_id UUID REFERENCES content_items(id),
    title VARCHAR(255) NOT NULL,
    event_type VARCHAR(50),  -- post, email_send, ad_launch, report, meeting
    platform VARCHAR(50),
    scheduled_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Marketing metrics (time-series)
CREATE TABLE marketing_metrics (
    id BIGSERIAL PRIMARY KEY,
    org_id UUID,
    channel VARCHAR(50) NOT NULL,  -- organic, social_twitter, social_linkedin, email, google_ads, meta_ads
    metric_name VARCHAR(100) NOT NULL,  -- impressions, clicks, conversions, revenue, followers, etc.
    metric_value FLOAT NOT NULL,
    dimensions JSONB DEFAULT '{}',  -- {"campaign": "spring_sale", "platform": "twitter"}
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_metrics_channel_date ON marketing_metrics(channel, recorded_at);
CREATE INDEX idx_metrics_org_date ON marketing_metrics(org_id, recorded_at);

-- Connected platform accounts
CREATE TABLE platform_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID,
    platform VARCHAR(50) NOT NULL,  -- twitter, linkedin, instagram, facebook, tiktok, mailchimp, etc.
    account_name VARCHAR(255),
    account_id VARCHAR(255),
    access_token_encrypted TEXT,  -- encrypted via Fernet (same as config_manager)
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMP,
    scopes JSONB DEFAULT '[]',
    config JSONB DEFAULT '{}',  -- platform-specific config (e.g., ayrshare profile ID)
    is_active BOOLEAN DEFAULT TRUE,
    connected_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP
);
```

### 8.3 Sub-Agent Orchestration Patterns for Marketing

**Content Campaign Launch (5-agent orchestration):**
```python
OrchestrationStrategy.marketing_campaign_launch(brief: str):
    Layer 1 (parallel):
        - Researcher: Market research + competitor analysis
        - SEO Researcher: Keyword research + SERP analysis
    Layer 2 (parallel, depends on Layer 1):
        - Blog Writer: Long-form content with SEO optimization
        - Social Writer: Platform-specific social posts (5 platforms)
        - Email Writer: Email campaign sequence (3 emails)
    Layer 3 (depends on all):
        - Synthesizer: Merge into unified campaign brief with content calendar
```

**Competitor Analysis (3-agent orchestration):**
```python
OrchestrationStrategy.competitor_analysis(competitors: list[str]):
    Layer 1 (parallel, one per competitor):
        - Researcher[0]: Analyze competitor[0] website, social, content
        - Researcher[1]: Analyze competitor[1] website, social, content
        - Researcher[N]: ...
    Layer 2:
        - Synthesizer: Comparative analysis, strengths/weaknesses, opportunities
```

**A/B Content Generation (2-agent):**
```python
OrchestrationStrategy.ab_content(brief: str, content_type: str):
    Layer 1 (parallel):
        - Builder A (Ollama): Generate variant A
        - Builder B (Claude): Generate variant B
    Layer 2:
        - Reviewer: Compare variants, score both, recommend winner
```

### 8.4 Integration with Existing Nexus Systems

**WorkRegistry Integration:**
- Campaign creation → WorkRegistry item (kind="campaign")
- Content generation → WorkRegistry item (kind="content", parent_id=campaign)
- Publishing → WorkRegistry item (kind="publish", parent_id=content)
- Analytics pull → WorkRegistry item (kind="analytics_sync")

**Knowledge Graph Integration:**
- Store brand profiles as entities in KG
- Campaign performance history as relationships
- Competitor intelligence as entities with temporal relationships
- Content topics and keyword clusters as graph nodes

**Memory System Integration:**
- Passive memory learns client preferences, content styles, best-performing topics
- RAG retrieval for brand context when generating content
- Historical campaign data informs future recommendations

**Reminder System Integration:**
- Content publishing schedule → Reminders
- Campaign milestone alerts
- Analytics report generation triggers
- Budget threshold warnings

---

## 9. Plugin Design

### 9.1 Social Media Plugin

```python
class SocialMediaPlugin(NexusPlugin):
    name = "social"
    description = "Social media management — posting, scheduling, analytics across platforms"
    version = "1.0.0"

    # Tools to register:
    # - social_post: Post content to one or more platforms
    # - social_schedule: Schedule a post for future publishing
    # - social_analytics: Get engagement metrics for a post or account
    # - social_accounts: List connected social media accounts
    # - social_trending: Get trending hashtags/topics for a platform
    # - social_calendar: View/manage the social media content calendar
    # - social_monitor: Check mentions/comments across platforms
    # - social_reply: Reply to a comment/mention on a platform

    # Commands:
    # /post <platform> <content>: Quick post to a platform
    # /schedule <datetime> <platform> <content>: Schedule a post
    # /social-stats [platform]: Show social media analytics summary
```

### 9.2 Email Marketing Plugin

```python
class EmailMarketingPlugin(NexusPlugin):
    name = "email_marketing"
    description = "Email campaign management — create, send, analyze email campaigns"
    version = "1.0.0"

    # Tools to register:
    # - email_create_campaign: Create a new email campaign
    # - email_set_content: Set HTML/text content for a campaign
    # - email_schedule: Schedule campaign for sending
    # - email_send_test: Send test email to verify content
    # - email_analytics: Get campaign performance metrics
    # - email_list_manage: Manage subscriber lists and segments
    # - email_template_list: List available email templates
    # - email_automation_create: Create an email automation sequence
    # - email_ab_test: Set up A/B test for a campaign

    # Commands:
    # /email-blast <list> <subject>: Quick email campaign creation
    # /email-stats [campaign_id]: Show email analytics
```

### 9.3 Ads Plugin

```python
class AdsPlugin(NexusPlugin):
    name = "ads"
    description = "Paid advertising management — Google Ads, Meta Ads, LinkedIn Ads"
    version = "1.0.0"

    # Tools to register:
    # - ads_create_campaign: Create ad campaign on a platform
    # - ads_manage_budget: Set/adjust campaign budgets
    # - ads_performance: Get campaign performance metrics
    # - ads_keywords: Manage keywords (Google Ads)
    # - ads_audiences: Manage targeting audiences
    # - ads_creative: Create/update ad creatives
    # - ads_recommendations: Get optimization recommendations
    # - ads_pause: Pause a campaign
    # - ads_resume: Resume a paused campaign

    # Commands:
    # /ads-report [platform]: Show ads performance summary
    # /ads-budget <campaign> <amount>: Quick budget adjustment
```

### 9.4 SEO Plugin

```python
class SEOPlugin(NexusPlugin):
    name = "seo"
    description = "SEO analysis and optimization — keyword research, site audit, ranking tracking"
    version = "1.0.0"

    # Tools to register:
    # - seo_keyword_research: Research keywords (volume, difficulty, CPC)
    # - seo_site_audit: Run technical SEO audit on a URL
    # - seo_backlink_analysis: Analyze backlink profile
    # - seo_competitor_analysis: Compare SEO metrics with competitors
    # - seo_content_optimize: Score and optimize content for target keywords
    # - seo_rank_check: Check ranking position for keywords
    # - seo_serp_analysis: Analyze top SERP results for a keyword
    # - seo_search_console: Query Google Search Console data

    # Commands:
    # /seo-audit <url>: Quick SEO audit
    # /keywords <topic>: Quick keyword research
    # /rankings [domain]: Show keyword rankings
```

---

## 10. Implementation Roadmap

### Phase 1: Foundation (1-2 weeks)
**Core marketing infrastructure:**
1. `core/marketing/` module: brand_voice.py, content_types.py, utm_builder.py
2. Database schema: brand_profiles, content_items, campaigns, calendar_events, marketing_metrics, platform_connections
3. Brand Voice system: Create/edit profiles, inject into system prompts, score content
4. Content approval workflow state machine
5. Marketing-specific sub-agent orchestration strategies

### Phase 2: Social Media (1-2 weeks)
**Social posting and analytics:**
1. `social_media_plugin.py` with Ayrshare integration (primary)
2. Direct Twitter/X API support via `tweepy` (for features Ayrshare misses)
3. Social media content calendar
4. Platform-specific content formatting (character limits, hashtag rules, media specs)
5. Engagement monitoring + notification
6. Analytics aggregation from connected platforms

### Phase 3: Email Marketing (1 week)
**Email campaign management:**
1. `email_marketing_plugin.py` with Mailchimp API (primary)
2. SendGrid adapter for transactional email
3. Email template management
4. Sequence/automation creation
5. A/B testing setup
6. Email analytics dashboard

### Phase 4: SEO (1 week)
**SEO analysis and content optimization:**
1. `seo_plugin.py` with Google Search Console (free, essential)
2. Ahrefs/SEMrush adapter (optional, for users with subscriptions)
3. Built-in content optimization engine (LLM + SERP analysis)
4. Keyword research tool using combination of data sources
5. Technical SEO audit (built-in, using web_fetch + Playwright)
6. On-page SEO checker

### Phase 5: Advertising (1-2 weeks)
**Paid ads management:**
1. `ads_plugin.py` with Google Ads API
2. Meta Marketing API adapter
3. Campaign creation workflows
4. Budget management + alerts
5. Performance reporting with GAQL
6. Automated optimization recommendations

### Phase 6: Analytics & Attribution (1 week)
**Unified marketing intelligence:**
1. GA4 API integration
2. Attribution engine (5 models)
3. Unified marketing dashboard (admin-ui page)
4. Automated report generation (weekly/monthly)
5. Cross-channel metrics aggregation
6. AI-powered insights (LLM analyzes metrics, generates recommendations)

### Phase 7: Content Generation Excellence (ongoing)
**The AI competitive advantage:**
1. Blog post generator with SEO optimization + brand voice
2. Social media batch generation (5 platforms from single brief)
3. Email sequence writer
4. Ad copy generator with platform-specific formatting
5. Landing page copy generator
6. Video script generator (TikTok/YouTube format)
7. Image generation integration (DALL-E / Stable Diffusion)
8. Content repurposing engine (blog -> social -> email -> ads)

---

## Summary: Total Integration Surface

### External APIs (by priority):

| Priority | API | Python Package | Monthly Cost | Purpose |
|----------|-----|---------------|-------------|---------|
| P0 | Ayrshare | social-post-api | $99 | Multi-platform social posting |
| P0 | Mailchimp | mailchimp-marketing | $0-20 | Email campaigns |
| P0 | Google Search Console | google-api-python-client | Free | SEO data |
| P0 | Google Analytics 4 | google-analytics-data | Free | Website analytics |
| P1 | Twitter/X API | tweepy | $100 | Direct Twitter features |
| P1 | Google Ads | google-ads | Free (+ ad spend) | Search/display ads |
| P1 | Meta Marketing | facebook-business | Free (+ ad spend) | Facebook/Instagram ads |
| P1 | SendGrid | sendgrid | $0-90 | Transactional email |
| P2 | LinkedIn API | httpx (custom) | Free | LinkedIn posting/analytics |
| P2 | Ahrefs | httpx (custom) | $99-399 | SEO intelligence |
| P2 | DALL-E | openai | ~$0.04/image | Image generation |
| P3 | SEMrush | httpx (custom) | $130-500 | SEO intelligence (alt) |
| P3 | Resend | resend | $0-20 | Email (developer alt) |
| P3 | Brevo | sib-api-v3-sdk | $0-65 | Multi-channel (email+SMS) |
| P3 | LinkedIn Marketing | httpx (custom) | Free (+ ad spend) | LinkedIn ads |

### New Python Dependencies (requirements.txt additions):

```
# Marketing Agency - Social Media
tweepy>=4.14.0                    # Twitter/X API
social-post-api>=1.0.0            # Ayrshare multi-platform posting [VERIFY-2026]
facebook-sdk>=3.1.0               # Meta Graph API (organic)

# Marketing Agency - Email
mailchimp-marketing>=3.0.80       # Mailchimp campaigns
sendgrid>=6.11.0                  # SendGrid transactional email

# Marketing Agency - Advertising
google-ads>=24.0.0                # Google Ads API [VERIFY-2026 version]
facebook-business>=19.0.0         # Meta Marketing API [VERIFY-2026 version]

# Marketing Agency - SEO & Analytics
google-api-python-client>=2.0.0   # Google Search Console + PageSpeed
google-auth>=2.28.0               # Google auth for all Google APIs
google-analytics-data>=0.18.0     # GA4 Data API [VERIFY-2026 version]

# Marketing Agency - Image Generation (optional)
openai>=1.0.0                     # DALL-E image generation

# Marketing Agency - Content Quality (optional)
# diffusers>=0.27.0               # Local Stable Diffusion (large dependency)
```

### New Database Tables: 6
- `brand_profiles`, `content_items`, `campaigns`, `calendar_events`,
  `marketing_metrics`, `platform_connections`

### New Files: ~15-20
- 4 plugins (~300-500 lines each)
- 8 core modules (~150-300 lines each)
- 2 admin-ui pages (marketing dashboard, content calendar)
- 1 chat-ui component (marketing panel)

### Estimated Total New Code: ~5,000-8,000 lines

---

## Items Requiring Live Web Verification [VERIFY-2026]

The following items were based on training knowledge through early 2025 and should be
verified against current documentation:

1. **Twitter/X API pricing tiers** — X changes pricing frequently
2. **LinkedIn Community Management API** approval process and timeline
3. **Instagram Stories API** — Meta may have added Stories publishing
4. **TikTok Content Posting API** — May have expanded capabilities
5. **Ayrshare feature set and pricing** — Fast-growing startup, likely changed
6. **Buffer platform support** — Regularly adds new platforms
7. **SurferSEO API availability** — Was in beta, may be GA now
8. **Clearscope API** — May have launched public API
9. **Midjourney API** — Long-awaited, may have launched
10. **Flux model availability** — Rapidly evolving in late 2024/2025
11. **Google Ads API version** — New versions released regularly
12. **Meta Graph API version** — Versions deprecated every 2 years
13. **Resend Audiences/Broadcasts** — Was new in 2024, likely matured
14. **ConvertKit/Kit API v4** — Was in beta
15. **Jasper API** — Was enterprise-only, may have expanded
16. **Copy.ai workflow API** — Was enterprise-only, may have expanded
17. **Python SDK versions** for all listed packages
18. **Rate limits** for all APIs (frequently adjusted)

**Recommendation:** Run a verification session with WebSearch/WebFetch enabled to
spot-check the top 10 items above before beginning implementation.
