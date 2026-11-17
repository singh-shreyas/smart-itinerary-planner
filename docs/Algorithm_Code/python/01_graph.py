# Weighted directed graph as an adjacency list (as in algorithms/graph.py)

def build_graph(nodes, edges):
    """nodes: ids; edges: (u, v, weight). Returns {u: [(v, weight), ...]}."""
    graph = {node: [] for node in nodes}
    for u, v, weight in edges:
        if u not in graph or v not in graph:
            raise ValueError(f"edge ({u}, {v}) uses an unknown node")
        if u == v:
            raise ValueError(f"self-loop on node {u}")
        if weight < 0:
            raise ValueError(f"negative weight on edge ({u}, {v})")   # Dijkstra needs w >= 0
        graph[u].append((v, weight))
    return graph


def reverse_graph(graph):
    """Every edge u -> v becomes v -> u. O(V + E)."""
    rev = {node: [] for node in graph}
    for u, neighbours in graph.items():
        for v, weight in neighbours:
            rev[v].append((u, weight))
    return rev


if __name__ == "__main__":
    g = build_graph("ABCD", [("A", "B", 10), ("B", "A", 10), ("A", "C", 20), ("C", "A", 20),
                             ("B", "C", 5), ("C", "B", 5), ("C", "D", 15), ("D", "C", 15)])
    for node, links in g.items():
        print(node, "->", links)
    try:
        build_graph("AB", [("A", "B", -3)])
    except ValueError as error:
        print("rejected:", error)
