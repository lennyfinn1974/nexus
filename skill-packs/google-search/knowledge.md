# Google Search Integration

## Overview
This skill provides web search capabilities via Google's Custom Search JSON API.
Use it when users need current information, want to look something up, or ask
questions that require real-time web data.

## When to Use
- User asks to search for something or look something up
- User needs current/recent information not in your training data
- User asks "what is X?" for topics that may have recent developments
- User explicitly asks to search the web or Google something

## How to Use
Call the `google_search` action with a concise search query.
The action returns titles, snippets, and URLs for the top results.

**Tips for good queries:**
- Keep queries short and specific (3-7 words)
- Use key terms, not full sentences
- Add year or "latest" for time-sensitive queries
- Use quotes for exact phrases

## Presenting Results
- Summarise the key findings from search results
- Cite sources with their titles and URLs
- If results don't fully answer the question, suggest refining the search
- Never fabricate information — only use what the search returns
