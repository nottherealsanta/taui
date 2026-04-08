<!--
  GraphView.svelte — Link graph visualization (stretch goal).

  Shows a force-directed graph of spec files and their relationships.
  Uses Canvas 2D for rendering since d3-force isn't a current dependency.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { appState } from '$stores/app-state.svelte'
  import { tabStore } from '$stores/tabs.svelte'

  interface Props {
    onclose?: () => void
  }
  const { onclose }: Props = $props()

  interface GraphNode {
    id: string
    label: string
    x: number
    y: number
    vx: number
    vy: number
  }

  interface GraphEdge {
    source: string
    target: string
  }

  let canvasEl: HTMLCanvasElement | undefined = $state()
  let nodes: GraphNode[] = $state([])
  let edges: GraphEdge[] = $state([])
  let animationId: number | null = null
  let draggingNode: GraphNode | null = null
  let hoveredNode: GraphNode | null = $state(null)

  // Build graph from spec nodes
  function buildGraph() {
    const graphNodes: GraphNode[] = []
    const graphEdges: GraphEdge[] = []
    const specRefs = new Set<string>()

    for (const node of appState.nodes) {
      if (!node.specRef) continue
      specRefs.add(node.specRef)
      graphNodes.push({
        id: node.specRef,
        label: node.markdown.split('\n')[0].trim() || node.specRef,
        x: Math.random() * 600 + 100,
        y: Math.random() * 400 + 100,
        vx: 0,
        vy: 0,
      })

      // Add edges from depends_on and related_to
      for (const dep of node.dependsOn) {
        graphEdges.push({ source: node.specRef, target: dep })
      }
      for (const rel of node.relatedTo) {
        graphEdges.push({ source: node.specRef, target: rel })
      }
    }

    // Filter edges to only include nodes in the graph
    nodes = graphNodes
    edges = graphEdges.filter((e) => specRefs.has(e.source) && specRefs.has(e.target))
  }

  // Simple force simulation
  function simulate() {
    const repulsion = 5000
    const attraction = 0.01
    const damping = 0.9
    const centerX = (canvasEl?.width ?? 800) / 2
    const centerY = (canvasEl?.height ?? 600) / 2

    // Repulsion between nodes
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x
        const dy = nodes[j].y - nodes[i].y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const force = repulsion / (dist * dist)
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        nodes[i].vx -= fx
        nodes[i].vy -= fy
        nodes[j].vx += fx
        nodes[j].vy += fy
      }
    }

    // Attraction along edges
    const nodeMap = new Map(nodes.map((n) => [n.id, n]))
    for (const edge of edges) {
      const src = nodeMap.get(edge.source)
      const tgt = nodeMap.get(edge.target)
      if (!src || !tgt) continue
      const dx = tgt.x - src.x
      const dy = tgt.y - src.y
      const fx = dx * attraction
      const fy = dy * attraction
      src.vx += fx
      src.vy += fy
      tgt.vx -= fx
      tgt.vy -= fy
    }

    // Center gravity
    for (const node of nodes) {
      node.vx += (centerX - node.x) * 0.001
      node.vy += (centerY - node.y) * 0.001
    }

    // Apply velocity and damping
    for (const node of nodes) {
      if (node === draggingNode) continue
      node.vx *= damping
      node.vy *= damping
      node.x += node.vx
      node.y += node.vy
    }
  }

  function render() {
    if (!canvasEl) return
    const ctx = canvasEl.getContext('2d')
    if (!ctx) return

    const w = canvasEl.clientWidth
    const h = canvasEl.clientHeight
    canvasEl.width = w * window.devicePixelRatio
    canvasEl.height = h * window.devicePixelRatio
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio)

    ctx.clearRect(0, 0, w, h)

    // Draw edges
    const nodeMap = new Map(nodes.map((n) => [n.id, n]))
    ctx.strokeStyle = 'rgba(125, 150, 180, 0.3)'
    ctx.lineWidth = 1
    for (const edge of edges) {
      const src = nodeMap.get(edge.source)
      const tgt = nodeMap.get(edge.target)
      if (!src || !tgt) continue
      ctx.beginPath()
      ctx.moveTo(src.x, src.y)
      ctx.lineTo(tgt.x, tgt.y)
      ctx.stroke()
    }

    // Draw nodes
    for (const node of nodes) {
      const isHovered = node === hoveredNode
      const radius = isHovered ? 6 : 4

      ctx.beginPath()
      ctx.arc(node.x, node.y, radius, 0, Math.PI * 2)
      ctx.fillStyle = isHovered ? '#7cc7ff' : '#5b8fbf'
      ctx.fill()

      if (isHovered) {
        ctx.font = '11px "IBM Plex Sans", sans-serif'
        ctx.fillStyle = '#e6edf3'
        ctx.textAlign = 'center'
        const label = node.label.length > 40 ? node.label.slice(0, 37) + '…' : node.label
        ctx.fillText(label, node.x, node.y - 10)
      }
    }
  }

  function tick() {
    simulate()
    render()
    animationId = requestAnimationFrame(tick)
  }

  function findNodeAt(x: number, y: number): GraphNode | null {
    for (const node of nodes) {
      const dx = node.x - x
      const dy = node.y - y
      if (dx * dx + dy * dy < 100) return node
    }
    return null
  }

  function handleMouseMove(e: MouseEvent) {
    if (!canvasEl) return
    const rect = canvasEl.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    if (draggingNode) {
      draggingNode.x = x
      draggingNode.y = y
      draggingNode.vx = 0
      draggingNode.vy = 0
    } else {
      hoveredNode = findNodeAt(x, y)
    }
  }

  function handleMouseDown(e: MouseEvent) {
    if (!canvasEl) return
    const rect = canvasEl.getBoundingClientRect()
    draggingNode = findNodeAt(e.clientX - rect.left, e.clientY - rect.top)
  }

  function handleMouseUp() {
    draggingNode = null
  }

  function handleClick(e: MouseEvent) {
    if (!canvasEl) return
    const rect = canvasEl.getBoundingClientRect()
    const node = findNodeAt(e.clientX - rect.left, e.clientY - rect.top)
    if (node) {
      // Open the spec file associated with this node
      const filePart = node.id.split('#')[0]
      if (filePart) {
        tabStore.openFile(filePart)
      }
    }
  }

  onMount(() => {
    buildGraph()
    animationId = requestAnimationFrame(tick)
  })

  onDestroy(() => {
    if (animationId !== null) {
      cancelAnimationFrame(animationId)
    }
  })
