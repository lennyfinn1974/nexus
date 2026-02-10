import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings, useSystemPrompt } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'

export default function PersonaPage() {
  const { data, isLoading } = useSettings()
  const { data: prompt, refetch: refetchPrompt } = useSystemPrompt()
  const update = useUpdateSettings()

  const [name, setName] = useState('Nexus')
  const [tone, setTone] = useState('balanced')
  const [instructions, setInstructions] = useState('')

  useEffect(() => {
    if (data) {
      for (const s of data.settings) {
        if (s.key === 'AGENT_NAME') setName(s.value || 'Nexus')
        if (s.key === 'PERSONA_TONE') setTone(s.value || 'balanced')
        if (s.key === 'CUSTOM_SYSTEM_PROMPT') setInstructions(s.value || '')
      }
    }
  }, [data])

  if (isLoading) return <CardSkeleton />

  function save() {
    update.mutate(
      { AGENT_NAME: name, PERSONA_TONE: tone, CUSTOM_SYSTEM_PROMPT: instructions },
      {
        onSuccess: () => { toast.success('Persona saved!'); refetchPrompt() },
        onError: () => toast.error('Save failed'),
      }
    )
  }

  return (
    <div className="space-y-6">
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Agent Identity</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="text-xs">Agent Name</Label>
            <p className="mb-1.5 text-[10px] text-muted-foreground">The name the agent uses to identify itself</p>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <Label className="text-xs">Response Tone</Label>
            <p className="mb-1.5 text-[10px] text-muted-foreground">Overall tone for agent responses</p>
            <Select value={tone} onValueChange={setTone}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="professional">Professional</SelectItem>
                <SelectItem value="balanced">Balanced</SelectItem>
                <SelectItem value="casual">Casual</SelectItem>
                <SelectItem value="technical">Technical</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Custom Instructions</Label>
            <p className="mb-1.5 text-[10px] text-muted-foreground">Extra behaviour instructions appended to the system prompt</p>
            <Textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="e.g. Always respond in British English. You work for Acme Corp."
              rows={5}
            />
          </div>
          <Button onClick={save} disabled={update.isPending}>
            {update.isPending ? 'Saving...' : 'Save Persona'}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">System Prompt Preview</CardTitle></CardHeader>
        <CardContent>
          <ScrollArea className="h-72">
            <pre className="whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
              {prompt?.full_prompt || 'Loading...'}
            </pre>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}
