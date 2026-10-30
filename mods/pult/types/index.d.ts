// A limit window: percent used and reset time in epoch seconds.
export type LimitWindow = { pct: number; resetsAt: number }

// Account limits as reported by the engine ($.session.usage() or session.measure).
export type Limits = {
  at: number
  five: LimitWindow | null
  week: LimitWindow | null
}

// One tool call shown on the Activity pane.
export type Activity = {
  id: string
  // Subagent loop running the call; null for the main loop.
  agentId: string | null
  tool: string
  label: string
  startedAt: number
  endedAt: number | null
  isError: boolean
  isAsked: boolean
}

// A model task-list item (TodoWrite).
export type Todo = { content: string; status: 'pending' | 'in_progress' | 'completed' }

// A session subagent as returned by $.agent.list().
export type AgentRow = { id: string; type: string; description: string; status: string }

// Subagent context size and approximate spend, from its responses.
export type AgentStat = { model: string; contextTokens: number; spent: number }

// A handoff written by the mod.
export type Checkpoint = { path: string; at: number; why: string }

// Task progress reported by the model through mcp__pult__progress.
export type Progress = {
  title: string
  done: number
  total: number
  unit: string
  now: string
  next: string
  sub: { label: string; done: number; total: number } | null
  counts: { label: string; n: number }[]
  at: number
}

declare module 'claude-code' {
  interface PluginState {
    pult: {
      limits: Limits | null
      nudgedFor: string
      contextPct: number | null
      contextWarned: boolean
      chatTokens: number | null
      newChatHinted: boolean
      activity: Activity[]
      todos: Todo[]
      agents: AgentRow[]
      agentStats: Record<string, AgentStat>
      tick: number
      turnStartedAt: number | null
      checkpoint: Checkpoint | null
      busy: { text: string; since: number } | null
      progress: Progress | null
      turnCalls: { count: number; nudged: boolean }
    }
  }
}
