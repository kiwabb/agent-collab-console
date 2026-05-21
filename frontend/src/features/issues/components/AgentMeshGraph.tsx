"use client";

const ROLE_LABEL: Record<string, string> = {
  conductor: "Conductor",
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  engineer_frontend: "FE Engineer",
  engineer_backend: "BE Engineer",
  qa: "QA",
  "specialist:security_reviewer": "Security",
  "specialist:performance_reviewer": "Performance",
  "specialist:doc_writer": "Doc Writer",
  "specialist:code_reviewer": "Code Reviewer",
  "specialist:migration_planner": "Migration",
  "specialist:dependency_auditor": "Dep Auditor",
  "specialist:api_contract_checker": "API Contract",
  "specialist:accessibility_reviewer": "A11y",
  "specialist:i18n_checker": "i18n",
  "specialist:log_summarizer": "Log Summarizer",
};

const ROLE_ABBREV: Record<string, string> = {
  conductor: "Co",
  product_manager: "PM",
  architect: "Ar",
  engineer: "En",
  engineer_frontend: "FE",
  engineer_backend: "BE",
  qa: "QA",
};

function getAbbrev(role: string): string {
  if (ROLE_ABBREV[role]) return ROLE_ABBREV[role];
  const label = ROLE_LABEL[role];
  if (label) return label.slice(0, 2);
  return role.slice(0, 2).toUpperCase();
}

function getNodeColor(status?: string): string {
  if (status === "done" || status === "completed") return "#22c55e";
  if (status === "failed") return "#ef4444";
  if (status === "running" || status === "in_progress") return "#f59e0b";
  return "#6b7280";
}

function getEdgeColor(messageType: string): string {
  switch (messageType) {
    case "handoff": return "#22c55e";
    case "critique": return "#ef4444";
    case "specialist_call": return "#3b82f6";
    case "specialist_result": return "#6366f1";
    case "clarification": return "#f59e0b";
    default: return "#6b7280";
  }
}

function getEdgeDash(messageType: string): string | undefined {
  if (messageType === "specialist_call") return "5 3";
  return undefined;
}

export interface AgentMeshNode {
  id: string;
  role: string;
  status?: string;
}

export interface AgentMeshEdge {
  id: string;
  from_node_key: string;
  to_node_key: string;
  message_type: string;
  body: string;
}

interface Props {
  nodes: AgentMeshNode[];
  edges: AgentMeshEdge[];
}

export function AgentMeshGraph({ nodes, edges }: Props) {
  if (nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-[13px] text-text-muted">
        No agent activity yet.
      </div>
    );
  }

  const cx = 200;
  const cy = 150;
  const r = 100;
  const nodeR = 22;

  const positions = nodes.map((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    return {
      id: node.id,
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      node,
    };
  });

  const posMap = new Map(positions.map((p) => [p.id, p]));

  return (
    <svg
      viewBox="0 0 400 300"
      className="w-full h-auto"
      aria-label="Agent mesh visualization"
    >
      {/* Edges */}
      {edges.map((edge) => {
        const from = posMap.get(edge.from_node_key);
        const to = posMap.get(edge.to_node_key);
        if (!from || !to) return null;
        const color = getEdgeColor(edge.message_type);
        const dash = getEdgeDash(edge.message_type);
        return (
          <line
            key={edge.id}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={color}
            strokeWidth={1.5}
            strokeDasharray={dash}
            opacity={0.7}
          />
        );
      })}

      {/* Nodes */}
      {positions.map(({ id, x, y, node }) => {
        const color = getNodeColor(node.status);
        const abbrev = getAbbrev(node.role);
        const label = ROLE_LABEL[node.role] ?? node.role;
        return (
          <g key={id}>
            <circle cx={x} cy={y} r={nodeR} fill={color} opacity={0.85} />
            <text
              x={x}
              y={y + 4}
              textAnchor="middle"
              fontSize={10}
              fontWeight="bold"
              fill="white"
              fontFamily="monospace"
            >
              {abbrev}
            </text>
            <text
              x={x}
              y={y + nodeR + 12}
              textAnchor="middle"
              fontSize={9}
              fill="#9ca3af"
              fontFamily="sans-serif"
            >
              {label.length > 10 ? label.slice(0, 9) + "…" : label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
