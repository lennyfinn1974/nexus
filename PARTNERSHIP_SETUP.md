# 🤝 Aries ↔ Nexus Partnership Setup Guide

## 🎯 Partnership Vision
Create a powerful AI duo where Aries (OpenClaw) and Nexus work together seamlessly:
- **Aries:** macOS integration, real-time communication, system control
- **Nexus:** Deep research, web automation, data processing, custom workflows

## 📋 Setup Checklist

### ✅ Phase 1: Basic Setup (COMPLETED)
- [x] Nexus dependencies installed
- [x] Virtual environment configured  
- [x] Web interface running on http://localhost:8080
- [x] Admin panel accessible at http://localhost:8080/admin
- [x] OpenClaw Bridge skill created

### 🔧 Phase 2: Configuration (TO DO)

1. **Configure Anthropic API Key**
   - Go to http://localhost:8080/admin
   - Add your Anthropic API key for Claude access
   - This enables Nexus to use the same models as Aries

2. **Configure OpenClaw Bridge**
   - In Nexus admin, navigate to Skills → OpenClaw Bridge
   - Set configuration:
     - `OPENCLAW_GATEWAY_URL`: `http://localhost:18789`
     - `OPENCLAW_TOKEN`: `9df94ec862f0d1c64ff6e0e19efa7dd8fef90ec9b8ce63fd`

### 🚀 Phase 3: Partnership Activation

## 🛠️ Quick Start Commands

```bash
# Start Nexus
cd /Users/lennyfinn/Downloads/nexus
./start-nexus.sh

# In another terminal, test the bridge (after configuration)
curl -X POST http://localhost:8080/api/skills/openclaw-bridge/send_to_aries \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello Aries! Nexus is online and ready to collaborate!"}'
```

## 🤖 Partnership Commands

Once configured, Nexus can:

**Send messages to Aries:**
- "Send to Aries: Research complete, found 15 relevant sources"
- "Notify OpenClaw that the data analysis is finished"

**Request assistance:**
- "Aries help with file management - need to organize 500 PDFs"
- "Transfer to Aries: Save this report to Apple Notes"

**Task handoffs:**
- "Handoff to OpenClaw: Schedule reminder for tomorrow at 9 AM"
- "Aries can you send this summary via email to the team?"

## 📊 Current Nexus Capabilities

**Expert-Level Skills Already Installed:**
- 🔍 **Google Search** - Web research
- 🌐 **Browser Automation** - Selenium-powered web control  
- 📄 **Web Scraping** - Content extraction
- 💱 **Currency Converter** - Financial utilities
- 🔧 **GitHub Integration** - Repository management
- 🌉 **OpenClaw Bridge** - Direct communication with Aries

## 🎯 Partnership Use Cases

### Research → Action Pipeline
1. **Nexus**: "Research latest AI developments"
2. **Nexus**: Comprehensive web search, data analysis
3. **Nexus**: "Aries, save this 20-page report to Apple Notes"
4. **Aries**: File saved, reminder scheduled

### Automation → Integration Workflow  
1. **Nexus**: Browser automation to extract data
2. **Nexus**: Process and analyze data
3. **Nexus**: "Aries, send results via Slack"
4. **Aries**: Message sent, stakeholders notified

### Monitoring → Response System
1. **Nexus**: Monitor competitor websites
2. **Nexus**: Detect significant changes
3. **Nexus**: "Aries, urgent notification needed"
4. **Aries**: Immediate alerts sent

## 🔮 Future Enhancements

**Phase 4: Advanced Skills** (Next Sprint)
- 🧠 **Research Conductor** - Multi-source research aggregation
- 📊 **Data Transformer** - Advanced processing pipeline
- 🔗 **API Orchestrator** - Multi-API workflow coordination
- 📑 **Document Analyst** - PDF/image analysis
- 📈 **Pattern Detector** - Time-series analysis

## 🆘 Troubleshooting

**Bridge Connection Issues:**
1. Verify OpenClaw is running (should be on port 18789)
2. Check token matches in both systems
3. Test gateway: `curl http://localhost:18789/health`

**Skill Loading Problems:**  
1. Check logs in Nexus admin interface
2. Verify Python dependencies in virtual environment
3. Restart Nexus after configuration changes

---

**Ready to create the most powerful AI partnership ever assembled!** 🚀✨