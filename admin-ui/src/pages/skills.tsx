import { useState, useEffect } from 'react'
import {
  useSkills, useSkillPacks, useDeleteSkill, useInstallSkillPack,
  useCatalogSearch, useCatalogCategories, useInstallCatalogSkill,
} from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import StatusBadge from '@/components/shared/status-badge'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import { Trash2, Download, Search, Package, ChevronDown, ChevronUp } from 'lucide-react'

export default function SkillsPage() {
  const { data: skills, isLoading } = useSkills()
  const { data: packs } = useSkillPacks()
  const deleteSkill = useDeleteSkill()
  const installPack = useInstallSkillPack()
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  // Catalog state
  const [catalogQuery, setCatalogQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null)

  const { data: categories } = useCatalogCategories()
  const { data: searchResults, isLoading: isSearching } = useCatalogSearch(debouncedQuery, selectedCategory)
  const installCatalog = useInstallCatalogSkill()

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(catalogQuery), 300)
    return () => clearTimeout(timer)
  }, [catalogQuery])

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-6">
      {/* Installed Skills */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Installed Skills</CardTitle></CardHeader>
        <CardContent>
          {!skills?.length ? (
            <p className="text-sm text-muted-foreground">No skills learned yet. Use <code>/learn &lt;topic&gt;</code> to start.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Domain</TableHead>
                  <TableHead className="text-right">Usage</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {skills.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="text-sm font-medium">{s.name}</TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px]">{s.type}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.domain}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{s.usage_count ?? 0}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget({ id: s.id, name: s.name })}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Skill Packs */}
      {(packs ?? []).length > 0 && (
        <Card className="border-border bg-card">
          <CardHeader><CardTitle className="text-sm">Available Skill Packs</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {packs?.map((p) => (
              <div key={p.id} className="flex items-center gap-4 rounded-lg border border-border bg-background p-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{p.name}</span>
                    <Badge variant="outline" className="text-[10px]">{p.type}</Badge>
                    {p.installed && <StatusBadge status="completed" />}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{p.description}</p>
                  {p.domain && <p className="mt-0.5 text-[10px] text-muted-foreground">Domain: {p.domain}</p>}
                  {p.config_keys.length > 0 && (
                    <p className="mt-0.5 text-[10px] text-muted-foreground">
                      Config: {p.config_keys.join(', ')}
                    </p>
                  )}
                </div>
                <Button
                  size="sm"
                  disabled={p.installed || installPack.isPending}
                  onClick={() => installPack.mutate(p.id, {
                    onSuccess: () => toast.success(`Installed ${p.name}`),
                    onError: (e) => toast.error(e.message),
                  })}
                >
                  <Download className="mr-1 h-3 w-3" />
                  {p.installed ? 'Installed' : 'Install'}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Skill Catalog Browser */}
      <Card className="border-border bg-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Package className="h-4 w-4" />
              Skill Catalog
            </CardTitle>
            {categories && (
              <span className="text-xs text-muted-foreground">
                {categories.reduce((sum: number, c: { count: number }) => sum + c.count, 0)} skills available
              </span>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search skills... (e.g. 'rag', 'react', 'security audit')"
              value={catalogQuery}
              onChange={(e) => setCatalogQuery(e.target.value)}
              className="pl-10"
            />
          </div>

          {/* Category Pills */}
          {categories && categories.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              <button
                className={`rounded-full px-3 py-1 text-[10px] font-medium transition-colors ${
                  selectedCategory === ''
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:bg-muted/80'
                }`}
                onClick={() => setSelectedCategory('')}
              >
                All
              </button>
              {categories.map((c: { category: string; count: number }) => (
                <button
                  key={c.category}
                  className={`rounded-full px-3 py-1 text-[10px] font-medium transition-colors ${
                    selectedCategory === c.category
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/80'
                  }`}
                  onClick={() => setSelectedCategory(prev => prev === c.category ? '' : c.category)}
                >
                  {c.category} ({c.count})
                </button>
              ))}
            </div>
          )}

          {/* Results */}
          {isSearching && (
            <div className="py-4 text-center text-xs text-muted-foreground">Searching...</div>
          )}

          {!isSearching && searchResults?.results && searchResults.results.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">
                {searchResults.total} result{searchResults.total !== 1 ? 's' : ''}
              </div>
              {searchResults.results.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded-lg border border-border bg-background p-3 transition-colors hover:border-primary/30"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <button
                          className="text-sm font-medium text-foreground hover:text-primary"
                          onClick={() => setExpandedSkill(expandedSkill === entry.id ? null : entry.id)}
                        >
                          {entry.name}
                        </button>
                        <Badge variant="outline" className="text-[10px]">
                          {entry.category}
                        </Badge>
                        {entry.installed && (
                          <Badge variant="secondary" className="text-[10px] text-green-600">
                            installed
                          </Badge>
                        )}
                        {entry.size_kb > 0 && (
                          <span className="text-[10px] text-muted-foreground">{entry.size_kb} KB</span>
                        )}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                        {entry.description || 'No description available'}
                      </p>
                      <div className="mt-1 flex items-center gap-2">
                        <code className="text-[10px] text-muted-foreground">{entry.id}</code>
                        {entry.source && (
                          <span className="text-[10px] text-muted-foreground">via {entry.source}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={() => setExpandedSkill(expandedSkill === entry.id ? null : entry.id)}
                      >
                        {expandedSkill === entry.id
                          ? <ChevronUp className="h-3 w-3" />
                          : <ChevronDown className="h-3 w-3" />
                        }
                      </Button>
                      <Button
                        size="sm"
                        disabled={entry.installed || installCatalog.isPending}
                        onClick={() => installCatalog.mutate(entry.id, {
                          onSuccess: (d) => toast.success(d.message || `Installed ${entry.name}`),
                          onError: (e) => toast.error(e.message),
                        })}
                      >
                        <Download className="mr-1 h-3 w-3" />
                        {entry.installed ? 'Installed' : 'Install'}
                      </Button>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  {expandedSkill === entry.id && (
                    <div className="mt-3 border-t border-border pt-3">
                      <p className="text-xs text-muted-foreground">{entry.description}</p>
                      <div className="mt-2 text-[10px] text-muted-foreground">
                        Use <code className="rounded bg-muted px-1">@{entry.id}</code> to explicitly invoke this skill after installation.
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {!isSearching && debouncedQuery && searchResults?.results?.length === 0 && (
            <div className="py-8 text-center">
              <p className="text-sm text-muted-foreground">No skills found matching "{debouncedQuery}"</p>
              <p className="mt-1 text-xs text-muted-foreground">Try different keywords or browse categories</p>
            </div>
          )}

          {!debouncedQuery && !selectedCategory && (
            <div className="py-6 text-center">
              <p className="text-sm text-muted-foreground">Search for skills to browse the catalog</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Try: "rag", "react", "security", "brainstorming", "docker"
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
        title="Delete Skill?"
        description={`Permanently delete "${deleteTarget?.name}". This cannot be undone.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (deleteTarget) {
            deleteSkill.mutate(deleteTarget.id, {
              onSuccess: () => toast.success('Skill deleted'),
            })
          }
        }}
      />
    </div>
  )
}
