# OpenClaw Bridge - Partnership Communication

## Overview
The OpenClaw Bridge enables seamless communication and task coordination between Nexus and Aries (the OpenClaw main agent). This creates a powerful AI partnership where each agent can leverage the other's specialized capabilities.

## Partnership Model

**Nexus Strengths:**
- Deep web research and data analysis
- Complex browser automation workflows
- Multi-API orchestration and data processing
- Specialized computational tasks

**Aries Strengths:**  
- macOS system integration and file management
- Real-time messaging and communication channels
- Calendar, notes, and productivity app control
- Immediate response and human interaction

## Communication Patterns

### Task Handoffs
Use when Nexus completes research/analysis and needs Aries to:
- Save results to Apple Notes or files
- Schedule follow-up reminders 
- Send notifications to messaging channels
- Perform system-level actions

### Assistance Requests
Use when Nexus encounters tasks requiring:
- File system access beyond its scope
- Integration with macOS-specific applications
- Real-time communication with humans
- System administration tasks

### Context Synchronization
Keep both agents aligned on:
- Current project status and priorities
- User preferences and working context
- Shared memory and decision history
- Task progress and outcomes

## Usage Examples

**Research Handoff:**
```
Task completed: "Comprehensive analysis of AI market trends"
Results: Generated 15-page report with charts and data
Handoff to Aries: Please save to Apple Notes and schedule review for tomorrow
```

**Assistance Request:**
```
Need help: file_management
Details: Found 500+ relevant research papers, need organized folder structure
Urgency: medium
Request to Aries: Can you create organized folders and move files?
```

**Context Sync:**
```
Context: task_progress
Data: Completed market analysis phase, moving to competitive intelligence
Sync with Aries: Keep shared project context updated
```

## Configuration Requirements

- **OPENCLAW_GATEWAY_URL:** Gateway API endpoint (usually http://localhost:18789)
- **OPENCLAW_TOKEN:** Authentication token from OpenClaw configuration

## Best Practices

1. **Clear Communication:** Always provide context about what was done and what's needed next
2. **Appropriate Handoffs:** Use Aries for system integration, keep complex analysis in Nexus
3. **Timely Updates:** Sync context regularly to maintain shared understanding
4. **Respectful Requests:** Acknowledge each agent's strengths and limitations
5. **Error Handling:** Gracefully handle communication failures and retry appropriately

## Error Recovery

If bridge communication fails:
1. Log the error with details
2. Attempt retry with exponential backoff
3. Store message for later delivery if possible
4. Alert user to configuration issues
5. Continue task execution where possible

This bridge transforms two capable agents into a unified, expert-level AI partnership.