</script>

<div class="graph-view">
  <div class="graph-header">
    <span class="graph-title">Graph View</span>
    <span class="node-count">{nodes.length} nodes, {edges.length} links</span>
    {#if onclose}
      <button class="close-btn" onclick={onclose}>✕</button>
    {/if}
  </div>

  <canvas
    bind:this={canvasEl}
    class="graph-canvas"
    onmousemove={handleMouseMove}
    onmousedown={handleMouseDown}
    onmouseup={handleMouseUp}
    onclick={handleClick}
  ></canvas>
</div>

<style lang="postcss">
  .graph-view {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    background-color: var(--bg-base);
  }

  .graph-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .graph-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--fg-primary);
  }

  .node-count {
    font-size: 10px;
    color: var(--fg-muted);
  }

  .close-btn {
    margin-left: auto;
    background: transparent;
    border: none;
    color: var(--fg-muted);
    cursor: pointer;
    font-size: 12px;
    padding: 4px 6px;
    border-radius: 3px;
    transition: all 0.15s;
  }

  .close-btn:hover {
    background-color: var(--element-hover);
    color: var(--fg-primary);
  }

  .graph-canvas {
    flex: 1;
    width: 100%;
    cursor: grab;
  }

  .graph-canvas:active {
    cursor: grabbing;
  }
</style>
