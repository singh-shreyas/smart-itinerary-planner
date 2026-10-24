"""Weighted directed graph stored as an adjacency list.

Nodes are place ids. graph[u] is a list of (v, weight) pairs, meaning "there is
a direct road link from u to v that takes `weight` minutes". Links are directed
because one-way streets can make A->B and B->A different.

Why an adjacency list and not a matrix? Each place only stores links to its few
nearest neighbours, so the graph is sparse: O(V + E) memory instead of O(V^2).
"""


def build_graph(nodes, edges):
    """Build an adjacency list.

    nodes: iterable of node ids (every node gets an entry, even with no edges)
    edges: iterable of (u, v, weight) tuples

    Time and space: O(V + E).
    """
    graph = {node: [] for node in nodes}
    for u, v, weight in edges:
        if u not in graph or v not in graph:
            raise ValueError(f"edge ({u}, {v}) uses an unknown node")
        if u == v:
            raise ValueError(f"self-loop on node {u}")
        if weight < 0:
            # Dijkstra is only correct for non-negative weights.
            raise ValueError(f"negative weight on edge ({u}, {v})")
        graph[u].append((v, weight))
    return graph


def reverse_graph(graph):
    """Return the graph with every edge reversed (u->v becomes v->u). O(V + E)."""
    reversed_graph = {node: [] for node in graph}
    for u, neighbours in graph.items():
        for v, weight in neighbours:
            reversed_graph[v].append((u, weight))
    return reversed_graph


def edge_count(graph):
    """Number of directed edges in the graph."""
    return sum(len(neighbours) for neighbours in graph.values())
