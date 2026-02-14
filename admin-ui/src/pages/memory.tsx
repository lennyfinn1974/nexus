import { useMemoryStatus, useKnowledgeGraph } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import StatCard from '@/components/shared/stat-card'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import {
  Search, Upload, GitBranch, Hash, Layers,
} from 'lucide-react'

function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${
        active
          ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]'
          : 'bg-zinc-400'
      }`}
    />
  )
}

export default function MemoryPage() {
  const { data: status, isLoading: statusLoading } = useMemoryStatus(10000)
  const { data: kgData } = useKnowledgeGraph(100)

  if (statusLoading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </div>
    )
  }

  const rag = status?.rag_pipeline
  const embed = status?.embedding_service
  const kg = status?.knowledge_graph
  const kgGraph = kgData

  return (
    <div className="space-y-6">
      {/* Status overview */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard
          label="Embedding Service"
          value={embed?.available ? 'Active' : 'Inactive'}
          sub={embed?.model || 'Not configured'}
        />
        <StatCard
          label="RAG Pipeline"
          value={rag?.active ? 'Active' : 'Inactive'}
          sub={rag ? `${rag.total_retrievals} retrievals` : 'Not initialized'}
        />
        <StatCard
          label="Knowledge Graph"
          value={kg ? `${kg.total_entities} entities` : 'Inactive'}
          sub={kg ? `${kg.total_relationships} rels` : 'Not initialized'}
        />
        <StatCard
          label="Memory Index"
          value={status?.memory_index ? 'Active' : 'Inactive'}
          sub={status?.working_memory ? 'Working memory on' : 'Single-agent mode'}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Embedding Service */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Hash className="h-4 w-4" />
              Embedding Service
              <StatusDot active={!!embed?.available} />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {embed ? (
              <>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Model</span>
                  <span className="font-mono">{embed.model}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Dimensions</span>
                  <span>{embed.dims}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">API Calls</span>
                  <span>{embed.total_calls}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Errors</span>
                  <span className={embed.total_errors > 0 ? 'text-red-500' : ''}>
                    {embed.total_errors}
                  </span>
                </div>
                <div className="border-t pt-3 mt-3">
                  <p className="text-xs font-medium text-muted-foreground mb-2">Cache</p>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <div className="text-lg font-semibold">{embed.cache.size}</div>
                      <div className="text-xs text-muted-foreground">Cached</div>
                    </div>
                    <div>
                      <div className="text-lg font-semibold">{embed.cache.hits}</div>
                      <div className="text-xs text-muted-foreground">Hits</div>
                    </div>
                    <div>
                      <div className="text-lg font-semibold">
                        {(embed.cache.hit_rate * 100).toFixed(0)}%
                      </div>
                      <div className="text-xs text-muted-foreground">Hit Rate</div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Embedding service not initialized. Ensure Ollama is running with nomic-embed-text.
              </p>
            )}
          </CardContent>
        </Card>

        {/* RAG Pipeline */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Search className="h-4 w-4" />
              RAG Pipeline
              <StatusDot active={!!rag?.active} />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {rag ? (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div className="text-center p-3 rounded-lg bg-muted/50">
                    <div className="text-2xl font-bold">{rag.total_retrievals}</div>
                    <div className="text-xs text-muted-foreground flex items-center justify-center gap-1">
                      <Search className="h-3 w-3" /> Retrievals
                    </div>
                  </div>
                  <div className="text-center p-3 rounded-lg bg-muted/50">
                    <div className="text-2xl font-bold">{rag.total_ingests}</div>
                    <div className="text-xs text-muted-foreground flex items-center justify-center gap-1">
                      <Upload className="h-3 w-3" /> Ingests
                    </div>
                  </div>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Avg Retrieve Time</span>
                  <span>{rag.avg_retrieve_ms}ms</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Avg Ingest Time</span>
                  <span>{rag.avg_ingest_ms}ms</span>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                RAG pipeline requires both embedding service and Redis clustering to be active.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Knowledge Graph */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <GitBranch className="h-4 w-4" />
              Knowledge Graph
              <StatusDot active={!!kg && kg.total_entities > 0} />
              {kg && (
                <Badge variant="outline" className="ml-auto text-xs">
                  {kg.total_extractions} extractions
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {kg ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="text-center p-3 rounded-lg bg-muted/50">
                    <div className="text-2xl font-bold">{kg.total_entities}</div>
                    <div className="text-xs text-muted-foreground">Entities</div>
                  </div>
                  <div className="text-center p-3 rounded-lg bg-muted/50">
                    <div className="text-2xl font-bold">{kg.total_relationships}</div>
                    <div className="text-xs text-muted-foreground">Relationships</div>
                  </div>
                  <div className="text-center p-3 rounded-lg bg-muted/50">
                    <div className="text-2xl font-bold">{kg.total_extractions}</div>
                    <div className="text-xs text-muted-foreground">Extractions</div>
                  </div>
                  <div className="text-center p-3 rounded-lg bg-muted/50">
                    <div className="text-2xl font-bold">{kg.avg_extract_ms}ms</div>
                    <div className="text-xs text-muted-foreground">Avg Extract</div>
                  </div>
                </div>

                {/* Entity types breakdown */}
                {kg.entity_types && Object.keys(kg.entity_types).length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">Entity Types</p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(kg.entity_types)
                        .sort(([, a], [, b]) => b - a)
                        .map(([type, count]) => (
                          <Badge key={type} variant="secondary" className="text-xs">
                            {type}: {count}
                          </Badge>
                        ))}
                    </div>
                  </div>
                )}

                {/* Relationship types breakdown */}
                {kg.relationship_types && Object.keys(kg.relationship_types).length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">Relationship Types</p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(kg.relationship_types)
                        .sort(([, a], [, b]) => b - a)
                        .map(([type, count]) => (
                          <Badge key={type} variant="outline" className="text-xs">
                            {type}: {count}
                          </Badge>
                        ))}
                    </div>
                  </div>
                )}

                {/* Graph preview — top entities */}
                {kgGraph && kgGraph.nodes.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">
                      Top Entities ({kgGraph.nodes.length})
                    </p>
                    <div className="space-y-1 max-h-48 overflow-y-auto">
                      {kgGraph.nodes.slice(0, 20).map((node) => (
                        <div
                          key={node.id}
                          className="flex items-center justify-between text-sm px-2 py-1 rounded hover:bg-muted/50"
                        >
                          <span className="flex items-center gap-2">
                            <Badge
                              variant="outline"
                              className={`text-[10px] px-1 ${
                                node.type === 'technology'
                                  ? 'border-blue-500/30 text-blue-500'
                                  : node.type === 'tool'
                                    ? 'border-green-500/30 text-green-500'
                                    : node.type === 'project'
                                      ? 'border-amber-500/30 text-amber-500'
                                      : node.type === 'concept'
                                        ? 'border-purple-500/30 text-purple-500'
                                        : ''
                              }`}
                            >
                              {node.type}
                            </Badge>
                            <span className="font-mono text-xs">{node.name}</span>
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {node.mention_count}x
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Knowledge graph not initialized. Enable it in Settings → Memory.
              </p>
            )}
          </CardContent>
        </Card>

        {/* System memory subsystems */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Layers className="h-4 w-4" />
              Memory Subsystems
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="flex items-center gap-2 p-3 rounded-lg border">
                <StatusDot active={!!status?.passive_memory} />
                <div>
                  <div className="text-sm font-medium">Passive Memory</div>
                  <div className="text-xs text-muted-foreground">Auto-learn preferences</div>
                </div>
              </div>
              <div className="flex items-center gap-2 p-3 rounded-lg border">
                <StatusDot active={!!status?.working_memory} />
                <div>
                  <div className="text-sm font-medium">Working Memory</div>
                  <div className="text-xs text-muted-foreground">Redis hot state</div>
                </div>
              </div>
              <div className="flex items-center gap-2 p-3 rounded-lg border">
                <StatusDot active={!!status?.memory_index} />
                <div>
                  <div className="text-sm font-medium">Memory Index</div>
                  <div className="text-xs text-muted-foreground">Vector search</div>
                </div>
              </div>
              <div className="flex items-center gap-2 p-3 rounded-lg border">
                <StatusDot active={!!embed?.available} />
                <div>
                  <div className="text-sm font-medium">Embeddings</div>
                  <div className="text-xs text-muted-foreground">{embed?.model || 'Not configured'}</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
